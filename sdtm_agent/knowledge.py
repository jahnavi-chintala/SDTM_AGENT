"""Structured SDTM reference metadata (SDTMIG v3.3/3.4 subset).

This is the authoritative, machine-readable layer the agent uses for
variable lists, core status and controlled terminology. The same content is
also turned into text chunks for the Vector Search index (see ig_corpus.py),
alongside any licensed SDTM IG text you load from a Unity Catalog volume.

Core: Req = required, Exp = expected, Perm = permissible.
"""

from __future__ import annotations

# (variable, label, type, core)
Var = tuple[str, str, str, str]


def _ids(prefix: str) -> list[Var]:
    return [
        ("STUDYID", "Study Identifier", "Char", "Req"),
        ("DOMAIN", "Domain Abbreviation", "Char", "Req"),
        ("USUBJID", "Unique Subject Identifier", "Char", "Req"),
        (f"{prefix}SEQ", "Sequence Number", "Num", "Req"),
    ]


def _visit(prefix: str, dtc_label: str, with_dy: bool = True) -> list[Var]:
    out = [
        ("VISITNUM", "Visit Number", "Num", "Exp"),
        ("VISIT", "Visit Name", "Char", "Perm"),
        (f"{prefix}DTC", dtc_label, "Char", "Exp"),
    ]
    if with_dy:
        out.append((f"{prefix}DY", f"Study Day of {dtc_label.replace('Date/Time of ', '')}", "Num", "Perm"))
    return out


def _timepoint(prefix: str) -> list[Var]:
    return [
        (f"{prefix}TPT", "Planned Time Point Name", "Char", "Perm"),
        (f"{prefix}TPTNUM", "Planned Time Point Number", "Num", "Perm"),
    ]


def _findings(prefix: str, test_label: str) -> list[Var]:
    return [
        (f"{prefix}TESTCD", f"{test_label} Short Name", "Char", "Req"),
        (f"{prefix}TEST", f"{test_label} Name", "Char", "Req"),
        (f"{prefix}CAT", f"Category for {test_label}", "Char", "Perm"),
        (f"{prefix}ORRES", "Result or Finding in Original Units", "Char", "Exp"),
        (f"{prefix}ORRESU", "Original Units", "Char", "Exp"),
        (f"{prefix}STRESC", "Character Result/Finding in Std Format", "Char", "Exp"),
        (f"{prefix}STRESN", "Numeric Result/Finding in Standard Units", "Num", "Exp"),
        (f"{prefix}STRESU", "Standard Units", "Char", "Exp"),
        (f"{prefix}STAT", "Completion Status", "Char", "Perm"),
        (f"{prefix}REASND", "Reason Not Done", "Char", "Perm"),
    ]


