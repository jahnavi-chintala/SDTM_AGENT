# SDTM Mapping Agent on Databricks

A conversational agent that maps raw (bronze) clinical study tables to CDISC SDTM datasets, using the
SDTM Implementation Guide as its only reference. A human reviews and approves every mapping in chat
before anything is written. The project is pure Python and runs on Unity Catalog, Vector Search,
Mosaic AI Model Serving, Jobs and Databricks Apps. The backend is Python; the chat UI is React (TypeScript).

```
Bronze table (UC) ──get_source_schema──┐
SDTM IG index (Vector Search) ─retrieve_sdtm_spec─┤
                                       ▼
                       generate_mapping (LLM) → DRAFT spec (Delta, versioned)
                                       │  ▲
                   review in chat:     │  │ update_mapping / preview_transform
                                       ▼  │
                       Approve button (human, recorded with SSO identity)
                                       │
                       execute_transform → Jobs API → PySpark → Silver SDTM table
                                       │
                       validate_output → findings reported in chat
                                       │
                       approved specs re-indexed nightly → retrievable examples (feedback loop)
```

## Scope (v1)

| Class | Domains |
|---|---|
| Special Purpose | DM, SV (trial design default; TA also defined: set `trial_design_domain=TA`) |
| Interventions | EX, CM |
| Events | AE, MH, DS |
| Findings | VS, LB, EG, QS, PE |

Out of scope for v1: define.xml, SUPPQUAL generation (the agent flags non-standard data for SUPP--),
and multi-study batch runs. Each session handles one study at a time, interactively.

## Deliverables → files

| # | Deliverable | Where |
|---|---|---|
| 1 | `ChatAgent` with the tool set (LangGraph) | `sdtm_agent/chat_agent.py`, `graph.py`, `tools.py`, `workflow.py` |
| 2 | Vector index setup for SDTM IG + mapping specs | `sdtm_agent/ig_corpus.py`, `vector_index.py`, `notebooks/00_setup.py` |
| 3 | PySpark transform executor (parameterized by spec) | `sdtm_agent/transform.py`, `mapping_spec.py`, `jobs/run_transform.py` |
| 4 | Validation module (variables, CT codelists, ...) | `sdtm_agent/validation.py` |
| 5 | MLflow logging + UC registration | `sdtm_agent/deployment.py`, `agent_entrypoint.py` |
| 6 | React chat frontend + FastAPI backend (Databricks App) | `app/frontend/`, `app/server.py` |
| 7 | Deployment notebook/job | `notebooks/01_log_and_deploy_agent.py`, `databricks.yml` |

## How it works

### Agent (LangGraph + MLflow `ChatAgent`)
`agent → tools → track → agent …`. The `track` node is a deterministic step. It reads each tool result
and moves the mapping workflow forward: `start → source_selected → draft_review → approved → running → executed`.
The current stage and the next required step go into the LLM's system prompt. The state is also returned
to the app (`custom_outputs.workflow`), so it carries over between turns.

| Tool | Purpose |
|---|---|
| `get_source_schema(study_id, table_name)` | Bronze table columns, types, row count, distinct sample values |
| `retrieve_sdtm_spec(domain, question)` | IG variables/core/codelists + Vector Search passages + approved mappings from earlier studies |
| `generate_mapping(source_cols, target_domain, study_id, source_table)` | LLM proposes a spec; static checks; one self-repair round; saved as **draft** |
| `execute_transform(mapping_spec, source_table)` | Starts the PySpark job for an **approved** spec, waits up to 90 s, returns validation |
| `validate_output(domain, dataset)` | Runs the conformance checks on any table |
| `list_source_tables`, `get_mapping`, `list_mappings`, `update_mapping`, `preview_transform`, `approve_mapping`, `get_transform_status` | Review loop |

