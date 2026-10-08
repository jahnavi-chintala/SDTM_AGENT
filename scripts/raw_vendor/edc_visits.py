"""EDC per-visit forms: visits, vitals, ECG, ECOG, samples, dosing, RECIST, AEs, disposition."""
from __future__ import annotations

import random
from datetime import timedelta

from common import rave_date_fields
from edc_base import Rave, coded, yn
from safety import GRADE_TXT
from samples import code_of
from study import DATA_CUT, Subject, visit_plan

DOSE = {"ZV-210": (20, "mg/kg"), "ZK-415": (3, "mg/kg"), "Paclitaxel": (80, "mg/m2")}
EX_OID = {"ZV-210": "EXZV", "ZK-415": "EXZK", "Paclitaxel": "EXPAC"}


def bsa(h: float, w: float) -> float:
    return round(((h * w) / 3600) ** 0.5, 2)        # Mosteller


def visit_forms(rave: Rave, rng: random.Random, s: Subject, samples: dict) -> None:
    hyper = any(a["pt"] == "Hypertension" for a in s.aes)
    weight = s.weight
    for f, d in visit_plan(s):
        code = code_of(f)
        missed = code not in ("SCR", "C1D1") and rng.random() < .015
        rave.add("SV", "Visit Date", s, f, d, {
            **yn("VISYN", not missed), **rave_date_fields("VISDAT", None if missed else d),
            **coded("VISREASND", "Subject unable to attend" if missed else ""),
            **coded("SVCNTMOD", "In Person" if not missed else "")})
        if missed:
            continue
        weight = round(weight + rng.gauss(-0.15, 0.8), 1)
        if code == "SCR" or code.endswith("D1") or code == "EOT":
            sys_bp = int(rng.gauss(150 if hyper and code not in ("SCR", "C1D1") else 124, 11))
            rave.add("VS", "Vital Signs", s, f, d, {
                **yn("VSPERF", True), **rave_date_fields("VSDAT", d),
                "VSTIM": f"{rng.randint(8, 11):02d}:{rng.randint(0, 59):02d}",
                "SYSBP_VSORRES": sys_bp, "DIABP_VSORRES": int(sys_bp * rng.uniform(.58, .68)),
                "PULSE_VSORRES": int(rng.gauss(78, 9)), "RESP_VSORRES": rng.choice([14, 16, 16,
                                                                                   18, 20]),
                "TEMP_VSORRES": round(rng.gauss(36.7, .3), 1), **coded("TEMP_VSORRESU", "C"),
                **coded("TEMP_VSLOC", rng.choice(["Oral", "Tympanic", "Axillary"])),
                **coded("VSPOS", "Sitting")})
            rave.add("VSW", "Height, Weight and BSA", s, f, d, {
                **rave_date_fields("VSDAT", d), "HEIGHT_VSORRES": s.height if code == "SCR"
                else "", "WEIGHT_VSORRES": weight,
                "BSA_VSORRES": bsa(s.height, weight)})
            pd = s.outcome in ("PD", "DEATH") and code == "EOT"
            rave.add("ECOG", "ECOG Performance Status", s, f, d, {
                **yn("RSPERF", True), **rave_date_fields("RSDAT", d),
                **coded("RSORRES", *rng.choice(
                    [("1 - Restricted in physically strenuous activity", "1"),
                     ("2 - Ambulatory, capable of self-care", "2")] if pd else
                    [("0 - Fully active", "0"), ("0 - Fully active", "0"),
                     ("1 - Restricted in physically strenuous activity", "1")]))})
        if code in ("SCR", "C1D1", "C2D1", "C4D1", "EOT"):
            for rep in range(1, 4 if code in ("C1D1", "C2D1") else 2):
                qtcf = int(rng.gauss(412, 14))
                rave.add("EG", "12-Lead ECG", s, f, d, {
                    "EGREPNUM": rep, **rave_date_fields("EGDAT", d),
                    "EGTIM": f"{rng.randint(8, 12):02d}:{rng.randint(0, 59):02d}",
                    "EGHR_EGORRES": int(rng.gauss(74, 9)), "PR_EGORRES": int(rng.gauss(160, 18)),
                    "QRS_EGORRES": int(rng.gauss(92, 8)), "QT_EGORRES": int(qtcf - 25),
                    "QTCF_EGORRES": qtcf,
                    **coded("EGINTP", "Abnormal, not clinically significant" if qtcf > 440
                            else "Normal", "ABNORMAL NCS" if qtcf > 440 else "NORMAL")}, rep)
        if s.childpot and (code == "SCR" or code.endswith("D1")):
            rave.add("PREG", "Pregnancy Test", s, f, d, {
                **yn("LBPERF", True), **rave_date_fields("LBDAT", d),
                **coded("LBSPEC", "Serum" if code == "SCR" else "Urine"),
                **coded("LBORRES", "Negative", "NEGATIVE")})
    _sample_logs(rave, rng, s, samples)
    _exposure(rave, rng, s, samples)


