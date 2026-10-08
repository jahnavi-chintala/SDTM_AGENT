"""Study design and the simulated "truth" every vendor file is cut from.

One fictional study (ZVR210-201): a randomised Phase 2 in first-line advanced
triple-negative breast cancer with three arms. Everything here is synthetic; the
drug codes, sites, investigators and patients do not exist.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

STUDYID = "ZVR210-201"
TITLE = ("A Phase 2, Randomised, Open-label Study of ZV-210 Alone or With ZK-415 Versus "
         "Paclitaxel in Previously Untreated Advanced Triple-negative Breast Cancer")
DATA_CUT = date(2026, 9, 15)
CYCLE_DAYS = 21

# arm code -> (label, drugs given each cycle)
ARMS = {
    "ZV210": ("ZV-210 20 mg/kg Q3W", ["ZV-210"]),
    "ZV210_ZK415": ("ZV-210 20 mg/kg + ZK-415 3 mg/kg Q3W", ["ZV-210", "ZK-415"]),
    "PACLI": ("Paclitaxel 80 mg/m2 Days 1, 8, 15 Q3W", ["Paclitaxel"]),
}
# Response tendency per arm: probability of shrinkage and typical depth.
ARM_EFFECT = {"ZV210": (0.55, 0.35), "ZV210_ZK415": (0.70, 0.45), "PACLI": (0.50, 0.30)}

# site -> (country, investigator, timezone offset, weight of enrolment)
SITES = {
    "101": ("USA", "Dr. Helen Okafor", "-05:00", 9),
    "102": ("USA", "Dr. Marcus Lindqvist", "-06:00", 7),
    "103": ("USA", "Dr. Priya Raman", "-08:00", 6),
    "201": ("ESP", "Dra. Lucía Ferrer", "+01:00", 8),
    "202": ("ESP", "Dr. Iñigo Arrieta", "+01:00", 5),
    "301": ("DEU", "Prof. Dr. Katrin Vogel", "+01:00", 8),
    "401": ("JPN", "Dr. Kenji Watanabe", "+09:00", 8),
    "501": ("AUS", "Dr. Fiona McAllister", "+10:00", 7),
}
SCREEN_FAIL_REASONS = [
    ("Inclusion 4 not met", "ECOG performance status 2 at screening"),
    ("Exclusion 7 met", "Untreated brain metastases on screening MRI"),
    ("Inclusion 6 not met", "ANC below 1.5 x10^9/L at screening"),
    ("Exclusion 11 met", "Uncontrolled hypertension"),
    ("Withdrawal by subject", "Subject declined further participation"),
    ("Inclusion 2 not met", "HER2 low status (IHC 2+) confirmed on central review"),
    ("Exclusion 3 met", "Prior PD-1/PD-L1 therapy in the metastatic setting"),
    ("Inclusion 6 not met", "Total bilirubin 2.1 x ULN"),
]
FIRST_NAMES = "ABCDEFGHIJKLMNOPRSTVWY"
N_RANDOMISED = 50
N_SCREEN_FAIL = 8


@dataclass
class Lesion:
    lid: str
    site: str
    detail: str
    target: bool
    baseline_mm: float


@dataclass
class Subject:
    site: str
    seq: int
    country: str
    sex: str
    birth: date
    age: int
    race: str
    ethnic: str
    initials: str
    height: float
    weight: float
    childpot: bool
    screen_date: date
    consent_date: date
    screen_fail: tuple[str, str] | None = None
    arm: str = ""
    strata: dict = field(default_factory=dict)
    rand_no: str = ""
    rand_date: date | None = None
    dose_dates: list[date] = field(default_factory=list)   # Day 1 of each cycle
    outcome: str = ""            # ONGOING, PD, AE, WITHDRAWN, DEATH
    eot_date: date | None = None
    death_date: date | None = None
    lesions: list[Lesion] = field(default_factory=list)
    tumour: list[dict] = field(default_factory=list)       # one dict per assessment
    aes: list[dict] = field(default_factory=list)

    @property
    def subnum(self) -> str:
        return f"{self.site}-{self.seq:03d}"

    @property
    def usubjid(self) -> str:
        return f"{STUDYID}-{self.subnum}"

    @property
    def randomised(self) -> bool:
        return self.rand_date is not None


RACE_BY_COUNTRY = {
    "USA": [("White", 60), ("Black or African American", 22), ("Asian", 8),
            ("Other", 4), ("Not Reported", 6)],
    "ESP": [("White", 92), ("Not Reported", 8)],
    "DEU": [("White", 90), ("Not Reported", 10)],
    "JPN": [("Asian", 100)],
    "AUS": [("White", 75), ("Asian", 18), ("Native Hawaiian or Other Pacific Islander", 3),
            ("Not Reported", 4)],
}


def _pick(rng: random.Random, weighted: list[tuple[str, int]]) -> str:
    return rng.choices([w[0] for w in weighted], [w[1] for w in weighted])[0]


def _initials(rng: random.Random) -> str:
    first, last = rng.choice(FIRST_NAMES), rng.choice(FIRST_NAMES)
    middle = rng.choice(FIRST_NAMES) if rng.random() < 0.35 else "-"
    return first + middle + last


def _lesions(rng: random.Random) -> list[Lesion]:
    pool = [("Breast", "Left breast primary, upper outer quadrant"),
            ("Breast", "Right breast primary, 10 o'clock"),
            ("Liver", "Segment VII hepatic metastasis"), ("Liver", "Segment IVa hepatic lesion"),
            ("Lung", "Right lower lobe nodule"), ("Lung", "Left upper lobe nodule"),
            ("Lymph node", "Left axillary lymph node"), ("Lymph node", "Mediastinal (4R) node"),
            ("Chest wall", "Right anterior chest wall soft-tissue mass")]
    chosen = rng.sample(pool, rng.randint(1, 4))
    out = [Lesion(f"T{i + 1:02d}", s, d, True,
                  round(rng.uniform(16 if s == "Lymph node" else 11, 58), 1))
           for i, (s, d) in enumerate(chosen)]
    for j in range(rng.choice([0, 1, 1, 2])):
        s, d = rng.choice([("Bone", "Thoracic spine (T8) sclerotic lesion"),
                           ("Pleura", "Right pleural effusion"),
                           ("Lymph node", "Supraclavicular nodes, non-measurable"),
                           ("Liver", "Multiple sub-centimetre hepatic foci")])
        out.append(Lesion(f"NT{j + 1:02d}", s, d, False, 0.0))
    return out


def _simulate_tumour(rng: random.Random, s: Subject) -> None:
    """Tumour assessments every 6 weeks from C1D1, applying RECIST 1.1 to the truth."""
    p_shrink, depth = ARM_EFFECT[s.arm]
    responds = rng.random() < p_shrink
    best = -rng.uniform(0.3, 0.95) * depth * 2 if responds else rng.uniform(-0.15, 0.1)
    escape_week = rng.choice([12, 18, 24, 30, 36, 48, 60, 999]) if responds else rng.choice(
        [6, 12, 12, 18, 24])
    base = sum(lz.baseline_mm for lz in s.lesions if lz.target)
    nadir, week, c1d1 = base, 6, s.dose_dates[0]
    s.tumour = [{"week": 0, "date": s.screen_date + timedelta(days=rng.randint(0, 6)),
                 "sizes": {lz.lid: lz.baseline_mm for lz in s.lesions if lz.target},
                 "sld": round(base, 1), "new": False, "nt": "NON-CR/NON-PD", "resp": "NE"}]
    while True:
        when = c1d1 + timedelta(days=week * 7 + rng.randint(-3, 5))
        if when > DATA_CUT:
            break
        frac = best * min(1, week / 12) if week < escape_week else best + 0.12 * (
            week - escape_week) / 6 + 0.15
        sizes = {lz.lid: max(0.0, round(lz.baseline_mm * (1 + frac + rng.gauss(0, 0.04)), 1))
                 for lz in s.lesions if lz.target}
        sld = round(sum(sizes.values()), 1)
        new = week >= escape_week and rng.random() < 0.35
        nadir = min(nadir, sld)
        if new or (sld >= nadir * 1.2 and sld - nadir >= 5):
            resp = "PD"
        elif sld == 0:
            resp = "CR"
        elif sld <= base * 0.7:
            resp = "PR"
        else:
            resp = "SD"
        s.tumour.append({"week": week, "date": when, "sizes": sizes, "sld": sld, "new": new,
                         "nt": "NON-CR/NON-PD" if resp != "PD" else rng.choice(
                             ["NON-CR/NON-PD", "PD"]), "resp": resp})
        if resp == "PD":
            break
        week += 6


def build_subjects(seed: int = 20260915) -> list[Subject]:
    """Simulate screening, randomisation, dosing and outcome for every subject."""
    rng = random.Random(seed)
    total = N_RANDOMISED + N_SCREEN_FAIL
    sites = rng.choices(list(SITES), [SITES[k][3] for k in SITES], k=total)
    start, span = date(2025, 3, 3), (date(2025, 12, 19) - date(2025, 3, 3)).days
    screens = sorted(start + timedelta(days=rng.randint(0, span)) for _ in range(total))
    fail_idx = set(rng.sample(range(total), N_SCREEN_FAIL))
    seq_by_site: dict[str, int] = {}
    blocks: dict[tuple, list[str]] = {}
    subjects, rand_counter = [], 1000
    for i, (site, scr) in enumerate(zip(sites, screens)):
        seq_by_site[site] = seq_by_site.get(site, 0) + 1
        country = SITES[site][0]
        age = int(min(81, max(27, rng.gauss(55, 11))))
        birth = scr - timedelta(days=age * 365 + rng.randint(30, 330))
        s = Subject(site=site, seq=seq_by_site[site], country=country, sex="F", birth=birth,
                    age=age, race=_pick(rng, RACE_BY_COUNTRY[country]),
                    ethnic=("Hispanic or Latino" if country == "ESP" or (
                        country == "USA" and rng.random() < 0.18) else "Not Hispanic or Latino"),
                    initials=_initials(rng), height=round(rng.gauss(161 if country == "JPN"
                                                                    else 166, 6), 1),
                    weight=round(rng.gauss(58 if country == "JPN" else 72, 12), 1),
                    childpot=age < 51 and rng.random() < 0.7, screen_date=scr,
                    consent_date=scr - timedelta(days=rng.randint(0, 5)))
        s.weight = max(41.0, s.weight)
        s.lesions = _lesions(rng)
        if i in fail_idx:
            s.screen_fail = SCREEN_FAIL_REASONS[len([x for x in subjects if x.screen_fail])]
            subjects.append(s)
            continue
        s.strata = {"PDL1_CPS": rng.choice(["<10", ">=10"]),
                    "PRIOR_TAXANE": rng.choice(["Yes", "No", "No"])}
        key = tuple(s.strata.values())
        if not blocks.get(key):   # permuted blocks of 3 within each stratum, as an IRT would
            blocks[key] = rng.sample(list(ARMS), 3)
        s.arm = blocks[key].pop()
        rand_counter += rng.randint(1, 3)
        s.rand_no = f"R{rand_counter}"
        s.rand_date = scr + timedelta(days=rng.randint(9, 24))
        _dose_and_outcome(rng, s)
        subjects.append(s)
    return subjects


def _dose_and_outcome(rng: random.Random, s: Subject) -> None:
    d = s.rand_date + timedelta(days=rng.randint(1, 3))
    s.dose_dates = [d]
    _simulate_tumour(rng, s)
    pd_date = next((t["date"] for t in s.tumour if t["resp"] == "PD"), None)
    stop_cycle = rng.randint(3, 9) if rng.random() < 0.11 else None    # AE discontinuation
    withdraw_cycle = rng.randint(2, 7) if rng.random() < 0.05 else None
    while True:
        nxt = d + timedelta(days=CYCLE_DAYS + (7 if rng.random() < 0.1 else 0))
        n = len(s.dose_dates)
        if pd_date and nxt > pd_date:
            s.outcome = "PD"
            break
        if stop_cycle and n >= stop_cycle:
            s.outcome = "AE"
            break
        if withdraw_cycle and n >= withdraw_cycle:
            s.outcome = "WITHDRAWN"
            break
        if nxt > DATA_CUT:
            s.outcome = "ONGOING"
            break
        d = nxt
        s.dose_dates.append(d)
    if s.outcome != "ONGOING":
        s.eot_date = min(DATA_CUT, s.dose_dates[-1] + timedelta(days=rng.randint(21, 35)))
        if s.outcome == "PD" and rng.random() < 0.3:
            s.death_date = s.eot_date + timedelta(days=rng.randint(40, 260))
            if s.death_date > DATA_CUT:
                s.death_date = None
    if s.outcome == "PD" and s.tumour[-1]["resp"] == "PD" and s.death_date and rng.random() < .2:
        s.outcome = "DEATH"


def visit_plan(s: Subject) -> list[tuple[str, date]]:
    """EDC folder name and date for every protocol visit the subject attended."""
    plan = [("Screening", s.screen_date)]
    if not s.randomised:
        return plan
    pacli = s.arm == "PACLI"
    for c, d1 in enumerate(s.dose_dates, 1):
        plan.append((f"Cycle {c} Day 1", d1))
        if c == 1 or pacli:
            for day in (8, 15):
                if d1 + timedelta(days=day - 1) <= DATA_CUT:
                    plan.append((f"Cycle {c} Day {day}", d1 + timedelta(days=day - 1)))
    if s.eot_date:
        plan.append(("End of Treatment", s.eot_date))
        fu = s.dose_dates[-1] + timedelta(days=30)
        if fu <= DATA_CUT and (not s.death_date or fu < s.death_date):
            plan.append(("30-Day Safety Follow-up", fu))
    return plan
