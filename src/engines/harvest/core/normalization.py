"""Harvest-scoped biomedical normalization helpers."""

from __future__ import annotations

import re
from typing import Any, Dict, List


_PLACEHOLDER_VALUES = {
    "",
    "n/a",
    "na",
    "none",
    "unknown",
    "unspecified",
    "insufficient data",
    "not specified",
    "not available",
}


def _flat_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(_flat_text(v) for v in value)
    if isinstance(value, dict):
        return " ".join(_flat_text(v) for v in value.values())
    return str(value)


def _simple_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


_DRUG_CLASS_RULES = [
    (re.compile(r"\b(antibody\s*(?:-\s*)?drug\s*conjugate|adc)\b", re.I), "ADC"),
    (re.compile(r"\b(bispecific|bi\s*-?specific|bsab)\b", re.I), "Bispecific Antibody"),
    (re.compile(r"\b(car\s*-?t|car\s*-?nk|tcr\s*-?t|til\b|cell\s+therapy|nk\s+cell)\b", re.I), "Cell Therapy"),
    (re.compile(r"\b(gene\s+therapy|gene\s+editing|crispr|aav|lentiviral)\b", re.I), "Gene Therapy"),
    (re.compile(r"\b(mrna|sirna|mirna|antisense|oligonucleotide|rna\s+therapy)\b", re.I), "RNA Therapy"),
    (re.compile(r"\b(vaccine|neoantigen\s+vaccine)\b", re.I), "Vaccine"),
    (re.compile(r"\b(oncolytic|oncolytic\s+virus|viral\s+therapy)\b", re.I), "Oncolytic Therapy"),
    (re.compile(r"\b(radioligand|lutetium|actinium|radioisotope)\b", re.I), "Radioligand Therapy"),
    (re.compile(r"\b(checkpoint|pd\s*-?1|pd\s*-?l1|ctla\s*-?4|lag\s*-?3|tim\s*-?3)\b", re.I), "Immune Checkpoint Therapy"),
    (re.compile(r"\b(monoclonal|mab\b|antibody)\b", re.I), "Monoclonal Antibody"),
    (re.compile(r"\b(small\s*molecule|kinase\s+inhibitor|\w+nib\b|\w+ib\b)\b", re.I), "Small Molecule"),
]


_DRUG_CLASS_ALIASES: Dict[str, str] = {
    "adc": "ADC",
    "antibodydrugconjugate": "ADC",
    "bispecificantibody": "Bispecific Antibody",
    "monoclonalantibody": "Monoclonal Antibody",
    "immunecheckpointtherapy": "Immune Checkpoint Therapy",
    "celltherapy": "Cell Therapy",
    "genetherapy": "Gene Therapy",
    "rnatherapy": "RNA Therapy",
    "smallmolecule": "Small Molecule",
    "vaccine": "Vaccine",
    "oncolytictherapy": "Oncolytic Therapy",
    "radioligandtherapy": "Radioligand Therapy",
}


def normalize_drug_class(raw_text: Any, explicit_label: Any = None) -> str:
    """Normalize modality/class labels into stable buckets."""
    merged_text = " ".join([_flat_text(explicit_label), _flat_text(raw_text)]).strip()
    if not merged_text:
        return "Unspecified"

    explicit_key = _simple_key(_flat_text(explicit_label))
    if explicit_key in _DRUG_CLASS_ALIASES:
        explicit_class = _DRUG_CLASS_ALIASES[explicit_key]
    else:
        explicit_class = ""

    for pattern, label in _DRUG_CLASS_RULES:
        if pattern.search(merged_text):
            return label

    if explicit_class:
        return explicit_class

    return "Unspecified"


_TARGET_ALIASES: Dict[str, str] = {
    "pd1": "PD-1",
    "cd279": "PD-1",
    "programmedcelldeathprotein1": "PD-1",
    "programmeddeath1": "PD-1",
    "pdl1": "PD-L1",
    "cd274": "PD-L1",
    "programmeddeathligand1": "PD-L1",
    "bh1": "PD-L1",
    "ctla4": "CTLA-4",
    "cd152": "CTLA-4",
    "lag3": "LAG-3",
    "tim3": "TIM-3",
    "her2": "HER2",
    "erbb2": "HER2",
    "neu": "HER2",
    "egfr": "EGFR",
    "erbb1": "EGFR",
    "vegf": "VEGF",
    "vegfa": "VEGF",
    "braf": "BRAF",
    "kras": "KRAS",
    "alk": "ALK",
    "ros1": "ROS1",
    "met": "MET",
    "fgfr2": "FGFR2",
    "fgfr3": "FGFR3",
    "parp": "PARP",
    "parp1": "PARP",
    "cd19": "CD19",
    "cd20": "CD20",
    "trop2": "TROP2",
    "mesothelin": "MESOTHELIN",
    "msln": "MESOTHELIN",
}


_TARGET_HINT_PATTERNS = [
    (re.compile(r"\bpd\s*-?1\b|programmed\s+cell\s+death\s+protein\s*1", re.I), "PD-1"),
    (re.compile(r"\bpd\s*-?l1\b|programmed\s+death\s+ligand\s*1|\bcd274\b", re.I), "PD-L1"),
    (re.compile(r"\bctla\s*-?4\b|\bcd152\b", re.I), "CTLA-4"),
    (re.compile(r"\berbb2\b|\bher2\b|\bneu\b", re.I), "HER2"),
    (re.compile(r"\begfr\b|epidermal\s+growth\s+factor\s+receptor", re.I), "EGFR"),
    (re.compile(r"\bvegf[a]?\b", re.I), "VEGF"),
]


def normalize_target_term(term: Any) -> str:
    """Normalize a target mention into canonical biomedical symbols."""
    raw = _flat_text(term).strip()
    if not raw:
        return ""

    if raw.lower() in _PLACEHOLDER_VALUES:
        return ""

    key = _simple_key(raw)
    for suffix in ["axis", "pathway", "signaling", "signalling", "receptor", "target"]:
        if key.endswith(suffix):
            key = key[: -len(suffix)]

    if key in _TARGET_ALIASES:
        return _TARGET_ALIASES[key]

    for pattern, label in _TARGET_HINT_PATTERNS:
        if pattern.search(raw):
            return label

    compact = re.sub(r"[^A-Za-z0-9\-]", "", raw).upper()
    if compact.endswith(("MAB", "NIB", "IB")):
        return ""
    if 2 <= len(compact) <= 10 and re.match(r"^[A-Z0-9\-]+$", compact):
        return compact

    try:
        from src.tools.scispacy_ner_service import SciSpacyNERService

        ner_result = SciSpacyNERService.get_instance().normalize_entity(raw, "TARGET")
        if ner_result:
            return ner_result
    except Exception:
        pass

    return ""


def extract_normalized_targets(raw_value: Any) -> List[str]:
    """Extract and normalize zero or more target terms from mixed raw values."""
    merged = _flat_text(raw_value)
    if not merged:
        return []

    candidates: List[str] = []

    split_parts = re.split(r"[,;|]|\band\b|\bwith\b|\bplus\b|/", merged, flags=re.I)
    for part in split_parts:
        token = part.strip(" .:-_()[]{}")
        if token:
            candidates.append(token)

    for pattern, _ in _TARGET_HINT_PATTERNS:
        for match in pattern.finditer(merged):
            candidates.append(match.group(0))

    normalized: List[str] = []
    seen = set()
    for token in candidates:
        canonical = normalize_target_term(token)
        if canonical and canonical not in seen:
            seen.add(canonical)
            normalized.append(canonical)
    return normalized
