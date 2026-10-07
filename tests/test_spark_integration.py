"""End-to-end test on a real local Spark + Delta engine (skipped without pyspark/delta-spark).

Bronze tables → approved specs (spec store) → jobs/run_transform.py → Silver SDTM
tables → validation results, plus: SQL preview == PySpark executor output, the
spec store's UPDATE/versioning, the IG corpus MERGE and the agent's data tools.
"""

import importlib.util
import json
from pathlib import Path

import pytest

pytest.importorskip("pyspark")
pytest.importorskip("delta")

ROOT = Path(__file__).resolve().parents[1]
BRONZE = "spark_catalog.abc123_bronze"
SILVER = "spark_catalog.abc123_sdtm"
META = "spark_catalog.sdtm_agent"


@pytest.fixture(scope="module")
def spark(tmp_path_factory):
    from delta import configure_spark_with_delta_pip
    from pyspark.sql import SparkSession

    builder = (
        SparkSession.builder.master("local[2]")
        .appName("sdtm-agent-tests")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .config("spark.sql.sources.default", "delta")  # as on Databricks
        .config("spark.sql.ansi.enabled", "true")  # SQL warehouses / serverless default
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.warehouse.dir", str(tmp_path_factory.mktemp("warehouse")))
    )
    spark = configure_spark_with_delta_pip(builder).getOrCreate()
    spark.sparkContext.setLogLevel("ERROR")
    _create_bronze(spark)
    yield spark
    spark.stop()


def _create_bronze(spark):
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {BRONZE}")
    spark.createDataFrame(
        [
            ("001", "01", "Male", "05-Jan-1980", "44", "2024-01-10"),
            ("002", "01", "Female", "17-Mar-1975", "48", "2024-01-12"),
            ("003", "02", "female", "30-Nov-1990", "33", "2024-01-15"),
        ],
        "subj string, site string, gender string, dob string, age string, first_dose string",
    ).write.saveAsTable(f"{BRONZE}.demog")
    spark.createDataFrame(
        [
            ("ABC123-01-001", 1.0, "SCREENING", "2024/01/09", "120", "80", "70"),
            ("ABC123-01-001", 2.0, "WEEK 1", "2024/01/17", "125", None, "72"),
            ("ABC123-01-002", 1.0, "SCREENING", "2024/01/12", "130", "85", None),
        ],
        "usubjid string, visit_no double, visit_name string, vdate string, sbp string, dbp string, pulse string",
    ).write.saveAsTable(f"{BRONZE}.vitals")
    spark.createDataFrame(
        [
            ("001", "headache", "Headache", "1", "N", "11-Jan-2024", "13-Jan-2024"),
            ("001", "nausea", "Nausea", "2", "N", "20-Jan-2024", "18-Jan-2024"),  # ends before it starts
            ("002", "rash", "Rash", "4", "Y", "15-Jan-2024", None),  # severity 4 is not a valid code
        ],
        "subj string, term string, pt string, sev string, serious string, onset string, resolved string",
    ).write.saveAsTable(f"{BRONZE}.ae_raw")


def _specs():
    from sdtm_agent.mapping_spec import MappingSpec

    common = dict(study_id="ABC123", status="approved", created_by="test", approved_by="reviewer")
    dm = MappingSpec(
        domain="DM",
        source_table=f"{BRONZE}.demog",
        variables=[
            {"target": "USUBJID", "expression": "concat_ws('-', 'ABC123', site, subj)"},
            {"target": "SUBJID", "source": "subj"},
            {"target": "SITEID", "source": "site"},
            {"target": "SEX", "source": "gender", "value_map": {"MALE": "M", "FEMALE": "F"}},
            {"target": "BRTHDTC", "source": "dob", "date_format": "dd-MMM-yyyy"},
            {"target": "AGE", "source": "age"},
            {"target": "AGEU", "constant": "YEARS"},
            {"target": "RFSTDTC", "source": "first_dose"},
            {"target": "COUNTRY", "constant": "USA"},
        ],
        **common,
    )
    vs = MappingSpec(
        domain="VS",
        source_table=f"{BRONZE}.vitals",
        dm_table=f"{SILVER}.dm",
        unpivot={
            "tests": [
                {"source_column": "sbp", "testcd": "SYSBP", "test": "Systolic Blood Pressure", "orresu": "mmHg"},
                {"source_column": "dbp", "testcd": "DIABP", "test": "Diastolic Blood Pressure", "orresu": "mmHg"},
                {"source_column": "pulse", "testcd": "PULSE", "test": "Pulse Rate", "orresu": "beats/min"},
            ]
        },
        variables=[
            {"target": "USUBJID", "source": "usubjid"},
            {"target": "VISITNUM", "source": "visit_no"},
            {"target": "VISIT", "source": "visit_name"},
            {"target": "VSDTC", "source": "vdate", "date_format": "yyyy/MM/dd"},
        ],
        **common,
    )
    ae = MappingSpec(
        domain="AE",
        source_table=f"{BRONZE}.ae_raw",
        dm_table=f"{SILVER}.dm",
        variables=[
            {"target": "USUBJID", "expression": "concat_ws('-', 'ABC123', '01', subj)"},
            {"target": "AETERM", "source": "term"},
            {"target": "AEDECOD", "source": "pt"},
            {"target": "AESEV", "source": "sev", "value_map": {"1": "MILD", "2": "MODERATE", "3": "SEVERE"}},
            {"target": "AESER", "source": "serious"},
            {"target": "AESTDTC", "source": "onset", "date_format": "dd-MMM-yyyy"},
            {"target": "AEENDTC", "source": "resolved", "date_format": "dd-MMM-yyyy"},
        ],
        **common,
    )
    sv = MappingSpec(
        domain="SV",
        source_table=f"{BRONZE}.vitals",
        dm_table=f"{SILVER}.dm",
        group_by=["USUBJID", "VISITNUM"],
        variables=[
            {"target": "USUBJID", "source": "usubjid"},
            {"target": "VISITNUM", "source": "visit_no"},
            {"target": "VISIT", "source": "visit_name"},
            {"target": "SVSTDTC", "source": "vdate", "date_format": "yyyy/MM/dd", "aggregate": "min"},
            {"target": "SVENDTC", "source": "vdate", "date_format": "yyyy/MM/dd", "aggregate": "max"},
        ],
        **common,
    )
    return {"DM": dm, "VS": vs, "AE": ae, "SV": sv}