def _sample_logs(rave: Rave, rng: random.Random, s: Subject, samples: dict) -> None:
    for k, lab in enumerate([x for x in samples["lab"] if x["s"] is s], 1):
        rave.add("LBSAMP", "Central Laboratory Sample Collection", s, lab["folder"], lab["date"], {
            **yn("LBPERF", True), **rave_date_fields("LBDAT", lab["date"]),
            "LBTIM": lab["time"], "LBREFID": lab["accession"],
            "LBCAT": "; ".join(p.title() for p in lab["panels"]),
            **yn("LBFAST", rng.random() < .4)}, k)
    for k, pk in enumerate([x for x in samples["pk"] if x["s"] is s], 1):
        rave.add("PCSAMP", "PK Sample Collection", s, pk["folder"], pk["dt"].date(), {
            **coded("PCTEST", pk["drug"]), **yn("PCPERF", True),
            **coded("PCTPT", pk["tpt"]), **rave_date_fields("PCDAT", pk["dt"].date()),
            "PCTIM": pk["dt"].strftime("%H:%M"), "PCREFID": pk["sample"]}, k)
    for k, ada in enumerate([x for x in samples["ada"] if x["s"] is s], 1):
        rave.add("ADASAMP", "Immunogenicity (ADA) Sample", s, ada["folder"], ada["dt"].date(), {
            **coded("ISTEST", f"Anti-{ada['drug']} antibodies"), **yn("ISPERF", True),
            **coded("ISTPT", "Pre-dose" if ada["code"].endswith("D1") else ada["code"]),
            **rave_date_fields("ISDAT", ada["dt"].date()), "ISTIM": ada["dt"].strftime("%H:%M"),
            "ISREFID": ada["sample"]}, k)
    for k, b in enumerate([x for x in samples["bio"] if x["s"] is s], 1):
        rave.add("BIOSAMP", "Biomarker Sample Collection", s, b["folder"], b["date"], {
            **coded("BSSPEC", b["specimen"]), **yn("BSPERF", True),
            **rave_date_fields("BSDAT", b["date"]), "BSTIM": b["time"], "BSKIT": b["kit"]}, k)


def _exposure(rave: Rave, rng: random.Random, s: Subject, samples: dict) -> None:
    reduced = {a["onset"] for a in s.aes if a["action"] == "Dose Reduced"}
    level = 1.0
    weight = s.weight
    for inf in [x for x in samples["infusions"] if x["s"] is s]:
        amount, unit = DOSE[inf["drug"]]
        if any(inf["date"] - timedelta(days=21) < r <= inf["date"] for r in reduced):
            level = max(0.5, level - 0.25)
        base = weight if unit == "mg/kg" else bsa(s.height, weight)
        planned = round(amount * base)
        given = round(planned * level * (1 if rng.random() > .04 else rng.uniform(.6, .9)))
        interrupted = given < planned * level - 1
        rave.add(EX_OID[inf["drug"]], f"{inf['drug']} Administration", s, inf["folder"],
                 inf["date"], {
                     **yn("EXYN", True), **rave_date_fields("EXSTDAT", inf["date"]),
                     "EXSTTIM": inf["start"], "EXENTIM": inf["end"], "EXCYCLE": inf["cycle"],
                     "EXPLDOS": f"{amount} {unit}", "EXWEIGHT": weight if unit == "mg/kg" else "",
                     "EXBSA": "" if unit == "mg/kg" else bsa(s.height, weight),
                     "EXDOSE": given, **coded("EXDOSU", "mg"),
                     **coded("EXROUTE", "Intravenous infusion", "INTRAVENOUS"),
                     **yn("EXDOSADJ", level < 1),
                     **coded("EXADJ", "Adverse event" if level < 1 else ""),
                     **yn("EXINTYN", interrupted),
                     **coded("EXINTRSN", rng.choice(["Infusion related reaction",
                                                     "Infusion pump failure"])
                             if interrupted else "")})


