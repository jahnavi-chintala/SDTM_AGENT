"""MLflow "models from code" entrypoint for the SDTM mapping agent."""

import mlflow

from sdtm_agent.chat_agent import SDTMMappingAgent

mlflow.models.set_model(SDTMMappingAgent())