@pytest.fixture(scope="module")
def pipeline(spark):
    """Create metadata tables, store approved specs and run the real job script per domain."""
    from sdtm_agent.config import load_config
    from sdtm_agent.spec_store import SpecStore, ddl
    from sdtm_agent.sql import SparkRunner

    config = load_config({"metadata_schema": META})
    for statement in ddl(config):
        spark.sql(statement)
    store = SpecStore(SparkRunner(spark), config)
    specs = _specs()
    for spec in specs.values():
        store.save(spec, comment="integration test")

    path = ROOT / "jobs" / "run_transform.py"
    module_spec = importlib.util.spec_from_file_location("run_transform", path)
    job = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(job)

    summaries = {}
    for i, (domain, spec) in enumerate(specs.items()):  # DM first: others use it for --DY
        summaries[domain] = job.main(
            [
                f"--spec-id={spec.spec_id}",
                f"--target-table={SILVER}.{domain.lower()}",
                "--requested-by=reviewer@example.com",
                f"--run-id={1000 + i}",
                f"--metadata-schema={META}",
            ]
        )
    return {"specs": specs, "summaries": summaries, "store": store, "config": config}


def rows(spark, table, order):
    return [r.asDict() for r in spark.table(table).orderBy(*order).collect()]


def test_dm_output(spark, pipeline):
    dm = rows(spark, f"{SILVER}.dm", ["USUBJID"])
    assert [r["USUBJID"] for r in dm] == ["ABC123-01-001", "ABC123-01-002", "ABC123-02-003"]
    assert [r["SEX"] for r in dm] == ["M", "F", "F"]
    assert dm[0]["BRTHDTC"] == "1980-01-05" and dm[0]["AGE"] == 44.0 and dm[0]["DOMAIN"] == "DM"
    assert list(spark.table(f"{SILVER}.dm").columns[:4]) == ["STUDYID", "DOMAIN", "USUBJID", "SUBJID"]
    props = {r.key: r.value for r in spark.sql(f"SHOW TBLPROPERTIES {SILVER}.dm").collect()}
    assert props["sdtm.spec_id"] == pipeline["specs"]["DM"].spec_id
    assert pipeline["summaries"]["DM"]["passed"] is True


def test_vs_unpivot_seq_and_study_day(spark, pipeline):
    vs = rows(spark, f"{SILVER}.vs", ["USUBJID", "VSSEQ"])
    assert len(vs) == 7  # 9 cells minus 2 nulls
    s1 = [r for r in vs if r["USUBJID"] == "ABC123-01-001"]
    assert [r["VSSEQ"] for r in s1] == [1.0, 2.0, 3.0, 4.0, 5.0]
    sysbp_v1 = next(r for r in s1 if r["VSTESTCD"] == "SYSBP" and r["VISITNUM"] == 1.0)
    assert sysbp_v1["VSORRES"] == "120" and sysbp_v1["VSSTRESN"] == 120.0 and sysbp_v1["VSORRESU"] == "mmHg"
    assert sysbp_v1["VSDTC"] == "2024-01-09" and sysbp_v1["VSDY"] == -1.0  # day before RFSTDTC 2024-01-10
    assert next(r for r in s1 if r["VISITNUM"] == 2.0)["VSDY"] == 8.0
    assert pipeline["summaries"]["VS"]["passed"] is True


