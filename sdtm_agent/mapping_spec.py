"""Mapping specification: the reviewable contract between the LLM's proposal,
the human reviewer and the transform executor.

A spec maps one bronze source table to one SDTM domain. Each target variable
is filled from exactly one of: a raw column (`source`), a Spark SQL
expression over raw columns (`expression`), or a `constant`, optionally
followed by a raw→CT `value_map` and/or ISO 8601 date conversion.

Findings domains with wide source data use `unpivot` (one source column per
test → one record per test). Visit-level domains such as SV use `group_by`
plus per-variable `aggregate`.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from sdtm_agent.knowledge import CONTROLLED_TERMINOLOGY, DOMAINS

SpecStatus = Literal["draft", "approved", "rejected", "superseded"]

# Reject anything that could turn an expression into another statement or a subquery.
_UNSAFE_SQL = re.compile(
    r";|--|/\*|\b(select|insert|update|delete|merge|drop|create|alter|truncate|grant|revoke|"
    r"copy|optimize|vacuum|call|refresh|use|set|reset)\b",
    re.IGNORECASE,
)

# Columns produced by `unpivot`, usable in expressions.
UNPIVOT_COLUMNS = ("__TESTCD", "__TEST", "__ORRES", "__ORRESU", "__CAT")


class VariableMapping(BaseModel):
    target: str = Field(description="SDTM variable name, e.g. AETERM")
    source: Optional[str] = Field(None, description="Raw column copied as-is")
    expression: Optional[str] = Field(None, description="Spark SQL expression over raw columns")
    constant: Optional[str] = Field(None, description="Constant value")
    value_map: dict[str, str] = Field(
        default_factory=dict, description="Raw value (case-insensitive) → SDTM controlled term"
    )
    date_format: Optional[str] = Field(
        None, description="Spark datetime pattern of the raw value (e.g. dd-MMM-yyyy) → converted to ISO 8601"
    )
    aggregate: Optional[Literal["min", "max", "first"]] = Field(
        None, description="Aggregation when the spec uses group_by"
    )
    rationale: Optional[str] = None
    confidence: Optional[Literal["high", "medium", "low"]] = None

    @model_validator(mode="after")
    def _normalise(self):
        self.target = self.target.strip().upper()
        self.value_map = {str(k).strip().upper(): str(v) for k, v in self.value_map.items()}
        return self

    def source_kinds(self) -> int:
        return sum(x is not None for x in (self.source, self.expression, self.constant))


class UnpivotTest(BaseModel):
    source_column: str
    testcd: str
    test: str
    orresu: Optional[str] = None
    category: Optional[str] = None


class Unpivot(BaseModel):
    tests: list[UnpivotTest]
    drop_null_results: bool = True


class MappingSpec(BaseModel):
    spec_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    study_id: str
    domain: str
    source_table: str
    version: int = 1
    status: SpecStatus = "draft"
    filter: Optional[str] = Field(None, description="Spark SQL predicate applied to source rows")
    unpivot: Optional[Unpivot] = None
    group_by: list[str] = Field(default_factory=list, description="Target variables to group by")
    variables: list[VariableMapping] = Field(default_factory=list)
    seq_order_by: list[str] = Field(default_factory=list, description="Target variables ordering --SEQ")
    dm_table: Optional[str] = Field(None, description="SDTM DM table providing RFSTDTC for --DY")
    notes: Optional[str] = None
    created_by: Optional[str] = None
    approved_by: Optional[str] = None
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    @model_validator(mode="after")
    def _normalise(self):
        self.domain = self.domain.strip().upper()
        self.group_by = [g.strip().upper() for g in self.group_by]
        self.seq_order_by = [s.strip().upper() for s in self.seq_order_by]
        return self

    def variable(self, target: str) -> VariableMapping | None:
        return next((v for v in self.variables if v.target == target.upper()), None)

    def upsert_variables(self, changes: list[VariableMapping]) -> None:
        for change in changes:
            self.variables = [v for v in self.variables if v.target != change.target] + [change]

    def remove_variables(self, targets: list[str]) -> None:
        drop = {t.strip().upper() for t in targets}
        self.variables = [v for v in self.variables if v.target not in drop]


# ---------------------------------------------------------------------- derivations
def prefix(domain: str) -> str:
    """Variable prefix (--) of a domain; SV/TA have none for shared variables."""
    return domain.upper()


def seq_variable(domain: str) -> str | None:
    name = f"{prefix(domain)}SEQ"
    return name if name in {v[0] for v in DOMAINS[domain]["variables"]} else None


def dy_pairs(domain: str) -> list[tuple[str, str]]:
    """(DTC variable, DY variable) pairs present in the domain, e.g. (AESTDTC, AESTDY)."""
    names = {v[0] for v in DOMAINS[domain]["variables"]}
    pairs = []
    for name in names:
        if name.endswith("DTC") and name not in ("RFSTDTC", "BRTHDTC"):
            dy = name[:-3] + "DY"
            if dy in names:
                pairs.append((name, dy))
    return sorted(pairs)


def auto_targets(spec: MappingSpec) -> set[str]:
    """Targets the executor fills automatically when the spec does not map them."""
    domain = spec.domain
    auto = {"STUDYID", "DOMAIN"}
    if seq_variable(domain):
        auto.add(seq_variable(domain))
    if spec.dm_table and domain != "DM":
        auto.update(dy for _, dy in dy_pairs(domain))
    if spec.unpivot:
        p = prefix(domain)
        auto.update(f"{p}{s}" for s in ("TESTCD", "TEST", "ORRES", "ORRESU", "STRESC", "STRESN", "STRESU"))
        if any(t.category for t in spec.unpivot.tests):
            auto.add(f"{p}CAT")
    names = {v[0] for v in DOMAINS[domain]["variables"]}
    return auto & names


# ---------------------------------------------------------------------- static checks
def _issue(severity: str, rule: str, message: str, variable: str | None = None) -> dict:
    return {"severity": severity, "rule": rule, "variable": variable, "message": message}


def unsafe_sql(fragment: str | None) -> bool:
    return bool(fragment) and bool(_UNSAFE_SQL.search(fragment))


def check_spec(spec: MappingSpec, source_columns: list[str] | None = None) -> list[dict]:
    """Static checks before a spec is shown for review or executed."""
    issues: list[dict] = []
    if spec.domain not in DOMAINS:
        return [_issue("error", "SPEC_DOMAIN", f"Unknown domain {spec.domain}")]

    spec_vars = DOMAINS[spec.domain]["variables"]
    known = {v[0] for v in spec_vars}
    core = {v[0]: v[3] for v in spec_vars}
    mapped = [v.target for v in spec.variables]
    covered = set(mapped) | auto_targets(spec)
    src_cols = {c.lower() for c in source_columns} if source_columns else None
    if src_cols is not None and spec.unpivot:
        src_cols |= {c.lower() for c in UNPIVOT_COLUMNS}

    for target in {t for t in mapped if mapped.count(t) > 1}:
        issues.append(_issue("error", "SPEC_DUPLICATE_TARGET", "Mapped more than once", target))

    for v in spec.variables:
        if v.target not in known:
            issues.append(
                _issue("error", "SPEC_UNKNOWN_VARIABLE", f"Not a {spec.domain} variable (non-standard data belongs in SUPP{spec.domain})", v.target)
            )
        if v.source_kinds() != 1:
            issues.append(_issue("error", "SPEC_SOURCE", "Set exactly one of source, expression or constant", v.target))
        if src_cols is not None and v.source and v.source.lower() not in src_cols:
            issues.append(_issue("error", "SPEC_MISSING_SOURCE_COLUMN", f"Source column '{v.source}' not in {spec.source_table}", v.target))
        if unsafe_sql(v.expression):
            issues.append(_issue("error", "SPEC_UNSAFE_EXPRESSION", "Expression must be a single scalar Spark SQL expression", v.target))
        allowed = CONTROLLED_TERMINOLOGY.get(v.target)
        if allowed:
            bad = sorted({val for val in v.value_map.values() if val not in allowed})
            if bad:
                issues.append(_issue("error", "SPEC_CT_VALUE", f"value_map targets {bad} not in codelist {allowed}", v.target))
            elif v.source and not v.value_map:
                issues.append(_issue("warning", "SPEC_CT_UNMAPPED", "Raw values are copied as-is; add a value_map unless they are already controlled terms", v.target))
        if v.target.endswith("DTC") and (v.source or v.expression) and not v.date_format:
            issues.append(_issue("warning", "SPEC_DATE_FORMAT", "No date_format: raw values must already be ISO 8601", v.target))
        if spec.group_by and v.target not in spec.group_by and not v.aggregate and v.constant is None:
            issues.append(_issue("warning", "SPEC_AGGREGATE", "Not in group_by and no aggregate; first non-null value is used", v.target))

    for target, c in core.items():
        if c == "Req" and target not in covered:
            issues.append(_issue("error", "SPEC_REQUIRED_UNMAPPED", "Required variable is not mapped", target))
        elif c == "Exp" and target not in covered:
            issues.append(_issue("warning", "SPEC_EXPECTED_UNMAPPED", "Expected variable is not mapped (include it, null if not collected)", target))

    if unsafe_sql(spec.filter):
        issues.append(_issue("error", "SPEC_UNSAFE_FILTER", "Filter must be a single Spark SQL predicate"))
    if spec.unpivot:
        if DOMAINS[spec.domain]["class"] != "Findings":
            issues.append(_issue("warning", "SPEC_UNPIVOT_CLASS", f"unpivot is meant for Findings domains, {spec.domain} is {DOMAINS[spec.domain]['class']}"))
        for t in spec.unpivot.tests:
            if src_cols is not None and t.source_column.lower() not in src_cols:
                issues.append(_issue("error", "SPEC_MISSING_SOURCE_COLUMN", f"Unpivot column '{t.source_column}' not in source", f"{spec.domain}TESTCD"))
            allowed = CONTROLLED_TERMINOLOGY.get(f"{spec.domain}TESTCD")
            if allowed and t.testcd not in allowed:
                issues.append(_issue("warning", "SPEC_CT_VALUE", f"Test code {t.testcd} not in stored codelist (extensible) {allowed}", f"{spec.domain}TESTCD"))
    for g in spec.group_by:
        if g not in mapped:
            issues.append(_issue("error", "SPEC_GROUP_BY", "group_by variable is not mapped", g))
    for s in spec.seq_order_by:
        if s not in covered:
            issues.append(_issue("warning", "SPEC_SEQ_ORDER", "seq_order_by variable is not mapped", s))
    if spec.domain != "DM" and not spec.dm_table and dy_pairs(spec.domain):
        issues.append(_issue("info", "SPEC_NO_DM", "No dm_table set, so study day (--DY) variables are not derived"))
    return issues


def has_errors(issues: list[dict]) -> bool:
    return any(i["severity"] == "error" for i in issues)
