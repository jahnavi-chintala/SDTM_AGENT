"""Biomarker vendors: liquid-biopsy genomics, tumour immunogenomics, serum proteomics."""
from __future__ import annotations

import random
from datetime import timedelta
from pathlib import Path

from common import eu_date, id_genomics, id_proteomics, iso, write_csv
from study import Subject

# gene, alteration, type, prevalence in TNBC (rough)
VARIANTS = [("TP53", "R273H", "SNV", .25), ("TP53", "R175H", "SNV", .15),
            ("TP53", "Y220C", "SNV", .08), ("PIK3CA", "H1047R", "SNV", .1),
            ("PIK3CA", "E545K", "SNV", .05), ("PTEN", "R130*", "SNV", .06),
            ("BRCA1", "c.68_69delAG", "INDEL", .06), ("RB1", "loss", "CNA", .08),
            ("MYC", "amplification", "CNA", .15), ("NF1", "S2597fs", "INDEL", .04),
            ("KMT2C", "E2804*", "SNV", .05), ("AKT1", "E17K", "SNV", .03)]
GEN_COLS = ["Study", "Patient ID", "Case ID", "Specimen ID", "Specimen Type", "Collection Date",
            "Received Date", "Report Date", "Visit", "Test", "Gene", "Alteration",
            "Alteration Type", "Variant Allele Frequency (%)", "Copy Number", "Tumor Fraction (%)",
            "bTMB (mut/Mb)", "MSI Status", "Clonal Hematopoiesis Flag", "QC Status",
            "Report Status"]
IMM_COLS = ["Sample Name", "Subject", "Sample Type", "Paired Normal", "Collection Date",
            "Assay", "TMB (mut/Mb)", "Neoantigen Count", "HLA-A Allele 1", "HLA-A Allele 2",
            "HLA-B Allele 1", "HLA-B Allele 2", "HLA-C Allele 1", "HLA-C Allele 2",
            "HLA LOH", "CD274 (PD-L1) TPM", "VEGFA TPM", "CD8A TPM",
            "Immune Infiltrate Score", "Tumor Purity (%)", "Mean Coverage", "QC Flag"]
PROT_COLS = ["SampleID", "PlateID", "WellID", "Assay", "UniProt", "Panel", "NPX", "LOD",
             "MissingFreq", "QC_Warning", "Assay_Warning", "Normalization", "Sample_Date"]
PROTEINS = [("VEGFA", "P15692"), ("PGF", "P49763"), ("ANGPT2", "O15123"), ("IL6", "P05231"),
            ("IL8", "P10145"), ("CXCL9", "Q07325"), ("CXCL10", "P02778"), ("IFNG", "P01579"),
            ("GZMB", "P10144"), ("PDCD1", "Q15116"), ("CD274", "Q9NZQ7"), ("TNFRSF9", "Q07011"),
            ("HGF", "P14210"), ("MMP9", "P14780"), ("CA125/MUC16", "Q8WXI7"), ("CEACAM5", "P06731")]
HLA = {"A": ["A*02:01", "A*01:01", "A*24:02", "A*03:01", "A*11:01", "A*26:01"],
       "B": ["B*07:02", "B*08:01", "B*44:02", "B*35:01", "B*40:01", "B*52:01"],
       "C": ["C*07:01", "C*07:02", "C*04:01", "C*03:04", "C*06:02", "C*12:02"]}


