"""Shared helpers: CSV writing, each vendor's date style, and each vendor's subject ID style.

Real transfers never agree on how a patient is identified or how a date is written, so the
formats below deliberately differ by vendor. The answer key records how they map back.
"""
from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

from study import Subject

MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def write_csv(path: Path, header: list[str], rows: list[dict], delimiter: str = ",") -> int:
    """Write rows (dicts keyed by header) and return the row count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=header, delimiter=delimiter, extrasaction="ignore",
                           lineterminator="\r\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in header})
    return len(rows)


# ---- dates, one style per source -------------------------------------------------------
def iso(d: date | None) -> str:
    return d.isoformat() if d else ""


def rave_raw(d: date | None) -> str:          # as typed into Rave: "07 MAR 2025"
    return f"{d.day:02d} {MON[d.month - 1]} {d.year}" if d else ""


def lab_date(d: date | None) -> str:          # central lab: "07-MAR-2025"
    return f"{d.day:02d}-{MON[d.month - 1]}-{d.year}" if d else ""


def compact(d: date | None) -> str:           # bioanalytical LIMS: "20250307"
    return d.strftime("%Y%m%d") if d else ""


def us_date(d: date | None) -> str:           # imaging core lab: "03/07/2025"
    return d.strftime("%m/%d/%Y") if d else ""


def eu_date(d: date | None) -> str:           # proteomics lab: "07.03.2025"
    return d.strftime("%d.%m.%Y") if d else ""


def stamp(d: date, hhmm: str, tz: str) -> str:   # eCOA device clock with offset
    return f"{d.isoformat()}T{hhmm}:{(d.toordinal() * 7) % 60:02d}{tz}"


def irt_stamp(d: date, hhmm: str) -> str:     # IRT audit stamp in UTC
    return datetime(d.year, d.month, d.day, int(hhmm[:2]), int(hhmm[3:])).strftime(
        "%d-%b-%Y %H:%M:%S") + " UTC"


def rave_date_fields(name: str, d: date | None, partial: str = "") -> dict:
    """A Rave date field as exported: value, as-typed raw text, and its parts.

    ``partial`` is "day" (day unknown) or "month" (only the year known), which is how
    sites in privacy-strict countries record birth dates.
    """
    if not d:
        return {name: "", f"{name}_RAW": "", f"{name}_YYYY": "", f"{name}_MM": "",
                f"{name}_DD": ""}
    if partial == "month":
        return {name: str(d.year), f"{name}_RAW": f"UN UNK {d.year}", f"{name}_YYYY": d.year,
                f"{name}_MM": "", f"{name}_DD": ""}
    if partial == "day":
        return {name: f"{d.year}-{d.month:02d}", f"{name}_RAW": f"UN {MON[d.month - 1]} {d.year}",
                f"{name}_YYYY": d.year, f"{name}_MM": d.month, f"{name}_DD": ""}
    return {name: iso(d), f"{name}_RAW": rave_raw(d), f"{name}_YYYY": d.year,
            f"{name}_MM": d.month, f"{name}_DD": d.day}


def rave_date_cols(name: str) -> list[str]:
    return [name, f"{name}_RAW", f"{name}_YYYY", f"{name}_MM", f"{name}_DD"]


# ---- subject identifiers, one style per source -----------------------------------------
def id_edc(s: Subject) -> str:           # EDC / IRT: "101-007"
    return s.subnum


def id_lab(s: Subject) -> str:           # central lab: site and patient run together "101007"
    return f"{s.site}{s.seq:03d}"


def id_pk(s: Subject) -> str:            # bioanalytical LIMS pads both parts: "0101-0007"
    return f"{int(s.site):04d}-{s.seq:04d}"


def id_imaging(s: Subject) -> str:       # imaging core lab: "ZVR210201_101_007"
    return f"ZVR210201_{s.site}_{s.seq:03d}"


def id_genomics(s: Subject) -> str:      # genomics requisition form, as handwritten: "101-07"
    return f"{s.site}-{s.seq:02d}" if s.seq < 100 else s.subnum


def id_proteomics(s: Subject, visit_code: str) -> str:   # sample-level: "ZV101007-C1D1"
    return f"ZV{s.site}{s.seq:03d}-{visit_code}"


def initials_for(s: Subject, vendor: str) -> str:
    """Initials as each vendor holds them; EU sites send none, and formats differ."""
    if s.country in ("DEU", "ESP"):
        return {"lab": "---", "safety": "PRIVACY", "pk": ""}.get(vendor, "")
    if vendor == "lab":
        return s.initials
    if vendor == "pk":
        return s.initials.replace("-", "")
    if vendor == "safety":
        return f"{s.initials[0]}.{s.initials[2]}."
    return ""


def visit_code(folder: str) -> str:
    """"Cycle 3 Day 1" -> "C3D1"; other folders get short protocol codes."""
    if folder.startswith("Cycle "):
        c, d = folder.replace("Cycle ", "").split(" Day ")
        return f"C{c}D{d}"
    return {"Screening": "SCR", "End of Treatment": "EOT", "30-Day Safety Follow-up": "FU30",
            "Unscheduled": "UNS"}.get(folder, folder.upper().replace(" ", "")[:8])
