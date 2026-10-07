# Databricks notebook source
# MAGIC %md
# MAGIC # SDTM Mapping Agent — setup and SDTM IG vector index
# MAGIC
# MAGIC 1. Creates the metadata schema and tables (`mapping_specs`, `validation_results`, `sdtm_ig_chunks`).
# MAGIC 2. Builds the SDTM IG corpus: built-in IG metadata + licensed IG documents from a UC volume (optional)
# MAGIC    + approved mapping specs (feedback loop).
# MAGIC 3. Creates / syncs the Vector Search endpoint and Delta Sync index.
# MAGIC
# MAGIC Safe to re-run. The `refresh_sdtm_index` job runs this notebook on a schedule.

# COMMAND ----------

# MAGIC %pip install -q -r ../requirements.txt
# MAGIC %restart_python

# COMMAND ----------

dbutils.widgets.text("metadata_schema", "main.sdtm_agent")
dbutils.widgets.text("vector_search_endpoint", "sdtm-agent-vs")
dbutils.widgets.text("vector_search_index", "main.sdtm_agent.sdtm_ig_index")
dbutils.widgets.text("embedding_endpoint", "databricks-gte-large-en")
dbutils.widgets.text("ig_volume_path", "")  # e.g. /Volumes/main/sdtm_agent/sdtm_ig (licensed IG PDF/text)

metadata_schema = dbutils.widgets.get("metadata_schema")
vs_endpoint = dbutils.widgets.get("vector_search_endpoint")
vs_index = dbutils.widgets.get("vector_search_index")
embedding_endpoint = dbutils.widgets.get("embedding_endpoint")
ig_volume_path = dbutils.widgets.get("ig_volume_path")

# COMMAND ----------

import os
import sys

sys.path.insert(0, os.path.abspath(".."))

from sdtm_agent.config import load_config
from sdtm_agent.spec_store import ddl
from sdtm_agent.vector_index import build_corpus_table, ensure_index

config = load_config({"metadata_schema": metadata_schema, "vector_search_index": vs_index})

# COMMAND ----------

# MAGIC %md ## 1. Metadata tables

# COMMAND ----------

for statement in ddl(config):
    spark.sql(statement)
print(f"Tables ready in {metadata_schema}")

# COMMAND ----------

# MAGIC %md ## 2. SDTM IG corpus

# COMMAND ----------

n = build_corpus_table(spark, config, ig_volume_path or None)
print(f"{n} chunks in {metadata_schema}.sdtm_ig_chunks")
display(spark.sql(f"SELECT domain, chunk_type, COUNT(*) AS chunks FROM {metadata_schema}.sdtm_ig_chunks GROUP BY ALL ORDER BY ALL"))

# COMMAND ----------

# MAGIC %md ## 3. Vector Search index

# COMMAND ----------

ensure_index(config, vs_endpoint, embedding_endpoint)
print(f"Index {vs_index} synced on endpoint {vs_endpoint}")
