"""SDTM conformance validation for a materialized dataset.

All checks are SQL so they run through any SqlRunner (SQL warehouse from the
agent, SparkSession from the transform job). Each finding is a dict:
{rule, severity, variable, message, count, examples}.

Rules (v1):
  SD_TABLE        table exists / readable
  SD_REQ_MISSING  required variable missing                 (error)
  SD_EXP_MISSING  expected variable missing                 (warning)
  SD_NONSTANDARD  column not defined for the domain         (warning → SUPPQUAL)
  SD_TYPE         Num variable stored as non-numeric type   (warning)
  SD_REQ_NULL     null values in a required variable        (error)
  SD_DOMAIN       DOMAIN value differs from the domain code (error)
  SD_CT           value outside the controlled terminology  (error)
  SD_ISO8601      --DTC value not ISO 8601                   (error)
  SD_SEQ_UNIQUE   --SEQ not unique within USUBJID            (error)
  SD_DM_UNIQUE    more than one DM record per subject        (error)
  SD_DM_SUBJECT   USUBJID not present in DM                  (error)
  SD_DATE_ORDER   end date before start date                 (error)
  SD_VARNAME      variable name longer than 8 characters     (error)
"""

from __future__ import annotations

from typing import Any

from sdtm_agent.knowledge import CONTROLLED_TERMINOLOGY, DOMAINS
from sdtm_agent.mapping_spec import seq_variable
from sdtm_agent.sql import SqlError, SqlRunner, check_table_name, quote_column, sql_string

ISO8601_REGEX = r"^[0-9]{4}(-[0-9]{2}(-[0-9]{2}(T[0-9]{2}(:[0-9]{2}(:[0-9]{2}(\\.[0-9]+)?)?)?)?)?)?$"
_NUMERIC_TYPES = ("double", "float", "int", "bigint", "smallint", "tinyint", "decimal", "long")


def _finding(rule: str, severity: str, message: str, variable: str | None = None, count: int | None = None, examples: list | None = None) -> dict:
    return {"rule": rule, "severity": severity, "variable": variable, "message": message, "count": count, "examples": examples or []}


def _columns(runner: SqlRunner, table: str) -> dict[str, str]:
    result = runner.query(f"DESCRIBE TABLE {table}")
    cols: dict[str, str] = {}
    for row in result.rows:
        name = row[0]
        if not name or name.startswith("#"):
            break  # partition / metadata section
        cols[name.upper()] = (row[1] or "").lower()
    return cols


