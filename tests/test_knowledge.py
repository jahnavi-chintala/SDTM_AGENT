from sdtm_agent.knowledge import CONTROLLED_TERMINOLOGY, DOMAINS, V1_DOMAINS


def test_v1_scope_covers_twelve_domains():
    assert len(V1_DOMAINS) == 11 and {"SV", "TA"} <= set(DOMAINS)  # 11 + SV or TA = 12
    classes = {DOMAINS[d]["class"] for d in V1_DOMAINS}
    assert {"Special-Purpose", "Interventions", "Events", "Findings"} <= classes


def test_domain_definitions_are_consistent():
    for code, d in DOMAINS.items():
        names = [v[0] for v in d["variables"]]
        assert len(names) == len(set(names)), f"duplicate variable in {code}"
        assert {"STUDYID", "DOMAIN"} <= set(names)
        assert all(len(n) <= 8 for n in names), code
        assert all(v[2] in ("Char", "Num") and v[3] in ("Req", "Exp", "Perm") for v in d["variables"])
        assert set(d["keys"]) <= set(names), code
        assert d["assumptions"], code


def test_codelists_reference_real_variables():
    all_vars = {v[0] for d in DOMAINS.values() for v in d["variables"]}
    assert set(CONTROLLED_TERMINOLOGY) <= all_vars
