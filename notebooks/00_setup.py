# Databricks notebook source
# MAGIC %md
# MAGIC # SDTM Mapping Agent — setup and SDTM IG vector index
# MAGIC
# MAGIC 1. Creates the metadata schema and tables (`mapping_specs`, `validation_results`, `sdtm_ig_chunks`).
# MAGIC 2. Builds the SDTM IG corpus: built-in IG metadata + licensed IG documents and CDISC Library
# MAGIC    .xlsx exports (one SDTMIG and one CDASHIG version) from a UC volume
# MAGIC    + approved mapping specs (feedback loop).
# MAGIC 3. Creates / syncs the Vector Search endpoint and Delta Sync index.
# MAGIC
# MAGIC Safe to re-run. The `refresh_sdtm_index` job runs this notebook on a schedule.

# COMMAND ----------

# MAGIC %pip install -q -r ../requirements.txt
# MAGIC %restart_python

# COMMAND ----------

dbutils.widgets.text("metadata_schema", "workspace.sdtm_agent")
dbutils.widgets.text("vector_search_endpoint", "sdtm-agent-vs")
dbutils.widgets.text("vector_search_index", "workspace.sdtm_agent.sdtm_ig_index")
dbutils.widgets.text("embedding_endpoint", "databricks-gte-large-en")
# Licensed IG documents and/or CDISC Library .xlsx exports (SDTMIG, SDTM, CDASHIG; several versions)
dbutils.widgets.text("ig_volume_path", "/Volumes/workspace/sdtm_agent/cdisc_library")
dbutils.widgets.text("sdtmig_version", "")   # e.g. 3.4; empty = latest in the volume
dbutils.widgets.text("cdashig_version", "")  # e.g. 2.3; empty = latest in the volume

metadata_schema = dbutils.widgets.get("metadata_schema")
vs_endpoint = dbutils.widgets.get("vector_search_endpoint")
vs_index = dbutils.widgets.get("vector_search_index")
embedding_endpoint = dbutils.widgets.get("embedding_endpoint")
ig_volume_path = dbutils.widgets.get("ig_volume_path")
sdtmig_version = dbutils.widgets.get("sdtmig_version")
cdashig_version = dbutils.widgets.get("cdashig_version")

# COMMAND ----------

import os
import sys

sys.path.insert(0, os.path.abspath(".."))

from sdtm_agent.config import load_config
from sdtm_agent.spec_store import ddl
from sdtm_agent.vector_index import build_corpus_table, ensure_index

config = load_config({"metadata_schema": metadata_schema, "vector_search_index": vs_index,
                      "sdtmig_version": sdtmig_version, "cdashig_version": cdashig_version})

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
