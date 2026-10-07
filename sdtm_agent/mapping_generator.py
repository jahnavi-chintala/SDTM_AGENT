"""LLM-driven proposal of a mapping spec from source columns to an SDTM domain.

With no study-specific specs to start from, the proposal is grounded on:
- the retrieved SDTM IG rules for the target domain (retrieval.py),
- the bronze table profile (column names, types, sample values),
- keyword hints from COLUMN_SYNONYMS,
- approved mappings from earlier studies (returned by retrieval).

The result is always a *draft*; a human approves it in chat before execution.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from sdtm_agent.knowledge import COLUMN_SYNONYMS, DOMAINS, variable_names
from sdtm_agent.mapping_spec import MappingSpec, check_spec, has_errors

SPEC_FORMAT = """Return ONLY a JSON object (no prose) with this structure:
{
  "filter": null | "<Spark SQL predicate on source columns, e.g. ae_term IS NOT NULL>",
  "unpivot": null | {"tests": [{"source_column": "<raw col>", "testcd": "<--TESTCD>", "test": "<--TEST>", "orresu": "<unit or null>", "category": null}], "drop_null_results": true},
  "group_by": [],
  "seq_order_by": ["<target variables ordering --SEQ>"],
  "variables": [
    {"target": "<SDTM variable>",
     "source": "<raw column>"            // OR
     "expression": "<Spark SQL scalar expression over raw columns>"  // OR
     "constant": "<fixed value>",
     "value_map": {"<raw value>": "<controlled term>"},   // optional, for CT variables
     "date_format": "<Spark datetime pattern of raw value, e.g. dd-MMM-yyyy>",  // optional, for --DTC
     "aggregate": null | "min" | "max" | "first",          // only with group_by
     "rationale": "<why>", "confidence": "high" | "medium" | "low"}
  ],
  "notes": "<assumptions, open questions for the reviewer, data that belongs in SUPPQUAL>"
}

Rules:
- Use exactly one of source / expression / constant per variable. Only use variables of the target domain.
- Map every Required variable. Map Expected variables when the source supports them.
- STUDYID, DOMAIN and --SEQ are derived automatically if you omit them. --DY is derived from DM.RFSTDTC.
- USUBJID: if no USUBJID column exists, build it, e.g. concat_ws('-', <study col or constant>, <site col>, <subject col>).
- Dates: SDTM --DTC must be ISO 8601. If the raw value is not ISO 8601, set date_format to its Spark pattern.
- Controlled terminology: if a raw value differs from the codelist, add a value_map (keys = raw values seen in samples).
- Findings domains with one column per test (wide data): use unpivot; the stacked columns are available to
  expressions as __TESTCD, __TEST, __ORRES, __ORRESU, __CAT and --TESTCD/--TEST/--ORRES/--ORRESU/--STRES* default to them.
- SV: group_by ["USUBJID", "VISITNUM"] (plus VISIT) with SVSTDTC aggregate "min" and SVENDTC aggregate "max".
- Expressions must be single Spark SQL scalar expressions: no SELECT, no semicolons, no comments.
- Put anything uncertain in notes and use confidence "low" so the reviewer checks it."""

SYSTEM = (
    "You are a senior CDISC SDTM programmer. You write precise, conservative source-to-SDTM mapping "
    "specifications. Never invent source columns. " + SPEC_FORMAT
)


def _tokens(column: str) -> list[str]:
    col = re.sub(r"([a-z])([A-Z])", r"\1_\2", column).lower()
    parts = [p for p in re.split(r"[^a-z0-9]+", col) if p]
    return [col.strip("_")] + ["_".join(parts[i : i + 2]) for i in range(len(parts) - 1)] + parts


def heuristic_hints(columns: list[str], domain: str) -> dict[str, str]:
    """Raw column → likely SDTM variable / test code from name keywords."""
    names = set(variable_names(domain))
    hints = {}
    for col in columns:
        if col.upper() in names:
            hints[col] = col.upper()
            continue
        for token in _tokens(col):
            if token in COLUMN_SYNONYMS:
                dom, var = COLUMN_SYNONYMS[token]
                if dom == domain or var in names or dom == "DM" and var in ("STUDYID", "USUBJID", "SUBJID", "SITEID"):
                    hints[col] = var
                    break
    return hints


def _extract_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("No JSON object in model response")
    return json.loads(text[start : end + 1])


def _content(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, list):  # some endpoints return content blocks
        content = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return str(content)


def generate_mapping_spec(
    llm: Any,
    *,
    study_id: str,
    domain: str,
    source_table: str,
    source_profile: list[dict],
    ig_rules: dict,
    dm_table: str | None = None,
    user_instructions: str | None = None,
    created_by: str | None = None,
) -> tuple[MappingSpec, list[dict]]:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    domain = domain.upper()
    if domain not in DOMAINS:
        raise ValueError(f"Unknown domain {domain}")
    columns = [c["name"] for c in source_profile]
    prompt = {
        "task": f"Propose the mapping from source table {source_table} to SDTM {domain} for study {study_id}.",
        "source_columns": source_profile,
        "keyword_hints": heuristic_hints(columns, domain),
        "sdtm_ig_rules": {k: ig_rules[k] for k in ("domain", "label", "class", "structure", "keys", "variables", "assumptions", "standard_tests") if k in ig_rules},
        "retrieved_ig_passages_and_prior_approved_mappings": ig_rules.get("retrieved_passages", []),
        "reviewer_instructions": user_instructions,
    }
    messages = [SystemMessage(content=SYSTEM), HumanMessage(content=json.dumps(prompt, default=str))]

    spec, issues, last_error = None, [], None
    for _ in range(2):  # proposal + one repair round
        response = llm.invoke(messages)
        raw = _content(response)
        try:
            data = _extract_json(raw)
            data.update(study_id=study_id, domain=domain, source_table=source_table, dm_table=dm_table, created_by=created_by)
            data.pop("spec_id", None)
            data.pop("status", None)
            spec = MappingSpec.model_validate(data)
            issues = check_spec(spec, columns)
            if not has_errors(issues):
                return spec, issues
            feedback = "The spec has these errors, return the corrected full JSON:\n" + json.dumps(
                [i for i in issues if i["severity"] == "error"]
            )
        except (ValueError, ValidationError) as exc:
            last_error = exc
            feedback = f"Your response was not a valid spec ({exc}). Return only the corrected JSON object."
        messages += [AIMessage(content=raw), HumanMessage(content=feedback)]

    if spec is None:
        raise ValueError(f"Could not generate a valid mapping spec: {last_error}")
    return spec, issues
