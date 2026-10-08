"""Build the synthetic raw multi-vendor data package for study ZVR210-201.

Usage (from the repo root):
    python scripts/raw_vendor/make_raw_vendor_data.py [--out sample_data/raw] [--seed N]

Deterministic: the same seed always writes the same files. Standard library only.
"""
from __future__ import annotations

import argparse
import random
import shutil
from pathlib import Path

from common import (id_edc, id_genomics, id_imaging, id_lab, id_pk, initials_for, iso,
                    write_csv)
from edc_base import Rave, subject_forms
from edc_visits import safety_forms, tumour_forms, visit_forms
from safety import build_aes
from samples import build_samples
from study import ARMS, DATA_CUT, STUDYID, build_subjects
from vendor_bioanalytical import build_bioanalytical
from vendor_biomarker import build_biomarkers
from vendor_imaging import build_imaging
from vendor_lab import build_lab
from vendor_ops import build_ecoa, build_irt, build_safety

# folder -> (vendor name in this package, real-world role it stands in for)
VENDORS = {
    "edc_rave": ("Sponsor EDC (Medidata Rave-style export)", "Site-entered CRF data"),
    "central_lab_meridian": ("Meridian Clinical Laboratories", "Central safety lab"),
    "bioanalytical_northbridge": ("Northbridge Bioanalytical", "PK and ADA lab for ZV-210"),
    "bioanalytical_kestrel": ("Kestrel Bioanalytical", "PK lab for ZK-415 (ADC + payload)"),
    "imaging_clearview": ("ClearView Imaging", "Imaging core lab, RECIST 1.1 BICR"),
    "genomics_helixseq": ("HelixSeq Genomics", "ctDNA (plasma) and buffy coat genomics"),
    "immunogenomics_genovue": ("GenoVue", "Tumour/normal exome + transcriptome"),
    "proteomics_proteomark": ("ProteoMark", "Soluble serum proteins (NPX)"),
    "irt_randosure": ("RandoSure IRT", "Randomisation and drug supply"),
    "ecoa_propoint": ("PRO-Point eCOA", "Patient-reported outcomes"),
    "safety_sponsor_pv": ("Sponsor pharmacovigilance database", "SAE line listing"),
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="sample_data/raw")
    ap.add_argument("--seed", type=int, default=20260915)
    args = ap.parse_args()
    root = Path(args.out) / STUDYID
    if root.exists():
        shutil.rmtree(root)
    rng = random.Random(args.seed)

    subjects = build_subjects(args.seed)
    for s in subjects:
        build_aes(rng, s)
    samples = build_samples(random.Random(args.seed + 1), subjects)
    serious = [(s.subnum, a["spid"]) for s in subjects for a in s.aes
               if a["serious"] and a["grade"] < 5]
    drop_sae = {random.Random(args.seed + 2).choice(serious)} if serious else set()

    rave = Rave(random.Random(args.seed + 3))
    erng = random.Random(args.seed + 4)
    for s in subjects:
        subject_forms(rave, erng, s)
        visit_forms(rave, erng, s, samples)
        tumour_forms(rave, erng, s)
        safety_forms(rave, erng, s, drop_sae)
    counts = {"edc_rave": rave.write(root / "edc_rave")}
    v = random.Random(args.seed + 5)
    counts["central_lab_meridian"] = build_lab(v, subjects, samples, root / "central_lab_meridian")
    bio = build_bioanalytical(v, samples, root / "_tmp_bioanalytical")
    for name, n in bio.items():
        folder = "bioanalytical_kestrel" if "kestrel" in name else "bioanalytical_northbridge"
        (root / folder).mkdir(parents=True, exist_ok=True)
        (root / "_tmp_bioanalytical" / name).rename(root / folder / name)
        counts.setdefault(folder, {})[name] = n
    shutil.rmtree(root / "_tmp_bioanalytical")
    counts["imaging_clearview"] = build_imaging(v, subjects, root / "imaging_clearview")
    bm = build_biomarkers(v, subjects, samples, root / "_tmp_bm")
    for name, n in bm.items():
        folder = {"helixseq": "genomics_helixseq", "genovue": "immunogenomics_genovue",
                  "proteomark": "proteomics_proteomark"}[name.split("_")[0]]
        (root / folder).mkdir(parents=True, exist_ok=True)
        (root / "_tmp_bm" / name).rename(root / folder / name)
        counts[folder] = {name: n}
    shutil.rmtree(root / "_tmp_bm")
    counts["irt_randosure"] = build_irt(v, subjects, samples, root / "irt_randosure")
    counts["ecoa_propoint"] = build_ecoa(v, subjects, root / "ecoa_propoint")
    counts["safety_sponsor_pv"] = build_safety(v, subjects, root / "safety_sponsor_pv")
    _answer_key(root, subjects, samples, drop_sae)
    manifest = [{"folder": f, "vendor": VENDORS[f][0], "role": VENDORS[f][1], "file": name,
                 "rows": n} for f, files in counts.items() for name, n in sorted(files.items())]
    write_csv(root / "MANIFEST.csv", ["folder", "vendor", "role", "file", "rows"], manifest)
    total = sum(m["rows"] for m in manifest)
    print(f"Wrote {len(manifest)} files, {total} rows, {len(subjects)} subjects to {root}")