DOMAINS: dict[str, dict] = {
    # ------------------------------------------------------------ Special Purpose
    "DM": {
        "label": "Demographics",
        "class": "Special-Purpose",
        "structure": "One record per subject",
        "keys": ["STUDYID", "USUBJID"],
        "variables": [
            ("STUDYID", "Study Identifier", "Char", "Req"),
            ("DOMAIN", "Domain Abbreviation", "Char", "Req"),
            ("USUBJID", "Unique Subject Identifier", "Char", "Req"),
            ("SUBJID", "Subject Identifier for the Study", "Char", "Req"),
            ("RFSTDTC", "Subject Reference Start Date/Time", "Char", "Exp"),
            ("RFENDTC", "Subject Reference End Date/Time", "Char", "Exp"),
            ("RFXSTDTC", "Date/Time of First Study Treatment", "Char", "Exp"),
            ("RFXENDTC", "Date/Time of Last Study Treatment", "Char", "Exp"),
            ("RFICDTC", "Date/Time of Informed Consent", "Char", "Exp"),
            ("RFPENDTC", "Date/Time of End of Participation", "Char", "Exp"),
            ("DTHDTC", "Date/Time of Death", "Char", "Exp"),
            ("DTHFL", "Subject Death Flag", "Char", "Exp"),
            ("SITEID", "Study Site Identifier", "Char", "Req"),
            ("BRTHDTC", "Date/Time of Birth", "Char", "Perm"),
            ("AGE", "Age", "Num", "Exp"),
            ("AGEU", "Age Units", "Char", "Exp"),
            ("SEX", "Sex", "Char", "Req"),
            ("RACE", "Race", "Char", "Exp"),
            ("ETHNIC", "Ethnicity", "Char", "Perm"),
            ("ARMCD", "Planned Arm Code", "Char", "Exp"),
            ("ARM", "Description of Planned Arm", "Char", "Exp"),
            ("ACTARMCD", "Actual Arm Code", "Char", "Exp"),
            ("ACTARM", "Description of Actual Arm", "Char", "Exp"),
            ("COUNTRY", "Country", "Char", "Req"),
            ("DMDTC", "Date/Time of Collection", "Char", "Perm"),
            ("DMDY", "Study Day of Collection", "Num", "Perm"),
        ],
        "assumptions": [
            "DM has exactly one record per subject; USUBJID must be unique within the study and identical across all domains.",
            "USUBJID is typically derived as STUDYID || '-' || SITEID || '-' || SUBJID (any sponsor convention that is unique across the submission is acceptable).",
            "RFSTDTC is the subject reference start date, usually the date of first study treatment; study day (--DY) in all other domains is computed relative to RFSTDTC.",
            "AGE is age at RFSTDTC (or informed consent) in AGEU units; if BRTHDTC is collected, AGE may be derived from it.",
            "SEX uses codelist SEX (M, F, U, UNDIFFERENTIATED). RACE uses codelist RACE; multiple races collected → RACE='MULTIPLE' with details in SUPPDM.",
            "ARMCD/ARM must match values in the TA domain; screen failures use ARMCD='SCRNFAIL', not assigned subjects 'NOTASSGN'.",
            "COUNTRY uses ISO 3166-1 alpha-3 codes (e.g. USA, GBR, DEU).",
            "All dates are ISO 8601 character strings (YYYY-MM-DD or YYYY-MM-DDThh:mm); partial dates are truncated (e.g. 2023-05), never imputed in SDTM.",
        ],
    },
    # ------------------------------------------------------------ Interventions
    "EX": {
        "label": "Exposure",
        "class": "Interventions",
        "structure": "One record per constant dosing interval per subject",
        "keys": ["STUDYID", "USUBJID", "EXTRT", "EXSTDTC"],
        "variables": _ids("EX")
        + [
            ("EXTRT", "Name of Treatment", "Char", "Req"),
            ("EXDOSE", "Dose", "Num", "Exp"),
            ("EXDOSU", "Dose Units", "Char", "Exp"),
            ("EXDOSFRM", "Dose Form", "Char", "Exp"),
            ("EXDOSFRQ", "Dosing Frequency per Interval", "Char", "Perm"),
            ("EXROUTE", "Route of Administration", "Char", "Perm"),
            ("EXLOT", "Lot Number", "Char", "Perm"),
            ("VISITNUM", "Visit Number", "Num", "Perm"),
            ("EXSTDTC", "Start Date/Time of Treatment", "Char", "Exp"),
            ("EXENDTC", "End Date/Time of Treatment", "Char", "Exp"),
            ("EXSTDY", "Study Day of Start of Treatment", "Num", "Perm"),
            ("EXENDY", "Study Day of End of Treatment", "Num", "Perm"),
        ],
        "assumptions": [
            "EX records protocol-specified study treatment as administered; one record per constant-dosing interval.",
            "EXTRT is the name of the study treatment (blinded studies still record the actual treatment in EX).",
            "EXDOSU, EXDOSFRM, EXROUTE and EXDOSFRQ use CDISC codelists UNIT, FRM, ROUTE and FREQ.",
            "First EXSTDTC per subject should equal DM.RFXSTDTC; last EXENDTC should equal DM.RFXENDTC.",
        ],
    },
    "CM": {
        "label": "Concomitant/Prior Medications",
        "class": "Interventions",
        "structure": "One record per recorded medication occurrence or constant-dosing interval per subject",
        "keys": ["STUDYID", "USUBJID", "CMTRT", "CMSTDTC"],
        "variables": _ids("CM")
        + [
            ("CMSPID", "Sponsor-Defined Identifier", "Char", "Perm"),
            ("CMTRT", "Reported Name of Drug, Med, or Therapy", "Char", "Req"),
            ("CMDECOD", "Standardized Medication Name", "Char", "Perm"),
            ("CMCAT", "Category for Medication", "Char", "Perm"),
            ("CMINDC", "Indication", "Char", "Perm"),
            ("CMCLAS", "Medication Class", "Char", "Perm"),
            ("CMDOSE", "Dose per Administration", "Num", "Perm"),
            ("CMDOSU", "Dose Units", "Char", "Perm"),
            ("CMDOSFRQ", "Dosing Frequency per Interval", "Char", "Perm"),
            ("CMROUTE", "Route of Administration", "Char", "Perm"),
            ("CMSTDTC", "Start Date/Time of Medication", "Char", "Perm"),
            ("CMENDTC", "End Date/Time of Medication", "Char", "Perm"),
            ("CMSTDY", "Study Day of Start of Medication", "Num", "Perm"),
            ("CMENDY", "Study Day of End of Medication", "Num", "Perm"),
            ("CMENRTPT", "End Relative to Reference Time Point", "Char", "Perm"),
        ],
        "assumptions": [
            "CMTRT holds the verbatim medication name as collected; CMDECOD holds the WHODrug standardized name.",
            "Ongoing medications have CMENDTC null and CMENRTPT='ONGOING' with CMENTPT describing the reference point.",
            "CMDOSU, CMROUTE and CMDOSFRQ use codelists UNIT, ROUTE and FREQ.",
        ],
    },
    # ------------------------------------------------------------ Events
    "AE": {
        "label": "Adverse Events",
        "class": "Events",
        "structure": "One record per adverse event per subject",
        "keys": ["STUDYID", "USUBJID", "AEDECOD", "AESTDTC"],
        "variables": _ids("AE")
        + [
            ("AESPID", "Sponsor-Defined Identifier", "Char", "Perm"),
            ("AETERM", "Reported Term for the Adverse Event", "Char", "Req"),
            ("AEMODIFY", "Modified Reported Term", "Char", "Perm"),
            ("AEDECOD", "Dictionary-Derived Term", "Char", "Req"),
            ("AEBODSYS", "Body System or Organ Class", "Char", "Exp"),
            ("AESOC", "Primary System Organ Class", "Char", "Exp"),
            ("AESEV", "Severity/Intensity", "Char", "Perm"),
            ("AESER", "Serious Event", "Char", "Exp"),
            ("AEACN", "Action Taken with Study Treatment", "Char", "Exp"),
            ("AEREL", "Causality", "Char", "Exp"),
            ("AEOUT", "Outcome of Adverse Event", "Char", "Perm"),
            ("AETOXGR", "Standard Toxicity Grade", "Char", "Perm"),
            ("AESTDTC", "Start Date/Time of Adverse Event", "Char", "Exp"),
            ("AEENDTC", "End Date/Time of Adverse Event", "Char", "Exp"),
            ("AESTDY", "Study Day of Start of Adverse Event", "Num", "Perm"),
            ("AEENDY", "Study Day of End of Adverse Event", "Num", "Perm"),
        ],
        "assumptions": [
            "AETERM is the verbatim term as reported; AEDECOD is the MedDRA preferred term and AEBODSYS/AESOC the system organ class.",
            "AESER is Y/N (codelist NY). If AESER='Y', the seriousness criteria flags (AESDTH, AESHOSP, ...) should be populated.",
            "AESEV uses codelist AESEV (MILD, MODERATE, SEVERE); oncology studies typically use AETOXGR (CTCAE grade) instead.",
            "AEOUT uses codelist OUT; AEACN uses codelist ACN.",
            "AEENDTC must not be before AESTDTC.",
        ],
    },
    "MH": {
        "label": "Medical History",
        "class": "Events",
        "structure": "One record per medical history event per subject",
        "keys": ["STUDYID", "USUBJID", "MHDECOD", "MHSTDTC"],
        "variables": _ids("MH")
        + [
            ("MHSPID", "Sponsor-Defined Identifier", "Char", "Perm"),
            ("MHTERM", "Reported Term for the Medical History", "Char", "Req"),
            ("MHDECOD", "Dictionary-Derived Term", "Char", "Perm"),
            ("MHCAT", "Category for Medical History", "Char", "Perm"),
            ("MHBODSYS", "Body System or Organ Class", "Char", "Perm"),
            ("MHPRESP", "Medical History Event Pre-Specified", "Char", "Perm"),
            ("MHOCCUR", "Medical History Occurrence", "Char", "Perm"),
            ("MHSTDTC", "Start Date/Time of Medical History Event", "Char", "Perm"),
            ("MHENDTC", "End Date/Time of Medical History Event", "Char", "Perm"),
            ("MHENRTPT", "End Relative to Reference Time Point", "Char", "Perm"),
        ],
        "assumptions": [
            "MHTERM is verbatim; MHDECOD is the MedDRA preferred term.",
            "MHOCCUR is only used for pre-specified conditions (MHPRESP='Y'), with values from codelist NY.",
            "Ongoing conditions: MHENRTPT='ONGOING'.",
        ],
    },
    "DS": {
        "label": "Disposition",
        "class": "Events",
        "structure": "One record per disposition status or protocol milestone per subject",
        "keys": ["STUDYID", "USUBJID", "DSCAT", "DSSTDTC"],
        "variables": _ids("DS")
        + [
            ("DSSPID", "Sponsor-Defined Identifier", "Char", "Perm"),
            ("DSTERM", "Reported Term for the Disposition Event", "Char", "Req"),
            ("DSDECOD", "Standardized Disposition Term", "Char", "Req"),
            ("DSCAT", "Category for Disposition Event", "Char", "Exp"),
            ("DSSCAT", "Subcategory for Disposition Event", "Char", "Perm"),
            ("EPOCH", "Epoch", "Char", "Perm"),
            ("DSDTC", "Date/Time of Collection", "Char", "Perm"),
            ("DSSTDTC", "Start Date/Time of Disposition Event", "Char", "Exp"),
            ("DSSTDY", "Study Day of Start of Disposition Event", "Num", "Perm"),
        ],
        "assumptions": [
            "DSCAT is one of DISPOSITION EVENT, PROTOCOL MILESTONE, OTHER EVENT.",
            "For DSCAT='DISPOSITION EVENT', DSDECOD uses codelist NCOMPLT (e.g. COMPLETED, ADVERSE EVENT, WITHDRAWAL BY SUBJECT); for PROTOCOL MILESTONE, codelist PROTMLST (e.g. INFORMED CONSENT OBTAINED, RANDOMIZED).",
            "Each subject should have one disposition event per epoch.",
        ],
    },
    # ------------------------------------------------------------ Findings
    "VS": {
        "label": "Vital Signs",
        "class": "Findings",
        "structure": "One record per vital sign measurement per time point per visit per subject",
        "keys": ["STUDYID", "USUBJID", "VSTESTCD", "VISITNUM", "VSTPTNUM"],
        "variables": _ids("VS")
        + _findings("VS", "Vital Signs Test")
        + [
            ("VSPOS", "Vital Signs Position of Subject", "Char", "Perm"),
            ("VSLOC", "Location of Vital Signs Measurement", "Char", "Perm"),
            ("VSLOBXFL", "Last Observation Before Exposure Flag", "Char", "Exp"),
        ]
        + _visit("VS", "Date/Time of Measurements")
        + _timepoint("VS"),
        "assumptions": [
            "Findings domains are normalized (long): one record per test. Wide source data (e.g. columns SYSBP, DIABP, PULSE) must be unpivoted.",
            "VSTESTCD/VSTEST use codelists VSTESTCD/VSTEST (e.g. SYSBP/Systolic Blood Pressure, DIABP/Diastolic Blood Pressure, PULSE/Pulse Rate, TEMP/Temperature, WEIGHT/Weight, HEIGHT/Height, RESP/Respiratory Rate).",
            "VSORRES holds the result as collected (character); VSSTRESN the numeric standardized result and VSSTRESU the standard unit (codelist VSRESU, e.g. mmHg, beats/min, C, kg, cm).",
            "If a test was not done: VSSTAT='NOT DONE', VSORRES null, VSREASND populated.",
            "VSLOBXFL='Y' flags the last non-missing result before first exposure (replaces VSBLFL in SDTMIG 3.3+).",
        ],
    },
    "LB": {
        "label": "Laboratory Test Results",
        "class": "Findings",
        "structure": "One record per lab test per time point per visit per subject",
        "keys": ["STUDYID", "USUBJID", "LBTESTCD", "LBSPEC", "VISITNUM", "LBTPTNUM"],
        "variables": _ids("LB")
        + [
            ("LBREFID", "Specimen ID", "Char", "Perm"),
        ]
        + _findings("LB", "Lab Test or Examination")
        + [
            ("LBORNRLO", "Reference Range Lower Limit in Orig Unit", "Char", "Exp"),
            ("LBORNRHI", "Reference Range Upper Limit in Orig Unit", "Char", "Exp"),
            ("LBSTNRLO", "Reference Range Lower Limit-Std Units", "Num", "Exp"),
            ("LBSTNRHI", "Reference Range Upper Limit-Std Units", "Num", "Exp"),
            ("LBNRIND", "Reference Range Indicator", "Char", "Exp"),
            ("LBSPEC", "Specimen Type", "Char", "Perm"),
            ("LBFAST", "Fasting Status", "Char", "Perm"),
            ("LBLOBXFL", "Last Observation Before Exposure Flag", "Char", "Exp"),
        ]
        + _visit("LB", "Date/Time of Specimen Collection")
        + _timepoint("LB"),
        "assumptions": [
            "LBTESTCD/LBTEST use codelists LBTESTCD/LBTEST (e.g. ALT, AST, BILI, CREAT, GLUC, HGB, WBC, PLAT).",
            "LBCAT groups tests (e.g. CHEMISTRY, HEMATOLOGY, URINALYSIS).",
            "LBNRIND (codelist NRIND: NORMAL, LOW, HIGH, ABNORMAL) compares the result with the reference range.",
            "Standardized results (LBSTRESN/LBSTRESU) use SI or conventional units consistently across the study.",
            "Lab data usually arrives long (one row per analyte) — no unpivot needed, but raw test names must be mapped to LBTESTCD.",
        ],
    },
    "EG": {
        "label": "ECG Test Results",
        "class": "Findings",
        "structure": "One record per ECG observation per replicate per time point or one record per lead per visit per subject",
        "keys": ["STUDYID", "USUBJID", "EGTESTCD", "VISITNUM", "EGTPTNUM"],
        "variables": _ids("EG")
        + _findings("EG", "ECG Test or Examination")
        + [
            ("EGPOS", "ECG Position of Subject", "Char", "Perm"),
            ("EGMETHOD", "Method of Test or Examination", "Char", "Perm"),
            ("EGLEAD", "Lead Location Used for Measurement", "Char", "Perm"),
            ("EGEVAL", "Evaluator", "Char", "Perm"),
            ("EGLOBXFL", "Last Observation Before Exposure Flag", "Char", "Exp"),
        ]
        + _visit("EG", "Date/Time of ECG")
        + _timepoint("EG"),
        "assumptions": [
            "EGTESTCD uses codelist EGTESTCD (e.g. PRAG/PR Interval Aggregate, QRSAG, QTAG, QTCFAG/QTcF Interval, RRAG, EGHRMN/ECG Mean Heart Rate, INTP/Interpretation).",
            "Interval results are numeric in msec; the overall interpretation is EGTESTCD='INTP' with EGORRES e.g. 'NORMAL' / 'ABNORMAL'.",
            "Wide ECG source data (columns per interval) must be unpivoted to one record per test.",
        ],
    },
    "QS": {
        "label": "Questionnaires",
        "class": "Findings",
        "structure": "One record per questionnaire per question per time point per visit per subject",
        "keys": ["STUDYID", "USUBJID", "QSCAT", "QSTESTCD", "VISITNUM"],
        "variables": _ids("QS")
        + [
            ("QSTESTCD", "Question Short Name", "Char", "Req"),
            ("QSTEST", "Question Name", "Char", "Req"),
            ("QSCAT", "Category of Question", "Char", "Req"),
            ("QSSCAT", "Subcategory for Question", "Char", "Perm"),
            ("QSORRES", "Finding in Original Units", "Char", "Exp"),
            ("QSORRESU", "Original Units", "Char", "Perm"),
            ("QSSTRESC", "Character Result/Finding in Std Format", "Char", "Exp"),
            ("QSSTRESN", "Numeric Finding in Standard Units", "Num", "Perm"),
            ("QSSTAT", "Completion Status", "Char", "Perm"),
            ("QSREASND", "Reason Not Performed", "Char", "Perm"),
            ("QSLOBXFL", "Last Observation Before Exposure Flag", "Char", "Exp"),
        ]
        + _visit("QS", "Date/Time of Finding"),
        "assumptions": [
            "QSCAT holds the instrument name (e.g. 'EQ-5D-5L', 'PHQ-9'); QSTESTCD/QSTEST come from the CDISC QRS supplement for that instrument when one exists.",
            "QSORRES is the response as collected (text); QSSTRESC/QSSTRESN the standardized (often numeric score) response.",
            "Questionnaires are almost always wide in source data (one column per item) and must be unpivoted.",
            "Derived total scores are included when collected on the CRF; otherwise they belong in ADaM.",
        ],
    },
    "PE": {
        "label": "Physical Examination",
        "class": "Findings",
        "structure": "One record per body system or abnormality per visit per subject",
        "keys": ["STUDYID", "USUBJID", "PETESTCD", "VISITNUM"],
        "variables": _ids("PE")
        + [
            ("PETESTCD", "Body System Examined Short Name", "Char", "Req"),
            ("PETEST", "Body System Examined", "Char", "Req"),
            ("PECAT", "Category for Examination", "Char", "Perm"),
            ("PELOC", "Location of Physical Exam Finding", "Char", "Perm"),
            ("PEORRES", "Verbatim Examination Finding", "Char", "Exp"),
            ("PESTRESC", "Character Result/Finding in Std Format", "Char", "Exp"),
            ("PESTAT", "Completion Status", "Char", "Perm"),
            ("PEREASND", "Reason Not Examined", "Char", "Perm"),
        ]
        + _visit("PE", "Date/Time of Examination"),
        "assumptions": [
            "PE records findings by body system (PETESTCD e.g. HEENT, CV, RESP, ABDOM, SKIN, NEURO).",
            "PEORRES is 'NORMAL' or the verbatim abnormality; abnormalities that are adverse events also go to AE (or MH if pre-existing).",
            "Many sponsors only collect 'exam done' flags — then PE may be replaced by recording the date in SV; confirm PE is needed per study.",
        ],
    },
    # ------------------------------------------------------------ Trial Design
    "SV": {
        "label": "Subject Visits",
        "class": "Special-Purpose",
        "structure": "One record per actual or planned visit per subject",
        "keys": ["STUDYID", "USUBJID", "VISITNUM"],
        "variables": [
            ("STUDYID", "Study Identifier", "Char", "Req"),
            ("DOMAIN", "Domain Abbreviation", "Char", "Req"),
            ("USUBJID", "Unique Subject Identifier", "Char", "Req"),
            ("VISITNUM", "Visit Number", "Num", "Req"),
            ("VISIT", "Visit Name", "Char", "Perm"),
            ("VISITDY", "Planned Study Day of Visit", "Num", "Perm"),
            ("EPOCH", "Epoch", "Char", "Perm"),
            ("SVPRESP", "Pre-specified", "Char", "Perm"),
            ("SVOCCUR", "Occurrence", "Char", "Perm"),
            ("SVSTDTC", "Start Date/Time of Observation", "Char", "Exp"),
            ("SVENDTC", "End Date/Time of Observation", "Char", "Exp"),
            ("SVSTDY", "Study Day of Start of Observation", "Num", "Perm"),
            ("SVENDY", "Study Day of End of Observation", "Num", "Perm"),
            ("SVUPDES", "Description of Unplanned Visit", "Char", "Perm"),
        ],
        "assumptions": [
            "SV has one record per subject per visit actually attended; derive it by grouping all subject-level visit dates by USUBJID and VISITNUM.",
            "SVSTDTC is the earliest and SVENDTC the latest date/time of any assessment at that visit.",
            "Unplanned visits get a decimal VISITNUM (e.g. 2.01) and SVUPDES describing the reason.",
            "VISITNUM/VISIT values must be consistent with the Trial Visits (TV) domain and with VISITNUM used in Findings domains.",
        ],
    },
    "TA": {
        "label": "Trial Arms",
        "class": "Trial Design",
        "structure": "One record per planned element per arm",
        "keys": ["STUDYID", "ARMCD", "TAETORD"],
        "variables": [
            ("STUDYID", "Study Identifier", "Char", "Req"),
            ("DOMAIN", "Domain Abbreviation", "Char", "Req"),
            ("ARMCD", "Planned Arm Code", "Char", "Req"),
            ("ARM", "Description of Planned Arm", "Char", "Req"),
            ("TAETORD", "Planned Order of Element within Arm", "Num", "Req"),
            ("ETCD", "Element Code", "Char", "Req"),
            ("ELEMENT", "Description of Element", "Char", "Perm"),
            ("TABRANCH", "Branch", "Char", "Exp"),
            ("TATRANS", "Transition Rule", "Char", "Exp"),
            ("EPOCH", "Epoch", "Char", "Req"),
        ],
        "assumptions": [
            "TA is study-level (no USUBJID): one record per element per arm, built from the protocol rather than subject data.",
            "ARMCD/ARM values must match DM.ARMCD/ARM; ARMCD is at most 20 characters.",
            "EPOCH values (e.g. SCREENING, TREATMENT, FOLLOW-UP) are reused in subject-level domains.",
        ],
    },
}

