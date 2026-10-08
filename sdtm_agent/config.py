"""Runtime configuration for the SDTM mapping agent.

Values come from (highest priority first): MLflow model config (set at log
time), environment variables, then defaults. A per-request context carries
the caller identity and UI approvals into the tools.
"""

from __future__ import annotations

import contextvars
import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentConfig:
    llm_endpoint: str = "databricks-meta-llama-3-3-70b-instruct"
    warehouse_id: str = ""
    # Bronze (raw) source tables. {study_id} is substituted, e.g. "clinical_bronze_{study_id}".
    bronze_catalog: str = "workspace"
    bronze_schema: str = "{study_id}_bronze"
    # Silver SDTM output and agent metadata tables.
    silver_catalog: str = "workspace"
    silver_schema: str = "{study_id}_sdtm"
    metadata_schema: str = "workspace.sdtm_agent"
    # Vector Search index over the SDTM IG corpus and approved mapping specs.
    vector_search_index: str = "workspace.sdtm_agent.sdtm_ig_index"
    # Job that runs notebooks/jobs/run_transform.py.
    transform_job_id: str = ""
    transform_wait_seconds: int = 90
    trial_design_domain: str = "SV"
    # CDISC standard versions indexed from the library volume; empty = latest found there.
    sdtmig_version: str = ""
    cdashig_version: str = ""
    # When true, approve_mapping only succeeds if the request carries an
    # approval flag set by a human in the chat UI (not by the LLM).
    require_ui_approval: bool = True
    max_iterations: int = 20

    @property
    def mapping_specs_table(self) -> str:
        return f"{self.metadata_schema}.mapping_specs"

    @property
    def validation_results_table(self) -> str:
        return f"{self.metadata_schema}.validation_results"

    def bronze_schema_for(self, study_id: str) -> str:
        return f"{self.bronze_catalog}.{self.bronze_schema.format(study_id=study_id.lower())}"

    def silver_schema_for(self, study_id: str) -> str:
        return f"{self.silver_catalog}.{self.silver_schema.format(study_id=study_id.lower())}"


_ENV = {
    "llm_endpoint": "SDTM_LLM_ENDPOINT",
    "warehouse_id": "SDTM_WAREHOUSE_ID",
    "bronze_catalog": "SDTM_BRONZE_CATALOG",
    "bronze_schema": "SDTM_BRONZE_SCHEMA",
    "silver_catalog": "SDTM_SILVER_CATALOG",
    "silver_schema": "SDTM_SILVER_SCHEMA",
    "metadata_schema": "SDTM_METADATA_SCHEMA",
    "vector_search_index": "SDTM_VECTOR_SEARCH_INDEX",
    "transform_job_id": "SDTM_TRANSFORM_JOB_ID",
    "transform_wait_seconds": "SDTM_TRANSFORM_WAIT_SECONDS",
    "trial_design_domain": "SDTM_TRIAL_DESIGN_DOMAIN",
    "sdtmig_version": "SDTM_SDTMIG_VERSION",
    "cdashig_version": "SDTM_CDASHIG_VERSION",
    "require_ui_approval": "SDTM_REQUIRE_UI_APPROVAL",
    "max_iterations": "SDTM_MAX_ITERATIONS",
}

_config: AgentConfig | None = None


def _coerce(name: str, value: Any) -> Any:
    default = getattr(AgentConfig, name)
    if isinstance(default, bool):
        return str(value).lower() in ("1", "true", "yes")
    if isinstance(default, int):
        return int(value)
    return str(value)


def load_config(overrides: dict[str, Any] | None = None) -> AgentConfig:
    values: dict[str, Any] = {}
    for name, env in _ENV.items():
        if os.environ.get(env):
            values[name] = _coerce(name, os.environ[env])
    for name, value in (overrides or {}).items():
        if name in _ENV and value not in (None, ""):
            values[name] = _coerce(name, value)
    return AgentConfig(**values)


def get_config() -> AgentConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def set_config(config: AgentConfig) -> None:
    global _config
    _config = config


@dataclass
class RequestContext:
    user: str = "unknown"
    # "spec_id:version" tokens a human approved with the chat UI button in this request.
    approved_spec_ids: set[str] = field(default_factory=set)


_request_context: contextvars.ContextVar[RequestContext] = contextvars.ContextVar(
    "sdtm_request_context", default=RequestContext()
)


def get_request_context() -> RequestContext:
    return _request_context.get()


def set_request_context(ctx: RequestContext) -> contextvars.Token:
    return _request_context.set(ctx)


def reset_request_context(token: contextvars.Token) -> None:
    _request_context.reset(token)
