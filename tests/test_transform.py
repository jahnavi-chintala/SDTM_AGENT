import pytest

from sdtm_agent.mapping_spec import MappingSpec
from sdtm_agent.transform import TransformError, build_plan, compile_sql, variable_expression


def test_variable_expression_date_and_value_map():
    spec = MappingSpec(
        study_id="ABC",
        domain="AE",
        source_table="main.b.ae",
        variables=[{"target": "AESTDTC", "source": "onset", "date_format": "dd-MMM-yyyy"},
                   {"target": "AESEV", "source": "sev", "value_map": {"1": "MILD", "2": "MODERATE"}}],
    )
    dtc = variable_expression(spec.variable("AESTDTC"), "Char")
    assert "try_to_timestamp(CAST(`onset` AS STRING), 'dd-MMM-yyyy')" in dtc and "'yyyy-MM-dd'" in dtc
    sev = variable_expression(spec.variable("AESEV"), "Char")
    assert "WHEN '1' THEN 'MILD'" in sev and "ELSE CAST(`sev` AS STRING)" in sev


def test_dm_sql():
    spec = MappingSpec(
        study_id="ABC",
        domain="DM",
        source_table="main.abc_bronze.demog",
        variables=[
            {"target": "USUBJID", "expression": "concat_ws('-', 'ABC', site, subj)"},
            {"target": "SUBJID", "source": "subj"},
            {"target": "SITEID", "source": "site"},
            {"target": "SEX", "source": "gender", "value_map": {"MALE": "M"}},
            {"target": "COUNTRY", "constant": "USA"},
            {"target": "AGE", "source": "age"},
        ],
        filter="subj IS NOT NULL",
    )
    sql = compile_sql(spec, ["subj", "site", "gender", "age"])
    assert "FROM main.abc_bronze.demog WHERE (subj IS NOT NULL)" in sql
    assert "TRY_CAST(`age` AS DOUBLE) AS `AGE`" in sql
    assert "'ABC' AS `STUDYID`" in sql and "'DM' AS `DOMAIN`" in sql
    final = sql.rsplit("SELECT", 1)[1]
    # IG order: STUDYID, DOMAIN, USUBJID, SUBJID ... SITEID ... AGE, SEX ... COUNTRY
    order = [final.index(f"AS `{v}`") for v in ("STUDYID", "DOMAIN", "USUBJID", "SUBJID", "SITEID", "AGE", "SEX", "COUNTRY")]
    assert order == sorted(order)
    assert "RFSTDTC" not in final


def test_findings_unpivot_seq_and_study_day():
    spec = MappingSpec(
        study_id="ABC",
        domain="VS",
        source_table="main.abc_bronze.vitals",
        dm_table="main.abc_sdtm.dm",
        unpivot={"tests": [
            {"source_column": "sbp", "testcd": "SYSBP", "test": "Systolic Blood Pressure", "orresu": "mmHg"},
            {"source_column": "dbp", "testcd": "DIABP", "test": "Diastolic Blood Pressure", "orresu": "mmHg"},
        ]},
        variables=[
            {"target": "USUBJID", "source": "usubjid"},
            {"target": "VISITNUM", "source": "visit_no"},
            {"target": "VSDTC", "source": "vdate", "date_format": "yyyy/MM/dd"},
        ],
    )
    sql = compile_sql(spec, ["usubjid", "visit_no", "vdate", "sbp", "dbp"])
    assert "stack(2, 'SYSBP', 'Systolic Blood Pressure', CAST(`sbp` AS STRING), 'mmHg'" in sql
    assert "WHERE `__ORRES` IS NOT NULL" in sql
    assert "TRY_CAST(`__ORRES` AS DOUBLE) AS `VSSTRESN`" in sql
    assert "ROW_NUMBER() OVER (PARTITION BY `USUBJID` ORDER BY `VSTESTCD` ASC NULLS LAST, `VISITNUM` ASC NULLS LAST" in sql
    assert "LEFT JOIN (SELECT `USUBJID`, `RFSTDTC` FROM main.abc_sdtm.dm)" in sql
    assert "AS `VSDY`" in sql and "datediff" in sql


def test_sv_group_by():
    spec = MappingSpec(
        study_id="ABC",
        domain="SV",
        source_table="main.abc_bronze.visits",
        group_by=["USUBJID", "VISITNUM"],
        variables=[
            {"target": "USUBJID", "source": "usubjid"},
            {"target": "VISITNUM", "source": "visit_no"},
            {"target": "VISIT", "source": "visit_name"},
            {"target": "SVSTDTC", "source": "vdate", "aggregate": "min"},
            {"target": "SVENDTC", "source": "vdate", "aggregate": "max"},
        ],
    )
    plan = build_plan(spec, ["usubjid", "visit_no", "visit_name", "vdate"])
    assert dict(plan.agg_exprs)["SVSTDTC"] == "MIN(`SVSTDTC`)"
    assert dict(plan.agg_exprs)["VISIT"] == "FIRST(`VISIT`, TRUE)"
    assert "GROUP BY `USUBJID`, `VISITNUM`" in compile_sql(spec)


def test_spec_with_errors_is_not_compiled():
    spec = MappingSpec(study_id="ABC", domain="AE", source_table="main.b.ae", variables=[{"target": "AETERM", "source": "term"}])
    with pytest.raises(TransformError, match="Required variable"):
        compile_sql(spec)


def test_pyspark_executor_matches_plan():
    pytest.importorskip("pyspark")
    from pyspark.sql import SparkSession

    from sdtm_agent.transform import build_dataframe

    spark = SparkSession.builder.master("local[1]").getOrCreate()
    spark.createDataFrame(
        [("S1", 1.0, "2024/01/05", "120", "80"), ("S1", 2.0, "2024/01/12", "125", None)],
        "usubjid string, visit_no double, vdate string, sbp string, dbp string",
    ).createOrReplaceTempView("vitals")
    spark.sql("CREATE DATABASE IF NOT EXISTS b")
    spark.table("vitals").write.mode("overwrite").saveAsTable("spark_catalog.b.vitals")
    spec = MappingSpec(
        study_id="ABC", domain="VS", source_table="spark_catalog.b.vitals",
        unpivot={"tests": [{"source_column": "sbp", "testcd": "SYSBP", "test": "Systolic Blood Pressure", "orresu": "mmHg"},
                           {"source_column": "dbp", "testcd": "DIABP", "test": "Diastolic Blood Pressure", "orresu": "mmHg"}]},
        variables=[{"target": "USUBJID", "source": "usubjid"}, {"target": "VISITNUM", "source": "visit_no"},
                   {"target": "VSDTC", "source": "vdate", "date_format": "yyyy/MM/dd"}],
    )
    rows = build_dataframe(spark, spec).orderBy("VSSEQ").collect()
    assert len(rows) == 3 and rows[0]["VSDTC"] == "2024-01-05" and rows[0]["DOMAIN"] == "VS"
