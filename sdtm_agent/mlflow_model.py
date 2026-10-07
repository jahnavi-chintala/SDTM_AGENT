"""MLflow ChatAgent wrapper so the SDTM agent can be served by Databricks Model Serving.

Logged with MLflow "models from code" (see notebooks/01_deploy_agent.py).
"""

from __future__ import annotations

import os
import uuid
from typing import Any, Optional

import mlflow
from mlflow.pyfunc import ChatAgent
from mlflow.types.agent import ChatAgentMessage, ChatAgentResponse, ChatContext

from sdtm_agent.agent import SDTMAgent


def _load_config() -> dict[str, Any]:
    try:
        return mlflow.models.ModelConfig().to_dict()
    except Exception:
        return {}


class SDTMChatAgent(ChatAgent):
    def __init__(self):
        config = _load_config()
        if config.get("warehouse_id") and not os.environ.get("SDTM_WAREHOUSE_ID"):
            os.environ["SDTM_WAREHOUSE_ID"] = str(config["warehouse_id"])
        self.agent = SDTMAgent(
            llm_endpoint=config.get("llm_endpoint"),
            max_iterations=int(config.get("max_iterations", 8)),
        )

    def predict(
        self,
        messages: list[ChatAgentMessage],
        context: Optional[ChatContext] = None,
        custom_inputs: Optional[dict[str, Any]] = None,
    ) -> ChatAgentResponse:
        history = [m.model_dump(exclude_none=True) for m in messages]
        new_messages = self.agent.run(history)
        return ChatAgentResponse(
            messages=[ChatAgentMessage(id=str(uuid.uuid4()), **m) for m in new_messages]
        )


mlflow.models.set_model(SDTMChatAgent())
