"""MLflow ChatAgent implementation of the SDTM mapping agent.

Logged with MLflow "models from code" (notebooks/02_log_and_deploy_agent.py) and
served by Mosaic AI Model Serving at /serving-endpoints/<name>/invocations.

Request custom_inputs (sent by the chat app):
  user               reviewer identity (from Databricks Apps SSO headers)
  approve_spec_ids   "spec_id:version" the reviewer approved with the UI button in this turn
  workflow           workflow state returned by the previous turn
Response custom_outputs:
  workflow           updated workflow state
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Generator, Optional

import mlflow
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from mlflow.pyfunc import ChatAgent
from mlflow.types.agent import ChatAgentChunk, ChatAgentMessage, ChatAgentResponse, ChatContext

from sdtm_agent.config import (
    RequestContext,
    get_config,
    load_config,
    reset_request_context,
    set_config,
    set_request_context,
)


# ---------------------------------------------------------------------- message conversion
def _text(content: Any) -> str:
    if isinstance(content, list):
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return content or ""


def to_langchain(messages: list[dict]) -> list[BaseMessage]:
    out: list[BaseMessage] = []
    for m in messages:
        role, content = m.get("role"), m.get("content") or ""
        if role == "user":
            out.append(HumanMessage(content=content))
        elif role == "system":
            out.append(SystemMessage(content=content))
        elif role == "assistant":
            calls = [
                {
                    "id": tc["id"],
                    "name": tc["function"]["name"],
                    "args": json.loads(tc["function"].get("arguments") or "{}"),
                }
                for tc in m.get("tool_calls") or []
            ]
            out.append(AIMessage(content=content, tool_calls=calls))
        elif role == "tool":
            out.append(ToolMessage(content=content, tool_call_id=m.get("tool_call_id"), name=m.get("name")))
    return out


def to_chat_agent_dict(message: BaseMessage) -> dict | None:
    msg_id = getattr(message, "id", None) or str(uuid.uuid4())
    if isinstance(message, AIMessage):
        d: dict[str, Any] = {"role": "assistant", "content": _text(message.content), "id": msg_id}
        if message.tool_calls:
            d["tool_calls"] = [
                {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": json.dumps(tc["args"])}}
                for tc in message.tool_calls
            ]
        return d
    if isinstance(message, ToolMessage):
        return {
            "role": "tool",
            "content": _text(message.content),
            "tool_call_id": message.tool_call_id,
            "name": message.name or "tool",
            "id": msg_id,
        }
    return None


# ---------------------------------------------------------------------- agent
def _model_config() -> dict:
    try:
        return mlflow.models.ModelConfig().to_dict()
    except Exception:
        return {}


class SDTMMappingAgent(ChatAgent):
    def __init__(self, llm: Any = None, tools: list | None = None, config_overrides: dict | None = None):
        from sdtm_agent.graph import build_graph
        from sdtm_agent.llm import get_chat_model
        from sdtm_agent.tools import ALL_TOOLS

        set_config(load_config({**_model_config(), **(config_overrides or {})}))
        cfg = get_config()
        self.graph = build_graph(
            llm or get_chat_model(), tools or ALL_TOOLS, trial_design=cfg.trial_design_domain, max_iterations=cfg.max_iterations
        )

    def _prepare(self, messages: list[ChatAgentMessage], custom_inputs: Optional[dict]) -> tuple[dict, Any]:
        ci = custom_inputs or {}
        ctx = RequestContext(user=str(ci.get("user") or "unknown"), approved_spec_ids=set(ci.get("approve_spec_ids") or []))
        token = set_request_context(ctx)
        history = [m.model_dump(exclude_none=True) for m in messages]
        state = {"messages": to_langchain(history), "workflow": ci.get("workflow") or {}}
        return state, token

    def _run(self, state: dict) -> Generator[tuple[str, Any], None, None]:
        for update in self.graph.stream(state, stream_mode="updates"):
            for node_output in update.values():
                if not node_output:
                    continue
                for msg in node_output.get("messages", []):
                    d = to_chat_agent_dict(msg)
                    if d:
                        yield "message", d
                if "workflow" in node_output:
                    yield "workflow", node_output["workflow"]

    def predict(
        self,
        messages: list[ChatAgentMessage],
        context: Optional[ChatContext] = None,
        custom_inputs: Optional[dict[str, Any]] = None,
    ) -> ChatAgentResponse:
        state, token = self._prepare(messages, custom_inputs)
        out, workflow = [], state["workflow"]
        try:
            for kind, value in self._run(state):
                if kind == "message":
                    out.append(ChatAgentMessage(**value))
                else:
                    workflow = value
        finally:
            reset_request_context(token)
        return ChatAgentResponse(messages=out, custom_outputs={"workflow": workflow})

    def predict_stream(
        self,
        messages: list[ChatAgentMessage],
        context: Optional[ChatContext] = None,
        custom_inputs: Optional[dict[str, Any]] = None,
    ) -> Generator[ChatAgentChunk, None, None]:
        state, token = self._prepare(messages, custom_inputs)
        workflow = state["workflow"]
        try:
            for kind, value in self._run(state):
                if kind == "message":
                    yield ChatAgentChunk(delta=ChatAgentMessage(**value))
                else:
                    workflow = value
            yield ChatAgentChunk(
                delta=ChatAgentMessage(id=str(uuid.uuid4()), role="assistant", content=""),
                custom_outputs={"workflow": workflow},
            )
        finally:
            reset_request_context(token)

