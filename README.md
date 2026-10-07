# SDTM Agent — Databricks Chatbot

A chat assistant for CDISC SDTM work that runs entirely on Databricks:

```
┌──────────────────────┐    REST     ┌─────────────────────────────┐   OpenAI-compatible   ┌──────────────────────┐
│ Databricks App       │ ──────────▶ │ Model Serving endpoint      │ ───────────────────▶ │ Foundation model     │
│ (Streamlit chat, app/)│            │ "sdtm-agent" (MLflow        │                      │ (tool calling LLM)   │
└──────────────────────┘             │  ChatAgent, sdtm_agent/)    │ ── Statement API ──▶ │ SQL warehouse / UC   │
                                     └─────────────────────────────┘                      └──────────────────────┘
```

## What the agent can do

| Tool | Purpose |
|---|---|
| `list_sdtm_domains`, `get_sdtm_domain_spec` | SDTMIG variables, labels, types and core (Req/Exp/Perm) for DM, AE, VS, LB, CM, EX, MH, DS |
| `get_controlled_terminology` | CDISC codelists (SEX, RACE, AESEV, AEOUT, …) |
| `suggest_sdtm_mapping` | Map raw/EDC column names to SDTM domains and variables |
| `list_tables`, `describe_table`, `run_sql_query` | Read-only exploration of Unity Catalog tables (writes are blocked) |
| `validate_sdtm_table` | Conformance check: missing Req/Exp variables, nulls in Req variables, codelist violations, duplicate subjects |

Example questions:
- *What are the required variables in the AE domain?*
- *Map these raw columns to SDTM: patient_id, gender, dob, site_no, treatment_arm*
- *Validate `main.sdtm.dm` against DM and write Spark SQL to fix the issues.*

## Repository layout

```
databricks.yml               Databricks Asset Bundle (deploy job + app)
requirements.txt             Agent dependencies
sdtm_agent/
  knowledge.py               SDTM domain specs, controlled terminology, column synonyms
  tools.py                   Tool functions + OpenAI tool specs
  agent.py                   Tool-calling loop against a Databricks LLM endpoint
  mlflow_model.py            MLflow ChatAgent wrapper (models-from-code)
notebooks/01_deploy_agent.py Log → register in UC → deploy to Model Serving
app/                         Streamlit chat UI (Databricks App)
tests/                       Unit tests (no Databricks connection required)
```

## Setup

### Prerequisites
- A Databricks workspace with Unity Catalog, Model Serving and Databricks Apps enabled
- A Foundation Model endpoint that supports tool calling (default `databricks-meta-llama-3-3-70b-instruct`;
  any Claude/Llama pay-per-token endpoint in your workspace works)
- A SQL warehouse ID (for the SQL/validation tools)
- [Databricks CLI](https://docs.databricks.com/dev-tools/cli/install.html) ≥ 0.250, authenticated: `databricks auth login --host <workspace-url>`

### 1. Deploy the agent endpoint
The app depends on the serving endpoint, so create the endpoint first. Either:

- **From the workspace:** add this repo as a Git folder, open `notebooks/01_deploy_agent.py`, set the widgets
  (`catalog`, `schema`, `endpoint_name`, `llm_endpoint`, `warehouse_id`) and *Run all*; or
- **With the bundle:**
  ```bash
  databricks bundle deploy -t dev --var="warehouse_id=<id>" --var="catalog=<catalog>"
  databricks bundle run deploy_sdtm_agent -t dev --var="warehouse_id=<id>" --var="catalog=<catalog>"
  ```
  (If the first `bundle deploy` complains that the endpoint does not exist yet, use the notebook route once.)

Endpoint creation takes ~15 minutes. The model is registered as `<catalog>.<schema>.sdtm_agent`.

### 2. Deploy and start the chat app
```bash
databricks bundle deploy -t dev --var="warehouse_id=<id>"
databricks bundle run sdtm_chatbot -t dev
```
The CLI prints the app URL. The app's service principal is granted `CAN_QUERY` on the agent endpoint
automatically through the app resource in `databricks.yml`.

### 3. Grant data access
The agent queries data with the permissions of the serving endpoint's identity. Give it access to the
clinical data, e.g.:
```sql
GRANT USE CATALOG ON CATALOG main TO `<service-principal>`;
GRANT USE SCHEMA, SELECT ON SCHEMA main.sdtm TO `<service-principal>`;
```

## Local development
```bash
pip install -r requirements.txt pytest
pytest tests

# Run the chat UI locally against a deployed endpoint
pip install -r app/requirements.txt
export SERVING_ENDPOINT=sdtm-agent   # uses your Databricks CLI profile for auth
streamlit run app/app.py
```

## Extending
- **More domains / terminology:** add entries to `DOMAINS`, `CONTROLLED_TERMINOLOGY` and `COLUMN_SYNONYMS`
  in `sdtm_agent/knowledge.py`. For full SDTMIG coverage, load the CDISC Library export into a UC table and
  point a tool at it.
- **New tools:** add a function to `sdtm_agent/tools.py`, register it in `TOOLS` and describe it in `TOOL_SPECS`.
- **Evaluation & review:** `agents.deploy` also creates a Review App and inference tables; use
  `mlflow.genai.evaluate` with a set of SDTM questions to track answer quality.
