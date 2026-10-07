"""LLM access through the Databricks Foundation Model API (LangChain chat model)."""

from __future__ import annotations

from typing import Any

from sdtm_agent.config import get_config

_chat_model: Any = None


def get_chat_model() -> Any:
    global _chat_model
    if _chat_model is None:
        from databricks_langchain import ChatDatabricks

        _chat_model = ChatDatabricks(endpoint=get_config().llm_endpoint, temperature=0.0, max_tokens=4096)
    return _chat_model


def set_chat_model(model: Any) -> None:
    """Override the chat model (tests, or a different provider)."""
    global _chat_model
    _chat_model = model