### Mapping spec
Each spec maps one source table to one SDTM domain (`sdtm_agent/mapping_spec.py`). Each variable comes
from exactly one of `source`, `expression` (one Spark SQL scalar expression) or `constant`. A variable can
also have a `value_map` (raw value → controlled term) and a `date_format` (raw value → ISO 8601). Spec-level options:
- `unpivot`: turns wide Findings data into one record per test (VS, EG, QS)
- `group_by` + `aggregate`: for SV, one record per subject per visit
- `filter`, `seq_order_by`, `dm_table`: `dm_table` is used to derive `--DY`

Derived automatically: `STUDYID`, `DOMAIN`, `--SEQ`, `--DY` (from `DM.RFSTDTC`), and `--TESTCD/--TEST/--ORRES/--STRES*` when unpivoting.

Specs are versioned in `<metadata_schema>.mapping_specs`. Any edit creates a new draft version.

### Human approval gate
`approve_mapping` succeeds only when the request carries `custom_inputs.approve_spec_ids = ["<spec_id>:<version>"]`.
Only the app's **Approve** button sets this, so the LLM cannot approve a spec on its own. Approval is also
refused if the spec has errors or a newer version exists. The approver's SSO email is stored in
`approved_by`. To allow approval in plain chat instead (for example in the Review App), set `require_ui_approval=false`.

### Transform executor
`transform.build_plan` compiles a spec into Spark SQL expressions, which are executed in one of two ways:
- `build_dataframe` / `run_pyspark`: PySpark DataFrame API, used by the `sdtm_transform` job. It writes the
  Silver table and tags it with the spec ID and version.
- `compile_sql`: the same plan as one SQL query, used for `preview_transform` on the SQL warehouse during review.

Expressions in a spec are checked so they can't contain statements, subqueries or comments.

### Validation rules
`SD_REQ_MISSING`, `SD_EXP_MISSING`, `SD_NONSTANDARD`, `SD_TYPE`, `SD_REQ_NULL`, `SD_DOMAIN`, `SD_CT`, `SD_ISO8601`,
`SD_SEQ_UNIQUE`, `SD_DM_UNIQUE`, `SD_DM_SUBJECT`, `SD_DATE_ORDER`, `SD_VARNAME`. The results of each job run are stored in
`<metadata_schema>.validation_results`.

### Chat app (`app/`)
- `frontend/`: React + TypeScript (Vite). It shows mapping specs as tables with low-confidence rows highlighted,
  spec checks, transform previews, validation findings, run status, a collapsible trace of agent steps, and
  the **Approve vN** button. Cards update when a spec is approved or superseded. Light/dark theme; works on phones.
- `server.py`: FastAPI. Serves the built UI from `static/` and exposes `/api/chat` and `/api/me`. It calls the agent
  endpoint server-side, so the browser never holds a token. The user's identity always comes from the Databricks Apps SSO
  headers (`X-Forwarded-Email`), never from the browser. System messages sent by the browser are dropped and approval tokens are format-checked.

### Knowledge / retrieval
- `knowledge.py`: structured IG metadata for the 12 domains + TA (variables, core status, a subset of CDISC CT, standard test codes, IG assumptions).
- `ig_corpus.py` turns that metadata into chunks. It can also chunk a **licensed SDTM IG** (PDF/TXT/HTML) you place in a UC volume
  (`ig_volume_path`) and add **approved mapping specs**. All chunks are tagged by domain.
- `cdisc_library.py` reads **CDISC Library Excel exports** in the same volume (`SDTMIG_v*.xlsx`, `SDTM_v*.xlsx`,
  `CDASHIG_v*.xlsx`; default volume `/Volumes/workspace/sdtm_agent/cdisc_library`).
  - It indexes one SDTMIG version (`sdtmig_version`, default the latest found) with its SDTM model.
  - It also indexes one CDASHIG version (`cdashig_version`), whose fields carry their SDTMIG target.
  - Indexing a single version stops retrieval from mixing definitions across versions.
