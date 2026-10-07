"""Versioned storage of mapping specs and validation results in Delta tables.

Every save appends a new (spec_id, version) row, so the full review history
is kept. Approved specs are also indexed into Vector Search by the setup
job, closing the feedback loop: approved mappings become retrievable
examples for future studies.
"""

from __future__ import annotations

import json
from typing import Any

from sdtm_agent.config import AgentConfig
from sdtm_agent.mapping_spec import MappingSpec
from sdtm_agent.sql import SqlRunner


def ddl(config: AgentConfig) -> list[str]:
    return [
        f"CREATE SCHEMA IF NOT EXISTS {config.metadata_schema}",
        f"""CREATE TABLE IF NOT EXISTS {config.mapping_specs_table} (
            spec_id STRING NOT NULL,
            version INT NOT NULL,
            study_id STRING,
            domain STRING,
            source_table STRING,
            status STRING,
            spec_json STRING,
            created_by STRING,
            approved_by STRING,
            comment STRING,
            updated_at TIMESTAMP
        ) USING DELTA COMMENT 'SDTM mapping specs proposed by the agent and reviewed in chat'
        TBLPROPERTIES (delta.enableChangeDataFeed = true)""",
        f"""CREATE TABLE IF NOT EXISTS {config.validation_results_table} (
            run_id STRING,
            spec_id STRING,
            spec_version INT,
            study_id STRING,
            domain STRING,
            table_name STRING,
            passed BOOLEAN,
            error_count INT,
            warning_count INT,
            record_count BIGINT,
            findings_json STRING,
            validated_at TIMESTAMP
        ) USING DELTA COMMENT 'SDTM validation results per transform run'""",
    ]


class SpecStore:
    def __init__(self, runner: SqlRunner, config: AgentConfig):
        self.runner = runner
        self.table = config.mapping_specs_table
        self.results_table = config.validation_results_table

    def save(self, spec: MappingSpec, comment: str | None = None) -> MappingSpec:
        self.runner.query(
            f"INSERT INTO {self.table} VALUES (:spec_id, CAST(:version AS INT), :study_id, :domain, "
            f":source_table, :status, :spec_json, :created_by, :approved_by, :comment, current_timestamp())",
            {
                "spec_id": spec.spec_id,
                "version": spec.version,
                "study_id": spec.study_id,
                "domain": spec.domain,
                "source_table": spec.source_table,
                "status": spec.status,
                "spec_json": spec.model_dump_json(),
                "created_by": spec.created_by,
                "approved_by": spec.approved_by,
                "comment": comment,
            },
        )
        return spec

    def get(self, spec_id: str, version: int | None = None) -> MappingSpec | None:
        sql = f"SELECT spec_json, status, approved_by FROM {self.table} WHERE spec_id = :spec_id"
        params: dict[str, Any] = {"spec_id": spec_id}
        if version is not None:
            sql += " AND version = CAST(:version AS INT)"
            params["version"] = version
        rows = self.runner.query(sql + " ORDER BY version DESC, updated_at DESC LIMIT 1", params).rows
        if not rows:
            return None
        spec = MappingSpec.model_validate(json.loads(rows[0][0]))
        spec.status, spec.approved_by = rows[0][1], rows[0][2]
        return spec

    def new_version(self, spec: MappingSpec, comment: str | None = None) -> MappingSpec:
        """Store an edited spec as the next version, back in draft status."""
        latest = self.get(spec.spec_id)
        spec.version = (latest.version if latest else 0) + 1
        spec.status, spec.approved_by = "draft", None
        return self.save(spec, comment)

    def set_status(self, spec: MappingSpec, status: str, user: str | None = None, comment: str | None = None) -> None:
        self.runner.query(
            f"UPDATE {self.table} SET status = :status, approved_by = :user, comment = :comment, "
            f"updated_at = current_timestamp() WHERE spec_id = :spec_id AND version = CAST(:version AS INT)",
            {"status": status, "user": user, "comment": comment, "spec_id": spec.spec_id, "version": spec.version},
        )
        if status == "approved":
            # Only one approved spec per study/domain/source table.
            self.runner.query(
                f"UPDATE {self.table} SET status = 'superseded', updated_at = current_timestamp() "
                f"WHERE study_id = :study_id AND domain = :domain AND source_table = :source_table "
                f"AND status = 'approved' AND NOT (spec_id = :spec_id AND version = CAST(:version AS INT))",
                {
                    "study_id": spec.study_id,
                    "domain": spec.domain,
                    "source_table": spec.source_table,
                    "spec_id": spec.spec_id,
                    "version": spec.version,
                },
            )

    def list(self, study_id: str | None = None, domain: str | None = None, status: str | None = None, limit: int = 50) -> list[dict]:
        where, params = ["1 = 1"], {}
        for col, val in (("study_id", study_id), ("domain", domain and domain.upper()), ("status", status)):
            if val:
                where.append(f"{col} = :{col}")
                params[col] = val
        sql = (
            f"SELECT spec_id, version, study_id, domain, source_table, status, created_by, approved_by, "
            f"CAST(updated_at AS STRING) AS updated_at FROM ("
            f"SELECT *, ROW_NUMBER() OVER (PARTITION BY spec_id ORDER BY version DESC) AS rn FROM {self.table}) "
            f"WHERE rn = 1 AND {' AND '.join(where)} ORDER BY updated_at DESC LIMIT {int(limit)}"
        )
        return self.runner.query(sql, params).records()

    def save_validation(self, run_id: str, spec: MappingSpec, report: dict) -> None:
        self.runner.query(
            f"INSERT INTO {self.results_table} VALUES (:run_id, :spec_id, CAST(:version AS INT), :study_id, :domain, "
            f":table_name, CAST(:passed AS BOOLEAN), CAST(:errors AS INT), CAST(:warnings AS INT), "
            f"CAST(:records AS BIGINT), :findings, current_timestamp())",
            {
                "run_id": run_id,
                "spec_id": spec.spec_id,
                "version": spec.version,
                "study_id": spec.study_id,
                "domain": spec.domain,
                "table_name": report.get("table"),
                "passed": str(bool(report.get("passed"))).lower(),
                "errors": report.get("error_count", 0),
                "warnings": report.get("warning_count", 0),
                "records": report.get("record_count", 0),
                "findings": json.dumps(report.get("findings", []), default=str),
            },
        )
