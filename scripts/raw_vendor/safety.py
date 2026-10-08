"""Adverse events per subject, drawn from a plausible toxicity profile for each arm."""
from __future__ import annotations

import random
from datetime import timedelta

from study import DATA_CUT, Subject

# verbatim term, MedDRA PT, SOC, max typical grade, P(related), P(serious)
COMMON = [
    ("Fatigue", "Fatigue", "General disorders and administration site conditions", 2, .6, 0),
    ("nausea", "Nausea", "Gastrointestinal disorders", 2, .6, 0),
    ("Decreased appetite", "Decreased appetite", "Metabolism and nutrition disorders", 2, .5, 0),
    ("Anemia", "Anaemia", "Blood and lymphatic system disorders", 3, .4, .05),
    ("Constipation", "Constipation", "Gastrointestinal disorders", 1, .3, 0),
    ("Headache", "Headache", "Nervous system disorders", 1, .3, 0),
    ("Joint pain", "Arthralgia", "Musculoskeletal and connective tissue disorders", 1, .2, 0),
    ("Cough", "Cough", "Respiratory, thoracic and mediastinal disorders", 1, .1, 0),
    ("Back pain", "Back pain", "Musculoskeletal and connective tissue disorders", 2, .05, 0),
    ("Fever", "Pyrexia", "General disorders and administration site conditions", 1, .3, .05),
    ("Urinary tract infection", "Urinary tract infection", "Infections and infestations",
     2, .05, .1),
    ("COVID-19", "COVID-19", "Infections and infestations", 2, 0, .1),
]
BY_DRUG = {
    "ZV-210": [
        ("Hypertension", "Hypertension", "Vascular disorders", 3, .9, 0),
        ("Proteinuria", "Proteinuria", "Renal and urinary disorders", 2, .9, 0),
        ("Nose bleed", "Epistaxis", "Respiratory, thoracic and mediastinal disorders", 1, .8, 0),
        ("Hypothyroidism", "Hypothyroidism", "Endocrine disorders", 2, .9, 0),
        ("Maculopapular rash", "Rash maculo-papular", "Skin and subcutaneous tissue disorders",
         2, .9, 0),
        ("Itching", "Pruritus", "Skin and subcutaneous tissue disorders", 1, .8, 0),
        ("ALT increased", "Alanine aminotransferase increased", "Investigations", 3, .8, 0),
        ("Pneumonitis", "Pneumonitis", "Respiratory, thoracic and mediastinal disorders",
         3, .95, .8),
        ("Infusion related reaction", "Infusion related reaction",
         "Injury, poisoning and procedural complications", 2, 1, .1),
    ],
    "ZK-415": [
        ("Neutropenia", "Neutrophil count decreased", "Investigations", 4, .95, 0),
        ("Stomatitis", "Stomatitis", "Gastrointestinal disorders", 2, .9, 0),
        ("Hair loss", "Alopecia", "Skin and subcutaneous tissue disorders", 2, .95, 0),
        ("Diarrhea", "Diarrhoea", "Gastrointestinal disorders", 3, .9, .1),
        ("Febrile neutropenia", "Febrile neutropenia", "Blood and lymphatic system disorders",
         3, 1, 1),
    ],
    "Paclitaxel": [
        ("Peripheral sensory neuropathy", "Peripheral sensory neuropathy",
         "Nervous system disorders", 3, .95, 0),
        ("Alopecia", "Alopecia", "Skin and subcutaneous tissue disorders", 2, 1, 0),
        ("Neutrophil count decreased", "Neutrophil count decreased", "Investigations",
         4, .95, 0),
        ("Muscle pain", "Myalgia", "Musculoskeletal and connective tissue disorders", 1, .8, 0),
        ("Hypersensitivity reaction", "Hypersensitivity", "Immune system disorders", 3, 1, .3),
    ],
}
ARM_DRUGS = {"ZV210": ["ZV-210"], "ZV210_ZK415": ["ZV-210", "ZK-415"], "PACLI": ["Paclitaxel"]}
GRADE_TXT = {1: "Grade 1 (Mild)", 2: "Grade 2 (Moderate)", 3: "Grade 3 (Severe)",
             4: "Grade 4 (Life-threatening)", 5: "Grade 5 (Death)"}


def build_aes(rng: random.Random, s: Subject) -> None:
    """Fill ``s.aes``; the AE that stopped treatment is forced for AE discontinuations."""
    if not s.randomised:
        return
    drugs = ARM_DRUGS[s.arm]
    pool = COMMON + [a for d in drugs for a in BY_DRUG[d]]
    first, last = s.dose_dates[0], (s.eot_date or DATA_CUT)
    span = max(7, (last - first).days)
    n = min(14, max(1, int(rng.gauss(2 + len(s.dose_dates) * 0.6, 1.5))))
    picks = rng.sample(pool, min(n, len(pool)))
    if s.outcome == "AE":
        drug_tox = [a for d in drugs for a in BY_DRUG[d] if a[3] >= 3]
        picks.append(rng.choice(drug_tox))
    for k, (term, pt, soc, gmax, p_rel, p_ser) in enumerate(picks, 1):
        forced = s.outcome == "AE" and k == len(picks)
        onset = (s.dose_dates[-1] + timedelta(days=rng.randint(2, 12)) if forced
                 else first + timedelta(days=rng.randint(1, span)))
        onset = min(onset, DATA_CUT - timedelta(days=1))
        grade = gmax if forced else rng.choices(range(1, gmax + 1),
                                                [6, 3, 1.2, .4][:gmax])[0]
        serious = forced and rng.random() < .5 or rng.random() < p_ser
        if serious and grade < 3:
            grade = 3
        dur = rng.randint(3, 60) if grade < 3 else rng.randint(7, 45)
        end = onset + timedelta(days=dur)
        ongoing = end > DATA_CUT or (rng.random() < .15 and not forced)
        related = {d: rng.random() < p_rel for d in drugs}
        if forced:
            related = {d: True for d in drugs}
        action = "Drug Withdrawn" if forced else (
            rng.choice(["Dose Not Changed", "Drug Interrupted", "Dose Reduced"]) if grade >= 3
            else "Dose Not Changed")
        s.aes.append({
            "spid": f"AE{k:03d}", "term": term, "pt": pt, "soc": soc, "grade": grade,
            "onset": onset, "end": None if ongoing else end, "serious": serious,
            "related": related, "action": action, "forced": forced,
            "outcome": ("Not Recovered/Not Resolved" if ongoing else
                        rng.choice(["Recovered/Resolved", "Recovered/Resolved",
                                    "Recovered/Resolved With Sequelae"]) if grade < 4
                        else "Recovering/Resolving"),
            "hosp": serious and rng.random() < .85,
            "aesi": pt in ("Pneumonitis", "Hypothyroidism", "Infusion related reaction"),
            "treated": rng.random() < .55,
        })
    if s.death_date:
        s.aes.append({"spid": f"AE{len(s.aes) + 1:03d}", "term": "Disease progression",
                      "pt": "Malignant neoplasm progression", "soc": "Neoplasms benign, "
                      "malignant and unspecified (incl cysts and polyps)", "grade": 5,
                      "onset": s.death_date - timedelta(days=rng.randint(5, 20)),
                      "end": s.death_date, "serious": True,
                      "related": {d: False for d in drugs}, "action": "Not Applicable",
                      "forced": False, "outcome": "Fatal", "hosp": True, "aesi": False,
                      "treated": True})
