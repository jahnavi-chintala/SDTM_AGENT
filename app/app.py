"""SDTM Mapping Agent — Streamlit chat frontend (Databricks App).

Calls the agent's Model Serving endpoint and renders each turn: the answer,
the agent's tool steps, mapping spec tables with Approve buttons, transform
previews and validation findings.

Auth: the app's service principal calls the endpoint (default). Set
SDTM_APP_AUTH=user and enable user authorization for the app to call it with
the signed-in user's token instead. Either way the user's SSO identity is sent
to the agent for the audit trail (created_by / approved_by).
"""

from __future__ import annotations

import json
import os

import pandas as pd
import requests
import streamlit as st
from databricks.sdk import WorkspaceClient

SERVING_ENDPOINT = os.environ.get("SERVING_ENDPOINT", "sdtm-mapping-agent")
AUTH_MODE = os.environ.get("SDTM_APP_AUTH", "service_principal")
TIMEOUT_SECONDS = 300
SPEC_TOOLS = {"generate_mapping", "update_mapping", "get_mapping"}

EXAMPLES = [
    "List the source tables for study {study}",
    "Map the demographics table of study {study} to DM",
    "Propose the AE mapping for study {study} from table ae_raw",
    "Show the mapping specs for study {study}",
]

st.set_page_config(page_title="SDTM Mapping Agent", page_icon="🧬", layout="wide")


# ---------------------------------------------------------------- endpoint
@st.cache_resource
def workspace() -> WorkspaceClient:
    return WorkspaceClient()


def current_user() -> tuple[str, str | None]:
    headers = st.context.headers
    user = headers.get("X-Forwarded-Email") or headers.get("X-Forwarded-Preferred-Username") or "local-user"
    return user, headers.get("X-Forwarded-Access-Token")


def call_agent(messages: list[dict], custom_inputs: dict) -> dict:
    w = workspace()
    user_token = current_user()[1]
    if AUTH_MODE == "user" and user_token:
        headers = {"Authorization": f"Bearer {user_token}"}
    else:
        headers = w.config.authenticate()
    resp = requests.post(
        f"{w.config.host.rstrip('/')}/serving-endpoints/{SERVING_ENDPOINT}/invocations",
        headers={**headers, "Content-Type": "application/json"},
        json={"messages": messages, "custom_inputs": custom_inputs},
        timeout=TIMEOUT_SECONDS,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"{resp.status_code}: {resp.text[:500]}")
    return resp.json()


# ---------------------------------------------------------------- rendering
def _tool_results(steps: list[dict]) -> list[tuple[str, dict]]:
    out = []
    for s in steps:
        if s.get("role") == "tool":
            try:
                out.append((s.get("name", ""), json.loads(s.get("content") or "{}")))
            except ValueError:
                out.append((s.get("name", ""), {"raw": s.get("content")}))
    return out


def render_spec(spec: dict, key: str) -> None:
    status = spec.get("status", "draft")
    badge = {"approved": "🟢", "draft": "🟡", "rejected": "🔴", "superseded": "⚪"}.get(status, "")
    st.markdown(
        f"**Mapping spec `{spec['spec_id']}` v{spec.get('version')}** {badge} {status} — "
        f"`{spec.get('source_table')}` → **{spec.get('domain')}** (`{spec.get('target_table')}`)"
    )
    if spec.get("mapping_table"):
        st.dataframe(pd.DataFrame(spec["mapping_table"]), hide_index=True, use_container_width=True)
    if spec.get("unpivot"):
        st.caption("Unpivot: " + ", ".join(f"{t['source_column']}→{t['testcd']}" for t in spec["unpivot"]["tests"]))
    if spec.get("filter"):
        st.caption(f"Filter: `{spec['filter']}`")
    issues = spec.get("issues") or []
    if issues:
        with st.expander(f"Spec checks: {sum(i['severity'] == 'error' for i in issues)} errors, "
                         f"{sum(i['severity'] == 'warning' for i in issues)} warnings"):
            st.dataframe(pd.DataFrame(issues), hide_index=True, use_container_width=True)
    if spec.get("notes"):
        st.info(spec["notes"])
    if status == "draft":
        has_errors = any(i["severity"] == "error" for i in issues)
        if st.button(
            f"✅ Approve {spec['domain']} spec v{spec.get('version')}",
            key=f"approve-{key}-{spec['spec_id']}-{spec.get('version')}",
            disabled=has_errors,
            help="Fix the spec errors first" if has_errors else "Records you as the approver",
        ):
            st.session_state.pending = (
                f"I approve mapping spec {spec['spec_id']} version {spec.get('version')}.",
                [f"{spec['spec_id']}:{spec.get('version')}"],
            )
            st.rerun()


