from sdtm_agent.ig_corpus import approved_spec_chunks, document_chunks, knowledge_chunks
from sdtm_agent.knowledge import DOMAINS
from sdtm_agent.mapping_spec import MappingSpec


def test_knowledge_chunks():
    chunks = knowledge_chunks()
    assert len({c["id"] for c in chunks}) == len(chunks)
    assert {c["domain"] for c in chunks} == set(DOMAINS)
    aesev = next(c for c in chunks if c["variable"] == "AESEV")
    assert "MILD" in aesev["content"] and aesev["domain"] == "AE"


def test_document_chunks_tag_sections():
    text = "Introduction\n" + "General text. " * 10 + "\n6.2.1 Adverse Events (AE)\n" + "AE text. " * 30 + \
           "\n6.3.10 Vital Signs (VS)\n" + "VS text. " * 300
    chunks = document_chunks(text, "sdtmig.pdf", max_chars=500)
    domains = [c["domain"] for c in chunks]
    assert domains[0] == "GENERAL" and "AE" in domains and domains[-1] == "VS"
    assert all(len(c["content"]) <= 800 for c in chunks)


def test_approved_spec_chunks():
    spec = MappingSpec(study_id="ABC", domain="AE", source_table="main.b.ae",
                       variables=[{"target": "AESEV", "source": "sev", "value_map": {"1": "MILD"}}])
    chunk = approved_spec_chunks([{"spec_json": spec.model_dump_json()}])[0]
    assert chunk["chunk_type"] == "approved_mapping" and "AESEV <- sev" in chunk["content"]
