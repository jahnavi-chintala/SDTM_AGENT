"""Agent-layer tests: tools, mapping generator and the LangGraph ChatAgent loop.

Skipped when langgraph / langchain-core / mlflow are not installed.
"""

import json

import pytest

pytest.importorskip("langchain_core")
pytest.importorskip("langgraph")

from langchain_core.messages import AIMessage  # noqa: E402

from sdtm_agent import config as config_mod  # noqa: E402
from sdtm_agent import retrieval, sql  # noqa: E402
from sdtm_agent.config import AgentConfig, RequestContext, reset_request_context, set_config, set_request_context  # noqa: E402
from sdtm_agent.mapping_generator import generate_mapping_spec, heuristic_hints  # noqa: E402
from sdtm_agent.mapping_spec import MappingSpec  # noqa: E402
from tests.conftest import FakeRunner  # noqa: E402

DM_JSON = {
    "variables": [
        {"target": "USUBJID", "expression": "concat_ws('-', 'ABC', site, subj)", "confidence": "high"},
        {"target": "SUBJID", "source": "subj"},
        {"target": "SITEID", "source": "site"},
        {"target": "SEX", "source": "gender", "value_map": {"Male": "M", "Female": "F"}},
        {"target": "COUNTRY", "constant": "USA", "confidence": "low"},
    ],
    "notes": "COUNTRY not collected; assumed USA.",
}


class ScriptedLLM:
    """Returns queued responses; supports bind_tools like a LangChain chat model."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages, *args, **kwargs):
        self.prompts.append(messages)
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch):
    set_config(AgentConfig(metadata_schema="main.meta", bronze_schema="{study_id}_bronze", silver_schema="{study_id}_sdtm"))
    monkeypatch.setattr(retrieval, "vector_search", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no index")))
    yield
    config_mod._config = None
    sql.set_runner(None)


def bronze_runner():
    runner = FakeRunner()
    runner.on(r"^DESCRIBE TABLE main\.abc_bronze\.demog", ["col_name", "data_type", "comment"],
              [["subj", "string", None], ["site", "string", None], ["gender", "string", None]])
    runner.on(r"collect_set", ["subj", "site", "gender"], [['["001","002"]', '["01"]', '["Male","Female"]']])
    runner.on(r"^SELECT COUNT\(\*\) FROM main\.abc_bronze\.demog", ["c"], [[2]])
    return runner


def test_heuristic_hints():
    hints = heuristic_hints(["PatientID", "Gender", "site_no", "dob"], "DM")
    assert hints == {"PatientID": "SUBJID", "Gender": "SEX", "site_no": "SITEID", "dob": "BRTHDTC"}


def test_generator_repairs_invalid_spec():
    bad = {"variables": [{"target": "SUBJID", "source": "subj"}]}  # missing required variables
    llm = ScriptedLLM([AIMessage(content="```json\n" + json.dumps(bad) + "\n```"), AIMessage(content=json.dumps(DM_JSON))])
    spec, issues = generate_mapping_spec(
        llm, study_id="ABC", domain="DM", source_table="main.abc_bronze.demog",
        source_profile=[{"name": "subj"}, {"name": "site"}, {"name": "gender"}],
        ig_rules=retrieval.retrieve("DM"),
    )
    assert spec.status == "draft" and spec.variable("SEX").value_map == {"MALE": "M", "FEMALE": "F"}
    assert len(llm.prompts) == 2 and "SPEC_REQUIRED_UNMAPPED" in llm.prompts[1][-1].content


def test_tools_generate_then_gated_approval(monkeypatch):
    from sdtm_agent import tools

    runner = bronze_runner()
    sql.set_runner(runner)
    monkeypatch.setattr(tools, "get_chat_model", lambda: ScriptedLLM([AIMessage(content=json.dumps(DM_JSON))]))

    view = json.loads(tools.generate_mapping.invoke(
        {"source_cols": [], "target_domain": "dm", "study_id": "ABC", "source_table": "demog"}))
    assert view["status"] == "draft" and view["target_table"] == "main.abc_sdtm.dm"
    assert {r["target"] for r in view["mapping_table"]} >= {"USUBJID", "SEX"}
    saved_json = next(p["spec_json"] for s, p in runner.calls if s.startswith("INSERT INTO main.meta.mapping_specs"))
    spec_id = view["spec_id"]

    runner.on(r"SELECT spec_json", ["spec_json", "status", "approved_by"], [[saved_json, "draft", None]])
    # The LLM cannot approve on its own...
    denied = json.loads(tools.approve_mapping.invoke({"spec_id": spec_id, "version": 1}))
    assert "reviewer" in denied["error"]
    # ...only with the UI approval token for this exact version.
    token = set_request_context(RequestContext(user="rev@x.com", approved_spec_ids={f"{spec_id}:1"}))
    try:
        ok = json.loads(tools.approve_mapping.invoke({"spec_id": spec_id, "version": 1}))
    finally:
        reset_request_context(token)
    assert ok == {"spec_id": spec_id, "version": 1, "status": "approved", "approved_by": "rev@x.com"}

    # Executing a non-approved spec is refused before any job is started.
    out = json.loads(tools.execute_transform.invoke({"mapping_spec": spec_id}))
    assert "must be approved" in out["error"]


def test_preview_uses_compiled_sql():
    from sdtm_agent import tools

    runner = bronze_runner()
    spec = MappingSpec(study_id="ABC", domain="DM", source_table="main.abc_bronze.demog", **DM_JSON)
    runner.on(r"SELECT spec_json", ["spec_json", "status", "approved_by"], [[spec.model_dump_json(), "draft", None]])
    runner.on(r"^WITH src AS", ["STUDYID", "SEX"], [["ABC", "M"]])
    sql.set_runner(runner)
    out = json.loads(tools.preview_transform.invoke({"spec_id": spec.spec_id, "limit": 5}))
    assert out["rows"] == [["ABC", "M"]] and out["sql"].endswith("LIMIT 5")


def test_chat_agent_loop():
    pytest.importorskip("mlflow")
    from langchain_core.tools import tool
    from mlflow.types.agent import ChatAgentMessage

    from sdtm_agent.chat_agent import SDTMMappingAgent

    @tool
    def retrieve_sdtm_spec(domain: str) -> str:
        """Retrieve IG rules."""
        return json.dumps({"domain": domain, "variables": ["AETERM"]})

    llm = ScriptedLLM([
        AIMessage(content="", tool_calls=[{"id": "c1", "name": "retrieve_sdtm_spec", "args": {"domain": "AE"}}]),
        AIMessage(content="AETERM and AEDECOD are required."),
    ])
    agent = SDTMMappingAgent(llm=llm, tools=[retrieve_sdtm_spec])
    resp = agent.predict([ChatAgentMessage(id="u1", role="user", content="AE required vars?")],
                         custom_inputs={"user": "a@b.com", "workflow": {"stage": "start", "specs": {}}})
    assert [m.role for m in resp.messages] == ["assistant", "tool", "assistant"]
    assert resp.messages[0].tool_calls[0].function.name == "retrieve_sdtm_spec"
    assert resp.messages[-1].content.startswith("AETERM")
    assert resp.custom_outputs["workflow"]["stage"] == "start"
    # The workflow state is injected into the system prompt
    assert "stage: start" in llm.prompts[0][0].content
