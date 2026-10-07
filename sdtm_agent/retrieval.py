"""Retrieval of SDTM IG rules for a domain.

Returns the structured variable table from knowledge.py (authoritative for
names/core/codelists) plus the most relevant passages from the Vector Search
index (IG text, assumptions, approved mappings from earlier studies). Falls
back to keyword search over the built-in corpus when no index is reachable,
so the agent still works in a fresh workspace.
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from typing import Any

from sdtm_agent.config import get_config
from sdtm_agent.ig_corpus import knowledge_chunks
from sdtm_agent.knowledge import CONTROLLED_TERMINOLOGY, DOMAINS, TEST_CODES

log = logging.getLogger(__name__)

_COLUMNS = ["id", "domain", "chunk_type", "variable", "title", "content", "source"]


def domain_spec(domain: str) -> dict[str, Any]:
    code = domain.strip().upper()
    if code not in DOMAINS:
        raise KeyError(f"Unknown domain '{domain}'. Supported: {sorted(DOMAINS)}")
    d = DOMAINS[code]
    return {
        "domain": code,
        "label": d["label"],
        "class": d["class"],
        "structure": d["structure"],
        "keys": d["keys"],
        "variables": [
            {"name": n, "label": lbl, "type": t, "core": c, **({"codelist": CONTROLLED_TERMINOLOGY[n]} if n in CONTROLLED_TERMINOLOGY else {})}
            for n, lbl, t, c in d["variables"]
        ],
        "assumptions": d.get("assumptions", []),
        **({"standard_tests": {k: {"test": v[0], "unit": v[1]} for k, v in TEST_CODES[code].items()}} if code in TEST_CODES else {}),
    }


def vector_search(query: str, domain: str, k: int = 6, client: Any = None) -> list[dict]:
    from databricks.sdk import WorkspaceClient

    client = client or WorkspaceClient()
    resp = client.vector_search_indexes.query_index(
        index_name=get_config().vector_search_index,
        columns=_COLUMNS,
        query_text=query,
        num_results=k,
        filters_json=json.dumps({"domain": [domain, "GENERAL"]}),
    )
    names = [c.name for c in resp.manifest.columns]
    rows = (resp.result.data_array if resp.result else None) or []
    return [dict(zip(names, r)) for r in rows]


@lru_cache(maxsize=1)
def _local_corpus() -> list[dict]:
    return knowledge_chunks()


def keyword_search(query: str, domain: str, k: int = 6) -> list[dict]:
    terms = {t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 2}
    scored = []
    for chunk in _local_corpus():
        if chunk["domain"] != domain:
            continue
        text = chunk["content"].lower()
        score = sum(text.count(t) for t in terms) + (5 if chunk["chunk_type"] == "assumptions" else 0)
        scored.append((score, chunk))
    scored.sort(key=lambda s: -s[0])
    return [dict(c, score=s) for s, c in scored[:k]]


def retrieve(domain: str, query: str | None = None, k: int = 6) -> dict[str, Any]:
    spec = domain_spec(domain)
    q = query or f"{spec['domain']} {spec['label']} mapping rules variables controlled terminology"
    try:
        passages, mode = vector_search(q, spec["domain"], k), "vector_search"
    except Exception as exc:  # index missing, no permission, local dev...
        log.warning("Vector search unavailable, using built-in corpus: %s", exc)
        passages, mode = keyword_search(q, spec["domain"], k), "builtin_fallback"
    spec["retrieved_passages"] = [
        {"title": p.get("title"), "type": p.get("chunk_type"), "source": p.get("source"), "text": p.get("content")}
        for p in passages
    ]
    spec["retrieval_mode"] = mode
    return spec
