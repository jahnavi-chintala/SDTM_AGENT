"""Mapping workflow state tracked by the agent graph's `track` step.

Kept free of LangGraph imports so it can be unit-tested on its own.
"""

from __future__ import annotations

import json
from typing import Any

SYSTEM_PROMPT = """You are the SDTM Mapping Agent: you help clinical data programmers turn raw (bronze) clinical
study tables in Databricks Unity Catalog into CDISC SDTM datasets, using the SDTM Implementation Guide only
(there are no study-specific mapping specs yet).

Supported domains (v1): {domains} plus {trial_design} for trial design.

Workflow — follow these steps in order and tell the user which step you are on:
1. Identify the study and source table (list_source_tables, get_source_schema). Map DM first: other domains
   need its USUBJID and RFSTDTC (for --DY).
2. Retrieve the IG rules for the target domain (retrieve_sdtm_spec).
3. Propose a mapping with generate_mapping. Present it as a markdown table (target | from | transform | confidence),
   then list issues, low-confidence rows and open questions from the notes. This is a DRAFT for human review.
4. Apply the user's corrections with update_mapping, and show sample output with preview_transform.
5. Approval is a human decision made in the chat UI. Never claim a spec is approved unless approve_mapping
   succeeded. If approve_mapping says approval must come from the reviewer, ask the user to click Approve.
6. After approval, run execute_transform. Report the validation findings (errors first) and propose concrete
   mapping fixes; fixes create a new draft version that needs approval again.

Rules:
- Ground every mapping decision in the retrieved IG rules or the source data profile; never invent columns
  or controlled terms. Say when something is an assumption.
- Respect controlled terminology exactly (case and spelling). Dates must be ISO 8601.
- Non-standard source data belongs in SUPP-- datasets (out of scope for v1): point it out, don't force it.
- Keep answers concise and structured. Don't paste raw JSON unless asked.

Current workflow state (from earlier tool results):
{workflow}"""

EMPTY_WORKFLOW: dict[str, Any] = {"stage": "start", "study_id": None, "source_table": None, "active_spec_id": None, "specs": {}}

NEXT_STEP = {
    "start": "Ask for / identify the study and the source table and target domain.",
    "source_selected": "Retrieve IG rules and generate a mapping for the target domain.",
    "draft_review": "Review the draft with the user; apply corrections with update_mapping; preview_transform; wait for UI approval.",
    "approved": "Run execute_transform for the approved spec.",
    "running": "Check the run with get_transform_status.",
    "executed": "Report validation findings and propose fixes.",
}


def parse_tool_result(content: Any) -> dict:
    try:
        data = json.loads(content if isinstance(content, str) else json.dumps(content))
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        return {}


def update_workflow(workflow: dict[str, Any], tool_name: str, result: dict) -> dict[str, Any]:
    """Advance the workflow state from one tool result."""
    wf = json.loads(json.dumps(workflow or EMPTY_WORKFLOW))
    wf.setdefault("specs", {})
    if not result or "error" in result:
        return wf
    if tool_name == "get_source_schema":
        wf["source_table"] = result.get("table")
        if wf["stage"] == "start":
            wf["stage"] = "source_selected"
    elif tool_name in ("generate_mapping", "update_mapping", "get_mapping") and result.get("spec_id"):
        sid = result["spec_id"]
        errors = sum(1 for i in result.get("issues", []) if i.get("severity") == "error")
        wf["specs"][sid] = {
            "domain": result.get("domain"),
            "version": result.get("version"),
            "status": result.get("status"),
            "errors": errors,
            "target_table": result.get("target_table"),
        }
        wf.update(active_spec_id=sid, study_id=result.get("study_id"), source_table=result.get("source_table"))
        wf["stage"] = "approved" if result.get("status") == "approved" else "draft_review"
    elif tool_name == "approve_mapping" and result.get("status") == "approved":
        sid = result["spec_id"]
        wf["specs"].setdefault(sid, {}).update(status="approved", version=result.get("version"))
        wf.update(active_spec_id=sid, stage="approved")
    elif tool_name in ("execute_transform", "get_transform_status") and result.get("run_id"):
        sid = wf.get("active_spec_id")
        done = result.get("life_cycle_state") in ("TERMINATED", "SKIPPED", "INTERNAL_ERROR")
        validation = result.get("validation") or {}
        if sid:
            wf["specs"].setdefault(sid, {}).update(
                run_id=result["run_id"],
                run_state=result.get("result_state") or result.get("life_cycle_state"),
                validation_passed=validation.get("passed"),
            )
        wf["stage"] = "executed" if done else "running"
    elif tool_name == "validate_output":
        sid = wf.get("active_spec_id")
        if sid:
            wf["specs"].setdefault(sid, {}).update(validation_passed=result.get("passed"), validation_errors=result.get("error_count"))
    return wf


def workflow_text(wf: dict[str, Any]) -> str:
    wf = wf or EMPTY_WORKFLOW
    lines = [
        f"- stage: {wf.get('stage')} → next: {NEXT_STEP.get(wf.get('stage'), '')}",
        f"- study: {wf.get('study_id') or '?'}; source table: {wf.get('source_table') or '?'}; active spec: {wf.get('active_spec_id') or '-'}",
    ]
    for sid, s in (wf.get("specs") or {}).items():
        lines.append(f"- spec {sid}: {json.dumps(s, default=str)}")
    return "\n".join(lines)
