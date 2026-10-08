"""Central safety laboratory cumulative transfer (one row per test result)."""
from __future__ import annotations

import random
from datetime import timedelta
from pathlib import Path

from common import id_lab, initials_for, lab_date, write_csv
from study import SITES, STUDYID, Subject

# code, name, battery, SI unit, low, high, sd-as-fraction, conventional unit, factor (SI->conv)
TESTS = [
    ("WBC", "White Blood Cell Count", "HEMATOLOGY", "10^9/L", 4.0, 11.0, .18, "10^3/uL", 1),
    ("NEUT", "Absolute Neutrophil Count", "HEMATOLOGY", "10^9/L", 1.8, 7.5, .22, "10^3/uL", 1),
    ("LYMPH", "Absolute Lymphocyte Count", "HEMATOLOGY", "10^9/L", 1.0, 4.0, .2, "10^3/uL", 1),
    ("HGB", "Hemoglobin", "HEMATOLOGY", "g/L", 120, 160, .07, "g/dL", .1),
    ("PLAT", "Platelet Count", "HEMATOLOGY", "10^9/L", 150, 400, .18, "10^3/uL", 1),
    ("ALT", "Alanine Aminotransferase", "CHEMISTRY", "U/L", 7, 35, .3, "U/L", 1),
    ("AST", "Aspartate Aminotransferase", "CHEMISTRY", "U/L", 10, 35, .25, "U/L", 1),
    ("ALP", "Alkaline Phosphatase", "CHEMISTRY", "U/L", 30, 120, .25, "U/L", 1),
    ("BILI", "Total Bilirubin", "CHEMISTRY", "umol/L", 3, 21, .3, "mg/dL", 1 / 17.1),
    ("CREAT", "Creatinine", "CHEMISTRY", "umol/L", 45, 90, .15, "mg/dL", 1 / 88.4),
    ("ALB", "Albumin", "CHEMISTRY", "g/L", 35, 50, .07, "g/dL", .1),
    ("SODIUM", "Sodium", "CHEMISTRY", "mmol/L", 135, 145, .015, "mEq/L", 1),
    ("K", "Potassium", "CHEMISTRY", "mmol/L", 3.5, 5.1, .07, "mEq/L", 1),
    ("GLUC", "Glucose", "CHEMISTRY", "mmol/L", 3.9, 5.6, .15, "mg/dL", 18.0),
    ("LDH", "Lactate Dehydrogenase", "CHEMISTRY", "U/L", 135, 214, .2, "U/L", 1),
    ("INR", "Prothrombin INR", "COAGULATION", "ratio", .8, 1.2, .06, "ratio", 1),
    ("APTT", "Activated Partial Thromboplastin Time", "COAGULATION", "s", 25, 37, .08, "s", 1),
    ("TSH", "Thyrotropin", "THYROID", "mIU/L", .4, 4.0, .35, "uIU/mL", 1),
    ("FT4", "Free Thyroxine", "THYROID", "pmol/L", 10, 22, .12, "ng/dL", 1 / 12.87),
    ("UPROT", "Urine Protein (dipstick)", "URINALYSIS", "", None, None, 0, "", 1),
    ("UBLD", "Urine Blood (dipstick)", "URINALYSIS", "", None, None, 0, "", 1),
    ("USG", "Urine Specific Gravity", "URINALYSIS", "", 1.005, 1.030, .004, "", 1),
    ("HBSAG", "Hepatitis B Surface Antigen", "SEROLOGY", "", None, None, 0, "", 1),
    ("HCVAB", "Hepatitis C Antibody", "SEROLOGY", "", None, None, 0, "", 1),
    ("HIV12", "HIV-1/2 Antigen/Antibody", "SEROLOGY", "", None, None, 0, "", 1),
]
COLS = ["PROTOCOL", "LAB_ID", "SITE_NUMBER", "INVESTIGATOR_NAME", "PATIENT_ID",
        "PATIENT_INITIALS", "YEAR_OF_BIRTH", "GENDER", "VISIT_DESCRIPTION", "LAB_VISIT_CODE",
        "ACCESSION_NUMBER", "COLLECTION_DATE", "COLLECTION_TIME", "RECEIVED_DATE",
        "REPORTED_DATE", "BATTERY", "TEST_CODE", "TEST_NAME", "SPECIMEN_TYPE",
        "REPORTED_RESULT", "REPORTED_UNITS", "REPORTED_LOW", "REPORTED_HIGH", "ABNORMAL_FLAG",
        "SI_RESULT", "SI_UNITS", "SI_LOW", "SI_HIGH", "TEST_STATUS", "RESULT_COMMENT"]


def _grade_on(s: Subject, pts: tuple[str, ...], when) -> int:
    """Highest grade of a matching AE that is active on ``when``."""
    g = 0
    for a in s.aes:
        end = a["end"] or when
        if a["pt"] in pts and a["onset"] - timedelta(days=3) <= when <= end:
            g = max(g, a["grade"])
    return g


