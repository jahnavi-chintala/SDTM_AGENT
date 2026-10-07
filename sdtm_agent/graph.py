"""LangGraph definition of the SDTM mapping agent.

    START → agent ──tool calls──▶ tools → track ─┐
              ▲                                  │
              └──────────────────────────────────┘
              └── no tool calls ──▶ END

- agent: LLM (Databricks Foundation Model API) with the SDTM tools bound.
- tools: executes the requested tool calls.
- track: deterministic step that reads tool results and advances the mapping
  workflow state (source → draft spec → approved → executed → validated).
  The state is injected into the agent prompt as the next required step and
  returned to the client as custom_outputs so it persists across turns.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from sdtm_agent.knowledge import V1_DOMAINS
from sdtm_agent.workflow import EMPTY_WORKFLOW, SYSTEM_PROMPT, parse_tool_result, workflow_text, update_workflow


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    workflow: dict[str, Any]


def build_graph(llm: Any, tools: list, trial_design: str = "SV", max_iterations: int = 20):
    model = llm.bind_tools(tools)
    tool_node = ToolNode(tools, handle_tool_errors=True)

    def agent(state: AgentState) -> dict:
        prompt = SYSTEM_PROMPT.format(
            domains=", ".join(V1_DOMAINS), trial_design=trial_design, workflow=workflow_text(state.get("workflow"))
        )
        response = model.invoke([SystemMessage(content=prompt)] + state["messages"])
        return {"messages": [response]}

    def track(state: AgentState) -> dict:
        wf = state.get("workflow") or EMPTY_WORKFLOW
        # Tool messages produced by the last tools step are at the end of the list.
        new_tool_msgs = []
        for msg in reversed(state["messages"]):
            if not isinstance(msg, ToolMessage):
                break
            new_tool_msgs.insert(0, msg)
        for msg in new_tool_msgs:
            wf = update_workflow(wf, msg.name or "", parse_tool_result(msg.content))
        return {"workflow": wf}

    def route(state: AgentState) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent)
    graph.add_node("tools", tool_node)
    graph.add_node("track", track)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route, {"tools": "tools", END: END})
    graph.add_edge("tools", "track")
    graph.add_edge("track", "agent")
    return graph.compile().with_config(recursion_limit=3 * max_iterations + 1)
