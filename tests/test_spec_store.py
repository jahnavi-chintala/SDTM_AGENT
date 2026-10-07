from sdtm_agent.config import AgentConfig
from sdtm_agent.mapping_spec import MappingSpec
from sdtm_agent.spec_store import SpecStore, ddl


def test_save_get_and_versioning(runner):
    cfg = AgentConfig(metadata_schema="main.meta")
    store = SpecStore(runner, cfg)
    spec = MappingSpec(study_id="ABC", domain="DM", source_table="main.b.dm", variables=[{"target": "SUBJID", "source": "subj"}])
    store.save(spec)
    sql, params = runner.calls[-1]
    assert sql.startswith("INSERT INTO main.meta.mapping_specs") and params["status"] == "draft" and params["version"] == 1

    runner.on(r"SELECT spec_json", ["spec_json", "status", "approved_by"], [[spec.model_dump_json(), "approved", "rev@x.com"]])
    loaded = store.get(spec.spec_id)
    assert loaded.status == "approved" and loaded.approved_by == "rev@x.com"

    edited = store.new_version(loaded, "fix SEX")
    assert edited.version == 2 and edited.status == "draft" and edited.approved_by is None

    store.set_status(edited, "approved", user="rev@x.com")
    assert "superseded" in runner.calls[-1][0] and runner.calls[-1][1]["version"] == 2
    assert all("main.meta" in s for s in ddl(cfg))
