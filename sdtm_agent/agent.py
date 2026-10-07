"""Tool-calling loop for the SDTM agent, using a Databricks-hosted LLM."""

from __future__ import annotations

import os
from typing import Any

from sdtm_agent.tools import TOOL_SPECS, execute_tool

DEFAULT_LLM_ENDPOINT = "databricks-meta-llama-3-3-70b-instruct"

SYSTEM_PROMPT = """You are an expert CDISC SDTM (Study Data Tabulation Model) assistant for clinical data programmers.

You help users:
- understand SDTM domains, variables, core status (Req/Exp/Perm) and controlled terminology;
- map raw/EDC source columns to SDTM domains and variables, and describe derivations
  (e.g. USUBJID = STUDYID || '-' || SITEID || '-' || SUBJID, --DY study day, ISO 8601 --DTC dates);
- explore clinical tables in Databricks Unity Catalog with read-only SQL;
- validate SDTM tables for conformance issues.

Rules:
- Use the tools to look up specifications and data instead of guessing. Cite the variables you rely on.
- Only run read-only SQL. Always fully qualify tables as catalog.schema.table.
- When proposing mapping code, write Spark SQL or PySpark that runs on Databricks.
- Be concise; use tables or bullet lists for variable lists and validation findings.
- If a question is outside SDTM / clinical data, say so briefly."""


def _to_dict(obj: Any) -> dict:
    return obj.model_dump() if hasattr(obj, "model_dump") else dict(obj)


class SDTMAgent:
    def __init__(self, llm_endpoint: str | None = None, max_iterations: int = 8, client: Any = None):
        self.llm_endpoint = llm_endpoint or os.environ.get("SDTM_LLM_ENDPOINT", DEFAULT_LLM_ENDPOINT)
        self.max_iterations = max_iterations
        self._client = client

    @property
    def client(self):
        if self._client is None:
            from databricks.sdk import WorkspaceClient

            self._client = WorkspaceClient().serving_endpoints.get_open_ai_client()
        return self._client

    def run(self, messages: list[dict]) -> list[dict]:
        """Answer the conversation; returns the new assistant and tool messages."""
        history = [{"role": "system", "content": SYSTEM_PROMPT}] + [_clean(m) for m in messages]
        new_messages: list[dict] = []

        for _ in range(self.max_iterations):
            response = self.client.chat.completions.create(
                model=self.llm_endpoint, messages=history, tools=TOOL_SPECS
            )
            msg = response.choices[0].message
            assistant: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
            tool_calls = [_to_dict(tc) for tc in (msg.tool_calls or [])]
            if tool_calls:
                assistant["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["function"]["name"],
                            "arguments": tc["function"]["arguments"],
                        },
                    }
                    for tc in tool_calls
                ]
            history.append(assistant)
            new_messages.append(assistant)

            if not tool_calls:
                return new_messages

            for tc in assistant["tool_calls"]:
                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": tc["function"]["name"],
                    "content": execute_tool(tc["function"]["name"], tc["function"]["arguments"]),
                }
                history.append(tool_msg)
                new_messages.append(tool_msg)

        new_messages.append(
            {
                "role": "assistant",
                "content": "I stopped after reaching the maximum number of tool calls. "
                "Please narrow down the question and try again.",
            }
        )
        return new_messages


def _clean(message: dict) -> dict:
    """Keep only the fields chat-completion endpoints accept."""
    allowed = {"role", "content", "tool_calls", "tool_call_id", "name"}
    out = {k: v for k, v in message.items() if k in allowed and v is not None}
    if out.get("role") != "tool":
        out.pop("name", None)
    out.setdefault("content", "")
    return out
