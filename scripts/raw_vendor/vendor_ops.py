"""Operational vendors: IRT (randomisation, kits), eCOA (questionnaires), safety database."""
from __future__ import annotations

import math
import random
from datetime import timedelta
from pathlib import Path

from common import initials_for, irt_stamp, lab_date, stamp, write_csv
from safety import ARM_DRUGS
from samples import code_of
from study import DATA_CUT, SITES, Subject, visit_plan

IRT_COLS = ["Study", "Country", "Site", "Subject Number", "Screening Date", "Screening Status",
            "Randomization Number", "Randomization Date (UTC)", "Stratum: PD-L1 CPS",
            "Stratum: Prior Taxane", "Treatment Arm", "Current Status", "Status Date (UTC)"]
KIT_COLS = ["Study", "Site", "Subject Number", "Visit", "Transaction", "Kit Number", "Kit Type",
            "Lot Number", "Expiry", "Transaction Date (UTC)", "Performed By"]
COA_COLS = ["Protocol", "Site", "Subject", "Device ID", "Questionnaire", "Language", "Visit",
            "Window Open", "Started", "Completed", "Status", "Reason Not Done", "Item",
            "Response Value", "Response Label"]
SAF_COLS = ["Case Number", "Case Version", "Initial Receipt Date", "Latest Receipt Date",
            "Report Type", "Study", "Center", "Patient ID", "Patient Initials", "Age", "Sex",
            "Country", "Event Verbatim", "MedDRA PT", "MedDRA SOC", "MedDRA Version",
            "Onset Date", "Seriousness Criteria", "Event Outcome", "Suspect Products",
            "Investigator Causality", "Company Causality", "Expectedness", "Action Taken"]
KITS = {"ZV-210": ("ZV-210 400 mg/16 mL vial", 400, "ZV24"), "ZK-415": ("ZK-415 100 mg "
                                                                       "lyophilised vial", 100, "ZK25")}
LANG = {"USA": "English (US)", "ESP": "Spanish (Spain)", "DEU": "German", "JPN": "Japanese",
        "AUS": "English (Australia)"}
SCALE4 = {1: "Not at all", 2: "A little", 3: "Quite a bit", 4: "Very much"}


def build_irt(rng: random.Random, subjects: list[Subject], samples: dict, out: Path) -> dict:
    rows, kits, kit_no = [], [], 100400
    mis = next(x.subnum for x in subjects if x.randomised and x.site == "301")
    for s in subjects:
        strata = dict(s.strata)
        if s.subnum == mis:                  # mis-stratified at randomisation: IRT != EDC
            strata["PDL1_CPS"] = "<10" if strata.get("PDL1_CPS") == ">=10" else ">=10"
        status, when = ("Screen Failed", s.screen_date + timedelta(days=rng.randint(3, 14))) \
            if s.screen_fail else ("Randomized", s.rand_date)
        if s.randomised and s.eot_date:
            status, when = "Treatment Discontinued", s.eot_date
        if s.death_date:
            status, when = "Deceased", s.death_date
        rows.append({
            "Study": "ZVR210-201", "Country": s.country, "Site": s.site,
            "Subject Number": s.subnum, "Screening Date": irt_stamp(s.screen_date, "14:05"),
            "Screening Status": "Screen Failed" if s.screen_fail else "Screened",
            "Randomization Number": s.rand_no,
            "Randomization Date (UTC)": irt_stamp(s.rand_date, f"{rng.randint(7, 20):02d}:"
                                                  f"{rng.randint(0, 59):02d}")
            if s.rand_date else "", "Stratum: PD-L1 CPS": strata.get("PDL1_CPS", ""),
            "Stratum: Prior Taxane": strata.get("PRIOR_TAXANE", ""),
            "Treatment Arm": {"ZV210": "A", "ZV210_ZK415": "B", "PACLI": "C"}.get(s.arm, ""),
            "Current Status": status, "Status Date (UTC)": irt_stamp(when, "09:00")})
    for inf in samples["infusions"]:
        if inf["drug"] not in KITS:
            continue                          # paclitaxel is sourced locally, not via IRT
        s = inf["s"]
        label, mg, lot = KITS[inf["drug"]]
        per_kg = 20 if inf["drug"] == "ZV-210" else 3
        for _ in range(math.ceil(per_kg * s.weight / mg)):
            kit_no += rng.randint(1, 4)
            kits.append({"Study": "ZVR210-201", "Site": s.site, "Subject Number": s.subnum,
                         "Visit": code_of(inf["folder"]), "Transaction": "Dispense",
                         "Kit Number": f"{kit_no:07d}", "Kit Type": label,
                         "Lot Number": f"{lot}{rng.choice(['A01', 'A02', 'B01'])}",
                         "Expiry": "31-Dec-2027", "Performed By": "Site Pharmacist",
                         "Transaction Date (UTC)": irt_stamp(inf["date"] - timedelta(
                             days=rng.choice([0, 0, 1])), "07:40")})
    return {"randosure_irt_subjects.csv": write_csv(out / "randosure_irt_subjects.csv",
                                                    IRT_COLS, rows),
            "randosure_irt_dispensing.csv": write_csv(out / "randosure_irt_dispensing.csv",
                                                      KIT_COLS, kits)}