- The Delta Sync Vector Search index uses `databricks-gte-large-en`. If the index is unavailable, retrieval falls back to keyword search over the built-in corpus.

CDISC IG text and the full CT are licensed, so they are not bundled here. Load them into the volume to improve retrieval,
and extend `CONTROLLED_TERMINOLOGY` (or point it at a CT table) for full codelist coverage.

## Setup

**Full step-by-step guide: [docs/DATABRICKS_SETUP.md](docs/DATABRICKS_SETUP.md).** Summary:

Prerequisites: Unity Catalog, serverless jobs, Model Serving, Vector Search, Databricks Apps,
a SQL warehouse, and the Databricks CLI ≥ 0.250 (`databricks auth login`).

1. **Service principal for the agent.** The agent writes specs and starts jobs, which automatic auth passthrough does not cover. Create a
   service principal and an OAuth secret for it, then store `host`, `client_id` and `client_secret` in a secret scope. Grant it:
   - `USE CATALOG`/`USE SCHEMA`/`SELECT` on the bronze schemas
   - `ALL PRIVILEGES` (or `CREATE TABLE`+`MODIFY`) on the Silver SDTM schemas and on the metadata schema
   - `CAN USE` on the warehouse, `CAN MANAGE RUN` on the `sdtm_transform` job, `CAN QUERY` on the LLM endpoint
2. **Deploy jobs:**
   ```bash
   databricks bundle deploy -t dev \
     --var="warehouse_id=<id>" --var="secret_scope=<scope>" \
     --var="bronze_schema={study_id}_bronze" --var="silver_schema={study_id}_sdtm"
   ```
   If this first deploy fails because the agent endpoint does not exist yet, comment out the `apps:` block,
   deploy, run step 3, then restore the block.
3. **Create the index, then log, register and deploy the agent:**
   `databricks bundle run setup_and_deploy_agent -t dev` (endpoint creation takes about 15 min).
4. **Build the UI and start the chat app** (Node 18+):
   ```bash
   npm --prefix app ci && npm --prefix app run build      # → app/static
   databricks bundle deploy -t dev && databricks bundle run sdtm_chatbot -t dev
   ```

The bundle wires the transform job ID into the agent config. The `refresh_sdtm_index` job re-indexes
approved specs nightly.

## Open questions and the defaults chosen

| Question | Default in this build | How to change |
|---|---|---|
| SV vs TA | **SV**: it can be derived from subject visit data; TA is protocol-level and is better entered than derived | `trial_design_domain` variable (both domains are defined) |
| Is PE needed? | Included; the IG notes say it may be dropped when only "exam done" is collected | Simply don't map it |
| Bronze schema consistency | One schema per study, pattern `{study_id}_bronze`; the agent profiles each table rather than assuming a layout | `bronze_catalog` / `bronze_schema` |
| App auth model | The app backend calls the endpoint as the app's service principal; the user's SSO email is passed for audit | `SDTM_APP_AUTH=user` in `app/app.yaml` (+ enable user authorization) to call as the signed-in user |
| Who approves, feedback loop | Any app user with access can click Approve; it is recorded per version; approved specs are indexed as examples | Restrict app access to reviewers via app permissions; add a role check in `approve_mapping` if needed |

## Local development

```bash
pip install -e ".[agent,dev]"
pip install fastapi httpx uvicorn   # for the app backend tests
pip install pyspark==3.5.3 delta-spark==3.2.1   # optional: end-to-end Spark tests (needs Java 17+)
pytest              # PySpark executor test runs only if pyspark is installed
npm --prefix app run typecheck
```
The tests use a fake SQL runner and a scripted LLM, so they need no Databricks connection.
To run the UI locally against a deployed endpoint (uses your Databricks CLI profile):
```bash
pip install -r app/requirements.txt
SERVING_ENDPOINT=sdtm-mapping-agent python app/server.py     # API on :8000
npm --prefix app install && npm --prefix app run dev           # UI on :5173, proxies /api to :8000
```