def build_biomarkers(rng: random.Random, subjects: list[Subject], samples: dict, out: Path) -> dict:
    gen_rows, imm_rows, prot_rows = [], [], []
    muts = {s.subnum: [v for v in VARIANTS if rng.random() < v[3]] or [VARIANTS[0]]
            for s in subjects}
    case = 2207000
    for b in samples["bio"]:
        s = b["s"]
        recv = b["date"] + timedelta(days=rng.randint(1, 4))
        if b["specimen"] in ("Plasma (ctDNA)", "Buffy coat"):
            case += rng.randint(3, 60)
            buffy = b["specimen"] == "Buffy coat"
            later = b["code"] != "SCR"
            responding = later and any(t["resp"] in ("PR", "CR") for t in s.tumour[1:])
            tf = round(rng.uniform(.5, 4) if responding else rng.uniform(3, 38), 1)
            qc = "PASS" if rng.random() > .05 else "QUALIFIED - LOW CFDNA YIELD"
            base = {"Study": "ZVR210-201", "Patient ID": id_genomics(s), "Case ID": f"TRF{case}",
                    "Specimen ID": b["kit"], "Specimen Type": "Whole blood (buffy coat)"
                    if buffy else "Plasma", "Collection Date": iso(b["date"]),
                    "Received Date": iso(recv),
                    "Report Date": iso(recv + timedelta(days=rng.randint(9, 16))),
                    "Visit": b["code"], "Test": "Germline/CHIP reference" if buffy else
                    "Liquid biopsy CGP (324 genes)", "MSI Status": "" if buffy else "MSS",
                    "QC Status": qc, "Report Status": "FINAL"}
            if buffy:   # the normal sample only flags clonal haematopoiesis
                chip = rng.random() < .12
                gen_rows.append({**base, "Gene": "DNMT3A" if chip else "",
                                 "Alteration": "R882H" if chip else "No CHIP variants detected",
                                 "Alteration Type": "SNV" if chip else "",
                                 "Variant Allele Frequency (%)": round(rng.uniform(1, 6), 2)
                                 if chip else "", "Clonal Hematopoiesis Flag": "Y" if chip
                                 else "N"})
                continue
            for gene, alt, typ, _ in muts[s.subnum]:
                vaf = round(tf * rng.uniform(.3, .55), 2)
                gen_rows.append({**base, "Gene": gene, "Alteration": alt, "Alteration Type": typ,
                                 "Variant Allele Frequency (%)": "" if typ == "CNA" else (
                                     vaf if vaf >= .1 else "<0.1"),
                                 "Copy Number": rng.choice([8, 11, 14]) if alt == "amplification"
                                 else (0 if alt == "loss" else ""),
                                 "Tumor Fraction (%)": tf,
                                 "bTMB (mut/Mb)": round(rng.uniform(2, 14), 1),
                                 "Clonal Hematopoiesis Flag": "N"})
        elif b["specimen"] == "Archival FFPE tissue":
            tmb = round(abs(rng.gauss(5, 3.5)), 1)
            h = {g: rng.sample(v, 2) for g, v in HLA.items()}
            imm_rows.append({
                "Sample Name": f"ZVR210-{s.site}-{s.seq:03d}-T", "Subject": s.subnum,
                "Sample Type": "FFPE tumor", "Paired Normal": f"ZVR210-{s.site}-{s.seq:03d}-N",
                "Collection Date": iso(b["date"] - timedelta(days=rng.randint(30, 900))),
                "Assay": "Exome + transcriptome (tumor/normal)", "TMB (mut/Mb)": tmb,
                "Neoantigen Count": int(tmb * rng.uniform(8, 22)),
                "HLA-A Allele 1": h["A"][0], "HLA-A Allele 2": h["A"][1],
                "HLA-B Allele 1": h["B"][0], "HLA-B Allele 2": h["B"][1],
                "HLA-C Allele 1": h["C"][0], "HLA-C Allele 2": h["C"][1],
                "HLA LOH": "Yes" if rng.random() < .15 else "No",
                "CD274 (PD-L1) TPM": round(rng.lognormvariate(2.2 if s.strata.get(
                    "PDL1_CPS") == ">=10" else 1.0, .6), 2),
                "VEGFA TPM": round(rng.lognormvariate(4.1, .5), 1),
                "CD8A TPM": round(rng.lognormvariate(2.5, .7), 2),
                "Immune Infiltrate Score": round(rng.uniform(.05, .9), 2),
                "Tumor Purity (%)": rng.randint(18, 85),
                "Mean Coverage": rng.randint(160, 420),
                "QC Flag": "PASS" if rng.random() > .06 else "LOW PURITY"})
        elif b["specimen"] == "Serum":
            plate = f"PM-PLATE-{(len(prot_rows) // 1400) + 1:02d}"
            well = f"{'ABCDEFGH'[rng.randint(0, 7)]}{rng.randint(1, 12)}"
            on_drug = b["code"] != "C1D1" and s.arm != "PACLI"
            for gene, uni in PROTEINS:
                npx = rng.gauss(4.5, 1.1)
                if gene == "VEGFA" and on_drug:
                    npx -= rng.uniform(1.5, 2.8)          # target engagement: free VEGF falls
                if gene in ("CXCL9", "CXCL10", "IFNG") and on_drug:
                    npx += rng.uniform(.4, 1.6)
                lod = round(rng.uniform(.8, 2.2), 2)
                prot_rows.append({
                    "SampleID": id_proteomics(s, b["code"]), "PlateID": plate, "WellID": well,
                    "Assay": gene, "UniProt": uni, "Panel": "Oncology Explore 384",
                    "NPX": round(npx, 3), "LOD": lod, "MissingFreq": round(rng.uniform(0, .2), 2),
                    "QC_Warning": "WARN" if rng.random() < .015 else "PASS",
                    "Assay_Warning": "", "Normalization": "Intensity",
                    "Sample_Date": eu_date(b["date"])})
    return {
        "helixseq_ctdna_genomics.csv": write_csv(out / "helixseq_ctdna_genomics.csv", GEN_COLS,
                                                 gen_rows),
        "genovue_immunogenomics.csv": write_csv(out / "genovue_immunogenomics.csv", IMM_COLS,
                                                imm_rows),
        "proteomark_serum_npx.csv": write_csv(out / "proteomark_serum_npx.csv", PROT_COLS,
                                              prot_rows, delimiter=";"),
    }
