# Setting up the SDTM Mapping Agent in Databricks

Step-by-step guide from an empty workspace to a working chat app. Expect about 1 hour, most of it waiting
for the serving endpoint and the vector index.

What gets created:

| Thing | Name (defaults) | Created by |
|---|---|---|
| Metadata schema + tables | `workspace.sdtm_agent.{mapping_specs, validation_results, sdtm_ig_chunks}` | job `setup_and_deploy_agent` |
| Vector Search endpoint + index | `sdtm-agent-vs`, `workspace.sdtm_agent.sdtm_ig_index` | job `setup_and_deploy_agent` |
| Registered model | `workspace.sdtm_agent.sdtm_mapping_agent` | job `setup_and_deploy_agent` |
| Agent serving endpoint | `sdtm-mapping-agent` | job `setup_and_deploy_agent` |
| Transform job | `[dev] SDTM transform` | `databricks bundle deploy` |
| Nightly index refresh job | `[dev] SDTM IG index refresh` | `databricks bundle deploy` |
| Chat app | `sdtm-mapping-chat` | `databricks bundle deploy` |
| Silver SDTM tables | `workspace.<study>_sdtm.<domain>` | transform job, after you approve a mapping |

---

## 0. Prerequisites

**Workspace features** (ask your admin if any are missing): Unity Catalog, serverless compute for jobs and notebooks,
Mosaic AI Model Serving, Foundation Model APIs, Vector Search, and Databricks Apps.

**Check that the LLM endpoint exists:** go to *Serving* and confirm that a pay-per-token endpoint with tool calling is listed,
e.g. `databricks-meta-llama-3-3-70b-instruct` or a `databricks-claude-*` endpoint. Also check for
`databricks-gte-large-en`, which is used for embeddings.

**On your laptop:**
- Databricks CLI ≥ 0.250: <https://docs.databricks.com/dev-tools/cli/install.html>
- Node.js 18+ (to build the React UI)
- `git clone` this repo and check out the branch

```bash
databricks auth login --host https://<your-workspace>.cloud.databricks.com
databricks current-user me        # should print your user
```

## 1. Bronze data and schemas

The agent reads one bronze schema per study, named `<study_id>_bronze` (lower-case) by default, and writes Silver
SDTM tables to `<study_id>_sdtm`. For a study `ABC123`, run this in a SQL editor:

```sql
-- bronze tables come from your existing ingestion pipeline, e.g. workspace.abc123_bronze.demog
CREATE SCHEMA IF NOT EXISTS workspace.abc123_sdtm;   -- Silver output
CREATE SCHEMA IF NOT EXISTS workspace.sdtm_agent;    -- agent metadata
```

If your schemas follow a different pattern, set the `bronze_schema` / `silver_schema` bundle variables (step 4).
`{study_id}` in them is replaced by the study ID typed in the app.

**SQL warehouse:** go to *SQL Warehouses* and use or create a serverless warehouse. Copy its **ID**, which is the last part of
the URL `/sql/warehouses/<id>`.

## 2. Service principal for the agent

The agent endpoint saves mapping specs and starts the transform job, and automatic auth passthrough does not cover that.
It therefore runs as a service principal.

1. *Settings → Identity and access → Service principals → Add*, name it `sdtm-agent`. Copy its **Application ID**.
2. On the service principal, open *Secrets → Generate secret* (OAuth). Copy the secret.
3. Store the credentials in a secret scope:
   ```bash
   databricks secrets create-scope sdtm-agent
   databricks secrets put-secret sdtm-agent host           # https://<your-workspace>.cloud.databricks.com
   databricks secrets put-secret sdtm-agent client_id      # Application ID
   databricks secrets put-secret sdtm-agent client_secret  # OAuth secret
   ```
4. Grants (replace `<app-id>` with the Application ID):
   ```sql
   GRANT USE CATALOG ON CATALOG workspace TO `<app-id>`;
   GRANT USE SCHEMA, SELECT ON SCHEMA workspace.abc123_bronze TO `<app-id>`;
   GRANT USE SCHEMA, SELECT ON SCHEMA workspace.abc123_sdtm TO `<app-id>`;
   GRANT ALL PRIVILEGES ON SCHEMA workspace.sdtm_agent TO `<app-id>`;
   ```
   - On the SQL warehouse, go to *Permissions* and give the service principal **Can use**.
   - On the Serving endpoints `databricks-meta-llama-3-3-70b-instruct` (or your LLM) and `databricks-gte-large-en`, give it **Can query** if they are not open to all users.
   - The **Can manage run** permission on the transform job is added in step 5, after the job exists.

## 3. (Optional) CDISC library and licensed SDTM IG text

Retrieval works out of the box from the built-in IG metadata. For better answers, put your licensed CDISC
content in a volume. The default is `/Volumes/workspace/sdtm_agent/cdisc_library/`; to use another, set
`ig_volume_path` in step 4. Two kinds of file are read:

