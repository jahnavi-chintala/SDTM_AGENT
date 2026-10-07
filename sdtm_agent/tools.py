"""LangChain tools exposed to the SDTM mapping agent.

Core tools from the build spec:
  get_source_schema, retrieve_sdtm_spec, generate_mapping, execute_transform, validate_output
Review-loop helpers:
  list_source_tables, get_mapping, list_mappings, update_mapping, preview_transform,
  approve_mapping, get_transform_status

Every tool returns a JSON string; errors are returned (not raised) so the LLM
can explain them or recover.
"""

from __future__ import annotations

import functools
import json
import time
from typing import Any, Optional

from langchain_core.tools import tool

from sdtm_agent import retrieval
from sdtm_agent.config import get_config, get_request_context
from sdtm_agent.llm import get_chat_model
from sdtm_agent.mapping_generator import generate_mapping_spec
from sdtm_agent.mapping_spec import MappingSpec, Unpivot, VariableMapping, check_spec, has_errors
from sdtm_agent.spec_store import SpecStore
from sdtm_agent.sql import check_schema_name, check_table_name, get_runner, quote_column
from sdtm_agent.transform import compile_sql
from sdtm_agent.validation import validate_dataset

MAX_PROFILE_COLUMNS = 80


def _json(obj: Any) -> str:
    return json.dumps(obj, default=str)


