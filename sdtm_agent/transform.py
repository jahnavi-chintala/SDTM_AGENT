"""Transform executor: materializes an SDTM dataset from a mapping spec.

A spec is first compiled into a `TransformPlan` of Spark SQL expression
strings. The plan is executed in two interchangeable ways:

- `run_pyspark(spark, spec)`: the PySpark DataFrame executor used by the
  transform job to write the Silver SDTM table.
- `compile_sql(spec)`: the same plan as one Spark SQL query, used by the
  agent to preview a few output rows on a SQL warehouse during review.

Stages: source (+filter) → unpivot (Findings) → row mapping → group_by
(e.g. SV) → join DM for study day → derive --SEQ / --DY → cast and order
columns as in the SDTM IG.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sdtm_agent.knowledge import DOMAINS
from sdtm_agent.mapping_spec import (
    UNPIVOT_COLUMNS,
    MappingSpec,
    VariableMapping,
    auto_targets,
    check_spec,
    dy_pairs,
    has_errors,
    prefix,
    seq_variable,
)
from sdtm_agent.sql import check_table_name, quote_column, sql_string


class TransformError(ValueError):
    pass


@dataclass
class TransformPlan:
    source_table: str
    filter: str | None = None
    unpivot_stack: str | None = None
    unpivot_drop_nulls: bool = True
    row_exprs: list[tuple[str, str]] = field(default_factory=list)
    group_by: list[str] = field(default_factory=list)
    agg_exprs: list[tuple[str, str]] = field(default_factory=list)
    dm_table: str | None = None
    final_exprs: list[tuple[str, str]] = field(default_factory=list)


def _q(name: str) -> str:
    return quote_column(name)


def _cast(expr: str, vtype: str) -> str:
    return f"TRY_CAST({expr} AS DOUBLE)" if vtype == "Num" else f"CAST({expr} AS STRING)"


def variable_expression(v: VariableMapping, vtype: str) -> str:
    """Spark SQL expression producing one SDTM variable from source columns."""
    if v.constant is not None:
        expr = sql_string(v.constant)
    elif v.source is not None:
        expr = _q(v.source)
    elif v.expression is not None:
        expr = f"({v.expression})"
    else:
        raise TransformError(f"{v.target}: no source, expression or constant")

    if v.date_format:
        out = "yyyy-MM-dd'T'HH:mm" if "H" in v.date_format else "yyyy-MM-dd"
        expr = (
            f"date_format(try_to_timestamp(CAST({expr} AS STRING), {sql_string(v.date_format)}), "
            f"{sql_string(out)})"
        )
    if v.value_map:
        whens = " ".join(f"WHEN {sql_string(k)} THEN {sql_string(val)}" for k, val in v.value_map.items())
        expr = f"CASE UPPER(TRIM(CAST({expr} AS STRING))) {whens} ELSE CAST({expr} AS STRING) END"
    return _cast(expr, vtype)


def _unpivot_stack(spec: MappingSpec) -> str:
    parts = []
    for t in spec.unpivot.tests:
        unit = sql_string(t.orresu) if t.orresu else "CAST(NULL AS STRING)"
        cat = sql_string(t.category) if t.category else "CAST(NULL AS STRING)"
        parts.append(
            f"{sql_string(t.testcd)}, {sql_string(t.test)}, CAST({_q(t.source_column)} AS STRING), {unit}, {cat}"
        )
    return f"stack({len(parts)}, {', '.join(parts)}) AS ({', '.join(UNPIVOT_COLUMNS)})"


def _study_day(dtc: str) -> str:
    d = f"CAST(try_to_timestamp(substr({_q(dtc)}, 1, 10), 'yyyy-MM-dd') AS DATE)"
    rf = "CAST(try_to_timestamp(substr(`__RFSTDTC`, 1, 10), 'yyyy-MM-dd') AS DATE)"
    return (
        f"CAST(CASE WHEN {d} IS NULL OR {rf} IS NULL THEN NULL "
        f"WHEN {d} >= {rf} THEN datediff({d}, {rf}) + 1 ELSE datediff({d}, {rf}) END AS DOUBLE)"
    )


def build_plan(spec: MappingSpec, source_columns: list[str] | None = None) -> TransformPlan:
    issues = check_spec(spec, source_columns)
    if has_errors(issues):
        errors = "; ".join(f"{i['variable'] or ''} {i['message']}".strip() for i in issues if i["severity"] == "error")
        raise TransformError(f"Mapping spec has errors: {errors}")

    domain = spec.domain
    ig_vars = DOMAINS[domain]["variables"]
    types = {name: vtype for name, _, vtype, _ in ig_vars}
    p = prefix(domain)
    plan = TransformPlan(
        source_table=check_table_name(spec.source_table),
        filter=spec.filter,
        dm_table=check_table_name(spec.dm_table) if spec.dm_table and domain != "DM" else None,
    )

    # Row mapping stage: explicit mappings, then automatic defaults.
    mapped: dict[str, str] = {v.target: variable_expression(v, types[v.target]) for v in spec.variables}
    if spec.unpivot:
        plan.unpivot_stack = _unpivot_stack(spec)
        plan.unpivot_drop_nulls = spec.unpivot.drop_null_results
        defaults = {
            f"{p}TESTCD": "`__TESTCD`",
            f"{p}TEST": "`__TEST`",
            f"{p}ORRES": "`__ORRES`",
            f"{p}ORRESU": "`__ORRESU`",
            f"{p}STRESC": "`__ORRES`",
            f"{p}STRESN": "`__ORRES`",
            f"{p}STRESU": "`__ORRESU`",
            f"{p}CAT": "`__CAT`",
        }
        for target, expr in defaults.items():
            if target in types and target not in mapped and target in auto_targets(spec):
                mapped[target] = _cast(expr, types[target])
    if "STUDYID" not in mapped:
        mapped["STUDYID"] = sql_string(spec.study_id)
    mapped["DOMAIN"] = sql_string(domain)
    plan.row_exprs = list(mapped.items())

    # Optional aggregation stage (e.g. SV: one record per subject per visit).
    if spec.group_by:
        plan.group_by = spec.group_by
        for target in mapped:
            if target in spec.group_by:
                continue
            v = spec.variable(target)
            agg = v.aggregate if v and v.aggregate else "first"
            func = {"min": "MIN({c})", "max": "MAX({c})", "first": "FIRST({c}, TRUE)"}[agg]
            plan.agg_exprs.append((target, func.format(c=_q(target))))

    # Final stage: derived variables, IG variable order.
    available = set(mapped)
    seq = seq_variable(domain)
    dy_targets = {dy: dtc for dtc, dy in dy_pairs(domain)} if plan.dm_table else {}
    for name, _, vtype, _ in ig_vars:
        if name in available:
            plan.final_exprs.append((name, _q(name)))
        elif name == seq:
            plan.final_exprs.append((name, _seq_expression(spec, available)))
        elif name in dy_targets and dy_targets[name] in available:
            plan.final_exprs.append((name, _study_day(dy_targets[name])))
    return plan


def _seq_expression(spec: MappingSpec, available: set[str]) -> str:
    keys = spec.seq_order_by or [k for k in DOMAINS[spec.domain]["keys"] if k not in ("STUDYID", "USUBJID")]
    order = [k for k in keys if k in available]
    # Tie-break on every other mapped column so numbering is deterministic.
    order += sorted(available - set(order) - {"STUDYID", "DOMAIN", "USUBJID"})
    order_sql = ", ".join(f"{_q(c)} ASC NULLS LAST" for c in order) or "`USUBJID`"
    return f"CAST(ROW_NUMBER() OVER (PARTITION BY `USUBJID` ORDER BY {order_sql}) AS DOUBLE)"


# ---------------------------------------------------------------------- SQL (preview)
def compile_sql(spec: MappingSpec, source_columns: list[str] | None = None) -> str:
    plan = build_plan(spec, source_columns)
    ctes = [f"src AS (SELECT * FROM {plan.source_table}" + (f" WHERE ({plan.filter})" if plan.filter else "") + ")"]
    current = "src"
    if plan.unpivot_stack:
        ctes.append(f"long AS (SELECT *, {plan.unpivot_stack} FROM src)")
        current = "long"
        if plan.unpivot_drop_nulls:
            ctes.append("long_nn AS (SELECT * FROM long WHERE `__ORRES` IS NOT NULL)")
            current = "long_nn"
    ctes.append("mapped AS (SELECT " + ", ".join(f"{e} AS {_q(t)}" for t, e in plan.row_exprs) + f" FROM {current})")
    current = "mapped"
    if plan.group_by:
        cols = [_q(g) for g in plan.group_by] + [f"{e} AS {_q(t)}" for t, e in plan.agg_exprs]
        ctes.append(f"grouped AS (SELECT {', '.join(cols)} FROM mapped GROUP BY {', '.join(_q(g) for g in plan.group_by)})")
        current = "grouped"
    if plan.dm_table:
        ctes.append(
            f"derived AS (SELECT t.*, dm.`RFSTDTC` AS `__RFSTDTC` FROM {current} t "
            f"LEFT JOIN (SELECT `USUBJID`, `RFSTDTC` FROM {plan.dm_table}) dm ON t.`USUBJID` = dm.`USUBJID`)"
        )
        current = "derived"
    select = ", ".join(f"{e} AS {_q(t)}" for t, e in plan.final_exprs)
    return "WITH " + ",\n".join(ctes) + f"\nSELECT {select} FROM {current}"


# ---------------------------------------------------------------------- PySpark executor
def build_dataframe(spark: Any, spec: MappingSpec):
    """Build the SDTM DataFrame for a spec with the PySpark DataFrame API."""
    from pyspark.sql import functions as F

    source = spark.table(check_table_name(spec.source_table))
    plan = build_plan(spec, source.columns)

    df = source
    if plan.filter:
        df = df.where(F.expr(plan.filter))
    if plan.unpivot_stack:
        df = df.selectExpr("*", plan.unpivot_stack)
        if plan.unpivot_drop_nulls:
            df = df.where(F.col("__ORRES").isNotNull())
    df = df.select(*[F.expr(e).alias(t) for t, e in plan.row_exprs])
    if plan.group_by:
        df = df.groupBy(*plan.group_by).agg(*[F.expr(e).alias(t) for t, e in plan.agg_exprs])
    if plan.dm_table:
        dm = spark.table(plan.dm_table).select("USUBJID", F.col("RFSTDTC").alias("__RFSTDTC"))
        df = df.join(dm, on="USUBJID", how="left")
    return df.select(*[F.expr(e).alias(t) for t, e in plan.final_exprs])


def run_pyspark(spark: Any, spec: MappingSpec, target_table: str) -> dict[str, Any]:
    """Materialize the SDTM dataset as a Delta table (overwrite) and tag it with the spec."""
    if spec.status != "approved":
        raise TransformError(f"Spec {spec.spec_id} is '{spec.status}'; only approved specs can be executed.")
    target_table = check_table_name(target_table)
    df = build_dataframe(spark, spec)
    (
        df.write.mode("overwrite")
        .option("overwriteSchema", "true")
        .option("userMetadata", f"sdtm_spec={spec.spec_id} v{spec.version}")
        .saveAsTable(target_table)
    )
    label = DOMAINS[spec.domain]["label"].replace("'", "")
    spark.sql(
        f"ALTER TABLE {target_table} SET TBLPROPERTIES ("
        f"'sdtm.domain' = '{spec.domain}', 'sdtm.spec_id' = '{spec.spec_id}', "
        f"'sdtm.spec_version' = '{spec.version}', 'sdtm.study_id' = {sql_string(spec.study_id)})"
    )
    spark.sql(f"COMMENT ON TABLE {target_table} IS 'SDTM {spec.domain} ({label}) generated from {spec.source_table}'")
    return {"table": target_table, "row_count": spark.table(target_table).count(), "columns": df.columns}
