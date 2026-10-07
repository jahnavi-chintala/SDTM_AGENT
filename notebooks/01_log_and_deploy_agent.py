# Databricks notebook source
# MAGIC %md
# MAGIC # SDTM Mapping Agent — test, log, register and deploy
# MAGIC
# MAGIC 1. Smoke-test the LangGraph agent in this notebook
# MAGIC 2. Log it with MLflow (models from code) and register it in Unity Catalog
# MAGIC 3. Deploy to Mosaic AI Model Serving (`/serving-endpoints/<name>/invocations`)

# COMMAND ----------

# MAGIC %pip install -q -r ../requirements.txt
# MAGIC %restart_python

# COMMAND ----------

dbutils.widgets.text("uc_model_name", "main.sdtm_agent.sdtm_mapping_agent")
dbutils.widgets.text("endpoint_name", "sdtm-mapping-agent")
dbutils.widgets.text("secret_scope", "")  # service principal OAuth creds: host, client_id, client_secret
dbutils.widgets.text("llm_endpoint", "databricks-meta-llama-3-3-70b-instruct")
dbutils.widgets.text("warehouse_id", "")
dbutils.widgets.text("bronze_catalog", "main")
dbutils.widgets.text("bronze_schema", "{study_id}_bronze")
dbutils.widgets.text("silver_catalog", "main")
dbutils.widgets.text("silver_schema", "{study_id}_sdtm")
dbutils.widgets.text("metadata_schema", "main.sdtm_agent")
dbutils.widgets.text("vector_search_index", "main.sdtm_agent.sdtm_ig_index")
dbutils.widgets.text("transform_job_id", "")
dbutils.widgets.dropdown("trial_design_domain", "SV", ["SV", "TA"])
dbutils.widgets.dropdown("require_ui_approval", "true", ["true", "false"])
dbutils.widgets.text("smoke_test_question", "Which variables are required in SDTM AE, and which use controlled terminology?")

uc_model_name = dbutils.widgets.get("uc_model_name")
endpoint_name = dbutils.widgets.get("endpoint_name")
secret_scope = dbutils.widgets.get("secret_scope")
agent_config = {
    key: dbutils.widgets.get(key)
    for key in (
        "llm_endpoint",
        "warehouse_id",
        "bronze_catalog",
        "bronze_schema",
        "silver_catalog",
        "silver_schema",
        "metadata_schema",
        "vector_search_index",
        "transform_job_id",
        "trial_design_domain",
        "require_ui_approval",
    )
}
agent_config["transform_wait_seconds"] = 90
print(agent_config)

# COMMAND ----------

import os
import sys

sys.path.insert(0, os.path.abspath(".."))

# COMMAND ----------

# MAGIC %md ## 1. Smoke test

# COMMAND ----------

from mlflow.types.agent import ChatAgentMessage

from sdtm_agent.chat_agent import SDTMMappingAgent

agent = SDTMMappingAgent(config_overrides=agent_config)
response = agent.predict(
    [ChatAgentMessage(id="1", role="user", content=dbutils.widgets.get("smoke_test_question"))],
    custom_inputs={"user": spark.sql("SELECT current_user()").first()[0]},
)
for m in response.messages:
    print(f"[{m.role}] {(m.content or '')[:400]}", m.tool_calls or "")
print(response.custom_outputs)

# COMMAND ----------

# MAGIC %md ## 2. Log and register in Unity Catalog

# COMMAND ----------

import mlflow

from sdtm_agent.deployment import log_and_register

model_info = log_and_register(agent_config, uc_model_name)
print(model_info.model_uri, "→", uc_model_name, "version", model_info.registered_model_version)

# COMMAND ----------

# Make sure the logged model loads and answers before deploying it.
loaded = mlflow.pyfunc.load_model(model_info.model_uri)
print(loaded.predict({"messages": [{"role": "user", "content": "List the SDTM domains you support."}]}))

# COMMAND ----------

# MAGIC %md ## 3. Deploy to Model Serving

# COMMAND ----------

from sdtm_agent.deployment import deploy_endpoint

deployment = deploy_endpoint(uc_model_name, model_info.registered_model_version, endpoint_name, secret_scope or None)
print(deployment)