def _answer_key(root: Path, subjects: list, samples: dict, drop_sae: set) -> None:
    """Ground truth for testing reconciliation: never part of a real vendor transfer."""
    key = root / "_answer_key"
    cross = [{"EDC_SUBJECT": id_edc(s), "USUBJID": s.usubjid, "IRT_SUBJECT": id_edc(s),
              "CENTRAL_LAB_PATIENT_ID": id_lab(s), "PK_LIMS_SUBJECT_NO": id_pk(s),
              "KESTREL_SUBJECT": f"{s.site}{s.seq:03d}", "IMAGING_SUBJECT_ID": id_imaging(s),
              "GENOMICS_PATIENT_ID": id_genomics(s),
              "PROTEOMICS_SAMPLE_PREFIX": f"ZV{s.site}{s.seq:03d}",
              "SAFETY_PATIENT_ID": f"{s.site}/{s.seq:03d}",
              "LAB_INITIALS": initials_for(s, "lab"), "SAFETY_INITIALS": initials_for(s, "safety"),
              "COUNTRY": s.country, "ARMCD": s.arm, "ARM": ARMS[s.arm][0] if s.arm else "",
              "STATUS": "SCREEN FAILURE" if s.screen_fail else s.outcome,
              "RAND_DATE": iso(s.rand_date), "FIRST_DOSE": iso(s.dose_dates[0] if s.dose_dates
                                                             else None),
              "LAST_DOSE": iso(s.dose_dates[-1] if s.dose_dates else None),
              "N_CYCLES": len(s.dose_dates), "DEATH_DATE": iso(s.death_date),
              "BEST_RESPONSE_TRUTH": next((r for r in ("CR", "PR", "SD", "PD") if any(
                  t["resp"] == r for t in s.tumour[1:])), "")} for s in subjects]
    write_csv(key / "subject_id_crosswalk.csv", list(cross[0]), cross)
    lab_typo = next((s for s in subjects if s.seq == 7 and any(
        x["s"] is s and x["code"] == "C2D1" for x in samples["lab"])), None)
    issues = [
        {"area": "Subject ID", "where": "central_lab_meridian", "detail":
         f"Patient {id_lab(lab_typo)} keyed with letter O instead of zero at C2D1"
         if lab_typo else "n/a"},
        {"area": "Missing samples", "where": "central_lab_meridian vs edc_rave/lbsamp.csv",
         "detail": "; ".join(f"{m['s'].subnum} {m['code']} accession {m['accession']}"
                             for m in samples["missing_lab"]) + " recorded as collected in EDC "
         "but absent from the lab transfer"},
        {"area": "SAE reconciliation", "where": "edc_rave/sae.csv vs safety_sponsor_pv",
         "detail": "; ".join(f"{a} {b}" for a, b in drop_sae) + " is serious in EDC AE form "
         "but has no SAE details page; a pulmonary embolism SAE exists only in the safety "
         "database"},
        {"area": "Stratification", "where": "irt_randosure vs edc_rave/rand.csv",
         "detail": "First randomised subject at site 301 has the PD-L1 stratum flipped in IRT"},
        {"area": "Subject ID", "where": "ecoa_propoint", "detail":
         "First randomised subject at site 102 has a trailing space in Subject"},
        {"area": "Subject ID", "where": "bioanalytical_kestrel", "detail":
         "About 5% of rows use the hyphenated EDC subject number instead of site+seq"},
        {"area": "Lab results", "where": "central_lab_meridian", "detail":
         "Re-issued rows with TEST_STATUS=CORRECTED duplicate an earlier FINAL result; "
         "haemolysed potassium results are CANCELLED with no value"},
        {"area": "Imaging", "where": "imaging_clearview vs edc_rave/rs.csv", "detail":
         "Central readers use their own lesion IDs (L1..), may pick different targets, and "
         "can disagree with the investigator; ADJ rows record adjudication"},
        {"area": "Dates", "where": "all vendors", "detail":
         "Each vendor uses its own date format (ISO, DD-MON-YYYY, YYYYMMDD, MM/DD/YYYY, "
         "DD/MM/YYYY, DD.MM.YYYY, UTC stamps); EU sites send year-only birth dates"},
    ]
    write_csv(key / "planted_discrepancies.csv", ["area", "where", "detail"], issues)
    write_csv(key / "study_design.csv", ["item", "value"], [
        {"item": "STUDYID", "value": STUDYID}, {"item": "Data cut-off", "value": iso(DATA_CUT)},
        *({"item": f"Arm {k}", "value": v[0]} for k, v in ARMS.items())])


if __name__ == "__main__":
    main()
