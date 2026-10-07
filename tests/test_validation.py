from sdtm_agent.validation import validate_dataset


def test_validation_findings(runner):
    describe = [[c, t, None] for c, t in [
        ("STUDYID", "string"), ("DOMAIN", "string"), ("USUBJID", "string"), ("AESEQ", "string"),
        ("AETERM", "string"), ("AESEV", "string"), ("AESTDTC", "string"), ("AEENDTC", "string"),
        ("AE_EXTRA_FLAG", "string"),
    ]] + [["# Partition Information", "", ""], ["AESTDTC", "string", None]]
    runner.on(r"^DESCRIBE TABLE", ["col_name", "data_type", "comment"], describe)
    runner.on(r"COUNT\(\*\) AS `__total`",
              ["__total", "null_STUDYID", "null_DOMAIN", "null_USUBJID", "null_AESEQ", "null_AETERM",
               "iso_AESTDTC", "iso_AEENDTC", "bad_domain", "order_AESTDTC"],
              [[10, 0, 0, 0, 0, 2, 3, 0, 0, 1]])
    runner.on(r"SELECT DISTINCT `AESTDTC`", ["AESTDTC"], [["05JAN2024"], ["2024/01/07"]])
    runner.on(r"SELECT `AESEV` AS value", ["value", "n"], [["Mild", 4]])
    runner.on(r"GROUP BY `USUBJID`, `AESEQ`", ["c"], [[0]])
    runner.on(r"LEFT ANTI JOIN", ["USUBJID"], [["ABC-9"]])

    report = validate_dataset(runner, "main.abc_sdtm.ae", "AE", dm_table="main.abc_sdtm.dm")
    rules = {(f["rule"], f["variable"]): f for f in report["findings"]}
    assert ("SD_REQ_MISSING", "AEDECOD") in rules
    assert rules[("SD_REQ_NULL", "AETERM")]["count"] == 2
    assert rules[("SD_ISO8601", "AESTDTC")]["examples"] == ["05JAN2024", "2024/01/07"]
    assert rules[("SD_CT", "AESEV")]["examples"] == ["Mild"]
    assert ("SD_DATE_ORDER", "AESTDTC") in rules
    assert ("SD_DM_SUBJECT", "USUBJID") in rules
    assert ("SD_NONSTANDARD", "AE_EXTRA_FLAG") in rules and ("SD_VARNAME", "AE_EXTRA_FLAG") in rules
    assert ("SD_TYPE", "AESEQ") in rules
    assert report["passed"] is False and report["record_count"] == 10
    assert report["findings"][0]["severity"] == "error"
    # The partition section of DESCRIBE must not be read as columns
    assert ("SD_NONSTANDARD", "# PARTITION INFORMATION") not in rules


def test_clean_dm_passes(runner):
    cols = ["STUDYID", "DOMAIN", "USUBJID", "SUBJID", "SITEID", "SEX", "COUNTRY"]
    runner.on(r"^DESCRIBE TABLE", ["col_name", "data_type", "comment"], [[c, "string", None] for c in cols])
    runner.on(r"COUNT\(\*\) AS `__total`", ["__total"], [[5]])
    runner.on(r"HAVING COUNT", ["c"], [[0]])
    report = validate_dataset(runner, "main.abc_sdtm.dm", "DM")
    assert report["passed"] is True
    assert {f["rule"] for f in report["findings"]} == {"SD_EXP_MISSING"}
