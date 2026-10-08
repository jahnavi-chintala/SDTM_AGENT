"""EDC (Medidata Rave-style) export: the writer plus the once-per-subject forms."""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from pathlib import Path

from common import rave_date_fields, write_csv
from study import SITES, Subject

PROJECT = "ZVR210201"
SYS_COLS = ["projectid", "project", "studyid", "environmentName", "subjectId", "StudySiteId",
            "Subject", "siteid", "Site", "SiteNumber", "SiteGroup", "instanceId", "InstanceName",
            "InstanceRepeatNumber", "folderid", "Folder", "FolderName", "FolderSeq",
            "TargetDays", "DataPageId", "DataPageName", "PageRepeatNumber", "RecordDate",
            "RecordId", "RecordPosition", "RecordActive", "SaveTs", "MinCreated", "MaxUpdated"]
SITE_IDS = {k: 3100 + i * 7 for i, k in enumerate(SITES)}


def coded(name: str, text: str, code: str | None = None) -> dict:
    """A Rave coded field: the label shown on the form and its stored code."""
    return {name: text, f"{name}_STD": (code if code is not None else text.upper()) if text
            else ""}


def yn(name: str, value: bool | None) -> dict:
    return coded(name, "" if value is None else ("Yes" if value else "No"),
                 None if value is None else ("Y" if value else "N"))


def folder_meta(folder: str) -> tuple[str, float, int]:
    """Folder OID, FolderSeq and TargetDays for a folder name."""
    if folder.startswith("Cycle "):
        c, d = (int(x) for x in folder.replace("Cycle ", "").split(" Day "))
        return f"C{c}D{d}", 3 + (c - 1) * 3 + [1, 8, 15].index(d), (c - 1) * 21 + d - 1
    if folder.startswith("Tumor Assessment"):
        w = int(folder.split()[-1])
        return f"TA{w:03d}", 500 + w, w * 7
    return {"Screening": ("SCRN", 1, -14), "Randomization": ("RAND", 2, -2),
            "End of Treatment": ("EOT", 800, 0), "30-Day Safety Follow-up": ("FU30", 801, 0),
            "Subject Logs": ("LOGS", 0, 0), "Survival Follow-up": ("SURV", 900, 0),
            "Unscheduled": ("UNS", 700, 0)}[folder]