def tumour_forms(rave: Rave, rng: random.Random, s: Subject) -> None:
    """Investigator RECIST 1.1 reads (the imaging core lab reads the same scans separately)."""
    if not s.randomised:
        return
    for ta in s.tumour:
        folder = "Screening" if ta["week"] == 0 else f"Tumor Assessment Week {ta['week']}"
        method = "CT with contrast" if rng.random() > .1 else "MRI"
        inv = {k: round(max(0, v + rng.gauss(0, 1.3)), 0) for k, v in ta["sizes"].items()}
        for n, lz in enumerate([x for x in s.lesions if x.target], 1):
            rave.add("TL", "Target Lesions", s, folder, ta["date"], {
                "TRLNKID": lz.lid, **rave_date_fields("TRDAT", ta["date"]),
                **coded("TULOC", lz.site), "TULOCDTL": lz.detail,
                **coded("TRMETHOD", method), "TRORRES": int(inv[lz.lid]),
                **coded("TRORRESU", "mm"),
                **coded("TRAXIS", "Short axis" if lz.site == "Lymph node" else "Longest diameter"),
                }, n)
        for n, lz in enumerate([x for x in s.lesions if not x.target], 1):
            status = "Present" if ta["week"] == 0 else (
                "Unequivocal progression" if ta["nt"] == "PD" else "Present / non-PD")
            rave.add("NTL", "Non-target Lesions", s, folder, ta["date"], {
                "TRLNKID": lz.lid, **rave_date_fields("TRDAT", ta["date"]),
                **coded("TULOC", lz.site), "TULOCDTL": lz.detail, **coded("TRSTAT", status)}, n)
        if ta["new"]:
            rave.add("NL", "New Lesions", s, folder, ta["date"], {
                "TRLNKID": "NEW01", **rave_date_fields("TRDAT", ta["date"]),
                **coded("TULOC", rng.choice(["Liver", "Brain", "Bone", "Lung", "Adrenal gland"])),
                **coded("TRMETHOD", method)}, 1)
        resp = {"NE": ("Not Evaluable", "NE"), "CR": ("Complete Response", "CR"),
                "PR": ("Partial Response", "PR"), "SD": ("Stable Disease", "SD"),
                "PD": ("Progressive Disease", "PD")}[ta["resp"]]
        shown = resp if ta["week"] else ("",)     # no response is assessed at baseline
        rave.add("RS", "Overall Response (RECIST 1.1)", s, folder, ta["date"], {
            **rave_date_fields("RSDAT", ta["date"]), "TRSUM": int(sum(inv.values())),
            **coded("TRGRESP", *shown), **yn("NEWLESYN", ta["new"]),
            **coded("OVRLRESP", *shown)})


def safety_forms(rave: Rave, rng: random.Random, s: Subject, drop_sae: set) -> None:
    for n, a in enumerate(s.aes, 1):
        rel = {d: ("Related" if r else "Not Related") for d, r in a["related"].items()}
        rave.add("AE", "Adverse Events", s, "Subject Logs", a["onset"], {
            "AESPID": a["spid"], "AETERM": a["term"], **rave_date_fields("AESTDAT", a["onset"]),
            **yn("AEONGO", a["end"] is None), **rave_date_fields("AEENDAT", a["end"]),
            **coded("AETOXGR", GRADE_TXT[a["grade"]], str(a["grade"])),
            **coded("AEREL_ZV210", rel.get("ZV-210", "")),
            **coded("AEREL_ZK415", rel.get("ZK-415", "")),
            **coded("AEREL_PAC", rel.get("Paclitaxel", "")),
            **coded("AEACN", a["action"]), **coded("AEOUT", a["outcome"]),
            **yn("AESER", a["serious"]), **yn("AESI", a["aesi"]), **yn("AECONTRT", a["treated"])},
            n)
        if a["serious"] and (s.subnum, a["spid"]) not in drop_sae:
            rave.add("SAE", "Serious Adverse Event Details", s, "Subject Logs", a["onset"], {
                "AESPID": a["spid"], **yn("AESDTH", a["grade"] == 5), **yn("AESLIFE",
                                                                             a["grade"] == 4),
                **yn("AESHOSP", a["hosp"]), **yn("AESDISAB", False), **yn("AESCONG", False),
                **yn("AESMIE", not a["hosp"]),
                **rave_date_fields("AEHOSTDAT", a["onset"] + timedelta(days=rng.randint(0, 2))
                                   if a["hosp"] else None),
                **rave_date_fields("AESAEDAT", a["onset"] + timedelta(days=rng.randint(0, 3)))},
                n)
    if s.randomised and s.eot_date:
        why = {"PD": ("Progressive disease", "PROGRESSIVE DISEASE"),
               "DEATH": ("Progressive disease", "PROGRESSIVE DISEASE"),
               "AE": ("Adverse event", "ADVERSE EVENT"),
               "WITHDRAWN": ("Withdrawal by subject", "WITHDRAWAL BY SUBJECT")}[s.outcome]
        rave.add("DSEOT", "End of Treatment", s, "End of Treatment", s.eot_date, {
            **rave_date_fields("DSSTDAT", s.dose_dates[-1] + timedelta(days=rng.randint(1, 20))),
            **coded("DSDECOD", *why), **rave_date_fields("LASTDOSE", s.dose_dates[-1])})
    if s.death_date:
        rave.add("DD", "Death Details", s, "Survival Follow-up", s.death_date, {
            **rave_date_fields("DTHDAT", s.death_date),
            **coded("DDORRES", "Disease progression", "PROGRESSIVE DISEASE"),
            **yn("AUTOPSY", False)})
        rave.add("DSEOS", "End of Study", s, "Survival Follow-up", s.death_date, {
            **rave_date_fields("DSSTDAT", s.death_date), **coded("DSDECOD", "Death", "DEATH")})
    elif s.outcome == "WITHDRAWN" and s.eot_date and s.eot_date <= DATA_CUT:
        rave.add("DSEOS", "End of Study", s, "End of Treatment", s.eot_date, {
            **rave_date_fields("DSSTDAT", s.eot_date),
            **coded("DSDECOD", "Withdrawal by subject", "WITHDRAWAL BY SUBJECT")})
