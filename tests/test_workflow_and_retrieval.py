from sdtm_agent import retrieval
from sdtm_agent.workflow import EMPTY_WORKFLOW, update_workflow, workflow_text


def test_workflow_transitions():
    wf = update_workflow(EMPTY_WORKFLOW, "get_source_schema", {"table": "main.b.ae"})
    assert wf["stage"] == "source_selected"
    wf = update_workflow(wf, "generate_mapping", {"spec_id": "s1", "version": 1, "status": "draft", "domain": "AE",
                                                  "study_id": "ABC", "source_table": "main.b.ae", "issues": []})
    assert wf["stage"] == "draft_review" and wf["specs"]["s1"]["status"] == "draft"
    assert update_workflow(wf, "approve_mapping", {"error": "Approval must come from the reviewer"}) == wf
    wf = update_workflow(wf, "approve_mapping", {"spec_id": "s1", "version": 1, "status": "approved"})
    assert wf["stage"] == "approved"
    wf = update_workflow(wf, "execute_transform", {"run_id": 7, "life_cycle_state": "RUNNING"})
    assert wf["stage"] == "running"
    wf = update_workflow(wf, "get_transform_status", {"run_id": 7, "life_cycle_state": "TERMINATED", "result_state": "SUCCESS",
                                                      "validation": {"passed": False}})
    assert wf["stage"] == "executed" and wf["specs"]["s1"]["validation_passed"] is False
    assert "spec s1" in workflow_text(wf)
    assert EMPTY_WORKFLOW["specs"] == {}  # not mutated


def test_retrieval_falls_back_without_vector_search(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("index not found")

    monkeypatch.setattr(retrieval, "vector_search", boom)
    result = retrieval.retrieve("vs", "systolic blood pressure units")
    assert result["retrieval_mode"] == "builtin_fallback"
    assert result["domain"] == "VS" and result["standard_tests"]["SYSBP"]["unit"] == "mmHg"
    assert result["retrieved_passages"] and all(p["text"] for p in result["retrieved_passages"])
