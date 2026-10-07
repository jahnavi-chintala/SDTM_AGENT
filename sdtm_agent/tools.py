"""Tools the SDTM agent can call.

Each tool is a plain Python function returning a JSON-serialisable value.
`TOOL_SPECS` describes them in OpenAI function-calling format, and
`execute_tool` dispatches a tool call by name.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

from sdtm_agent.knowledge import COLUMN_SYNONYMS, CONTROLLED_TERMINOLOGY, DOMAINS

MAX_ROWS = 100

_READ_ONLY_PREFIXES = ("select", "with", "show", "describe", "desc", "explain")
_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(insert|update|delete|merge|drop|create|alter|truncate|grant|revoke|copy|optimize|vacuum|replace)\b",
    re.IGNORECASE,
)
_TABLE_NAME = re.compile(r"^`?[A-Za-z0-9_\-]+`?(\.`?[A-Za-z0-9_\-]+`?){0,2}$")
_SCHEMA_NAME = re.compile(r"^`?[A-Za-z0-9_\-]+`?\.`?[A-Za-z0-9_\-]+`?$")


# --------------------------------------------------------------------------- #
# Reference tools (no Databricks access needed)
# --------------------------------------------------------------------------- #
def list_sdtm_domains() -> list[dict[str, str]]:
    return [
        {"domain": code, "label": d["label"], "class": d["class"]}
        for code, d in DOMAINS.items()
    ]


def get_sdtm_domain_spec(domain: str) -> dict[str, Any]:
    code = domain.strip().upper()
    if code not in DOMAINS:
        return {"error": f"Unknown domain '{domain}'. Known domains: {sorted(DOMAINS)}"}
    d = DOMAINS[code]
    return {
        "domain": code,
        "label": d["label"],
        "class": d["class"],
        "structure": d["structure"],
        "variables": [
            {
                "name": name,
                "label": label,
                "type": vtype,
                "core": core,
                **({"codelist": CONTROLLED_TERMINOLOGY[name]} if name in CONTROLLED_TERMINOLOGY else {}),
            }
            for name, label, vtype, core in d["variables"]
        ],
    }


def get_controlled_terminology(variable: str) -> dict[str, Any]:
    name = variable.strip().upper()
    if name not in CONTROLLED_TERMINOLOGY:
        return {"error": f"No codelist stored for '{variable}'. Available: {sorted(CONTROLLED_TERMINOLOGY)}"}
    return {"variable": name, "allowed_values": CONTROLLED_TERMINOLOGY[name]}


def _tokens(column: str) -> list[str]:
    col = re.sub(r"([a-z])([A-Z])", r"\1_\2", column).lower()
    parts = [p for p in re.split(r"[^a-z0-9]+", col) if p]
    # Whole name plus adjacent pairs, so "heart_rate" and "ae_term" also match.
    return [col.strip("_")] + ["_".join(parts[i : i + 2]) for i in range(len(parts) - 1)] + parts


def suggest_sdtm_mapping(columns: list[str]) -> dict[str, Any]:
    """Suggest a target SDTM domain and variable for each raw column name."""
    all_vars = {name: code for code, d in DOMAINS.items() for name, *_ in d["variables"]}
    mappings, domain_votes = [], {}
    for column in columns:
        match = None
        if column.strip().upper() in all_vars:
            var = column.strip().upper()
            match = (all_vars[var], var, "exact SDTM variable name")
        else:
            for token in _tokens(column):
                if token in COLUMN_SYNONYMS:
                    dom, var = COLUMN_SYNONYMS[token]
                    match = (dom, var, f"keyword '{token}'")
                    break
        if match:
            dom, var, reason = match
            if var not in ("STUDYID", "DOMAIN", "USUBJID", "SUBJID"):
                domain_votes[dom] = domain_votes.get(dom, 0) + 1
            mappings.append({"raw_column": column, "domain": dom, "variable": var, "reason": reason})
        else:
            mappings.append({"raw_column": column, "domain": None, "variable": None, "reason": "no match; review manually"})
    likely = max(domain_votes, key=domain_votes.get) if domain_votes else None
    return {"likely_domain": likely, "domain_votes": domain_votes, "mappings": mappings}


# --------------------------------------------------------------------------- #
# Databricks SQL tools
# --------------------------------------------------------------------------- #
def _is_read_only(sql: str) -> bool:
    stripped = sql.strip().rstrip(";").strip()
    if ";" in stripped:
        return False
    return stripped.lower().startswith(_READ_ONLY_PREFIXES) and not _FORBIDDEN_KEYWORDS.search(stripped)


def _execute_sql(sql: str) -> dict[str, Any]:
    """Run a statement on a Databricks SQL warehouse via the Statement Execution API."""
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementState

    warehouse_id = os.environ.get("SDTM_WAREHOUSE_ID")
    if not warehouse_id:
        return {"error": "SDTM_WAREHOUSE_ID is not configured for the agent."}
    resp = WorkspaceClient().statement_execution.execute_statement(
        statement=sql, warehouse_id=warehouse_id, wait_timeout="50s", row_limit=MAX_ROWS
    )
    if resp.status.state != StatementState.SUCCEEDED:
        err = resp.status.error.message if resp.status.error else resp.status.state.value
        return {"error": f"Query did not succeed: {err}"}
    columns = [c.name for c in resp.manifest.schema.columns]
    rows = (resp.result.data_array if resp.result else None) or []
    return {"columns": columns, "rows": rows, "row_count": len(rows), "truncated": bool(resp.manifest.truncated)}


def run_sql_query(query: str) -> dict[str, Any]:
    if not _is_read_only(query):
        return {"error": "Only single read-only statements (SELECT/WITH/SHOW/DESCRIBE) are allowed."}
    return _execute_sql(query)


def list_tables(schema: str) -> dict[str, Any]:
    if not _SCHEMA_NAME.match(schema.strip()):
        return {"error": "Schema must be in the form catalog.schema"}
    return _execute_sql(f"SHOW TABLES IN {schema.strip()}")


def describe_table(table: str) -> dict[str, Any]:
    if not _TABLE_NAME.match(table.strip()):
        return {"error": "Invalid table name. Use catalog.schema.table"}
    return _execute_sql(f"DESCRIBE TABLE {table.strip()}")


def validate_sdtm_table(table: str, domain: str) -> dict[str, Any]:
    """Check a table against the SDTM spec: missing variables, nulls in required
    variables and values outside controlled terminology."""
    spec = get_sdtm_domain_spec(domain)
    if "error" in spec:
        return spec
    described = describe_table(table)
    if "error" in described:
        return described
    present = {
        row[0].upper()
        for row in described["rows"]
        if row and row[0] and not row[0].startswith("#")
    }
    variables = spec["variables"]
    required = [v["name"] for v in variables if v["core"] == "Req"]
    expected = [v["name"] for v in variables if v["core"] == "Exp"]
    known = {v["name"] for v in variables}

    findings: dict[str, Any] = {
        "table": table,
        "domain": spec["domain"],
        "missing_required": [v for v in required if v not in present],
        "missing_expected": [v for v in expected if v not in present],
        "non_standard_columns": sorted(present - known),
    }

    req_present = [v for v in required if v in present]
    if req_present:
        exprs = ", ".join(f"SUM(CASE WHEN `{v}` IS NULL THEN 1 ELSE 0 END) AS `{v}`" for v in req_present)
        nulls = _execute_sql(f"SELECT COUNT(*) AS total_rows, {exprs} FROM {table.strip()}")
        if "error" not in nulls and nulls["rows"]:
            row = dict(zip(nulls["columns"], nulls["rows"][0]))
            findings["total_rows"] = int(row.pop("total_rows") or 0)
            findings["nulls_in_required"] = {k: int(v) for k, v in row.items() if v and int(v) > 0}

    ct_issues = {}
    for var in (v for v in present if v in CONTROLLED_TERMINOLOGY):
        allowed = ", ".join("'" + a.replace("'", "''") + "'" for a in CONTROLLED_TERMINOLOGY[var])
        bad = _execute_sql(
            f"SELECT DISTINCT `{var}` FROM {table.strip()} "
            f"WHERE `{var}` IS NOT NULL AND `{var}` NOT IN ({allowed}) LIMIT 20"
        )
        if "error" not in bad and bad["rows"]:
            ct_issues[var] = [r[0] for r in bad["rows"]]
    findings["controlled_terminology_issues"] = ct_issues

    if "STUDYID" in present and "USUBJID" in present and spec["domain"] == "DM":
        dup = _execute_sql(
            f"SELECT COUNT(*) FROM (SELECT USUBJID FROM {table.strip()} GROUP BY USUBJID HAVING COUNT(*) > 1)"
        )
        if "error" not in dup and dup["rows"]:
            findings["duplicate_usubjid_count"] = int(dup["rows"][0][0])

    findings["passed"] = not (
        findings["missing_required"]
        or findings.get("nulls_in_required")
        or ct_issues
        or findings.get("duplicate_usubjid_count")
    )
    return findings


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
TOOLS: dict[str, Callable[..., Any]] = {
    "list_sdtm_domains": list_sdtm_domains,
    "get_sdtm_domain_spec": get_sdtm_domain_spec,
    "get_controlled_terminology": get_controlled_terminology,
    "suggest_sdtm_mapping": suggest_sdtm_mapping,
    "run_sql_query": run_sql_query,
    "list_tables": list_tables,
    "describe_table": describe_table,
    "validate_sdtm_table": validate_sdtm_table,
}


def _fn(name: str, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties or {}, "required": required or []},
        },
    }


TOOL_SPECS: list[dict] = [
    _fn("list_sdtm_domains", "List the SDTM domains the agent has reference specifications for."),
    _fn(
        "get_sdtm_domain_spec",
        "Get the SDTMIG specification of a domain: variables, labels, types, core (Req/Exp/Perm) and codelists.",
        {"domain": {"type": "string", "description": "Two-letter domain code, e.g. DM, AE, VS, LB"}},
        ["domain"],
    ),
    _fn(
        "get_controlled_terminology",
        "Get the CDISC controlled terminology (allowed values) for an SDTM variable such as SEX or AESEV.",
        {"variable": {"type": "string"}},
        ["variable"],
    ),
    _fn(
        "suggest_sdtm_mapping",
        "Suggest the target SDTM domain and variable for each raw (source/EDC) column name.",
        {"columns": {"type": "array", "items": {"type": "string"}}},
        ["columns"],
    ),
    _fn(
        "run_sql_query",
        f"Run a single read-only Spark SQL query (SELECT/WITH/SHOW/DESCRIBE) on Databricks. Returns at most {MAX_ROWS} rows.",
        {"query": {"type": "string"}},
        ["query"],
    ),
    _fn(
        "list_tables",
        "List the tables in a Unity Catalog schema.",
        {"schema": {"type": "string", "description": "catalog.schema"}},
        ["schema"],
    ),
    _fn(
        "describe_table",
        "Show the columns and types of a Unity Catalog table.",
        {"table": {"type": "string", "description": "catalog.schema.table"}},
        ["table"],
    ),
    _fn(
        "validate_sdtm_table",
        "Validate a Databricks table against an SDTM domain: missing required/expected variables, "
        "nulls in required variables, controlled terminology violations and duplicate subjects.",
        {
            "table": {"type": "string", "description": "catalog.schema.table"},
            "domain": {"type": "string", "description": "Two-letter domain code"},
        },
        ["table", "domain"],
    ),
]


def execute_tool(name: str, arguments: str | dict | None) -> str:
    """Run a tool by name and return its result as a JSON string."""
    if name not in TOOLS:
        return json.dumps({"error": f"Unknown tool '{name}'"})
    try:
        args = json.loads(arguments) if isinstance(arguments, str) and arguments else (arguments or {})
        result = TOOLS[name](**args)
    except Exception as exc:  # surface errors to the LLM instead of failing the request
        result = {"error": f"{type(exc).__name__}: {exc}"}
    return json.dumps(result, default=str)