def _value(rng: random.Random, s: Subject, t: tuple, when, base: dict) -> str | float | None:
    code, _, _, _, lo, hi, sd, *_ = t
    if code in ("HBSAG", "HCVAB", "HIV12"):
        return "NEGATIVE"
    if code in ("UPROT", "UBLD"):
        g = _grade_on(s, ("Proteinuria",), when) if code == "UPROT" else 0
        return {0: rng.choice(["NEGATIVE"] * 6 + ["TRACE"]), 1: "1+", 2: "2+", 3: "3+"}[min(g, 3)]
    mid = base.setdefault(code, rng.uniform(lo + (hi - lo) * .3, lo + (hi - lo) * .7))
    v = mid * (1 + rng.gauss(0, sd / 2))
    if code == "NEUT":
        g = _grade_on(s, ("Neutrophil count decreased", "Febrile neutropenia"), when)
        v = {1: rng.uniform(1.5, 1.8), 2: rng.uniform(1.0, 1.5), 3: rng.uniform(.5, 1.0),
             4: rng.uniform(.1, .5)}.get(g, v)
    elif code == "HGB" and (g := _grade_on(s, ("Anaemia",), when)):
        v = {1: rng.uniform(100, 118), 2: rng.uniform(80, 100), 3: rng.uniform(65, 80)}[min(g, 3)]
    elif code == "ALT" and (g := _grade_on(s, ("Alanine aminotransferase increased",), when)):
        v = hi * {1: rng.uniform(1.2, 3), 2: rng.uniform(3, 5), 3: rng.uniform(5, 15)}[min(g, 3)]
    elif code == "TSH" and _grade_on(s, ("Hypothyroidism",), when):
        v = rng.uniform(7, 28)
    elif code == "FT4" and _grade_on(s, ("Hypothyroidism",), when):
        v = rng.uniform(5, 9.5)
    dec = 2 if code in ("INR", "K", "WBC", "NEUT", "LYMPH", "TSH") else (
        3 if code == "USG" else 1 if code in ("GLUC", "FT4", "SODIUM", "APTT") else 0)
    return round(v, dec) if dec else int(round(v))


def build_lab(rng: random.Random, subjects: list[Subject], samples: dict, out: Path) -> dict:
    rows, base_by_subj, typo_done = [], {}, False
    missing = {id(m) for m in samples["missing_lab"]}
    for lab in samples["lab"]:
        if id(lab) in missing:
            continue
        s = lab["s"]
        us = SITES[s.site][0] == "USA"
        received = lab["date"] + timedelta(days=rng.choice([1, 1, 1, 2, 2, 3, 6]))
        base = base_by_subj.setdefault(s.subnum, {})
        pid = id_lab(s)
        if not typo_done and s.seq == 7 and lab["code"] == "C2D1":
            pid, typo_done = pid.replace("0", "O", 1), True    # keyed by hand at the lab
        hemolysed = rng.random() < .03
        for t in TESTS:
            if t[2] not in lab["panels"]:
                continue
            code, name, battery, si_u, lo, hi, _, conv_u, f = t
            v = _value(rng, s, t, lab["date"], base)
            status, comment = "FINAL", ""
            if code == "K" and hemolysed:
                v, status, comment = None, "CANCELLED", "Specimen hemolyzed; test not performed"
            numeric = isinstance(v, (int, float)) and lo is not None
            flag = ""
            if numeric:
                flag = ("LL" if v < lo * .5 else "L") if v < lo else (
                    ("HH" if v > hi * 3 else "H") if v > hi else "")
            conv = round(v * f, 2) if numeric and us else v
            row = {"PROTOCOL": STUDYID.replace("-", ""), "LAB_ID": "MCL-EU" if s.country in (
                "DEU", "ESP") else ("MCL-SG" if s.country in ("JPN", "AUS") else "MCL-US"),
                "SITE_NUMBER": f"00{s.site}", "INVESTIGATOR_NAME": SITES[s.site][1].upper(),
                "PATIENT_ID": pid, "PATIENT_INITIALS": initials_for(s, "lab"),
                "YEAR_OF_BIRTH": s.birth.year, "GENDER": "F",
                "VISIT_DESCRIPTION": lab["folder"].upper(),
                "LAB_VISIT_CODE": lab["code"].replace("C", "CY").replace("D", "DY")
                if lab["code"].startswith("C") else lab["code"],
                "ACCESSION_NUMBER": lab["accession"], "COLLECTION_DATE": lab_date(lab["date"]),
                "COLLECTION_TIME": lab["time"], "RECEIVED_DATE": lab_date(received),
                "REPORTED_DATE": lab_date(received + timedelta(days=rng.choice([0, 0, 1]))),
                "BATTERY": battery, "TEST_CODE": code, "TEST_NAME": name,
                "SPECIMEN_TYPE": "URINE" if battery == "URINALYSIS" else (
                    "WHOLE BLOOD" if battery == "HEMATOLOGY" else (
                        "PLASMA" if battery == "COAGULATION" else "SERUM")),
                "REPORTED_RESULT": "" if v is None else conv,
                "REPORTED_UNITS": conv_u if us else si_u,
                "REPORTED_LOW": round(lo * f, 2) if us and lo is not None else lo,
                "REPORTED_HIGH": round(hi * f, 2) if us and hi is not None else hi,
                "ABNORMAL_FLAG": flag, "SI_RESULT": "" if v is None else v, "SI_UNITS": si_u,
                "SI_LOW": lo, "SI_HIGH": hi, "TEST_STATUS": status, "RESULT_COMMENT": comment}
            rows.append(row)
            if flag in ("HH", "LL") and rng.random() < .25:   # re-run and re-issued
                rows.append({**row, "TEST_STATUS": "CORRECTED", "RESULT_COMMENT":
                             "Result confirmed on repeat analysis; supersedes prior report"})
    return {"central_lab_results.csv": write_csv(out / "central_lab_results.csv", COLS, rows)}
