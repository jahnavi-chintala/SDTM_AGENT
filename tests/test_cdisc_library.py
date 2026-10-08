"""CDISC Library .xlsx reader and chunker, on tiny made-up workbooks (CDISC content is licensed)."""

import zipfile
from xml.sax.saxutils import escape

from sdtm_agent.cdisc_library import find_library_files, library_chunks, read_xlsx

_CT = ('<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
       '<Default Extension="xml" ContentType="application/xml"/></Types>')
_M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _col(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def make_xlsx(path, sheets: dict[str, list[list[str]]]) -> None:
    """A minimal valid workbook using inline strings."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", _CT)
        names = list(sheets)
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{_M}" xmlns:r="{_R}"><sheets>' + "".join(
            f'<sheet name="{n}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, n in enumerate(names))
            + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i + 1}" Target="worksheets/sheet{i + 1}.xml" '
                             f'Type="{_R}/worksheet"/>' for i in range(len(names)))
                   + "</Relationships>")
        for i, n in enumerate(names):
            rows = "".join(
                f'<row r="{r + 1}">' + "".join(
                    f'<c r="{_col(c)}{r + 1}" t="inlineStr"><is><t>{escape(v)}</t></is></c>'
                    for c, v in enumerate(row) if v) + "</row>"
                for r, row in enumerate(sheets[n]))
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml",
                       f'<worksheet xmlns="{_M}"><sheetData>{rows}</sheetData></worksheet>')


IG_VARS = ["Version", "Variable Order", "Class", "Dataset Name", "Variable Name", "Variable Label",
           "Type", "CDISC CT Codelist Code(s)", "Codelist Submission Value(s)",
           "Described Value Domain(s)", "Value List", "Role", "CDISC Notes", "Core"]
DS = ["Version", "Class", "Dataset Name", "Dataset Label", "Structure"]


def _ig(tmp_path, version: str, label: str):
    make_xlsx(tmp_path / f"SDTMIG_v{version}.xlsx", {
        "ReadMe": [["Made-up test workbook"]],
        "Variables": [IG_VARS, [f"SDTMIG v{version}", "1", "Events", "XX", "XXTERM", label, "Char",
                                "", "", "", "", "Topic", "Verbatim term.", "Req"],
                      [f"SDTMIG v{version}", "2", "Events", "XX", "XXSEV", "Severity", "Char",
                       "C00001", "SEVCODE", "", "", "Record Qualifier", "", "Perm"]],
        "Datasets": [DS, [f"SDTMIG v{version}", "Events", "XX", "Example Events",
                          "One record per event"]]})


def test_read_xlsx_keeps_cell_positions(tmp_path):
    make_xlsx(tmp_path / "t.xlsx", {"S": [["a", "", "c"], [], ["x"]]})
    assert read_xlsx(str(tmp_path / "t.xlsx"))["S"] == [["a", "", "c"], [], ["x"]]


def test_finds_versions_and_ignores_download_suffix(tmp_path):
    (tmp_path / "SDTMIG" / "v3.4").mkdir(parents=True)
    _ig(tmp_path / "SDTMIG" / "v3.4", "3.4", "Reported Term")
    make_xlsx(tmp_path / "SDTM_v2.1 (1).xlsx", {"Variables": [["Version"]]})
    make_xlsx(tmp_path / "notes.xlsx", {"S": [["x"]]})
    found = find_library_files(str(tmp_path))
    assert set(found) == {"SDTMIG", "SDTM"} and set(found["SDTM"]) == {"2.1"}


def test_indexes_only_the_chosen_sdtmig_version(tmp_path):
    _ig(tmp_path, "3.2", "Old Label")
    _ig(tmp_path, "3.4", "Reported Term")
    latest = library_chunks(str(tmp_path))
    assert {c["source"] for c in latest} == {"SDTMIG v3.4"}
    var = next(c for c in latest if c["variable"] == "XXSEV")
    assert var["domain"] == "XX" and "SEVCODE (C00001)" in var["content"] and "Permissible" in var["content"]
    overview = next(c for c in latest if c["chunk_type"] == "domain_overview")
    assert "One record per event" in overview["content"] and "XXTERM (Reported Term" in overview["content"]
    pinned = library_chunks(str(tmp_path), sdtmig_version="3.2")
    assert {c["source"] for c in pinned} == {"SDTMIG v3.2"}
    assert any("Old Label" in c["content"] for c in pinned)
    assert library_chunks(str(tmp_path), sdtmig_version="9.9") == []


def test_cdashig_chunks_carry_sdtm_target(tmp_path):
    make_xlsx(tmp_path / "CDASHIG_v2.3.xlsx", {"Variables": [
        ["Version", "Class", "Domain", "Variable Order", "CDASHIG Variable", "CDASHIG Variable Label",
         "DRAFT CDASHIG Definition", "Question Text", "Prompt", "Type", "CDASHIG Core", "SDTMIG Target"],
        ["CDASHIG v2.3", "Events", "XX", "1", "XXSTDAT", "Start Date", "Date it began.",
         "When did it start?", "Start Date", "Char", "HR", "XXSTDTC"]]})
    chunks = library_chunks(str(tmp_path))
    assert len(chunks) == 1 and chunks[0]["chunk_type"] == "cdash_variable"
    assert chunks[0]["variable"] == "XXSTDTC" and "SDTMIG target: XXSTDTC" in chunks[0]["content"]


def test_cdashig_scenarios_do_not_collide(tmp_path):
    head = ["Version", "Class", "Domain", "Data Collection Scenario/Implementation Option", "Variable Order",
            "CDASHIG Variable", "CDASHIG Variable Label", "Question Text", "Prompt", "SDTMIG Target"]
    row = ["CDASHIG v2.3", "Findings", "XX", "", "1", "STUDYID", "Study Identifier",
           "What is the study identifier?", "Study", "STUDYID"]
    make_xlsx(tmp_path / "CDASHIG_v2.3.xlsx", {"Variables": [
        head, row[:3] + ["Dispensed"] + row[4:], row[:3] + ["Returned"] + row[4:]]})
    chunks = library_chunks(str(tmp_path))
    assert len({c["id"] for c in chunks}) == 2 and "[Returned]" in chunks[1]["title"]


def test_codelist_without_submission_value_reads_cleanly(tmp_path):
    _ig(tmp_path, "3.4", "Reported Term")
    term = next(c for c in library_chunks(str(tmp_path)) if c["variable"] == "XXTERM")
    assert "Codelist" not in term["content"]


def test_missing_volume_is_empty():
    assert library_chunks("") == [] and library_chunks("/no/such/volume") == []