class Rave:
    """Collects form records and writes one CSV per form, as a Rave clinical-view export."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.forms: dict[str, dict] = {}
        self.ids = {"instance": 880000, "page": 1200000, "record": 5600000}
        self.page_ids: dict[tuple, int] = {}

    def add(self, oid: str, page: str, s: Subject, folder: str, when: date | None,
            fields: dict, repeat: int = 1) -> None:
        form = self.forms.setdefault(oid, {"page": page, "cols": [], "rows": []})
        for k in fields:
            if k not in form["cols"]:
                form["cols"].append(k)
        fo, seq, target = folder_meta(folder)
        key = (s.subnum, oid, folder)
        if key not in self.page_ids:
            self.ids["page"] += self.rng.randint(1, 4)
            self.page_ids[key] = self.ids["page"]
        self.ids["record"] += self.rng.randint(1, 3)
        self.ids["instance"] += 1
        when = when or date(2025, 3, 3)
        created = datetime(when.year, when.month, when.day, self.rng.randint(8, 18),
                           self.rng.randint(0, 59), self.rng.randint(0, 59)) + timedelta(
            days=self.rng.choice([0, 0, 1, 1, 2, 3, 5, 9, 16]))
        updated = created + timedelta(days=self.rng.choice([0, 0, 0, 0, 2, 7, 21, 40]),
                                      minutes=self.rng.randint(0, 600))
        row = {"projectid": 412, "project": PROJECT, "studyid": 1871,
               "environmentName": "PROD", "subjectId": 90000 + int(s.site) * 40 + s.seq,
               "StudySiteId": SITE_IDS[s.site], "Subject": s.subnum,
               "siteid": SITE_IDS[s.site] + 1,
               "Site": f"{s.site} - {SITES[s.site][1].split()[-1]}", "SiteNumber": s.site,
               "SiteGroup": SITES[s.site][0], "instanceId": self.ids["instance"],
               "InstanceName": folder, "InstanceRepeatNumber": 0, "folderid": 7000 + int(seq),
               "Folder": fo, "FolderName": folder, "FolderSeq": f"{float(seq):.1f}",
               "TargetDays": target, "DataPageId": self.page_ids[key], "DataPageName": page,
               "PageRepeatNumber": 0, "RecordDate": "", "RecordId": self.ids["record"],
               "RecordPosition": repeat if oid in LOG_FORMS else 0, "RecordActive": 1,
               "SaveTs": updated.strftime("%Y-%m-%dT%H:%M:%S"),
               "MinCreated": created.strftime("%d %b %Y %H:%M:%S"),
               "MaxUpdated": updated.strftime("%d %b %Y %H:%M:%S")}
        row.update(fields)
        form["rows"].append(row)

    def write(self, out: Path) -> dict[str, int]:
        counts = {}
        for oid, form in sorted(self.forms.items()):
            counts[f"{oid.lower()}.csv"] = write_csv(out / f"{oid.lower()}.csv",
                                                     SYS_COLS + form["cols"], form["rows"])
        return counts


LOG_FORMS = {"AE", "CM", "MH", "PRTX", "SAE", "TL", "NTL", "NL", "LBSAMP", "PCSAMP",
             "ADASAMP", "BIOSAMP", "EG"}
MH_POOL = ["Hypertension", "Type 2 diabetes mellitus", "Hypothyroidism", "Gastro-oesophageal "
           "reflux disease", "Osteoarthritis", "Depression", "Anxiety", "Hypercholesterolaemia",
           "Asthma", "Migraine", "Osteopenia", "Iron deficiency anaemia", "Menopause",
           "Appendicectomy", "Cholecystectomy", "Lumbar disc herniation"]
CM_POOL = [("Amlodipine", 5, "mg", "QD", "Oral", "Hypertension"),
           ("Metformin", 500, "mg", "BID", "Oral", "Type 2 diabetes mellitus"),
           ("Levothyroxine", 50, "ug", "QD", "Oral", "Hypothyroidism"),
           ("Omeprazole", 20, "mg", "QD", "Oral", "Gastro-oesophageal reflux disease"),
           ("Paracetamol", 1, "g", "PRN", "Oral", "Pain"),
           ("Ondansetron", 8, "mg", "PRN", "Oral", "Prophylaxis of nausea"),
           ("Dexamethasone", 8, "mg", "ONCE", "Intravenous", "Premedication"),
           ("Diphenhydramine", 50, "mg", "ONCE", "Intravenous", "Premedication"),
           ("Loperamide", 2, "mg", "PRN", "Oral", "Diarrhoea"),
           ("Atorvastatin", 20, "mg", "QD", "Oral", "Hypercholesterolaemia"),
           ("Sertraline", 50, "mg", "QD", "Oral", "Depression"),
           ("Filgrastim", 300, "ug", "QD", "Subcutaneous", "Neutropenia prophylaxis"),
           ("Oxycodone", 5, "mg", "PRN", "Oral", "Cancer pain")]


def subject_forms(rave: Rave, rng: random.Random, s: Subject) -> None:
    """Demographics, consent, eligibility, history, randomisation and medication logs."""
    scr = s.screen_date
    birth_partial = "month" if s.country in ("DEU", "ESP") else ""
    race_cols = {f"RACE_{k}": 0 for k in ("WHITE", "BLACK", "ASIAN", "AMERIND", "NHPI", "NR",
                                          "OTH")}
    race_key = {"White": "WHITE", "Black or African American": "BLACK", "Asian": "ASIAN",
                "Native Hawaiian or Other Pacific Islander": "NHPI", "Not Reported": "NR",
                "Other": "OTH"}[s.race]
    race_cols[f"RACE_{race_key}"] = 1
    rave.add("DM", "Demographics", s, "Screening", scr, {
        **rave_date_fields("BRTHDAT", s.birth, birth_partial), "AGE": s.age,
        **coded("AGEU", "Years", "YEARS"), **coded("SEX", "Female", "F"),
        **yn("CHILDPOT", s.childpot),
        **coded("CHILDPOTRSN", "" if s.childpot else rng.choice(
            ["Post-menopausal", "Surgically sterile"])),
        **coded("ETHNIC", s.ethnic), **race_cols, "RACEOTHSP": ""})
    rave.add("IC", "Informed Consent", s, "Screening", s.consent_date, {
        **rave_date_fields("DSSTDAT", s.consent_date), "PROTVER": "Version 2.0, 14-Jan-2025",
        **yn("OPTBIO", s.country != "DEU" or rng.random() < .5),
        **yn("OPTGEN", rng.random() < .85)})
    if s.screen_fail:
        crit, text = s.screen_fail
        rave.add("IE", "Eligibility Criteria", s, "Screening", scr, {
            **yn("IEYN", False), **coded("IECAT", "Exclusion" if "Exclusion" in crit else
                                         "Inclusion"), "IETESTCD": crit.split(" ")[1]
            if crit[0] in "IE" else "", "IETEST": text})
        rave.add("DSSF", "Screen Failure", s, "Screening", scr + timedelta(days=5), {
            **rave_date_fields("DSSTDAT", scr + timedelta(days=rng.randint(3, 14))),
            **coded("DSDECOD", "Screen Failure", "SCREEN FAILURE"), "DSTERM": f"{crit}: {text}"})
    else:
        rave.add("IE", "Eligibility Criteria", s, "Screening", scr, {
            **yn("IEYN", True), **coded("IECAT", ""), "IETESTCD": "", "IETEST": ""})
    dx = s.screen_date - timedelta(days=rng.randint(200, 2400))
    met = s.screen_date - timedelta(days=rng.randint(20, 120))
    rave.add("CANHX", "Breast Cancer History", s, "Screening", scr, {
        **rave_date_fields("DIAGDAT", dx, "day" if rng.random() < .3 else ""),
        **coded("HISTTYPE", rng.choice(["Invasive ductal carcinoma"] * 5 + [
            "Invasive lobular carcinoma", "Metaplastic carcinoma"])),
        **coded("GRADE", rng.choice(["Grade 2", "Grade 3", "Grade 3"])),
        **coded("ERSTAT", "Negative", "NEG"), **coded("PRSTAT", "Negative", "NEG"),
        **coded("HER2STAT", rng.choice(["IHC 0", "IHC 1+"])),
        **coded("STAGEDX", rng.choice(["IIA", "IIB", "IIIA", "IIIC", "IV"])),
        **rave_date_fields("METDAT", met), **yn("DENOVO", rng.random() < .25),
        **yn("BRCAMUT", rng.random() < .12)})
    prior = s.strata.get("PRIOR_TAXANE") == "Yes" or rng.random() < .5
    rave.add("PRTX", "Prior Cancer Therapy", s, "Subject Logs", scr, {
        "PRSPID": "1" if prior else "", **yn("PRTXYN", prior),
        "PRTRT": rng.choice(["Doxorubicin + cyclophosphamide, then paclitaxel",
                             "Docetaxel + cyclophosphamide",
                             "Carboplatin + paclitaxel (neoadjuvant)"]) if prior else "",
        **coded("PRSET", "Neoadjuvant" if prior and rng.random() < .6 else
                ("Adjuvant" if prior else "")),
        **rave_date_fields("PRSTDAT", dx + timedelta(days=30) if prior else None, "day"),
        **rave_date_fields("PRENDAT", dx + timedelta(days=170) if prior else None, "day")}, 1)
    for k, term in enumerate(rng.sample(MH_POOL, rng.randint(1, 5)), 1):
        ongo = rng.random() < .6
        rave.add("MH", "Medical History", s, "Subject Logs", scr, {
            "MHSPID": f"{k:02d}", "MHTERM": term,
            **rave_date_fields("MHSTDAT", scr - timedelta(days=rng.randint(200, 6000)),
                               rng.choice(["", "day", "month"])),
            **yn("MHONGO", ongo),
            **rave_date_fields("MHENDAT", None if ongo else scr - timedelta(days=rng.randint(
                30, 150)), "day")}, k)
    cms = rng.sample(CM_POOL, rng.randint(1, 4) + (2 if s.randomised else 0))
    for k, (trt, dose, unit, frq, route, ind) in enumerate(cms, 1):
        st = scr - timedelta(days=rng.randint(10, 2000)) if ind not in (
            "Premedication", "Prophylaxis of nausea", "Diarrhoea", "Neutropenia prophylaxis") \
            else (s.dose_dates[0] if s.dose_dates else scr)
        rave.add("CM", "Concomitant Medications", s, "Subject Logs", st, {
            "CMSPID": f"{k:03d}", "CMTRT": trt if rng.random() > .08 else trt.upper(),
            **rave_date_fields("CMSTDAT", st, "day" if st < scr and rng.random() < .3 else ""),
            **yn("CMONGO", rng.random() < .7), "CMDSTXT": dose, **coded("CMDOSU", unit),
            **coded("CMDOSFRQ", frq), **coded("CMROUTE", route), "CMINDC": ind}, k)
    if s.randomised:
        rave.add("RAND", "Randomization", s, "Randomization", s.rand_date, {
            **rave_date_fields("RANDDAT", s.rand_date), "RANDNO": s.rand_no,
            **coded("ARM", ARM_LABEL[s.arm], s.arm),
            **coded("STRAT1", f"PD-L1 CPS {s.strata['PDL1_CPS']}", s.strata["PDL1_CPS"]),
            **coded("STRAT2", s.strata["PRIOR_TAXANE"], s.strata["PRIOR_TAXANE"][0])})


ARM_LABEL = {"ZV210": "Arm A: ZV-210", "ZV210_ZK415": "Arm B: ZV-210 + ZK-415",
             "PACLI": "Arm C: Paclitaxel"}