def build_ecoa(rng: random.Random, subjects: list[Subject], out: Path) -> dict:
    rows = []
    stray = next(x.subnum for x in subjects if x.randomised and x.site == "102")
    for s in subjects:
        if not s.randomised:
            continue
        tz = SITES[s.site][2]
        device = f"PP-{rng.randint(10000, 99999)}"
        pd_dates = [t["date"] for t in s.tumour if t["resp"] == "PD"]
        for f, d in visit_plan(s):
            code = code_of(f)
            if not (code.endswith("D1") or code in ("EOT", "FU30")) or code.startswith("C1D8"):
                continue
            subj = s.subnum + (" " if s.subnum == stray else "")   # stray space at entry
            base = {"Protocol": "ZVR210-201", "Site": s.site, "Subject": subj,
                    "Device ID": device, "Questionnaire": "EORTC QLQ-C30 (v3.0)",
                    "Language": LANG[s.country], "Visit": code, "Window Open": d.isoformat()}
            if rng.random() < .07:
                rows.append({**base, "Status": "Missed", "Reason Not Done": rng.choice(
                    ["Device not charged", "Subject too unwell", "Window expired"])})
                continue
            worse = 1 if pd_dates and d >= pd_dates[0] - timedelta(days=21) else 0
            start = f"{rng.randint(7, 10):02d}:{rng.randint(0, 59):02d}"
            for q in range(1, 31):
                if q >= 29:      # global health items, 1 (very poor) to 7 (excellent)
                    v = max(1, min(7, int(rng.gauss(5 - 1.5 * worse, 1))))
                    label = str(v)
                else:
                    v = max(1, min(4, int(rng.gauss(1.6 + worse, .8))))
                    label = SCALE4[v]
                rows.append({**base, "Started": stamp(d, start, tz), "Completed": stamp(
                    d, f"{int(start[:2]):02d}:{min(59, int(start[3:]) + 9):02d}", tz),
                    "Status": "Completed", "Item": f"Q{q}", "Response Value": v,
                    "Response Label": label})
    return {"propoint_ecoa_qlqc30.csv": write_csv(out / "propoint_ecoa_qlqc30.csv", COA_COLS,
                                                  rows)}


def build_safety(rng: random.Random, subjects: list[Subject], out: Path) -> dict:
    rows, case = [], 4500
    extra_done = False
    for s in subjects:
        events = [a for a in s.aes if a["serious"]]
        if not extra_done and s.randomised and len(s.dose_dates) > 4 and s.arm != "PACLI":
            extra_done = True        # reported to safety directly, never entered in EDC
            events.append({"term": "Pulmonary embolism", "pt": "Pulmonary embolism",
                           "soc": "Respiratory, thoracic and mediastinal disorders",
                           "onset": s.dose_dates[3] + timedelta(days=6), "grade": 3,
                           "related": {d: False for d in ARM_DRUGS[s.arm]}, "hosp": True,
                           "outcome": "Recovering/Resolving", "action": "Drug Interrupted"})
        for a in events:
            case += rng.randint(2, 30)
            versions = rng.choice([1, 1, 2, 3])
            onset = a["onset"]
            onset_txt = lab_date(onset) if rng.random() > .1 else f"UNK-{lab_date(onset)[3:]}"
            crit = "; ".join(c for c, on in [("Death", a["grade"] == 5),
                                              ("Life-threatening", a["grade"] == 4),
                                              ("Hospitalization", a["hosp"]),
                                              ("Other medically important", not a["hosp"])] if on)
            for v in range(1, versions + 1):
                received = onset + timedelta(days=rng.randint(0, 2) + (v - 1) * rng.randint(6, 20))
                if received > DATA_CUT:
                    break
                rows.append({
                    "Case Number": f"{(onset + timedelta(days=1)).year}ZV{case:07d}", "Case Version": v,
                    "Initial Receipt Date": lab_date(onset + timedelta(days=1)),
                    "Latest Receipt Date": lab_date(received), "Report Type": "Study",
                    "Study": "ZVR210-201", "Center": s.site,
                    "Patient ID": f"{s.site}/{s.seq:03d}",
                    "Patient Initials": initials_for(s, "safety"), "Age": s.age, "Sex": "Female",
                    "Country": s.country, "Event Verbatim": a["term"].upper(),
                    "MedDRA PT": a["pt"], "MedDRA SOC": a["soc"], "MedDRA Version": "27.1",
                    "Onset Date": onset_txt, "Seriousness Criteria": crit,
                    "Event Outcome": a["outcome"] if v == versions else "Not Recovered/Not Resolved",
                    "Suspect Products": "; ".join(a["related"]),
                    "Investigator Causality": "; ".join(
                        f"{d}: {'Related' if r else 'Not related'}" for d, r in a["related"].items()),
                    "Company Causality": "Related" if any(a["related"].values()) else
                    "Not related", "Expectedness": "Unlisted" if a["pt"] in (
                        "Pulmonary embolism", "Pneumonitis") else "Listed",
                    "Action Taken": a["action"]})
    return {"sponsor_safety_sae_listing.csv": write_csv(out / "sponsor_safety_sae_listing.csv",
                                                        SAF_COLS, rows)}
