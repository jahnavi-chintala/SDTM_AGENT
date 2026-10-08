"""Bioanalytical transfers: PK concentrations and anti-drug antibodies from two labs.

ZV-210 goes to one lab (LIMS export, compact dates, padded IDs); ZK-415 to another
(different column names, day-first dates, its own ID habits).
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta
from pathlib import Path

from common import compact, id_pk, initials_for, write_csv
from study import STUDYID

# analyte -> (peak per dose at the reference dose, half-life days, LLOQ, ULOQ, unit)
PK = {"ZV-210": (410.0, 11.0, 0.05, 250.0, "ug/mL"),
      "ZK-415 (ADC)": (62000.0, 4.2, 20.0, 50000.0, "ng/mL"),
      "ZKP-1 (free payload)": (95.0, 1.4, 0.5, 400.0, "pg/mL")}
TPT_TEXT = {"PRE": "Pre-dose", "EOI": "End of infusion", "4H POST": "4 h after start",
            "168H": "Day 8 (168 h)", "336H": "Day 15 (336 h)", "EOT": "End of treatment"}
NB_COLS = ["STUDY_NUMBER", "LIMS_SAMPLE_ID", "SUBJECT_NO", "SUBJ_INITIALS", "VISIT",
           "NOMINAL_TIME", "NOMINAL_HOURS", "COLLECTION_DATE", "COLLECTION_TIME", "MATRIX",
           "ANALYTE", "CONCENTRATION", "UNITS", "LLOQ", "ULOQ", "BLQ_FLAG", "DILUTION_FACTOR",
           "ANALYTICAL_RUN", "ASSAY_DATE", "SAMPLE_CONDITION", "REASSAY_REASON", "COMMENTS"]
KB_COLS = ["Study", "Sample Barcode", "Subject", "Visit", "Timepoint", "Draw Date",
           "Draw Time", "Analyte", "Result", "Unit", "LLOQ", "Result Qualifier", "Batch",
           "Analysis Date", "Notes"]
ADA_COLS = ["STUDY_NUMBER", "LIMS_SAMPLE_ID", "SUBJECT_NO", "VISIT", "COLLECTION_DATE",
            "ANALYTE", "TIER", "ASSAY_RESULT", "SIGNAL_TO_NOISE", "CUT_POINT",
            "PERCENT_INHIBITION", "TITER", "FINAL_ADA_STATUS", "ANALYTICAL_RUN", "ASSAY_DATE"]


def _conc(analyte: str, t: datetime, doses: list[datetime], rng: random.Random) -> float:
    peak, t_half, *_ = PK[analyte]
    k = math.log(2) / (t_half * 24)
    total = 0.0
    for d in doses:
        h = (t - d).total_seconds() / 3600
        if h < 0:
            continue
        rise = min(1.0, h / 1.0) if h < 1 else 1.0          # infusion ramps over the first hour
        total += peak * rise * math.exp(-k * max(0.0, h - 1))
    return total * math.exp(rng.gauss(0, .25))


def build_bioanalytical(rng: random.Random, samples: dict, out: Path) -> dict:
    doses: dict[tuple, list[datetime]] = {}
    for inf in samples["infusions"]:
        doses.setdefault((inf["s"].subnum, inf["drug"]), []).append(inf["start_dt"])
    dosed = sorted({p["s"].subnum for p in samples["pk"]})    # sorted keeps runs repeatable
    ada_pos = {n for n in dosed if rng.random() < .09}
    nb_rows, kb_rows, ada_rows = [], [], []
    run = {"NB": 2300, "KB": 610}
    for p in samples["pk"]:
        s, drug = p["s"], p["drug"]
        dlist = [d for d in doses[(s.subnum, drug)] if d <= p["dt"]]
        assay = p["dt"].date() + timedelta(days=rng.randint(25, 70))
        if drug == "ZV-210":
            conc = _conc("ZV-210", p["dt"], dlist, rng)
            peak, _, lloq, uloq, unit = PK["ZV-210"]
            if s.subnum in ada_pos and p["code"] not in ("C1D1", "C1D8"):
                conc *= .45                                   # ADA-driven clearance
            blq = conc < lloq
            dil = 1 if conc <= uloq else 10
            run["NB"] += rng.random() < .3
            nb_rows.append({
                "STUDY_NUMBER": STUDYID, "LIMS_SAMPLE_ID": p["sample"], "SUBJECT_NO": id_pk(s),
                "SUBJ_INITIALS": initials_for(s, "pk"), "VISIT": p["code"],
                "NOMINAL_TIME": TPT_TEXT[p["tpt"]], "NOMINAL_HOURS": p["nominal_h"] or 1.0,
                "COLLECTION_DATE": compact(p["dt"].date()),
                "COLLECTION_TIME": p["dt"].strftime("%H%M"), "MATRIX": "SERUM",
                "ANALYTE": "ZV-210", "CONCENTRATION": "BLQ" if blq else round(conc, 3),
                "UNITS": unit, "LLOQ": lloq, "ULOQ": uloq, "BLQ_FLAG": "Y" if blq else "N",
                "DILUTION_FACTOR": dil, "ANALYTICAL_RUN": f"NB-R{run['NB']}",
                "ASSAY_DATE": compact(assay),
                "SAMPLE_CONDITION": "FROZEN" if rng.random() > .02 else "PARTIALLY THAWED",
                "REASSAY_REASON": "Above ULOQ; re-assayed at 1:10" if dil > 1 else "",
                "COMMENTS": ""})
        else:
            for analyte in ("ZK-415 (ADC)", "ZKP-1 (free payload)"):
                conc = _conc(analyte, p["dt"], dlist, rng)
                _, _, lloq, _, unit = PK[analyte]
                run["KB"] += rng.random() < .25
                kb_rows.append({
                    "Study": "ZVR210/201", "Sample Barcode": p["sample"],
                    "Subject": f"{s.site}{s.seq:03d}" if rng.random() > .05 else s.subnum,
                    "Visit": p["code"].replace("C", "Cycle ").replace("D", " Day ")
                    if p["code"].startswith("C") else p["code"], "Timepoint": TPT_TEXT[p["tpt"]],
                    "Draw Date": p["dt"].strftime("%d/%m/%Y"),
                    "Draw Time": p["dt"].strftime("%H:%M"), "Analyte": analyte,
                    "Result": f"<{lloq}" if conc < lloq else round(conc, 1), "Unit": unit,
                    "LLOQ": lloq, "Result Qualifier": "BLQ" if conc < lloq else "",
                    "Batch": f"KB{run['KB']:05d}", "Analysis Date": assay.strftime("%d/%m/%Y"),
                    "Notes": "Haemolysed (slight)" if rng.random() < .02 else ""})
    for a in samples["ada"]:
        s = a["s"]
        pos = s.subnum in ada_pos and a["code"] not in ("C1D1",)
        sn = round(rng.uniform(2.2, 9.0) if pos else rng.uniform(.8, 1.35), 2)
        base = {"STUDY_NUMBER": STUDYID, "LIMS_SAMPLE_ID": a["sample"], "SUBJECT_NO": id_pk(s),
                "VISIT": a["code"], "COLLECTION_DATE": compact(a["dt"].date()),
                "ANALYTE": f"Anti-{a['drug']} antibodies",
                "ANALYTICAL_RUN": f"ADA-R{rng.randint(100, 180)}",
                "ASSAY_DATE": compact(a["dt"].date() + timedelta(days=rng.randint(40, 90)))}
        screen_pos = pos or sn > 1.3
        ada_rows.append({**base, "TIER": "SCREENING", "SIGNAL_TO_NOISE": sn, "CUT_POINT": 1.31,
                         "ASSAY_RESULT": "POSITIVE" if screen_pos else "NEGATIVE",
                         "FINAL_ADA_STATUS": "" if screen_pos else "NEGATIVE"})
        if screen_pos:
            inh = round(rng.uniform(45, 92) if pos else rng.uniform(5, 18), 1)
            ada_rows.append({**base, "TIER": "CONFIRMATORY", "PERCENT_INHIBITION": inh,
                             "CUT_POINT": "21.4%", "ASSAY_RESULT": "POSITIVE" if pos else
                             "NEGATIVE", "FINAL_ADA_STATUS": "" if pos else "NEGATIVE"})
        if pos:
            ada_rows.append({**base, "TIER": "TITER", "TITER": rng.choice(
                ["1:50", "1:150", "1:450", "1:1350"]), "ASSAY_RESULT": "POSITIVE",
                "FINAL_ADA_STATUS": "POSITIVE"})
    return {
        "northbridge_pk_zv210.csv": write_csv(out / "northbridge_pk_zv210.csv", NB_COLS,
                                              nb_rows),
        "kestrel_pk_zk415.csv": write_csv(out / "kestrel_pk_zk415.csv", KB_COLS, kb_rows),
        "northbridge_ada.csv": write_csv(out / "northbridge_ada.csv", ADA_COLS, ada_rows),
    }
