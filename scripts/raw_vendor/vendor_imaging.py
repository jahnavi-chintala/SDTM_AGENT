"""Imaging core lab: blinded independent central review (BICR) under RECIST 1.1."""
from __future__ import annotations

import random
from datetime import timedelta
from pathlib import Path

from common import id_imaging, us_date, write_csv
from study import Subject

LES_COLS = ["Protocol", "Subject ID", "Site", "Timepoint", "Scan Date", "Modality", "Reader",
            "Lesion ID", "Lesion Type", "Organ", "Location", "Measurement (mm)",
            "Measurement Axis", "Lesion Status", "Read Date"]
TP_COLS = ["Protocol", "Subject ID", "Site", "Timepoint", "Scan Date", "Reader",
           "Sum of Diameters (mm)", "Nadir SOD (mm)", "Change From Baseline (%)",
           "Change From Nadir (%)", "Target Response", "Non-Target Response", "New Lesion",
           "Overall Response", "Image Quality", "Adjudication Selected", "Adjudication Reason",
           "Read Date"]


def _response(sld: float, base: float, nadir: float, new: bool, nt_pd: bool) -> str:
    if new or nt_pd or (sld >= nadir * 1.2 and sld - nadir >= 5):
        return "PD"
    if sld == 0:
        return "CR"
    return "PR" if sld <= base * .7 else "SD"


def build_imaging(rng: random.Random, subjects: list[Subject], out: Path) -> dict:
    les_rows, tp_rows = [], []
    for s in subjects:
        if not s.randomised:
            continue
        targets = [lz for lz in s.lesions if lz.target]
        readers = {}
        for reader in ("R1", "R2"):
            # Each reader picks their own targets: R2 sometimes drops the smallest lesion.
            chosen = targets if reader == "R1" or len(targets) < 3 or rng.random() < .6 else \
                sorted(targets, key=lambda x: x.baseline_mm)[1:]
            readers[reader] = {"lesions": chosen, "base": None, "nadir": None,
                               "bias": rng.gauss(0, .04)}
        for ta in s.tumour:
            tp = "BASELINE" if ta["week"] == 0 else f"WEEK {ta['week']}"
            scan = ta["date"] + timedelta(days=rng.choice([0, 0, 0, 0, -1, 1]))
            quality = "ADEQUATE" if rng.random() > .025 else "SUBOPTIMAL - SLICE THICKNESS > 5MM"
            calls = {}
            for reader, st in readers.items():
                read_date = scan + timedelta(days=rng.randint(4, 30))
                sizes = {}
                for n, lz in enumerate(st["lesions"], 1):
                    true = ta["sizes"][lz.lid]
                    mm = round(max(0.0, true * (1 + st["bias"]) + rng.gauss(0, 1.6)), 1)
                    if 0 < mm < 5 and lz.site != "Lymph node":
                        mm = 5.0                      # RECIST: too small to measure -> 5 mm
                    sizes[f"L{n}"] = mm
                    les_rows.append({
                        "Protocol": "ZVR210-201", "Subject ID": id_imaging(s), "Site": s.site,
                        "Timepoint": tp, "Scan Date": us_date(scan), "Modality": "CT",
                        "Reader": reader, "Lesion ID": f"L{n}", "Lesion Type": "TARGET",
                        "Organ": lz.site.upper(), "Location": lz.detail, "Measurement (mm)": mm,
                        "Measurement Axis": "SHORT" if lz.site == "Lymph node" else "LONG",
                        "Lesion Status": "MEASURED", "Read Date": us_date(read_date)})
                for n, lz in enumerate([x for x in s.lesions if not x.target], 1):
                    les_rows.append({
                        "Protocol": "ZVR210-201", "Subject ID": id_imaging(s), "Site": s.site,
                        "Timepoint": tp, "Scan Date": us_date(scan), "Modality": "CT",
                        "Reader": reader, "Lesion ID": f"NT{n}", "Lesion Type": "NON-TARGET",
                        "Organ": lz.site.upper(), "Location": lz.detail,
                        "Lesion Status": "UNEQUIVOCAL PROGRESSION" if ta["nt"] == "PD" and
                        reader == "R1" else "PRESENT", "Read Date": us_date(read_date)})
                new = ta["new"] and (reader == "R1" or rng.random() < .7)
                if new:
                    les_rows.append({
                        "Protocol": "ZVR210-201", "Subject ID": id_imaging(s), "Site": s.site,
                        "Timepoint": tp, "Scan Date": us_date(scan), "Modality": "CT",
                        "Reader": reader, "Lesion ID": "N1", "Lesion Type": "NEW",
                        "Organ": rng.choice(["LIVER", "LUNG", "BONE"]),
                        "Lesion Status": "UNEQUIVOCAL", "Read Date": us_date(read_date)})
                sld = round(sum(sizes.values()), 1)
                if st["base"] is None:
                    st["base"] = st["nadir"] = sld
                    resp = ""
                else:
                    resp = _response(sld, st["base"], st["nadir"], new,
                                     ta["nt"] == "PD" and reader == "R1")
                    if quality != "ADEQUATE" and rng.random() < .5:
                        resp = "NE"
                calls[reader] = resp
                tp_rows.append({
                    "Protocol": "ZVR210-201", "Subject ID": id_imaging(s), "Site": s.site,
                    "Timepoint": tp, "Scan Date": us_date(scan), "Reader": reader,
                    "Sum of Diameters (mm)": sld, "Nadir SOD (mm)": st["nadir"],
                    "Change From Baseline (%)": round((sld - st["base"]) / st["base"] * 100, 1)
                    if st["base"] else "",
                    "Change From Nadir (%)": round((sld - st["nadir"]) / st["nadir"] * 100, 1)
                    if st["nadir"] else "",
                    "Target Response": "" if not resp else ("NE" if resp == "NE" else _response(
                        sld, st["base"], st["nadir"], False, False)),
                    "Non-Target Response": "" if not resp else (
                        "PD" if ta["nt"] == "PD" and reader == "R1" else "NON-CR/NON-PD"),
                    "New Lesion": "" if not resp else ("YES" if new else "NO"),
                    "Overall Response": resp, "Image Quality": quality,
                    "Read Date": us_date(read_date)})
                st["nadir"] = min(st["nadir"], sld)
            if calls.get("R1") and calls["R1"] != calls["R2"]:
                pick = rng.choice(["R1", "R2"])
                tp_rows.append({"Protocol": "ZVR210-201", "Subject ID": id_imaging(s),
                                "Site": s.site, "Timepoint": tp, "Scan Date": us_date(scan),
                                "Reader": "ADJ", "Overall Response": calls[pick],
                                "Adjudication Selected": pick,
                                "Adjudication Reason": "Discordant overall response",
                                "Read Date": us_date(scan + timedelta(days=rng.randint(30, 45)))})
    return {"clearview_bicr_lesions.csv": write_csv(out / "clearview_bicr_lesions.csv",
                                                    LES_COLS, les_rows),
            "clearview_bicr_timepoints.csv": write_csv(out / "clearview_bicr_timepoints.csv",
                                                       TP_COLS, tp_rows)}