V1_DOMAINS = ["DM", "EX", "CM", "AE", "MH", "DS", "VS", "LB", "EG", "QS", "PE"]  # + SV or TA

# Subset of CDISC controlled terminology, keyed by SDTM variable name.
# Extensible codelists (e.g. units) are only checked where listed here.
_NY = ["N", "Y"]
CONTROLLED_TERMINOLOGY: dict[str, list[str]] = {
    "SEX": ["F", "M", "U", "UNDIFFERENTIATED"],
    "AGEU": ["YEARS", "MONTHS", "WEEKS", "DAYS", "HOURS"],
    "ETHNIC": ["HISPANIC OR LATINO", "NOT HISPANIC OR LATINO", "NOT REPORTED", "UNKNOWN"],
    "RACE": [
        "AMERICAN INDIAN OR ALASKA NATIVE",
        "ASIAN",
        "BLACK OR AFRICAN AMERICAN",
        "NATIVE HAWAIIAN OR OTHER PACIFIC ISLANDER",
        "WHITE",
        "MULTIPLE",
        "NOT REPORTED",
        "OTHER",
        "UNKNOWN",
    ],
    "DTHFL": ["Y"],
    "AESEV": ["MILD", "MODERATE", "SEVERE"],
    "AESER": _NY,
    "AEOUT": [
        "FATAL",
        "NOT RECOVERED/NOT RESOLVED",
        "RECOVERED/RESOLVED",
        "RECOVERED/RESOLVED WITH SEQUELAE",
        "RECOVERING/RESOLVING",
        "UNKNOWN",
    ],
    "AEACN": [
        "DOSE INCREASED",
        "DOSE NOT CHANGED",
        "DOSE RATE REDUCED",
        "DOSE REDUCED",
        "DRUG INTERRUPTED",
        "DRUG WITHDRAWN",
        "NOT APPLICABLE",
        "UNKNOWN",
    ],
    "MHPRESP": ["Y"],
    "MHOCCUR": _NY,
    "SVPRESP": ["Y"],
    "SVOCCUR": _NY,
    "DSCAT": ["DISPOSITION EVENT", "PROTOCOL MILESTONE", "OTHER EVENT"],
    "LBNRIND": ["ABNORMAL", "HIGH", "LOW", "NORMAL"],
    "LBFAST": ["N", "Y", "U"],
    "VSTESTCD": ["BMI", "DIABP", "HEIGHT", "MAP", "PULSE", "RESP", "SYSBP", "TEMP", "WEIGHT", "OXYSAT"],
    "VSPOS": ["SITTING", "STANDING", "SUPINE"],
    "EGPOS": ["SITTING", "STANDING", "SUPINE"],
    "EGTESTCD": ["EGHRMN", "INTP", "PRAG", "QRSAG", "QTAG", "QTCBAG", "QTCFAG", "RRAG"],
    "VSSTAT": ["NOT DONE"],
    "LBSTAT": ["NOT DONE"],
    "EGSTAT": ["NOT DONE"],
    "QSSTAT": ["NOT DONE"],
    "PESTAT": ["NOT DONE"],
    "VSLOBXFL": ["Y"],
    "LBLOBXFL": ["Y"],
    "EGLOBXFL": ["Y"],
    "QSLOBXFL": ["Y"],
    "EXROUTE": ["INTRAMUSCULAR", "INTRAVENOUS", "ORAL", "SUBCUTANEOUS", "TOPICAL", "TRANSDERMAL", "INHALATION"],
}