def render_validation(report: dict) -> None:
    if not report:
        return
    ok = report.get("passed")
    st.markdown(
        f"**Validation of `{report.get('table') or report.get('table_name')}`:** "
        + ("✅ passed" if ok else f"❌ {report.get('error_count')} errors")
        + f", {report.get('warning_count')} warnings, {report.get('record_count')} records"
    )
    if report.get("findings"):
        df = pd.DataFrame(report["findings"])
        st.dataframe(df, hide_index=True, use_container_width=True)


def render_steps(steps: list[dict], key: str) -> None:
    results = _tool_results(steps)
    for i, (name, result) in enumerate(results):
        if "error" in result:
            continue
        if name in SPEC_TOOLS and result.get("spec_id"):
            render_spec(result, f"{key}-{i}")
        elif name == "preview_transform" and result.get("columns"):
            st.markdown(f"**Preview of spec `{result['spec_id']}` v{result['version']}**")
            st.dataframe(pd.DataFrame(result["rows"], columns=result["columns"]), hide_index=True, use_container_width=True)
        elif name == "validate_output":
            render_validation(result)
        elif name in ("execute_transform", "get_transform_status"):
            st.markdown(
                f"**Transform run** [{result.get('run_id')}]({result.get('run_page_url')}) — "
                f"{result.get('result_state') or result.get('life_cycle_state')}"
            )
            render_validation(result.get("validation"))
    calls = [s for s in steps if s.get("tool_calls")]
    if calls:
        with st.expander(f"🔧 Agent steps ({len(results)} tool calls)"):
            for s in steps:
                for tc in s.get("tool_calls") or []:
                    st.markdown(f"**→ {tc['function']['name']}**")
                    st.code(tc["function"].get("arguments") or "{}", language="json")
                if s.get("role") == "tool":
                    st.markdown(f"**← {s.get('name')}**")
                    try:
                        st.json(json.loads(s["content"]), expanded=False)
                    except (ValueError, TypeError):
                        st.code(s.get("content", ""))


# ---------------------------------------------------------------- state
st.session_state.setdefault("messages", [])
st.session_state.setdefault("workflow", {})
user, _ = current_user()

with st.sidebar:
    st.header("🧬 SDTM Mapping Agent")
    study_id = st.text_input("Study ID", value=st.session_state.get("study_id", ""), placeholder="e.g. ABC123")
    st.session_state.study_id = study_id
    st.caption(f"Signed in as {user} · endpoint `{SERVING_ENDPOINT}`")
    if st.button("New conversation", use_container_width=True):
        st.session_state.messages, st.session_state.workflow = [], {}
        st.rerun()

    wf = st.session_state.workflow
    if wf.get("specs"):
        st.subheader("Specs in this session")
        for sid, s in wf["specs"].items():
            icon = {"approved": "🟢", "draft": "🟡"}.get(s.get("status"), "⚪")
            line = f"{icon} **{s.get('domain')}** `{sid}` v{s.get('version')} — {s.get('status')}"
            if s.get("validation_passed") is not None:
                line += " · validation " + ("✅" if s["validation_passed"] else "❌")
            st.markdown(line)
    st.subheader("Try asking")
    for example in EXAMPLES:
        text = example.format(study=study_id or "<study>")
        if st.button(text, use_container_width=True, disabled=not study_id):
            st.session_state.pending = (text, [])
            st.rerun()
    st.caption(
        "Mappings are derived from the SDTM IG only and are drafts until you approve them. "
        "Nothing is written to Silver tables before approval."
    )

# ---------------------------------------------------------------- chat
st.title("SDTM Mapping Assistant")
if not study_id:
    st.info("Enter a study ID in the sidebar to start.")

for idx, m in enumerate(st.session_state.messages):
    with st.chat_message(m["role"]):
        if m["role"] == "assistant":
            render_steps(m.get("steps", []), key=str(idx))
        st.markdown(m["content"])

typed = st.chat_input("Ask the SDTM mapping agent...", disabled=not study_id)
pending = st.session_state.pop("pending", None)
prompt, approve_ids = (typed, []) if typed else (pending if pending else (None, []))

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    history = [{"role": "system", "content": f"The user is working on study {study_id}."}] + [
        {"role": m["role"], "content": m["content"]} for m in st.session_state.messages
    ]
    custom_inputs = {"user": user, "approve_spec_ids": approve_ids, "workflow": st.session_state.workflow}

    with st.chat_message("assistant"):
        with st.spinner("Working..."):
            try:
                result = call_agent(history, custom_inputs)
                steps = result.get("messages", [])
                st.session_state.workflow = (result.get("custom_outputs") or {}).get("workflow", st.session_state.workflow)
                answer = next(
                    (s["content"] for s in reversed(steps) if s.get("role") == "assistant" and s.get("content")),
                    "_The agent returned no answer._",
                )
            except Exception as exc:
                steps, answer = [], f"⚠️ Error calling `{SERVING_ENDPOINT}`: {exc}"
        render_steps(steps, key=str(len(st.session_state.messages)))
        st.markdown(answer)
    st.session_state.messages.append({"role": "assistant", "content": answer, "steps": steps})
    st.rerun()
