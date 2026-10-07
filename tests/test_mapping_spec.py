from sdtm_agent.mapping_spec import MappingSpec, auto_targets, check_spec, dy_pairs, has_errors


def dm_spec(**kw):
    base = dict(
        study_id="ABC",
        domain="dm",
        source_table="main.abc_bronze.demog",
        variables=[
            {"target": "usubjid", "expression": "concat_ws('-', 'ABC', site, subj)"},
            {"target": "SUBJID", "source": "subj"},
            {"target": "SITEID", "source": "site"},
            {"target": "SEX", "source": "gender", "value_map": {"male": "M", "Female": "F"}},
            {"target": "COUNTRY", "constant": "USA"},
        ],
    )
    base.update(kw)
    return MappingSpec(**base)


def test_valid_spec_has_no_errors():
    spec = dm_spec()
    assert spec.domain == "DM" and spec.variable("USUBJID")
    assert spec.variable("SEX").value_map == {"MALE": "M", "FEMALE": "F"}
    issues = check_spec(spec, ["subj", "site", "gender"])
    assert not has_errors(issues), issues
    assert any(i["rule"] == "SPEC_EXPECTED_UNMAPPED" for i in issues)


def test_errors_are_detected():
    spec = dm_spec()
    spec.upsert_variables(
        [
            dm_spec().variables[0].model_copy(update={"target": "BOGUS"}),
            dm_spec().variables[3].model_copy(update={"value_map": {"MALE": "Male"}}),
            dm_spec().variables[1].model_copy(update={"target": "AGE", "source": "age", "constant": "1"}),
        ]
    )
    spec.remove_variables(["COUNTRY"])
    spec.filter = "1=1; DROP TABLE x"
    rules = {(i["rule"], i["variable"]) for i in check_spec(spec, ["subj", "site", "gender"])}
    assert ("SPEC_UNKNOWN_VARIABLE", "BOGUS") in rules
    assert ("SPEC_CT_VALUE", "SEX") in rules
    assert ("SPEC_SOURCE", "AGE") in rules
    assert ("SPEC_REQUIRED_UNMAPPED", "COUNTRY") in rules
    assert ("SPEC_UNSAFE_FILTER", None) in rules


def test_missing_source_column_and_unsafe_expression():
    spec = dm_spec()
    spec.upsert_variables([spec.variables[0].model_copy(update={"expression": "(SELECT max(x) FROM other)"})])
    rules = {i["rule"] for i in check_spec(spec, ["subj", "gender"])}
    assert {"SPEC_UNSAFE_EXPRESSION", "SPEC_MISSING_SOURCE_COLUMN"} <= rules


def test_auto_targets_for_findings_unpivot():
    spec = MappingSpec(
        study_id="ABC",
        domain="VS",
        source_table="main.abc_bronze.vitals",
        dm_table="main.abc_sdtm.dm",
        unpivot={"tests": [{"source_column": "sbp", "testcd": "SYSBP", "test": "Systolic Blood Pressure", "orresu": "mmHg"}]},
        variables=[{"target": "USUBJID", "source": "usubjid"}],
    )
    auto = auto_targets(spec)
    assert {"STUDYID", "DOMAIN", "VSSEQ", "VSTESTCD", "VSTEST", "VSORRES", "VSDY"} <= auto
    assert not has_errors(check_spec(spec, ["usubjid", "sbp"]))
    assert ("AESTDTC", "AESTDY") in dy_pairs("AE")
