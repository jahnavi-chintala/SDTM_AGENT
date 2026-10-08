"""Chunks from CDISC Library Excel exports (SDTMIG, SDTM model, CDASHIG) kept in a UC volume.

The CDISC Library exports each standard version as an .xlsx with a ``Datasets`` and a
``Variables`` sheet. Several versions usually sit side by side, so only one version of each
standard is indexed: the one configured (``sdtmig_version`` / ``cdashig_version``), or the
latest found. Mixing versions would let retrieval return, say, a 3.1.2 variable definition
while mapping to 3.4.

CDISC content is licensed, so none of it is bundled in this repo. The reader uses only the
standard library because .xlsx is a zip of XML parts.
"""

from __future__ import annotations

import logging
import os
import re
import zipfile
from xml.etree import ElementTree as ET

from sdtm_agent.ig_corpus import CORE_NAMES, _chunk

log = logging.getLogger(__name__)

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
       "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
_FILE = re.compile(r"^(SDTMIG|SDTM|CDASHIG|CDASH_Model)_v(\d+(?:\.\d+)*)(?: \(\d+\))?\.xlsx$", re.I)
# SDTM model version each SDTMIG version is built on.
SDTM_MODEL_FOR_IG = {"3.1.2": "1.2", "3.1.3": "1.3", "3.2": "1.4", "3.3": "1.7", "3.4": "2.0"}