# Standard test codes and names for common Findings tests (used for unpivoting wide data).
TEST_CODES: dict[str, dict[str, tuple[str, str | None]]] = {
    "VS": {
        "SYSBP": ("Systolic Blood Pressure", "mmHg"),
        "DIABP": ("Diastolic Blood Pressure", "mmHg"),
        "PULSE": ("Pulse Rate", "beats/min"),
        "RESP": ("Respiratory Rate", "breaths/min"),
        "TEMP": ("Temperature", "C"),
        "WEIGHT": ("Weight", "kg"),
        "HEIGHT": ("Height", "cm"),
        "BMI": ("Body Mass Index", "kg/m2"),
        "OXYSAT": ("Oxygen Saturation", "%"),
    },
    "EG": {
        "EGHRMN": ("ECG Mean Heart Rate", "beats/min"),
        "PRAG": ("PR Interval, Aggregate", "msec"),
        "QRSAG": ("QRS Duration, Aggregate", "msec"),
        "QTAG": ("QT Interval, Aggregate", "msec"),
        "QTCFAG": ("QTcF Interval, Aggregate", "msec"),
        "QTCBAG": ("QTcB Interval, Aggregate", "msec"),
        "RRAG": ("RR Interval, Aggregate", "msec"),
        "INTP": ("Interpretation", None),
    },
}

