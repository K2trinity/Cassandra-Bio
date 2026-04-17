# src/engines/report_engine/disease_survey/renderer.py
"""Pure rendering functions: DiseaseSurveyState → section dicts for DocumentComposer."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

from .aggregator import build_chart_data, group_by_phase, group_by_target
from .models import DiseaseSurveyState


def render_executive_summary(state: DiseaseSurveyState) -> Dict[str, Any]:
    phase_breakdown = group_by_phase(state.trials)
    return {
        "disease_name": state.disease_name,
        "query": state.query,
        "total_assets": len(state.drug_assets),
        "total_trials": len(state.trials),
        "total_sponsors": len(state.sponsors),
        "total_literature": len(state.literature),
        "summary_text": state.summary_text or "",
        "phase_breakdown": phase_breakdown,
        "generated_at": state.generated_at.isoformat(),
    }


def render_drug_pipeline(state: DiseaseSurveyState) -> Dict[str, Any]:
    by_phase: Dict[str, int] = defaultdict(int)
    by_modality: Dict[str, int] = defaultdict(int)

    for asset in state.drug_assets:
        phase = asset.phase or "Unknown"
        by_phase[phase] += 1
        if asset.modality:
            by_modality[asset.modality] += 1

    raw_by_target = group_by_target(state.drug_assets)
    by_target = {k: len(v) for k, v in raw_by_target.items()}

    assets = [
        {
            "asset_name": a.asset_name,
            "aliases": a.aliases,
            "modality": a.modality,
            "targets": a.targets,
            "sponsor": a.sponsor,
            "phase": a.phase,
            "status": a.status,
            "trial_ids": a.trial_ids,
            "indication_subtype": a.indication_subtype,
        }
        for a in state.drug_assets
    ]

    return {
        "assets": assets,
        "by_phase": dict(by_phase),
        "by_target": dict(by_target),
        "by_modality": dict(by_modality),
        "phase_chart": build_chart_data(dict(by_phase), "bar"),
        "target_chart": build_chart_data(dict(by_target), "pie"),
    }


def render_trial_landscape(state: DiseaseSurveyState) -> Dict[str, Any]:
    by_phase: Dict[str, int] = defaultdict(int)
    by_status: Dict[str, int] = defaultdict(int)

    for trial in state.trials:
        by_phase[trial.phase or "Unknown"] += 1
        by_status[trial.status or "Unknown"] += 1

    trials = [
        {
            "nct_id": t.nct_id,
            "title": t.title,
            "asset_name": t.asset_name,
            "sponsor": t.sponsor,
            "phase": t.phase,
            "status": t.status,
            "enrollment": t.enrollment,
            "primary_endpoint": t.primary_endpoint,
        }
        for t in state.trials
    ]

    return {
        "trials": trials,
        "by_phase": dict(by_phase),
        "by_status": dict(by_status),
        "total": len(state.trials),
        "phase_chart": build_chart_data(dict(by_phase), "bar"),
    }


def render_sponsor_analysis(state: DiseaseSurveyState) -> Dict[str, Any]:
    sponsors = [
        {
            "company_name": s.company_name,
            "pipeline_count": s.pipeline_count,
            "lead_phase": s.lead_phase,
            "ticker": s.ticker,
            "market_cap": s.market_cap,
            "cash_runway_months": s.cash_runway_months,
            "rd_ratio": s.rd_ratio,
        }
        for s in state.sponsors
    ]
    return {
        "sponsors": sponsors,
        "total": len(state.sponsors),
    }


def render_target_biology(state: DiseaseSurveyState) -> Dict[str, Any]:
    seen: Dict[str, Dict[str, Any]] = {}
    for asset in state.drug_assets:
        for target in asset.targets:
            if target not in seen:
                seen[target] = {
                    "target_name": target,
                    "asset_count": 0,
                    "asset_names": [],
                }
            seen[target]["asset_count"] += 1
            seen[target]["asset_names"].append(asset.asset_name)

    benchmark_map = {e.target_name: e for e in state.cns_benchmark}
    targets = []
    for name, entry in seen.items():
        bm = benchmark_map.get(name)
        targets.append({
            **entry,
            "publication_count_5yr": bm.publication_count_5yr if bm else 0,
            "trial_count_5yr": bm.trial_count_5yr if bm else 0,
            "trend": bm.trend if bm else "unknown",
        })

    return {
        "targets": targets,
        "total_unique": len(targets),
    }


def render_safety_profile(state: DiseaseSurveyState) -> Dict[str, Any]:
    ae_entries = [
        {
            "nct_id": t.nct_id,
            "title": t.title,
            "asset_name": t.asset_name,
            "ae_grade3plus": t.ae_grade3plus,
            "sae": t.sae,
        }
        for t in state.trials
        if t.ae_grade3plus or t.sae
    ]
    return {
        "ae_entries": ae_entries,
        "trials_with_ae_data": len(ae_entries),
        "total_trials": len(state.trials),
    }


def render_literature_review(state: DiseaseSurveyState) -> Dict[str, Any]:
    by_year: Dict[int, int] = defaultdict(int)
    journal_counts: Dict[str, int] = defaultdict(int)

    for rec in state.literature:
        if rec.year is not None:
            by_year[rec.year] += 1
        if rec.journal:
            journal_counts[rec.journal] += 1

    top_journals = sorted(journal_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    records = [
        {
            "pmid": r.pmid,
            "title": r.title,
            "journal": r.journal,
            "year": r.year,
            "authors": r.authors,
            "doi": r.doi,
        }
        for r in state.literature
    ]

    return {
        "records": records,
        "total": len(state.literature),
        "by_year": dict(by_year),
        "top_journals": [{"journal": j, "count": c} for j, c in top_journals],
        "year_chart": build_chart_data(dict(by_year), "bar"),
    }


def render_cns_benchmark(state: DiseaseSurveyState) -> Dict[str, Any]:
    matched = [e.target_name for e in state.cns_benchmark if e.matched]
    entries = [
        {
            "target_name": e.target_name,
            "publication_count_5yr": e.publication_count_5yr,
            "trial_count_5yr": e.trial_count_5yr,
            "top_journal_citations": e.top_journal_citations,
            "trend": e.trend,
            "matched": e.matched,
        }
        for e in state.cns_benchmark
    ]
    return {
        "entries": entries,
        "matched_targets": matched,
        "total": len(entries),
    }


def render_market_landscape(state: DiseaseSurveyState) -> Dict[str, Any]:
    with_financials = [
        {
            "company_name": s.company_name,
            "ticker": s.ticker,
            "market_cap": s.market_cap,
            "cash_runway_months": s.cash_runway_months,
            "rd_ratio": s.rd_ratio,
            "pipeline_count": s.pipeline_count,
            "lead_phase": s.lead_phase,
        }
        for s in state.sponsors
        if s.ticker or s.market_cap is not None
    ]
    return {
        "sponsors_with_financials": with_financials,
        "total_sponsors": len(state.sponsors),
    }
