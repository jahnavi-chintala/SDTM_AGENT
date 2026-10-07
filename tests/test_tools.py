import json
from types import SimpleNamespace

from sdtm_agent import tools
from sdtm_agent.agent import SDTMAgent


def test_domain_spec_has_required_variables():
    spec = tools.get_sdtm_domain_spec("dm")
    required = {v["name"] for v in spec["variables"] if v["core"] == "Req"}
    assert {"STUDYID", "USUBJID", "SEX", "COUNTRY"} <= required
    sex = next(v for v in spec["variables"] if v["name"] == "SEX")
    assert "F" in sex["codelist"]


def test_unknown_domain_returns_error():
    assert "error" in tools.get_sdtm_domain_spec("ZZ")


def test_suggest_mapping():
    result = tools.suggest_sdtm_mapping(["patient_id", "Gender", "DOB", "site_no", "AETERM"])
    by_col = {m["raw_column"]: m for m in result["mappings"]}
    assert by_col["patient_id"]["variable"] == "SUBJID"
    assert by_col["Gender"]["variable"] == "SEX"
    assert by_col["DOB"]["variable"] == "BRTHDTC"
    assert by_col["site_no"]["variable"] == "SITEID"
    assert by_col["AETERM"]["domain"] == "AE"
    assert result["likely_domain"] == "DM"


def test_read_only_guard():
    assert tools._is_read_only("SELECT * FROM main.sdtm.dm")
    assert tools._is_read_only("with x as (select 1) select * from x;")
    assert not tools._is_read_only("DROP TABLE main.sdtm.dm")
    assert not tools._is_read_only("SELECT 1; DELETE FROM main.sdtm.dm")
    assert "error" in tools.run_sql_query("update main.sdtm.dm set sex = 'M'")


def test_validate_table(monkeypatch):
    def fake_sql(sql):
        if sql.startswith("DESCRIBE"):
            names = ["STUDYID", "DOMAIN", "USUBJID", "SUBJID", "SITEID", "SEX", "EXTRA_COL"]
            return {"columns": ["col_name"], "rows": [[n] for n in names]}
        if "total_rows" in sql:
            return {"columns": ["total_rows", "STUDYID", "SEX"], "rows": [[10, 0, 2]]}
        if "DISTINCT `SEX`" in sql:
            return {"columns": ["SEX"], "rows": [["Male"]]}
        return {"columns": ["c"], "rows": [[0]]}

    monkeypatch.setattr(tools, "_execute_sql", fake_sql)
    result = tools.validate_sdtm_table("main.sdtm.dm", "DM")
    assert result["missing_required"] == ["COUNTRY"]
    assert result["non_standard_columns"] == ["EXTRA_COL"]
    assert result["nulls_in_required"] == {"SEX": 2}
    assert result["controlled_terminology_issues"] == {"SEX": ["Male"]}
    assert result["passed"] is False


def test_execute_tool_handles_bad_args():
    out = json.loads(tools.execute_tool("get_sdtm_domain_spec", "{}"))
    assert "error" in out
    assert "error" in json.loads(tools.execute_tool("nope", "{}"))


def test_agent_tool_loop():
    def completion(message):
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    responses = iter(
        [
            completion(
                SimpleNamespace(
                    content=None,
                    tool_calls=[
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "get_sdtm_domain_spec", "arguments": '{"domain": "AE"}'},
                        }
                    ],
                )
            ),
            completion(SimpleNamespace(content="AETERM and AEDECOD are required.", tool_calls=None)),
        ]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: next(responses)))
    )
    out = SDTMAgent(llm_endpoint="test", client=client).run([{"role": "user", "content": "AE required?"}])
    assert [m["role"] for m in out] == ["assistant", "tool", "assistant"]
    assert json.loads(out[1]["content"])["domain"] == "AE"
    assert out[-1]["content"].startswith("AETERM")
