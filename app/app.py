"""Streamlit chat interface for the SDTM agent, deployed as a Databricks App."""

import json
import os

import streamlit as st
from databricks.sdk import WorkspaceClient

SERVING_ENDPOINT = os.environ.get("SERVING_ENDPOINT", "sdtm-agent")

EXAMPLES = [
    "What are the required variables in the AE domain?",
    "Map these raw columns to SDTM: patient_id, gender, dob, site_no, treatment_arm",
    "List the tables in main.clinical_raw",
    "Validate main.sdtm.dm against the DM domain",
]

st.set_page_config(page_title="SDTM Assistant", page_icon="🧬", layout="wide")


@st.cache_resource
def get_client() -> WorkspaceClient:
    return WorkspaceClient()


def query_agent(messages: list[dict]) -> list[dict]:
    """Call the agent serving endpoint with the chat history (ChatAgent schema)."""
    payload = {"messages": [{"role": m["role"], "content": m["content"]} for m in messages]}
    response = get_client().api_client.do(
        "POST", f"/serving-endpoints/{SERVING_ENDPOINT}/invocations", body=payload
    )
    return response.get("messages", [])


def render_tool_steps(steps: list[dict]) -> None:
    calls = [s for s in steps if s.get("tool_calls") or s.get("role") == "tool"]
    if not calls:
        return
    with st.expander(f"🔧 Agent steps ({sum(1 for s in calls if s.get('role') == 'tool')} tool calls)"):
        for step in calls:
            if step.get("role") == "assistant":
                for tc in step["tool_calls"]:
                    fn = tc["function"]
                    st.markdown(f"**Call** `{fn['name']}`")
                    st.code(fn.get("arguments") or "{}", language="json")
            else:
                st.markdown(f"**Result** `{step.get('name', '')}`")
                try:
                    st.json(json.loads(step["content"]), expanded=False)
                except (ValueError, TypeError):
                    st.code(step.get("content", ""))


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("🧬 SDTM Assistant")
    st.caption(f"Agent endpoint: `{SERVING_ENDPOINT}`")
    st.markdown(
        "Ask about SDTM domains, controlled terminology, raw-to-SDTM mappings, "
        "or have the agent query and validate tables in Unity Catalog."
    )
    if st.button("Clear conversation", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
    st.subheader("Try asking")
    for example in EXAMPLES:
        if st.button(example, use_container_width=True):
            st.session_state.pending = example

# ---------------------------------------------------------------- chat
st.title("SDTM Agent Chat")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        render_tool_steps(message.get("steps", []))
        st.markdown(message["content"])

prompt = st.chat_input("Ask the SDTM agent...") or st.session_state.pop("pending", None)

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                new_messages = query_agent(st.session_state.messages)
                final = next(
                    (m for m in reversed(new_messages) if m.get("role") == "assistant" and m.get("content")),
                    {"content": "_The agent returned no answer._"},
                )
                answer, steps = final["content"], new_messages
            except Exception as exc:
                answer, steps = f"⚠️ Error calling `{SERVING_ENDPOINT}`: {exc}", []
        render_tool_steps(steps)
        st.markdown(answer)

    st.session_state.messages.append({"role": "assistant", "content": answer, "steps": steps})