def test_ae_validation_catches_bad_data(spark, pipeline):
    from sdtm_agent.sql import SparkRunner
    from sdtm_agent.validation import validate_dataset

    ae = rows(spark, f"{SILVER}.ae", ["USUBJID", "AESEQ"])
    assert [r["AESEV"] for r in ae] == ["MILD", "MODERATE", "4"]
    assert ae[0]["AESTDY"] == 2.0 and ae[0]["AEENDY"] == 4.0
    report = validate_dataset(SparkRunner(spark), f"{SILVER}.ae", "AE", dm_table=f"{SILVER}.dm")
    found = {(f["rule"], f["variable"]): f for f in report["findings"]}
    assert found[("SD_CT", "AESEV")]["examples"] == ["4"]
    assert found[("SD_DATE_ORDER", "AESTDTC")]["count"] == 1
    assert report["passed"] is False and pipeline["summaries"]["AE"]["passed"] is False


def test_sv_one_record_per_visit(spark, pipeline):
    sv = rows(spark, f"{SILVER}.sv", ["USUBJID", "VISITNUM"])
    assert [(r["USUBJID"], r["VISITNUM"], r["SVSTDTC"], r["SVSTDY"]) for r in sv] == [
        ("ABC123-01-001", 1.0, "2024-01-09", -1.0),
        ("ABC123-01-001", 2.0, "2024-01-17", 8.0),
        ("ABC123-01-002", 1.0, "2024-01-12", 1.0),
    ]
    assert pipeline["summaries"]["SV"]["passed"] is True


def test_sql_preview_matches_pyspark_executor(spark, pipeline):
    from sdtm_agent.transform import build_dataframe, compile_sql

    for domain, spec in pipeline["specs"].items():
        executor = build_dataframe(spark, spec)
        preview = spark.sql(compile_sql(spec))
        assert preview.columns == executor.columns, domain
        key = lambda r: json.dumps(r.asDict(), sort_keys=True, default=str)  # noqa: E731
        assert sorted(map(key, preview.collect())) == sorted(map(key, executor.collect())), domain


def test_validation_results_stored(spark, pipeline):
    results = spark.sql(f"SELECT run_id, domain, passed FROM {META}.validation_results ORDER BY run_id").collect()
    assert [(r.run_id, r.domain, r.passed) for r in results] == [
        ("1000", "DM", True), ("1001", "VS", True), ("1002", "AE", False), ("1003", "SV", True),
    ]


def test_spec_store_versioning_on_delta(spark, pipeline):
    store, dm = pipeline["store"], pipeline["specs"]["DM"]
    edited = store.get(dm.spec_id).model_copy(deep=True)
    edited.upsert_variables([edited.variable("COUNTRY").model_copy(update={"constant": "CAN"})])
    store.new_version(edited, comment="country fix")
    latest = store.get(dm.spec_id)
    assert latest.version == 2 and latest.status == "draft" and latest.variable("COUNTRY").constant == "CAN"
    store.set_status(latest, "approved", user="reviewer@example.com")
    listed = {r["spec_id"]: r for r in store.list("ABC123", domain="DM")}
    assert listed[dm.spec_id]["version"] == 2 and listed[dm.spec_id]["status"] == "approved"
    assert store.get(dm.spec_id, version=1).status == "superseded"


def test_ig_corpus_table_merge(spark, pipeline):
    from sdtm_agent.vector_index import build_corpus_table

    n1 = build_corpus_table(spark, pipeline["config"])
    n2 = build_corpus_table(spark, pipeline["config"])
    assert n1 == n2 == spark.table(f"{META}.sdtm_ig_chunks").count()
    approved = spark.sql(f"SELECT content FROM {META}.sdtm_ig_chunks WHERE chunk_type = 'approved_mapping'").collect()
    assert approved and any("SEX <- gender" in r.content for r in approved)


def test_agent_data_tools_on_spark(spark, pipeline):
    pytest.importorskip("langchain_core")
    from sdtm_agent import sql, tools
    from sdtm_agent.config import set_config

    set_config(pipeline["config"])
    sql.set_runner(sql.SparkRunner(spark))
    try:
        schema = json.loads(tools.get_source_schema.invoke({"study_id": "ABC123", "table_name": f"{BRONZE}.demog"}))
        gender = next(c for c in schema["columns"] if c["name"] == "gender")
        assert schema["row_count"] == 3 and set(gender["sample_values"]) == {"Male", "Female", "female"}

        ae_id = pipeline["specs"]["AE"].spec_id
        preview = json.loads(tools.preview_transform.invoke({"spec_id": ae_id, "limit": 2}))
        assert "error" not in preview, preview
        assert len(preview["rows"]) == 2 and preview["columns"][:3] == ["STUDYID", "DOMAIN", "USUBJID"]

        report = json.loads(tools.validate_output.invoke({"domain": "VS", "dataset": f"{SILVER}.vs"}))
        assert report["passed"] is True and report["record_count"] == 7
    finally:
        sql.set_runner(None)
