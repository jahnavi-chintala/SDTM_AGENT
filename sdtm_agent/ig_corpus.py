"""Builds the text corpus behind the SDTM Vector Search index.

Chunk sources:
1. Structured IG metadata in knowledge.py (domain overviews, assumptions,
   one chunk per variable, codelists) — always available.
2. The SDTM Implementation Guide text itself, if you have a licensed copy
   (PDF/TXT/MD/HTML) in a Unity Catalog volume. CDISC content is licensed,
   so it is not bundled in this repo.
3. Approved mapping specs from earlier reviews — the feedback loop that
   turns human-approved mappings into retrievable examples.

Every chunk carries a `domain` tag so retrieval can filter by domain.
"""

from __future__ import annotations

import hashlib
import json
import re
import textwrap
from typing import Iterable

from sdtm_agent.knowledge import CONTROLLED_TERMINOLOGY, DOMAINS, TEST_CODES

CORE_NAMES = {"Req": "Required", "Exp": "Expected", "Perm": "Permissible"}


def _chunk(domain: str, chunk_type: str, title: str, content: str, source: str, variable: str | None = None) -> dict:
    key = f"{source}|{domain}|{chunk_type}|{variable or ''}|{title}|{content[:200]}"
    return {
        "id": hashlib.sha1(key.encode()).hexdigest(),
        "domain": domain,
        "chunk_type": chunk_type,
        "variable": variable,
        "title": title,
        "content": content,
        "source": source,
    }


def knowledge_chunks() -> list[dict]:
    chunks = []
    for code, d in DOMAINS.items():
        var_lines = "\n".join(f"- {n} ({lbl}; {t}; {CORE_NAMES[c]})" for n, lbl, t, c in d["variables"])
        chunks.append(
            _chunk(
                code,
                "domain_overview",
                f"{code} — {d['label']}",
                f"SDTM domain {code} ({d['label']}), class {d['class']}.\n"
                f"Structure: {d['structure']}.\nNatural keys: {', '.join(d['keys'])}.\nVariables:\n{var_lines}",
                "sdtm_knowledge",
            )
        )
        chunks.append(
            _chunk(
                code,
                "assumptions",
                f"{code} assumptions",
                f"SDTM IG assumptions for {code} ({d['label']}):\n" + "\n".join(f"- {a}" for a in d.get("assumptions", [])),
                "sdtm_knowledge",
            )
        )
        for name, label, vtype, core in d["variables"]:
            text = f"{code}.{name}: {label}. Type {vtype}. Core: {CORE_NAMES[core]}."
            if name in CONTROLLED_TERMINOLOGY:
                text += f" Controlled terminology: {', '.join(CONTROLLED_TERMINOLOGY[name])}."
            if name.endswith("DTC"):
                text += " ISO 8601 character date/time (YYYY-MM-DDThh:mm:ss, partial dates truncated)."
            if name.endswith("DY"):
                text += " Study day relative to DM.RFSTDTC: date - RFSTDTC + 1 on/after, date - RFSTDTC before (no day 0)."
            if name.endswith("SEQ"):
                text += " Unique sequence number per USUBJID within the domain."
            chunks.append(_chunk(code, "variable", f"{code}.{name}", text, "sdtm_knowledge", name))
    for domain, tests in TEST_CODES.items():
        lines = "\n".join(f"- {cd}: {name}" + (f" (unit {u})" if u else "") for cd, (name, u) in tests.items())
        chunks.append(_chunk(domain, "codelist", f"{domain}TESTCD codelist", f"Standard {domain} test codes:\n{lines}", "sdtm_knowledge", f"{domain}TESTCD"))
    return chunks


_HEADING = re.compile(r"\b([A-Z][A-Za-z/,\- ]{2,60})\s*\(([A-Z]{2})\)")


def document_chunks(text: str, source: str, max_chars: int = 1800, overlap: int = 200) -> list[dict]:
    """Chunk IG text, tagging each chunk with the domain of the current section.

    Section headings such as '6.2.1 Adverse Events (AE)' switch the domain.
    Text before any recognised heading is tagged 'GENERAL'.
    """
    chunks: list[dict] = []
    domain, buf, carried = "GENERAL", "", ""

    def flush(keep_overlap: bool):
        nonlocal buf, carried
        body = buf.strip()
        if len(body) > 50 and body != carried.strip():
            chunks.append(_chunk(domain, "ig_text", f"SDTM IG — {domain}", body, source))
        carried = body[-overlap:] + "\n" if keep_overlap else ""
        buf = carried

    # PDF extraction can produce very long lines; wrap them so chunks stay bounded.
    lines = [part for raw in text.splitlines() for part in (textwrap.wrap(raw, max_chars // 2) or [""])]
    for line in lines:
        m = _HEADING.search(line)
        if m and m.group(2) in DOMAINS and len(line) < 120 and m.group(2) != domain:
            flush(keep_overlap=False)
            domain = m.group(2)
        buf += line + "\n"
        if len(buf) >= max_chars:
            flush(keep_overlap=True)
    flush(keep_overlap=False)
    return chunks


def approved_spec_chunks(specs: Iterable[dict]) -> list[dict]:
    """Chunks from approved mapping specs (rows with spec_json)."""
    chunks = []
    for row in specs:
        spec = json.loads(row["spec_json"]) if isinstance(row.get("spec_json"), str) else row
        lines = []
        for v in spec.get("variables", []):
            src = v.get("source") or v.get("expression") or (f"constant '{v.get('constant')}'" if v.get("constant") is not None else "")
            extra = []
            if v.get("value_map"):
                extra.append(f"value_map {json.dumps(v['value_map'])}")
            if v.get("date_format"):
                extra.append(f"date_format {v['date_format']}")
            lines.append(f"- {v['target']} <- {src}" + (f" ({'; '.join(extra)})" if extra else ""))
        if spec.get("unpivot"):
            tests = ", ".join(f"{t['source_column']}→{t['testcd']}" for t in spec["unpivot"]["tests"])
            lines.append(f"- unpivot: {tests}")
        content = (
            f"Approved {spec['domain']} mapping (study {spec['study_id']}, source {spec['source_table']}, "
            f"version {spec.get('version')}):\n" + "\n".join(lines)
        )
        chunks.append(
            _chunk(spec["domain"], "approved_mapping", f"Approved {spec['domain']} mapping {spec['spec_id']}", content, f"spec:{spec['spec_id']}")
        )
    return chunks