def _col_index(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group():
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_xlsx(path: str) -> dict[str, list[list[str]]]:
    """Every sheet of a workbook as rows of strings (cells keep their column positions)."""
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", _NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))
        rels = {r.get("Id"): r.get("Target")
                for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        out: dict[str, list[list[str]]] = {}
        for sheet in ET.fromstring(z.read("xl/workbook.xml")).find("m:sheets", _NS):
            target = rels[sheet.get(f"{{{_NS['r']}}}id")].lstrip("/")
            target = target if target.startswith("xl/") else f"xl/{target}"
            rows = []
            for row in ET.fromstring(z.read(target)).iter(f"{{{_NS['m']}}}row"):
                cells: dict[int, str] = {}
                for c in row.findall("m:c", _NS):
                    v, kind = c.find("m:v", _NS), c.get("t")
                    if kind == "s" and v is not None:
                        val = shared[int(v.text)]
                    elif kind == "inlineStr":
                        val = "".join(t.text or "" for t in c.iter(f"{{{_NS['m']}}}t"))
                    else:
                        val = v.text if v is not None and v.text else ""
                    cells[_col_index(c.get("r"))] = val.strip()
                rows.append([cells.get(i, "") for i in range(max(cells) + 1)] if cells else [])
            out[sheet.get("name")] = rows
    return out


def _records(rows: list[list[str]]) -> list[dict[str, str]]:
    """Rows under the header row (the one starting with 'Version') as dicts."""
    start = next((i for i, r in enumerate(rows) if r and r[0] == "Version"), None)
    if start is None:
        return []
    header = rows[start]
    return [{h: (r[i] if i < len(r) else "") for i, h in enumerate(header) if h}
            for r in rows[start + 1:] if any(r)]


def find_library_files(volume_path: str) -> dict[str, dict[str, str]]:
    """{standard: {version: path}} for every CDISC Library workbook under the path."""
    found: dict[str, dict[str, str]] = {}
    for root, _, files in os.walk(volume_path):
        for name in files:
            m = _FILE.match(name)
            if m:
                std = {"sdtmig": "SDTMIG", "sdtm": "SDTM", "cdashig": "CDASHIG",
                       "cdash_model": "CDASH_Model"}[m.group(1).lower()]
                found.setdefault(std, {})[m.group(2)] = os.path.join(root, name)
    return found


def _latest(versions: dict[str, str]) -> str | None:
    return max(versions, key=lambda v: [int(p) for p in v.split(".")]) if versions else None


def sdtmig_chunks(path: str, version: str) -> list[dict]:
    """One overview chunk per dataset and one chunk per variable."""
    book = read_xlsx(path)
    source = f"SDTMIG v{version}"
    variables = _records(book.get("Variables", []))
    chunks = []
    for ds in _records(book.get("Datasets", [])):
        code = ds.get("Dataset Name", "")
        own = [v for v in variables if v.get("Dataset Name") == code]
        lines = "\n".join(f"- {v['Variable Name']} ({v.get('Variable Label', '')}; "
                          f"{v.get('Type', '')}; {CORE_NAMES.get(v.get('Core', ''), v.get('Core', ''))})"
                          for v in own)
        chunks.append(_chunk(code, "domain_overview", f"{source} — {code} {ds.get('Dataset Label', '')}",
                             f"{source} dataset {code} ({ds.get('Dataset Label', '')}), class "
                             f"{ds.get('Class', '')}.\nStructure: {ds.get('Structure', '')}.\n"
                             f"Variables:\n{lines}", source))
    for v in variables:
        code, name = v.get("Dataset Name", ""), v.get("Variable Name", "")
        text = (f"{source} {code}.{name}: {v.get('Variable Label', '')}. Type {v.get('Type', '')}. "
                f"Role {v.get('Role', '')}. Core: {CORE_NAMES.get(v.get('Core', ''), v.get('Core', ''))}.")
        codelist = " ".join(x for x in (v.get("Codelist Submission Value(s)", ""),
                                        f"({v['CDISC CT Codelist Code(s)']})"
                                        if v.get("CDISC CT Codelist Code(s)") else "") if x)
        if codelist:
            text += f" Codelist: {codelist}."
        if v.get("Described Value Domain(s)"):
            text += f" Format: {v['Described Value Domain(s)']}."
        if v.get("Value List"):
            text += f" Values: {v['Value List']}."
        if v.get("CDISC Notes"):
            text += f"\nCDISC notes: {v['CDISC Notes']}"
        chunks.append(_chunk(code, "variable", f"{source} {code}.{name}", text, source, name))
    return chunks


def sdtm_model_chunks(path: str, version: str) -> list[dict]:
    """Class-level variable definitions from the SDTM model (domain 'GENERAL' unless dataset-specific)."""
    source = f"SDTM v{version}"
    chunks = []
    for v in _records(read_xlsx(path).get("Variables", [])):
        code = v.get("Dataset Name") or "GENERAL"
        text = (f"{source} {v.get('Class', '')} variable {v.get('Variable Name', '')}: "
                f"{v.get('Variable Label', '')}. Type {v.get('Type', '')}. Role {v.get('Role', '')}.")
        for key in ("Definition", "Notes", "Usage Restrictions"):
            if v.get(key):
                text += f"\n{key}: {v[key]}"
        chunks.append(_chunk(code, "model_variable", f"{source} {v.get('Variable Name', '')}",
                             text, source, v.get("Variable Name")))
    return chunks


def cdashig_chunks(path: str, version: str) -> list[dict]:
    """CDASH collection fields with their SDTMIG target: the bridge from raw CRF columns to SDTM."""
    source = f"CDASHIG v{version}"
    chunks = []
    for v in _records(read_xlsx(path).get("Variables", [])):
        code, name = v.get("Domain", ""), v.get("CDASHIG Variable", "")
        target = v.get("SDTMIG Target", "")
        # The same field repeats once per collection scenario; keep them apart.
        # Its column title differs between CDASHIG versions, so match on the prefix.
        scenario = next((val for key, val in v.items()
                         if key.startswith("Data Collection Scenario")), "")
        where = f"{code}.{name}" + (f" [{scenario}]" if scenario else "")
        text = (f"{source} {where}: {v.get('CDASHIG Variable Label', '')}. "
                f"Question: {v.get('Question Text', '')} Prompt: {v.get('Prompt', '')}. "
                f"SDTMIG target: {target or 'not submitted'}.")
        definition = v.get("DRAFT CDASHIG Definition") or v.get("CDASHIG Definition", "")
        if definition:
            text += f"\nDefinition: {definition}"
        if v.get("Implementation Notes") or v.get("Mapping Instructions"):
            text += f"\nMapping: {v.get('Implementation Notes') or v.get('Mapping Instructions')}"
        chunks.append(_chunk(code or "GENERAL", "cdash_variable", f"{source} {where}", text,
                             source, target or name))
    return chunks


def library_chunks(volume_path: str, sdtmig_version: str = "", cdashig_version: str = "") -> list[dict]:
    """Chunks for one SDTMIG version (plus its SDTM model) and one CDASHIG version."""
    if not volume_path or not os.path.isdir(volume_path):
        return []
    found = find_library_files(volume_path)
    chunks: list[dict] = []
    ig = sdtmig_version or _latest(found.get("SDTMIG", {}))
    if ig and ig in found.get("SDTMIG", {}):
        chunks += sdtmig_chunks(found["SDTMIG"][ig], ig)
        model = SDTM_MODEL_FOR_IG.get(ig)
        if model and model in found.get("SDTM", {}):
            chunks += sdtm_model_chunks(found["SDTM"][model], model)
    elif ig:
        log.warning("SDTMIG v%s not found under %s (have %s)", ig, volume_path,
                    sorted(found.get("SDTMIG", {})))
    cd = cdashig_version or _latest(found.get("CDASHIG", {}))
    if cd and cd in found.get("CDASHIG", {}):
        chunks += cdashig_chunks(found["CDASHIG"][cd], cd)
    elif cd:
        log.warning("CDASHIG v%s not found under %s", cd, volume_path)
    log.info("CDISC library: SDTMIG v%s, CDASHIG v%s -> %d chunks", ig, cd, len(chunks))
    return chunks