- **CDISC Library Excel exports** named like `SDTMIG_v3.4.xlsx`, `SDTM_v2.0.xlsx` and `CDASHIG_v2.3.xlsx`
  (subfolders are fine).
  - Several versions can sit side by side. One SDTMIG version and one CDASHIG version are indexed: set
    `sdtmig_version` / `cdashig_version` in step 4, or leave them empty for the latest one found.
  - The matching SDTM model version is added with the SDTMIG.
  - CDASHIG rows carry each collection field's SDTMIG target, which helps map raw CRF columns.
- **IG text** as PDF, TXT, MD or HTML.

## 4. Configure the bundle

Edit `databricks.yml`:
```yaml
targets:
  dev:
    mode: development
    default: true
    workspace:
      host: https://<your-workspace>.cloud.databricks.com
```
Pass the rest as variables. Every command below uses the same flags, so it is easiest to put them in a variable:
```bash
export BUNDLE_VARS='--var=warehouse_id=<warehouse-id> --var=secret_scope=sdtm-agent'
# optional: --var=llm_endpoint=databricks-claude-... --var=bronze_schema={study_id}_raw --var=ig_volume_path=/Volumes/...
#           --var=sdtmig_version=3.4 --var=cdashig_version=2.3   (default: latest in the volume)
```

## 5. Deploy the jobs

The app references the agent endpoint, which does not exist yet. For the **first** deploy, comment out the `apps:` block
in `databricks.yml`, then run:
```bash
databricks bundle validate -t dev $BUNDLE_VARS
databricks bundle deploy   -t dev $BUNDLE_VARS
```
Then go to *Workflows*, open **[dev …] SDTM transform**, and under *Permissions* give the `sdtm-agent` service principal **Can manage run**.

## 6. Build the index and deploy the agent

```bash
databricks bundle run setup_and_deploy_agent -t dev $BUNDLE_VARS
```
This runs `notebooks/00_setup.py`, which creates the tables, builds the IG corpus and creates and syncs the Vector Search index.
It then runs `notebooks/01_log_and_deploy_agent.py`, which smoke-tests the agent, logs it to MLflow, registers it in UC and deploys the
endpoint. The endpoint takes about 15 minutes to become **Ready**; check *Serving → sdtm-mapping-agent*.

The first cell of `01_log_and_deploy_agent` prints a real LLM answer. If it fails there, the LLM endpoint name or permissions are wrong.

## 7. Build and start the chat app

Restore the `apps:` block in `databricks.yml`, then:
```bash
npm --prefix app ci && npm --prefix app run build      # builds the React UI into app/static
databricks bundle deploy -t dev $BUNDLE_VARS
databricks bundle run sdtm_chatbot -t dev $BUNDLE_VARS # prints the app URL
```
To share the app, open *Compute → Apps → sdtm-mapping-chat → Permissions* and give reviewers **Can use**.

## 8. Smoke test in the app

Enter the study ID (e.g. `ABC123`) in the sidebar, then:

| Ask | Expect |
|---|---|
| *List the source tables for study ABC123* | Your bronze tables |
| *Which variables are required in DM?* | STUDYID, DOMAIN, USUBJID, SUBJID, SITEID, SEX, COUNTRY |
| *Map the demographics table of study ABC123 to DM* | A **draft** spec card with a mapping table and an Approve button |
| *Preview the DM spec* | Sample DM rows (nothing is written) |
| Click **Approve v1** | Card turns **approved** |
| *Run the transform* | Run link + validation report; table `workspace.abc123_sdtm.dm` exists |

Map DM first: the other domains use `DM.USUBJID` and `DM.RFSTDTC` (for `--DY`).

## Troubleshooting

| Symptom | Where to look / fix |
|---|---|
| App says *Agent endpoint returned 403* | The app's service principal is missing **Can query** on `sdtm-mapping-agent`; redeploy the app (the bundle grants it) |
| *Agent endpoint returned 504/timeout* | First call after scale-to-zero, or a long transform wait; retry. Endpoint logs: *Serving → sdtm-mapping-agent → Logs* |
| *No SQL warehouse configured* | `warehouse_id` was not passed when running `setup_and_deploy_agent` |
| `PERMISSION_DENIED` on a table / schema | Grants in step 2 for the `sdtm-agent` service principal |
| *SDTM_TRANSFORM_JOB_ID is not configured* | Re-run `setup_and_deploy_agent` after `bundle deploy` (it wires the job ID in) |
| `execute_transform` fails to start the job | Service principal is missing **Can manage run** on the transform job (step 5) |
| Retrieval says `builtin_fallback` | Index not ready or the service principal lacks SELECT on `workspace.sdtm_agent.sdtm_ig_index`; agent still works |
| Transform run failed | *Workflows → SDTM transform → run → Output*; the error names the spec and variable |
| Every request and response | Inference table created by `agents.deploy` (see the endpoint's *Inference tables* tab) |

## Production

- Use `-t prod`, and set `run_as` to the service principal in `databricks.yml` so jobs write tables as the service principal instead of you.
- Restrict the app's **Can use** permission to the people allowed to approve mappings.
