import re
from typing import Any, Callable

import pytest

from sdtm_agent.sql import QueryResult


class FakeRunner:
    """Records SQL and answers with the first handler whose regex matches."""

    def __init__(self, handlers: list[tuple[str, Callable[[str, dict], QueryResult]]] | None = None):
        self.handlers = handlers or []
        self.calls: list[tuple[str, dict]] = []

    def on(self, pattern: str, columns: list[str], rows: list[list[Any]]):
        self.handlers.append((pattern, lambda sql, params: QueryResult(columns, rows)))
        return self

    def query(self, sql: str, params: dict | None = None) -> QueryResult:
        self.calls.append((sql, params or {}))
        for pattern, handler in self.handlers:
            if re.search(pattern, sql, re.IGNORECASE | re.DOTALL):
                return handler(sql, params or {})
        return QueryResult([], [])


@pytest.fixture
def runner():
    return FakeRunner()