def validate_dataset(
    runner: SqlRunner,
    table: str,
    domain: str,
    dm_table: str | None = None,
    max_examples: int = 5,
) -> dict[str, Any]:
    domain = domain.strip().upper()
    if domain not in DOMAINS:
        return {"error": f"Unknown domain {domain}"}
    table = check_table_name(table)
    findings: list[dict] = []

    try:
        cols = _columns(runner, table)
    except SqlError as exc:
        return {"table": table, "domain": domain, "passed": False, "findings": [_finding("SD_TABLE", "error", str(exc))]}

    spec_vars = DOMAINS[domain]["variables"]
    present = set(cols)
    known = {v[0] for v in spec_vars}

    # -------- structure
    for name, _, vtype, core in spec_vars:
        if name not in present:
            if core == "Req":
                findings.append(_finding("SD_REQ_MISSING", "error", "Required variable missing", name))
            elif core == "Exp":
                findings.append(_finding("SD_EXP_MISSING", "warning", "Expected variable missing", name))
        elif vtype == "Num" and not cols[name].startswith(_NUMERIC_TYPES):
            findings.append(_finding("SD_TYPE", "warning", f"Numeric variable stored as {cols[name]}", name))
    for name in sorted(present - known):
        findings.append(_finding("SD_NONSTANDARD", "warning", f"Not a standard {domain} variable; move to SUPP{domain}", name))
    for name in sorted(present):
        if len(name) > 8:
            findings.append(_finding("SD_VARNAME", "error", "Variable names must be at most 8 characters", name))

    # -------- one aggregate query for counts
    required = [v[0] for v in spec_vars if v[3] == "Req" and v[0] in present]
    exprs = ["COUNT(*) AS `__total`"]
    exprs += [f"COUNT_IF({quote_column(v)} IS NULL OR TRIM(CAST({quote_column(v)} AS STRING)) = '') AS `null_{v}`" for v in required]
    dtc_vars = [v for v in present & known if v.endswith("DTC")]
    exprs += [
        f"COUNT_IF({quote_column(v)} IS NOT NULL AND NOT {quote_column(v)} RLIKE '{ISO8601_REGEX}') AS `iso_{v}`"
        for v in dtc_vars
    ]
    if "DOMAIN" in present:
        exprs.append(f"COUNT_IF(`DOMAIN` IS NULL OR `DOMAIN` != {sql_string(domain)}) AS `bad_domain`")
    date_pairs = [
        (st, st.replace("STDTC", "ENDTC"))
        for st in present
        if st.endswith("STDTC") and st.replace("STDTC", "ENDTC") in present
    ]
    exprs += [
        f"COUNT_IF(LENGTH({quote_column(en)}) >= 10 AND LENGTH({quote_column(st)}) >= 10 "
        f"AND SUBSTR({quote_column(en)}, 1, 10) < SUBSTR({quote_column(st)}, 1, 10)) AS `order_{st}`"
        for st, en in date_pairs
    ]
    counts = runner.query(f"SELECT {', '.join(exprs)} FROM {table}").records()[0]
    total = int(counts.pop("__total") or 0)
    for key, value in counts.items():
        n = int(value or 0)
        if not n:
            continue
        kind, _, var = key.partition("_")
        if kind == "null":
            findings.append(_finding("SD_REQ_NULL", "error", f"{n} of {total} records have no value", var, n))
        elif kind == "iso":
            ex = runner.query(
                f"SELECT DISTINCT {quote_column(var)} FROM {table} WHERE {quote_column(var)} IS NOT NULL "
                f"AND NOT {quote_column(var)} RLIKE '{ISO8601_REGEX}' LIMIT {max_examples}"
            )
            findings.append(_finding("SD_ISO8601", "error", f"{n} values are not ISO 8601", var, n, [r[0] for r in ex.rows]))
        elif kind == "bad":
            findings.append(_finding("SD_DOMAIN", "error", f"{n} records with DOMAIN != '{domain}'", "DOMAIN", n))
        elif kind == "order":
            findings.append(_finding("SD_DATE_ORDER", "error", f"{n} records end before they start", var, n))

    # -------- controlled terminology
    for var in sorted(v for v in present if v in CONTROLLED_TERMINOLOGY):
        allowed = ", ".join(sql_string(a) for a in CONTROLLED_TERMINOLOGY[var])
        col = quote_column(var)
        bad = runner.query(
            f"SELECT {col} AS value, COUNT(*) AS n FROM {table} "
            f"WHERE {col} IS NOT NULL AND TRIM(CAST({col} AS STRING)) != '' AND CAST({col} AS STRING) NOT IN ({allowed}) "
            f"GROUP BY {col} ORDER BY n DESC LIMIT {max_examples}"
        )
        if bad.rows:
            n = sum(int(r[1]) for r in bad.rows)
            findings.append(
                _finding("SD_CT", "error", f"Values outside codelist {CONTROLLED_TERMINOLOGY[var]}", var, n, [r[0] for r in bad.rows])
            )

    # -------- keys
    seq = seq_variable(domain)
    if seq and seq in present and "USUBJID" in present:
        dup = runner.query(
            f"SELECT COUNT(*) FROM (SELECT `USUBJID`, {quote_column(seq)} FROM {table} "
            f"GROUP BY `USUBJID`, {quote_column(seq)} HAVING COUNT(*) > 1)"
        ).scalar()
        if int(dup or 0):
            findings.append(_finding("SD_SEQ_UNIQUE", "error", f"{dup} duplicate (USUBJID, {seq}) pairs", seq, int(dup)))
    if domain == "DM" and "USUBJID" in present:
        dup = runner.query(
            f"SELECT COUNT(*) FROM (SELECT `USUBJID` FROM {table} GROUP BY `USUBJID` HAVING COUNT(*) > 1)"
        ).scalar()
        if int(dup or 0):
            findings.append(_finding("SD_DM_UNIQUE", "error", f"{dup} subjects have more than one DM record", "USUBJID", int(dup)))
    if dm_table and domain != "DM" and "USUBJID" in present:
        dm_table = check_table_name(dm_table)
        orphans = runner.query(
            f"SELECT DISTINCT t.`USUBJID` FROM {table} t LEFT ANTI JOIN {dm_table} dm ON t.`USUBJID` = dm.`USUBJID` "
            f"LIMIT {max_examples}"
        )
        if orphans.rows:
            findings.append(
                _finding("SD_DM_SUBJECT", "error", "Subjects not found in DM", "USUBJID", len(orphans.rows), [r[0] for r in orphans.rows])
            )

    severity_rank = {"error": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda f: (severity_rank[f["severity"]], f["rule"], f["variable"] or ""))
    errors = sum(f["severity"] == "error" for f in findings)
    return {
        "table": table,
        "domain": domain,
        "record_count": total,
        "passed": errors == 0,
        "error_count": errors,
        "warning_count": sum(f["severity"] == "warning" for f in findings),
        "findings": findings,
    }