# Raw-column keyword -> (SDTM domain, SDTM variable). Seeds mapping proposals.
COLUMN_SYNONYMS: dict[str, tuple[str, str]] = {
    "study": ("DM", "STUDYID"),
    "studyid": ("DM", "STUDYID"),
    "protocol": ("DM", "STUDYID"),
    "subject": ("DM", "SUBJID"),
    "subjid": ("DM", "SUBJID"),
    "patient": ("DM", "SUBJID"),
    "usubjid": ("DM", "USUBJID"),
    "site": ("DM", "SITEID"),
    "siteid": ("DM", "SITEID"),
    "sex": ("DM", "SEX"),
    "gender": ("DM", "SEX"),
    "dob": ("DM", "BRTHDTC"),
    "birth": ("DM", "BRTHDTC"),
    "age": ("DM", "AGE"),
    "race": ("DM", "RACE"),
    "ethnic": ("DM", "ETHNIC"),
    "ethnicity": ("DM", "ETHNIC"),
    "country": ("DM", "COUNTRY"),
    "arm": ("DM", "ARM"),
    "treatment_arm": ("DM", "ARM"),
    "consent": ("DM", "RFICDTC"),
    "death": ("DM", "DTHDTC"),
    "adverse": ("AE", "AETERM"),
    "ae_term": ("AE", "AETERM"),
    "event": ("AE", "AETERM"),
    "preferred_term": ("AE", "AEDECOD"),
    "pt": ("AE", "AEDECOD"),
    "soc": ("AE", "AESOC"),
    "severity": ("AE", "AESEV"),
    "serious": ("AE", "AESER"),
    "causality": ("AE", "AEREL"),
    "relationship": ("AE", "AEREL"),
    "outcome": ("AE", "AEOUT"),
    "onset": ("AE", "AESTDTC"),
    "resolution": ("AE", "AEENDTC"),
    "systolic": ("VS", "SYSBP"),
    "sbp": ("VS", "SYSBP"),
    "diastolic": ("VS", "DIABP"),
    "dbp": ("VS", "DIABP"),
    "pulse": ("VS", "PULSE"),
    "heart_rate": ("VS", "PULSE"),
    "temperature": ("VS", "TEMP"),
    "temp": ("VS", "TEMP"),
    "weight": ("VS", "WEIGHT"),
    "height": ("VS", "HEIGHT"),
    "bmi": ("VS", "BMI"),
    "position": ("VS", "VSPOS"),
    "lab": ("LB", "LBTEST"),
    "analyte": ("LB", "LBTEST"),
    "test_code": ("LB", "LBTESTCD"),
    "specimen": ("LB", "LBSPEC"),
    "ref_low": ("LB", "LBORNRLO"),
    "ref_high": ("LB", "LBORNRHI"),
    "normal_low": ("LB", "LBORNRLO"),
    "normal_high": ("LB", "LBORNRHI"),
    "fasting": ("LB", "LBFAST"),
    "ecg": ("EG", "EGTESTCD"),
    "qtcf": ("EG", "QTCFAG"),
    "qtc": ("EG", "QTCFAG"),
    "pr_interval": ("EG", "PRAG"),
    "qrs": ("EG", "QRSAG"),
    "rr_interval": ("EG", "RRAG"),
    "interpretation": ("EG", "INTP"),
    "questionnaire": ("QS", "QSCAT"),
    "item": ("QS", "QSTESTCD"),
    "score": ("QS", "QSORRES"),
    "response": ("QS", "QSORRES"),
    "body_system": ("PE", "PETEST"),
    "exam": ("PE", "PETEST"),
    "finding": ("PE", "PEORRES"),
    "medication": ("CM", "CMTRT"),
    "drug": ("CM", "CMTRT"),
    "conmed": ("CM", "CMTRT"),
    "indication": ("CM", "CMINDC"),
    "route": ("CM", "CMROUTE"),
    "frequency": ("CM", "CMDOSFRQ"),
    "dose": ("EX", "EXDOSE"),
    "dose_unit": ("EX", "EXDOSU"),
    "dosing": ("EX", "EXDOSE"),
    "exposure": ("EX", "EXTRT"),
    "lot": ("EX", "EXLOT"),
    "history": ("MH", "MHTERM"),
    "medical_history": ("MH", "MHTERM"),
    "disposition": ("DS", "DSTERM"),
    "discontinuation": ("DS", "DSDECOD"),
    "completion": ("DS", "DSDECOD"),
    "visit": ("SV", "VISIT"),
    "visitnum": ("SV", "VISITNUM"),
    "visit_date": ("SV", "SVSTDTC"),
}


def variables(domain: str) -> list[Var]:
    return DOMAINS[domain.upper()]["variables"]


def variable_names(domain: str) -> list[str]:
    return [v[0] for v in variables(domain)]


def variable_types(domain: str) -> dict[str, str]:
    return {name: vtype for name, _, vtype, _ in variables(domain)}
