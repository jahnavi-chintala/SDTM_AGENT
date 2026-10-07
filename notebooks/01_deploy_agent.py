# Databricks notebook source
# MAGIC %md
# MAGIC # Deploy the SDTM agent
# MAGIC
# MAGIC 1. Smoke-test the agent in this notebook
# MAGIC 2. Log it to MLflow (models from code) and register it in Unity Catalog
# MAGIC 3. Deploy it to a Model Serving endpoint with `databricks.agents.deploy`
# MAGIC
# MAGIC The Streamlit chat app (`app/`) talks to the endpoint created here.

# COMMAND ----------

# MAGIC %pip install -q -r ../requirements.txt
# MAGIC %restart_python

# COMMAND ----------

dbutils.widgets.text("catalog", "main")
dbutils.widgets.text("schema", "sdtm_agent")
dbutils.widgets.text("model_name", "sdtm_agent")
dbutils.widgets.text("endpoint_name", "sdtm-agent")
dbutils.widgets.text("llm_endpoint", "databricks-meta-llama-3-3-70b-instruct")
dbutils.widgets.text("warehouse_id", "")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
uc_model_name = f"{catalog}.{schema}.{dbutils.widgets.get('model_name')}"
endpoint_name = dbutils.widgets.get("endpoint_name")
llm_endpoint = dbutils.widgets.get("llm_endpoint")
warehouse_id = dbutils.widgets.get("warehouse_id")

agent_config = {"llm_endpoint": llm_endpoint, "warehouse_id": warehouse_id, "max_iterations": 8}
print(uc_model_name, endpoint_name, agent_config)

# COMMAND ----------

import os
import sys

repo_root = os.path.abspath("..")
sys.path.insert(0, repo_root)
os.environ["SDTM_WAREHOUSE_ID"] = warehouse_id
os.environ["SDTM_LLM_ENDPOINT"] = llm_endpoint

# COMMAND ----------

# MAGIC %md ## 1. Smoke test

# COMMAND ----------

from sdtm_agent.agent import SDTMAgent

for m in SDTMAgent(llm_endpoint=llm_endpoint).run(
    [{"role": "user", "content": "Which variables are required in the DM domain?"}]
):
    print(m["role"], "->", m.get("tool_calls") or m["content"][:500])

# COMMAND ----------

# MAGIC %md ## 2. Log and register the agent

# COMMAND ----------

import mlflow
from mlflow.models.resources import DatabricksServingEndpoint, DatabricksSQLWarehouse

mlflow.set_registry_uri("databricks-uc")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")

# Resources enable automatic auth passthrough from the serving endpoint.
resources = [DatabricksServingEndpoint(endpoint_name=llm_endpoint)]
if warehouse_id:
    resources.append(DatabricksSQLWarehouse(warehouse_id=warehouse_id))

with mlflow.start_run(run_name="sdtm_agent"):
    model_info = mlflow.pyfunc.log_model(
        name="sdtm_agent",
        python_model=os.path.join(repo_root, "sdtm_agent", "mlflow_model.py"),
        code_paths=[os.path.join(repo_root, "sdtm_agent")],
        model_config=agent_config,
        resources=resources,
        input_example={"messages": [{"role": "user", "content": "What is the AE domain?"}]},
        pip_requirements=[
            "mlflow>=3.1.0",
            "databricks-sdk>=0.40.0",
            "openai>=1.40.0",
            "pydantic>=2.0",
        ],
        registered_model_name=uc_model_name,
    )

print(model_info.model_uri, model_info.registered_model_version)

# COMMAND ----------

# Validate the logged model loads and answers before deploying.
loaded = mlflow.pyfunc.load_model(model_info.model_uri)
print(loaded.predict({"messages": [{"role": "user", "content": "List the SDTM domains you know."}]}))

# COMMAND ----------

# MAGIC %md ## 3. Deploy to Model Serving

# COMMAND ----------

from databricks import agents

deployment = agents.deploy(
    uc_model_name,
    model_info.registered_model_version,
    endpoint_name=endpoint_name,
    scale_to_zero=True,
    environment_vars={"SDTM_WAREHOUSE_ID": warehouse_id, "SDTM_LLM_ENDPOINT": llm_endpoint},
    tags={"project": "sdtm-agent"},
)
print(deployment)
