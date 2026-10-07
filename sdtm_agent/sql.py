"""SQL runners.

Validation, schema lookup and the mapping spec store all speak SQL through a
small `SqlRunner` interface so the same code runs:
- inside the Model Serving endpoint, via a SQL warehouse (Statement Execution API)
- inside a Databricks job/notebook, via the active SparkSession
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Protocol

MAX_ROWS = 1000

_IDENT = r"`?[A-Za-z0-9_\-]+`?"
_TABLE_RE = re.compile(rf"^{_IDENT}\.{_IDENT}\.{_IDENT}$")
_SCHEMA_RE = re.compile(rf"^{_IDENT}\.{_IDENT}$")
_COLUMN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SqlError(RuntimeError):
    pass


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]

    def records(self) -> list[dict[str, Any]]:
        return [dict(zip(self.columns, r)) for r in self.rows]

    def scalar(self) -> Any:
        return self.rows[0][0] if self.rows and self.rows[0] else None


class SqlRunner(Protocol):
    def query(self, sql: str, params: dict[str, Any] | None = None) -> QueryResult: ...


class WarehouseRunner:
    """Runs statements on a Databricks SQL warehouse with named parameters (:name)."""

    def __init__(self, warehouse_id: str, client: Any = None, row_limit: int = MAX_ROWS):
        if not warehouse_id:
            raise SqlError("No SQL warehouse configured (SDTM_WAREHOUSE_ID).")
        self.warehouse_id = warehouse_id
        self.row_limit = row_limit
        self._client = client

    @property
    def client(self):
        if self._client is None:
            from databricks.sdk import WorkspaceClient

            self._client = WorkspaceClient()
        return self._client

    def query(self, sql: str, params: dict[str, Any] | None = None) -> QueryResult:
        from databricks.sdk.service.sql import StatementParameterListItem, StatementState

        parameters = [
            StatementParameterListItem(name=k, value=None if v is None else str(v))
            for k, v in (params or {}).items()
        ]
        resp = self.client.statement_execution.execute_statement(
            statement=sql,
            warehouse_id=self.warehouse_id,
            parameters=parameters or None,
            wait_timeout="50s",
            row_limit=self.row_limit,
        )
        statement_id = resp.statement_id
        # Long statements keep running after wait_timeout; poll until done.
        while resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(2)
            resp = self.client.statement_execution.get_statement(statement_id)
        if resp.status.state != StatementState.SUCCEEDED:
            err = resp.status.error.message if resp.status.error else resp.status.state.value
            raise SqlError(err)
        columns = [c.name for c in resp.manifest.schema.columns] if resp.manifest and resp.manifest.schema else []
        rows = (resp.result.data_array if resp.result else None) or []
        return QueryResult(columns, rows)


class SparkRunner:
    """Runs statements with the active SparkSession (jobs and notebooks)."""

    def __init__(self, spark: Any, row_limit: int = MAX_ROWS):
        self.spark = spark
        self.row_limit = row_limit

    def query(self, sql: str, params: dict[str, Any] | None = None) -> QueryResult:
        df = self.spark.sql(sql, args=params or None)
        rows = df.limit(self.row_limit).collect()
        return QueryResult(df.columns, [list(r) for r in rows])


_default_runner: SqlRunner | None = None


def get_runner() -> SqlRunner:
    """Runner used by the agent tools. Tests and jobs can override with set_runner()."""
    global _default_runner
    if _default_runner is None:
        from sdtm_agent.config import get_config

        _default_runner = WarehouseRunner(get_config().warehouse_id)
    return _default_runner


def set_runner(runner: SqlRunner | None) -> None:
    global _default_runner
    _default_runner = runner


# ------------------------------------------------------------------ identifiers
def check_table_name(name: str) -> str:
    name = name.strip()
    if not _TABLE_RE.match(name):
        raise ValueError(f"Invalid table name '{name}'. Use catalog.schema.table.")
    return name


def check_schema_name(name: str) -> str:
    name = name.strip()
    if not _SCHEMA_RE.match(name):
        raise ValueError(f"Invalid schema name '{name}'. Use catalog.schema.")
    return name


def quote_column(name: str) -> str:
    if not _COLUMN_RE.match(name):
        raise ValueError(f"Invalid column name '{name}'")
    return f"`{name}`"


def sql_string(value: str) -> str:
    """Spark SQL string literal."""
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"
