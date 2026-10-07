"""MLflow logging, Unity Catalog registration and Model Serving deployment."""

from __future__ import annotations

import os
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PIP_REQUIREMENTS = [
    "mlflow>=3.1.0",
    "databricks-sdk>=0.50.0",
    "databricks-langchain>=0.5.0",
    "langgraph>=1.2.0",
    "langgraph-prebuilt>=1.1.0",
    "langchain-core>=0.3.0",
    "pydantic>=2.0",
]

# Keys passed as MLflow model config (see config.AgentConfig).
CONFIG_KEYS = (
    "llm_endpoint",
    "warehouse_id",
    "bronze_catalog",
    "bronze_schema",
    "silver_catalog",
    "silver_schema",
    "metadata_schema",
    "vector_search_index",
    "transform_job_id",
    "transform_wait_seconds",
    "trial_design_domain",
    "require_ui_approval",
    "max_iterations",
)


def log_and_register(agent_config: dict[str, Any], uc_model_name: str) -> Any:
    """Log the agent with models-from-code and register it in Unity Catalog."""
    import mlflow
    from mlflow.models.resources import (
        DatabricksServingEndpoint,
        DatabricksSQLWarehouse,
        DatabricksVectorSearchIndex,
    )

    mlflow.set_registry_uri("databricks-uc")
    config = {k: agent_config[k] for k in CONFIG_KEYS if agent_config.get(k) not in (None, "")}

    # Resources enable automatic auth passthrough for these from the serving endpoint.
    resources = [
        DatabricksServingEndpoint(endpoint_name=config["llm_endpoint"]),
        DatabricksVectorSearchIndex(index_name=config["vector_search_index"]),
    ]
    if config.get("warehouse_id"):
        resources.append(DatabricksSQLWarehouse(warehouse_id=config["warehouse_id"]))

    with mlflow.start_run(run_name="sdtm_mapping_agent"):
        return mlflow.pyfunc.log_model(
            name="sdtm_mapping_agent",
            python_model=os.path.join(REPO_ROOT, "agent_entrypoint.py"),
            code_paths=[os.path.join(REPO_ROOT, "sdtm_agent")],
            model_config=config,
            resources=resources,
            input_example={
                "messages": [{"role": "user", "content": "Which variables are required in SDTM AE?"}],
                "custom_inputs": {"user": "example@company.com"},
            },
            pip_requirements=PIP_REQUIREMENTS,
            registered_model_name=uc_model_name,
        )


def deploy_endpoint(
    uc_model_name: str,
    version: int | str,
    endpoint_name: str,
    secret_scope: str | None = None,
) -> Any:
    """Deploy to Mosaic AI Model Serving with databricks-agents (also creates a review app
    and inference tables).

    The agent writes mapping specs and starts the transform job, which automatic
    auth passthrough does not cover. Give the endpoint a service principal by storing
    its OAuth credentials in `secret_scope` (keys: host, client_id, client_secret).
    """
    from databricks import agents

    env = {}
    if secret_scope:
        env = {
            "DATABRICKS_HOST": f"{{{{secrets/{secret_scope}/host}}}}",
            "DATABRICKS_CLIENT_ID": f"{{{{secrets/{secret_scope}/client_id}}}}",
            "DATABRICKS_CLIENT_SECRET": f"{{{{secrets/{secret_scope}/client_secret}}}}",
        }
    return agents.deploy(
        uc_model_name,
        int(version),
        endpoint_name=endpoint_name,
        scale_to_zero=False,
        environment_vars=env or None,
        tags={"project": "sdtm-mapping-agent"},
    )
