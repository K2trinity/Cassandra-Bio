# src/engines/report_engine/disease_survey/aggregator.py
"""Pure-function aggregator: harvest rows → DiseaseSurveyState."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .models import (
    CNSBenchmarkEntry,
    DiseaseSurveyState,
    DrugAsset,
    LiteratureRecord,
    SponsorProfile,
    TrialRecord,
)

TOP_CNS_JOURNALS = {
    "nature neuroscience",
    "lancet neurology",
    "the lancet neurology",
    "new england journal of medicine",
    "nejm",
    "brain",
    "annals of neurology",
    "molecular neurodegeneration",
    "acta neuropathologica",
    "neuron",
    "cell stem cell",
    "nature medicine",
    "jama neurology",
    "alzheimer's & dementia",
    "alzheimers & dementia",
    "alzheimer's research & therapy",
}

KNOWN_CNS_TARGETS: Dict[str, str] = {
    "amyloid": "Aβ",
    "abeta": "Aβ",
    "aβ": "Aβ",
    "a-beta": "Aβ",
    "beta-amyloid": "Aβ",
    "beta amyloid": "Aβ",
    "tau": "Tau",
    "p-tau": "Tau",
    "bace1": "BACE1",
    "bace-1": "BACE1",
    "bace 1": "BACE1",
    "mglur5": "mGluR5",
    "nmda": "NMDA",
    "alpha-synuclein": "α-Synuclein",
    "α-synuclein": "α-Synuclein",
    "a-synuclein": "α-Synuclein",
    "trem2": "TREM2",
    "cd33": "CD33",
    "sv2a": "SV2A",
    "gsk-3": "GSK-3β",
    "gsk3": "GSK-3β",
    "neuroinflammation": "Neuroinflammation",
    "microglial": "Neuroinflammation",
    "microglia": "Neuroinflammation",
}

_PHASE_ORDER = {
    "Phase 4": 5, "Phase 3": 4, "Phase 2/3": 3.5,
    "Phase 2": 3, "Phase 1/2": 2.5, "Phase 1": 2,
    "Preclinical": 1,
}

_PALETTE = [
    "#4A90E2", "#E85D75", "#50C878", "#F5A623", "#9B59B6",
    "#1ABC9C", "#E74C3C", "#3498DB", "#2ECC71", "#F39C12",
    "#8E44AD", "#16A085", "#C0392B", "#2980B9", "#27AE60",
]


def _safe_str(val: Any, max_len: int = 500) -> str:
    text = str(val or "").strip()
    return text[:max_len] if len(text) > max_len else text


def _extract_targets_from_text(text: str) -> List[str]:
    found: List[str] = []
    lower = text.lower()
    for keyword, canonical in KNOWN_CNS_TARGETS.items():
        if keyword in lower and canonical not in found:
            found.append(canonical)
    try:
        from src.tools.biomedical_normalization import extract_normalized_targets
        extra = extract_normalized_targets(text)
        for t in extra:
            if t and t not in found:
                found.append(t)
    except Exception:
        pass
    return found


def _parse_trial_row(row: Dict[str, Any]) -> tuple[Optional[TrialRecord], Optional[DrugAsset]]:
    nct_id = _safe_str(row.get("nct_id"))
    title = _safe_str(row.get("title"))
    if not nct_id or not title:
        return None, None

    meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    intervention = _safe_str(meta.get("intervention", ""))
    sponsor = _safe_str(meta.get("sponsor", ""))
    phase = _safe_str(meta.get("phase", ""))
    status = _safe_str(meta.get("status", ""))

    trial = TrialRecord(
        nct_id=nct_id,
        title=title,
        asset_name=intervention.split(",")[0].strip() if intervention else None,
        sponsor=sponsor or None,
        phase=phase or None,
        status=status or None,
        enrollment=_safe_str(meta.get("enrollment")) or None,
        primary_endpoint=_safe_str(meta.get("primary_endpoint")) or None,
        secondary_endpoint=_safe_str(meta.get("secondary_endpoint")) or None,
        ae_grade3plus=_safe_str(meta.get("ae_grade3plus")) or None,
        sae=_safe_str(meta.get("sae")) or None,
    )

    asset = None
    if intervention:
        asset_name = intervention.split(",")[0].strip()
        if asset_name:
            combined_text = f"{intervention} {title} {row.get('summary', '')}"
            targets = _extract_targets_from_text(combined_text)
            try:
                from src.tools.biomedical_normalization import normalize_drug_class
                modality = normalize_drug_class(intervention)
            except Exception:
                modality = ""
            asset = DrugAsset(
                asset_name=asset_name,
                modality=modality,
                targets=targets,
                sponsor=sponsor,
                phase=phase or None,
                status=status or None,
                trial_ids=[nct_id],
            )
    return trial, asset


def _parse_pubmed_row(row: Dict[str, Any]) -> Optional[LiteratureRecord]:
    pmid = _safe_str(row.get("pmid"))
    title = _safe_str(row.get("title"))
    if not pmid or not title:
        return None
    year_raw = row.get("year") or row.get("publication_year")
    year = int(year_raw) if year_raw and str(year_raw).isdigit() else None
    return LiteratureRecord(
        pmid=pmid,
        title=title,
        journal=_safe_str(row.get("journal")) or None,
        year=year,
        authors=_safe_str(row.get("authors")) or None,
        doi=_safe_str(row.get("doi")) or None,
    )


def _detect_disease_name(query: str, rows: List[Dict[str, Any]]) -> str:
    for keyword, name in [
        ("alzheimer", "Alzheimer's Disease"),
        ("parkinson", "Parkinson's Disease"),
        ("als", "Amyotrophic Lateral Sclerosis"),
        ("huntington", "Huntington's Disease"),
        ("multiple sclerosis", "Multiple Sclerosis"),
    ]:
        if keyword in query.lower():
            return name
    return query


def aggregate_survey_data(rows: List[Dict[str, Any]], query: str) -> DiseaseSurveyState:
    literature: List[LiteratureRecord] = []
    trials: List[TrialRecord] = []
    assets_map: Dict[str, DrugAsset] = {}
    seen_nct: set = set()

    for row in rows:
        source = _safe_str(row.get("source", "")).lower()
        if "pubmed" in source or row.get("pmid"):
            rec = _parse_pubmed_row(row)
            if rec:
                literature.append(rec)
        if "clinicaltrial" in source or row.get("nct_id"):
            trial, asset = _parse_trial_row(row)
            if trial and trial.nct_id not in seen_nct:
                trials.append(trial)
                seen_nct.add(trial.nct_id)
            if asset and asset.asset_name not in assets_map:
                assets_map[asset.asset_name] = asset
            elif asset and asset.asset_name in assets_map:
                existing = assets_map[asset.asset_name]
                for tid in asset.trial_ids:
                    if tid not in existing.trial_ids:
                        existing.trial_ids.append(tid)

    drug_assets = list(assets_map.values())
    sponsors = list(group_by_sponsor(drug_assets).values())
    all_targets = []
    for a in drug_assets:
        for t in a.targets:
            if t not in all_targets:
                all_targets.append(t)
    cns_benchmark = compute_cns_benchmark(literature, all_targets)
    disease_name = _detect_disease_name(query, rows)

    return DiseaseSurveyState(
        disease_name=disease_name,
        query=query,
        drug_assets=drug_assets,
        trials=trials,
        sponsors=sponsors,
        literature=literature,
        cns_benchmark=cns_benchmark,
        generated_at=datetime.now(timezone.utc),
    )


def group_by_target(assets: List[DrugAsset]) -> Dict[str, List[DrugAsset]]:
    groups: Dict[str, List[DrugAsset]] = defaultdict(list)
    for asset in assets:
        for target in asset.targets:
            groups[target].append(asset)
    return dict(groups)


def group_by_phase(trials: List[TrialRecord]) -> Dict[str, int]:
    counts: Dict[str, int] = defaultdict(int)
    for trial in trials:
        phase = trial.phase or "Unknown"
        counts[phase] += 1
    return dict(counts)


def group_by_sponsor(assets: List[DrugAsset]) -> Dict[str, SponsorProfile]:
    sponsor_assets: Dict[str, List[DrugAsset]] = defaultdict(list)
    for asset in assets:
        if asset.sponsor:
            sponsor_assets[asset.sponsor].append(asset)
    result: Dict[str, SponsorProfile] = {}
    for name, asset_list in sponsor_assets.items():
        phases = [a.phase for a in asset_list if a.phase]
        lead = max(phases, key=lambda p: _PHASE_ORDER.get(p, 0)) if phases else None
        result[name] = SponsorProfile(
            company_name=name,
            pipeline_count=len(asset_list),
            lead_phase=lead,
        )
    return result


def compute_publication_trend(
    literature: List[LiteratureRecord], window: int = 5
) -> Dict[int, int]:
    counts: Dict[int, int] = defaultdict(int)
    for rec in literature:
        if rec.year is not None:
            counts[rec.year] += 1
    return dict(counts)


def compute_cns_benchmark(
    literature: List[LiteratureRecord], targets: List[str]
) -> List[CNSBenchmarkEntry]:
    current_year = datetime.now(timezone.utc).year
    cutoff = current_year - 5

    target_pubs: Dict[str, int] = defaultdict(int)
    target_top_journal: Dict[str, int] = defaultdict(int)

    for rec in literature:
        if rec.year is not None and rec.year < cutoff:
            continue
        title_lower = rec.title.lower()
        journal_lower = (rec.journal or "").lower()
        is_top = journal_lower in TOP_CNS_JOURNALS

        for keyword, canonical in KNOWN_CNS_TARGETS.items():
            if keyword in title_lower:
                target_pubs[canonical] += 1
                if is_top:
                    target_top_journal[canonical] += 1

    entries: List[CNSBenchmarkEntry] = []
    all_targets_set = set(targets) | set(target_pubs.keys())
    for t in all_targets_set:
        pub_count = target_pubs.get(t, 0)
        top_count = target_top_journal.get(t, 0)
        if pub_count >= 10:
            trend = "rising"
        elif pub_count >= 3:
            trend = "stable"
        elif pub_count > 0:
            trend = "declining"
        else:
            trend = "stable"
        entries.append(CNSBenchmarkEntry(
            target_name=t,
            publication_count_5yr=pub_count,
            trial_count_5yr=0,
            top_journal_citations=top_count,
            trend=trend,
            matched=(t in targets),
        ))
    return entries


def build_chart_data(group_data: Dict, chart_type: str) -> Dict[str, Any]:
    labels = list(group_data.keys())
    values = []
    for v in group_data.values():
        if isinstance(v, list):
            values.append(len(v))
        elif isinstance(v, (int, float)):
            values.append(v)
        else:
            values.append(1)

    colors = [_PALETTE[i % len(_PALETTE)] for i in range(len(labels))]

    dataset: Dict[str, Any] = {"data": values}
    if chart_type in ("pie", "doughnut", "polarArea"):
        dataset["backgroundColor"] = colors
    else:
        dataset["backgroundColor"] = colors
        dataset["borderColor"] = colors
        dataset["label"] = "Count"

    return {"labels": labels, "datasets": [dataset]}