def _safe(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return _json(fn(*args, **kwargs))
        except Exception as exc:
            return _json({"error": f"{type(exc).__name__}: {exc}"})

    return wrapper


def _store() -> SpecStore:
    return SpecStore(get_runner(), get_config())


def _resolve_source_table(study_id: str, table_name: str) -> str:
    if table_name.count(".") == 2:
        return check_table_name(table_name)
    return check_table_name(f"{get_config().bronze_schema_for(study_id)}.{table_name}")


def _target_table(spec: MappingSpec) -> str:
    return check_table_name(f"{get_config().silver_schema_for(spec.study_id)}.{spec.domain.lower()}")


def _spec_view(spec: MappingSpec, issues: list[dict] | None = None) -> dict:
    """Compact, reviewable view of a spec for the chat UI."""
    rows = []
    for v in sorted(spec.variables, key=lambda v: v.target):
        how = v.source or v.expression or (f"'{v.constant}'" if v.constant is not None else "")
        steps = []
        if v.date_format:
            steps.append(f"date {v.date_format}→ISO 8601")
        if v.value_map:
            steps.append("map " + ", ".join(f"{k}→{val}" for k, val in v.value_map.items()))
        if v.aggregate:
            steps.append(v.aggregate)
        rows.append(
            {"target": v.target, "from": how, "transform": "; ".join(steps), "confidence": v.confidence, "rationale": v.rationale}
        )
    return {
        "spec_id": spec.spec_id,
        "version": spec.version,
        "status": spec.status,
        "study_id": spec.study_id,
        "domain": spec.domain,
        "source_table": spec.source_table,
        "target_table": _target_table(spec),
        "filter": spec.filter,
        "unpivot": spec.unpivot.model_dump() if spec.unpivot else None,
        "group_by": spec.group_by,
        "dm_table": spec.dm_table,
        "notes": spec.notes,
        "mapping_table": rows,
        "issues": issues if issues is not None else check_spec(spec),
    }


def _load(spec_id: str) -> MappingSpec:
    spec = _store().get(spec_id.strip())
    if spec is None:
        raise KeyError(f"No mapping spec with id {spec_id}")
    return spec


def _default_dm_table(study_id: str, domain: str) -> str | None:
    return None if domain.upper() == "DM" else f"{get_config().silver_schema_for(study_id)}.dm"


# ===================================================================== source data
@tool
@_safe
def list_source_tables(study_id: str) -> Any:
    """List the raw (bronze) tables available for a study in Unity Catalog."""
    schema = check_schema_name(get_config().bronze_schema_for(study_id))
    rows = get_runner().query(f"SHOW TABLES IN {schema}").rows
    return {"schema": schema, "tables": [r[1] for r in rows]}


def describe_columns(table: str) -> list[dict]:
    cols = []
    for row in get_runner().query(f"DESCRIBE TABLE {table}").rows:
        if not row[0] or row[0].startswith("#"):
            break  # partition / metadata section
        cols.append({"name": row[0], "type": row[1], "comment": row[2] if len(row) > 2 else None})
    return cols


def profile_table(table: str, columns: list[str] | None = None, sample_rows: int = 2000, max_values: int = 8) -> dict:
    runner = get_runner()
    cols = describe_columns(table)
    if columns:
        wanted = {c.lower() for c in columns}
        cols = [c for c in cols if c["name"].lower() in wanted]
    cols = cols[:MAX_PROFILE_COLUMNS]
    if cols:
        exprs = ", ".join(
            f"slice(collect_set(CAST({quote_column(c['name'])} AS STRING)), 1, {max_values}) AS {quote_column(c['name'])}"
            for c in cols
        )
        samples = runner.query(f"SELECT {exprs} FROM (SELECT * FROM {table} LIMIT {sample_rows})").records()
        values = samples[0] if samples else {}
        for c in cols:
            v = values.get(c["name"])
            c["sample_values"] = json.loads(v) if isinstance(v, str) and v.startswith("[") else v
    row_count = runner.query(f"SELECT COUNT(*) FROM {table}").scalar()
    return {"table": table, "row_count": int(row_count or 0), "columns": cols}


@tool
@_safe
def get_source_schema(study_id: str, table_name: str) -> Any:
    """Fetch a bronze table's schema from Unity Catalog: column names, types, comments,
    row count and up to 8 distinct sample values per column. table_name may be a bare
    table name (resolved in the study's bronze schema) or catalog.schema.table."""
    return profile_table(_resolve_source_table(study_id, table_name))


# ===================================================================== SDTM IG
@tool
@_safe
def retrieve_sdtm_spec(domain: str, question: Optional[str] = None) -> Any:
    """Retrieve SDTM IG rules for a domain (DM, AE, VS, ...): variables with core status and
    controlled terminology, IG assumptions, and the most relevant IG passages and previously
    approved mappings from Vector Search. Pass `question` to focus retrieval."""
    return retrieval.retrieve(domain, question)


# ===================================================================== mapping specs
@tool
@_safe
def generate_mapping(
    source_cols: list[str],
    target_domain: str,
    study_id: str,
    source_table: str,
    instructions: Optional[str] = None,
) -> Any:
    """Propose a column/value mapping spec from bronze source columns to an SDTM domain.
    Retrieves the IG rules and profiles the source columns first, then asks the LLM for a
    spec and saves it as a DRAFT for human review. Pass an empty source_cols list to use all
    columns. `instructions` carries reviewer guidance (e.g. 'severity is coded 1/2/3')."""
    cfg = get_config()
    domain = target_domain.strip().upper()
    table = _resolve_source_table(study_id, source_table)
    profile = profile_table(table, source_cols or None)
    if not profile["columns"]:
        return {"error": f"None of the columns {source_cols} exist in {table}"}
    rules = retrieval.retrieve(domain, f"{domain} mapping " + " ".join(c["name"] for c in profile["columns"]))
    spec, issues = generate_mapping_spec(
        get_chat_model(),
        study_id=study_id,
        domain=domain,
        source_table=table,
        source_profile=profile["columns"],
        ig_rules=rules,
        dm_table=_default_dm_table(study_id, domain),
        user_instructions=instructions,
        created_by=get_request_context().user,
    )
    _store().save(spec, comment="generated by agent")
    view = _spec_view(spec, issues)
    view["retrieval_mode"] = rules.get("retrieval_mode")
    view["next_step"] = "Draft only: review the mapping table with the user. Do not execute until approved."
    if cfg.trial_design_domain not in ("SV", "TA"):
        view["warning"] = "SDTM_TRIAL_DESIGN_DOMAIN should be SV or TA"
    return view


@tool
@_safe
def get_mapping(spec_id: str) -> Any:
    """Show the latest version of a mapping spec, its issues and the full JSON."""
    spec = _load(spec_id)
    view = _spec_view(spec)
    view["spec_json"] = spec.model_dump(exclude={"updated_at"})
    return view


@tool
@_safe
def list_mappings(study_id: str, domain: Optional[str] = None, status: Optional[str] = None) -> Any:
    """List mapping specs for a study (latest version of each), optionally by domain/status."""
    return {"specs": _store().list(study_id, domain, status)}


@tool
@_safe
def update_mapping(
    spec_id: str,
    set_variables: Optional[list[dict]] = None,
    remove_variables: Optional[list[str]] = None,
    filter: Optional[str] = None,
    unpivot: Optional[dict] = None,
    group_by: Optional[list[str]] = None,
    seq_order_by: Optional[list[str]] = None,
    dm_table: Optional[str] = None,
    notes: Optional[str] = None,
    change_summary: Optional[str] = None,
) -> Any:
    """Apply the reviewer's corrections to a mapping spec and save them as a new DRAFT version.
    set_variables: list of variable mappings to add/replace, each like
      {"target": "AESEV", "source": "severity", "value_map": {"1": "MILD", "2": "MODERATE", "3": "SEVERE"}}
      (exactly one of source / expression / constant; optional value_map, date_format, aggregate).
    remove_variables: target variable names to drop. Other arguments replace the spec field.
    Use filter="" to clear the filter."""
    spec = _load(spec_id)
    if set_variables:
        spec.upsert_variables([VariableMapping.model_validate(v) for v in set_variables])
    if remove_variables:
        spec.remove_variables(remove_variables)
    if filter is not None:
        spec.filter = filter or None
    if unpivot is not None:
        spec.unpivot = Unpivot.model_validate(unpivot) if unpivot else None
    if group_by is not None:
        spec.group_by = [g.upper() for g in group_by]
    if seq_order_by is not None:
        spec.seq_order_by = [s.upper() for s in seq_order_by]
    if dm_table is not None:
        spec.dm_table = check_table_name(dm_table) if dm_table else None
    if notes is not None:
        spec.notes = notes
    _store().new_version(spec, comment=change_summary or "updated in chat")
    return _spec_view(spec)


@tool
@_safe
def preview_transform(spec_id: str, limit: int = 10) -> Any:
    """Preview the first rows the spec would produce (runs read-only on the SQL warehouse,
    nothing is written). Use it during review, before approval."""
    spec = _load(spec_id)
    source_cols = [c["name"] for c in describe_columns(spec.source_table)]
    sql = compile_sql(spec, source_cols) + f"\nLIMIT {max(1, min(int(limit), 50))}"
    result = get_runner().query(sql)
    return {"spec_id": spec.spec_id, "version": spec.version, "columns": result.columns, "rows": result.rows, "sql": sql}


@tool
@_safe
def approve_mapping(spec_id: str, version: int, comment: Optional[str] = None) -> Any:
    """Mark a spec version as APPROVED. Only call this when the user has explicitly approved this
    exact spec version. Approval is rejected if the spec has errors or a newer version exists."""
    cfg, ctx = get_config(), get_request_context()
    latest = _load(spec_id)
    if int(version) != latest.version:
        return {"error": f"Version {version} is outdated; the latest is v{latest.version}. Review that version instead."}
    if cfg.require_ui_approval and f"{latest.spec_id}:{latest.version}" not in ctx.approved_spec_ids:
        return {
            "error": "Approval must come from the reviewer: ask the user to click 'Approve' for this spec version in the chat UI.",
            "spec_id": latest.spec_id,
            "version": latest.version,
        }
    issues = check_spec(latest)
    if has_errors(issues):
        return {"error": "Spec has errors and cannot be approved", "issues": issues}
    _store().set_status(latest, "approved", user=ctx.user, comment=comment)
    return {"spec_id": latest.spec_id, "version": latest.version, "status": "approved", "approved_by": ctx.user}


# ===================================================================== execution
def _run_summary(client: Any, run_id: int) -> dict:
    run = client.jobs.get_run(run_id)
    state = run.state
    return {
        "run_id": run_id,
        "run_page_url": run.run_page_url,
        "life_cycle_state": state.life_cycle_state.value if state and state.life_cycle_state else None,
        "result_state": state.result_state.value if state and state.result_state else None,
        "message": state.state_message if state else None,
    }


def _validation_for_run(run_id: int) -> dict | None:
    cfg = get_config()
    rows = get_runner().query(
        f"SELECT table_name, passed, error_count, warning_count, record_count, findings_json "
        f"FROM {cfg.validation_results_table} WHERE run_id = :run_id ORDER BY validated_at DESC LIMIT 1",
        {"run_id": str(run_id)},
    ).records()
    if not rows:
        return None
    r = rows[0]
    r["findings"] = json.loads(r.pop("findings_json") or "[]")
    return r


@tool
@_safe
def execute_transform(mapping_spec: str, source_table: Optional[str] = None) -> Any:
    """Run the PySpark transform job for an APPROVED mapping spec (pass its spec_id) and write
    the Silver SDTM table. The job validates the output and stores the report.
    Optionally override the source table (catalog.schema.table) for this run."""
    from databricks.sdk import WorkspaceClient

    cfg, ctx = get_config(), get_request_context()
    spec = _load(mapping_spec)
    if spec.status != "approved":
        return {"error": f"Spec {spec.spec_id} v{spec.version} is '{spec.status}'. It must be approved by the reviewer first."}
    if not cfg.transform_job_id:
        return {"error": "SDTM_TRANSFORM_JOB_ID is not configured."}
    client = WorkspaceClient()
    params = {
        "spec_id": spec.spec_id,
        "spec_version": str(spec.version),
        "target_table": _target_table(spec),
        "requested_by": ctx.user,
    }
    if source_table:
        params["source_table"] = check_table_name(source_table)
    run_id = client.jobs.run_now(job_id=int(cfg.transform_job_id), job_parameters=params).run_id

    deadline = time.time() + cfg.transform_wait_seconds
    summary = _run_summary(client, run_id)
    while summary["life_cycle_state"] not in ("TERMINATED", "SKIPPED", "INTERNAL_ERROR") and time.time() < deadline:
        time.sleep(5)
        summary = _run_summary(client, run_id)
    summary["target_table"] = params["target_table"]
    if summary["result_state"] == "SUCCESS":
        summary["validation"] = _validation_for_run(run_id)
    elif summary["life_cycle_state"] not in ("TERMINATED", "SKIPPED", "INTERNAL_ERROR"):
        summary["next_step"] = "Still running. Check again with get_transform_status(run_id)."
    return summary


@tool
@_safe
def get_transform_status(run_id: int) -> Any:
    """Check a transform job run; when finished, includes the validation report."""
    from databricks.sdk import WorkspaceClient

    summary = _run_summary(WorkspaceClient(), int(run_id))
    if summary["result_state"] == "SUCCESS":
        summary["validation"] = _validation_for_run(int(run_id))
    return summary


@tool
@_safe
def validate_output(domain: str, dataset: str, dm_table: Optional[str] = None) -> Any:
    """Validate an SDTM dataset (catalog.schema.table) against the domain's IG rules: required/expected
    variables, nulls in required variables, controlled terminology, ISO 8601 dates, --SEQ uniqueness,
    DM subject consistency. Returns findings with severity, counts and example values."""
    return validate_dataset(get_runner(), dataset, domain, dm_table)


ALL_TOOLS = [
    list_source_tables,
    get_source_schema,
    retrieve_sdtm_spec,
    generate_mapping,
    get_mapping,
    list_mappings,
    update_mapping,
    preview_transform,
    approve_mapping,
    execute_transform,
    get_transform_status,
    validate_output,
]
