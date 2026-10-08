"""Every sample and infusion, planned once so EDC and the vendor files refer to the same ones."""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from study import Subject, visit_plan

# timepoint label, folder (None = the cycle's Day 1 for that cycle), hours after start of infusion
PK_SCHEDULE = [("C1D1", "PRE", -0.5), ("C1D1", "EOI", None), ("C1D1", "4H POST", 4),
               ("C1D8", "168H", 168), ("C1D15", "336H", 336), ("C2D1", "PRE", -0.5),
               ("C2D1", "EOI", None), ("C4D1", "PRE", -0.5), ("C4D1", "EOI", None),
               ("C8D1", "PRE", -0.5), ("EOT", "EOT", 0)]
ADA_VISITS = ["C1D1", "C2D1", "C4D1", "C8D1", "EOT", "FU30"]
INFUSION_MIN = {"ZV-210": 60, "ZK-415": 30, "Paclitaxel": 60}
BIO_DRUGS = {"ZV210": ["ZV-210"], "ZV210_ZK415": ["ZV-210", "ZK-415"], "PACLI": []}


def _hhmm(t: datetime) -> str:
    return t.strftime("%H:%M")


def code_of(folder: str) -> str:
    if folder.startswith("Cycle "):
        c, d = folder.replace("Cycle ", "").split(" Day ")
        return f"C{c}D{d}"
    return {"Screening": "SCR", "End of Treatment": "EOT",
            "30-Day Safety Follow-up": "FU30"}[folder]


def build_samples(rng: random.Random, subjects: list[Subject]) -> dict:
    """Return lab draws, PK/ADA/biomarker samples and infusion times, keyed for reuse."""
    out = {"lab": [], "pk": [], "ada": [], "bio": [], "infusions": [], "missing_lab": []}
    acc = 40021000 + rng.randint(0, 900)
    nb, kb, hx, pm = 3100400, 552000, 10450, 7700
    for s in subjects:
        visits = visit_plan(s)
        by_code = {code_of(f): (f, d) for f, d in visits}
        # infusions: start between 08:30 and 11:30; drugs given one after another
        for f, d in visits:
            code = code_of(f)
            if not code.startswith("C"):
                continue
            day = code.split("D")[1]
            drugs = ["Paclitaxel"] if s.arm == "PACLI" else (
                BIO_DRUGS[s.arm] if day == "1" else [])
            t = datetime(d.year, d.month, d.day, rng.randint(8, 11), rng.choice([0, 15, 30, 45]))
            for drug in drugs:
                end = t + timedelta(minutes=INFUSION_MIN[drug] + rng.choice([0, 0, 3, 5, 12]))
                out["infusions"].append({"s": s, "folder": f, "code": code, "drug": drug,
                                         "date": d, "start": _hhmm(t), "end": _hhmm(end),
                                         "start_dt": t, "end_dt": end,
                                         "cycle": int(code[1:].split("D")[0])})
                t = end + timedelta(minutes=30)
        inf = {(i["code"], i["drug"]): i for i in out["infusions"] if i["s"] is s}
        # central safety labs
        for f, d in visits:
            code = code_of(f)
            if code == "FU30" or (code.startswith("C") and not code.endswith("D1")
                                  and code not in ("C1D8", "C1D15")):
                continue
            first = inf.get((code, "ZV-210")) or inf.get((code, "Paclitaxel"))
            draw = (first["start_dt"] - timedelta(minutes=rng.randint(20, 90))) if first else \
                datetime(d.year, d.month, d.day, rng.randint(8, 12), rng.choice([5, 20, 40]))
            cyc = int(code[1:].split("D")[0]) if code.startswith("C") else 0
            panels = ["HEMATOLOGY", "CHEMISTRY"]
            if code == "SCR":
                panels += ["COAGULATION", "URINALYSIS", "THYROID", "SEROLOGY"]
            elif code.endswith("D1"):
                panels.append("URINALYSIS")
                if cyc % 2 == 1:
                    panels.append("THYROID")
            elif code == "EOT":
                panels += ["URINALYSIS", "THYROID"]
            acc += rng.randint(3, 40)
            rec = {"s": s, "folder": f, "code": code, "date": draw.date(), "time": _hhmm(draw),
                   "accession": f"{acc}", "panels": panels}
            if rng.random() < 0.025 and code != "SCR":
                out["missing_lab"].append(rec)      # site says collected; lab never got it
            out["lab"].append(rec)
        # PK and ADA for biologic arms
        for drug in BIO_DRUGS.get(s.arm, []):
            for code, tpt, hours in PK_SCHEDULE:
                if code not in by_code:
                    continue
                f, d = by_code[code]
                anchor = inf.get((code, drug)) or inf.get(("C1D1", drug))
                if hours is None:
                    t = anchor["end_dt"] + timedelta(minutes=rng.randint(2, 15))
                elif hours < 0:
                    t = anchor["start_dt"] - timedelta(minutes=rng.randint(10, 55))
                elif code in ("C1D8", "C1D15", "EOT"):
                    t = datetime(d.year, d.month, d.day, rng.randint(8, 12), rng.randint(0, 59))
                else:
                    t = anchor["start_dt"] + timedelta(hours=hours, minutes=rng.randint(-10, 20))
                if drug == "ZV-210":
                    nb += rng.randint(1, 9)
                    sid = f"NB{nb}"
                else:
                    kb += rng.randint(1, 9)
                    sid = f"KB-{kb}"
                out["pk"].append({"s": s, "folder": f, "code": code, "tpt": tpt, "drug": drug,
                                  "dt": t, "sample": sid, "nominal_h": hours,
                                  "dose_start": anchor["start_dt"]})
            for code in ADA_VISITS:
                if code not in by_code:
                    continue
                f, d = by_code[code]
                anchor = inf.get((code, drug))
                t = (anchor["start_dt"] - timedelta(minutes=rng.randint(10, 50)) if anchor
                     else datetime(d.year, d.month, d.day, rng.randint(8, 12), 30))
                nb += rng.randint(1, 9)
                out["ada"].append({"s": s, "folder": f, "code": code, "drug": drug, "dt": t,
                                   "sample": (f"NB{nb}A" if drug == "ZV-210" else f"KB-{nb}A")})
        # biomarkers: plasma ctDNA, buffy coat, serum proteins, archival tissue
        plan = [("SCR", "Plasma (ctDNA)"), ("SCR", "Buffy coat"), ("SCR", "Archival FFPE tissue"),
                ("C3D1", "Plasma (ctDNA)"), ("EOT", "Plasma (ctDNA)"),
                ("C1D1", "Serum"), ("C1D8", "Serum"), ("C2D1", "Serum"), ("C3D1", "Serum"),
                ("EOT", "Serum")]
        for code, spec in plan:
            if code not in by_code or (s.screen_fail and spec != "Archival FFPE tissue"):
                continue
            if s.screen_fail:
                continue
            f, d = by_code[code]
            hx += rng.randint(1, 5)
            pm += rng.randint(1, 5)
            out["bio"].append({"s": s, "folder": f, "code": code, "specimen": spec, "date": d,
                               "time": f"{rng.randint(8, 11):02d}:{rng.choice(['05', '25', '50'])}",
                               "kit": f"BK{hx:06d}" if spec != "Serum" else f"PM{pm:05d}"})
    return out


def first_dose(samples: dict, s: Subject) -> date | None:
    days = [i["date"] for i in samples["infusions"] if i["s"] is s]
    return min(days) if days else None
