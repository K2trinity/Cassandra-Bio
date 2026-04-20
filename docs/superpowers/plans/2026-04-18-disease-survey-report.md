# Disease Survey Report 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增疾病综合调研报告模块，将 harvest 数据聚合为多维度结构化表格 + 全量图表的 IR 文档，替代当前 raw JSON 平铺展示。

**Architecture:** 新建 `src/engines/report_engine/disease_survey/` 包（4 个文件：models/aggregator/renderer/__init__），aggregator 将 harvest rows 聚合为 Pydantic 模型，renderer 将模型转为 IR chapter dicts，由现有 DocumentComposer 装订成完整 IR 文档。在 ReportWriterAgent.write_report() 中增加路由判断，符合条件时走新管线。

**Tech Stack:** Python 3.11, Pydantic v2, 现有 IR schema (kpiGrid/widget/table/callout/paragraph blocks), chart_to_svg (Chart.js 格式)

---

## 文件变更清单

| 操作 | 文件路径 | 职责 |
|------|----------|------|
| 新建 | `src/engines/report_engine/disease_survey/__init__.py` | 导出 `generate_disease_survey_report()` |
| 新建 | `src/engines/report_engine/disease_survey/models.py` | DiseaseSurveyState + 全部数据模型 |
| 新建 | `src/engines/report_engine/disease_survey/aggregator.py` | harvest rows → DiseaseSurveyState 聚合 |
| 新建 | `src/engines/report_engine/disease_survey/renderer.py` | DiseaseSurveyState → IR chapter dicts |
| 新建 | `tests/test_disease_survey_models.py` | models 单测 |
| 新建 | `tests/test_disease_survey_aggregator.py` | aggregator 单测 |
| 新建 | `tests/test_disease_survey_renderer.py` | renderer 单测 |
| 新建 | `tests/test_disease_survey_integration.py` | 端到端集成测试 |
| 修改 | `src/agents/report_writer.py:186-192` | 路由判断 + 新管线调用 |

---

## Task 1: 数据模型 (models.py)

**Files:**
- Create: `src/engines/report_engine/disease_survey/models.py`
- Create: `tests/test_disease_survey_models.py`

- [ ] **Step 1: 编写 models 测试**

```python
# tests/test_disease_survey_models.py
"""Tests for disease survey data models."""
from datetime import datetime

import pytest
from pydantic import ValidationError

from src.engines.report_engine.disease_survey.models import (
    CNSBenchmarkEntry,
    DiseaseSurveyState,
    DrugAsset,
    LiteratureRecord,
    SponsorProfile,
    TrialRecord,
)


def test_drug_asset_minimal():
    asset = DrugAsset(asset_name="Lecanemab", sponsor="Eisai")
    assert asset.asset_name == "Lecanemab"
    assert asset.targets == []
    assert asset.phase is None


def test_drug_asset_full():
    asset = DrugAsset(
        asset_name="Lecanemab",
        aliases=["BAN2401"],
        modality="Monoclonal Antibody",
        targets=["Aβ"],
        sponsor="Eisai",
        phase="Phase 3",
        status="Approved",
        trial_ids=["NCT01767311"],
        indication_subtype="Early AD",
    )
    assert asset.aliases == ["BAN2401"]
    assert "Aβ" in asset.targets


def test_trial_record_minimal():
    trial = TrialRecord(nct_id="NCT01767311", title="Clarity AD")
    assert trial.nct_id == "NCT01767311"
    assert trial.enrollment is None


def test_sponsor_profile_with_financials():
    sp = SponsorProfile(
        company_name="Eisai",
        pipeline_count=3,
        lead_phase="Phase 3",
        ticker="ESALY",
        market_cap=30e9,
    )
    assert sp.pipeline_count == 3
    assert sp.ticker == "ESALY"


def test_cns_benchmark_entry():
    entry = CNSBenchmarkEntry(
        target_name="Aβ",
        publication_count_5yr=120,
        trial_count_5yr=45,
        top_journal_citations=30,
        trend="rising",
        matched=True,
    )
    assert entry.matched is True
    assert entry.trend == "rising"


def test_literature_record():
    rec = LiteratureRecord(pmid="12345678", title="Amyloid cascade hypothesis revisited")
    assert rec.journal is None
    assert rec.year is None


def test_disease_survey_state_minimal():
    state = DiseaseSurveyState(disease_name="Alzheimer's Disease", query="AD drug pipeline")
    assert state.drug_assets == []
    assert state.trials == []
    assert state.sponsors == []
    assert state.literature == []
    assert state.cns_benchmark == []
    assert state.summary_text is None
    assert isinstance(state.generated_at, datetime)


def test_disease_survey_state_rejects_bad_type():
    with pytest.raises(ValidationError):
        DiseaseSurveyState(disease_name=123, query="test")
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
"C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe" -m pytest tests/test_disease_survey_models.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'src.engines.report_engine.disease_survey'`

- [ ] **Step 3: 创建 models.py**

```python
# src/engines/report_engine/disease_survey/models.py
"""Pydantic models for the disease survey report module."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class DrugAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_name: str = Field(..., min_length=1)
    aliases: List[str] = Field(default_factory=list)
    modality: str = ""
    targets: List[str] = Field(default_factory=list)
    sponsor: str = ""
    phase: Optional[str] = None
    status: Optional[str] = None
    trial_ids: List[str] = Field(default_factory=list)
    indication_subtype: Optional[str] = None


class TrialRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nct_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    asset_name: Optional[str] = None
    sponsor: Optional[str] = None
    phase: Optional[str] = None
    status: Optional[str] = None
    enrollment: Optional[str] = None
    primary_endpoint: Optional[str] = None
    secondary_endpoint: Optional[str] = None
    ae_grade3plus: Optional[str] = None
    sae: Optional[str] = None


class SponsorProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_name: str = Field(..., min_length=1)
    pipeline_count: int = 0
    lead_phase: Optional[str] = None
    ticker: Optional[str] = None
    market_cap: Optional[float] = None
    cash_runway_months: Optional[float] = None
    rd_ratio: Optional[float] = None


class CNSBenchmarkEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_name: str = Field(..., min_length=1)
    publication_count_5yr: int = 0
    trial_count_5yr: int = 0
    top_journal_citations: int = 0
    trend: str = "stable"
    matched: bool = False


class LiteratureRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pmid: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    journal: Optional[str] = None
    year: Optional[int] = None
    authors: Optional[str] = None
    doi: Optional[str] = None
    relevance_tag: Optional[str] = None


class DiseaseSurveyState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disease_name: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)
    drug_assets: List[DrugAsset] = Field(default_factory=list)
    trials: List[TrialRecord] = Field(default_factory=list)
    sponsors: List[SponsorProfile] = Field(default_factory=list)
    literature: List[LiteratureRecord] = Field(default_factory=list)
    cns_benchmark: List[CNSBenchmarkEntry] = Field(default_factory=list)
    summary_text: Optional[str] = None
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: 创建空 __init__.py 使包可导入**

```python
# src/engines/report_engine/disease_survey/__init__.py
"""Disease survey report module."""
```

- [ ] **Step 5: 运行测试确认通过**

Run:
```bash
"C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe" -m pytest tests/test_disease_survey_models.py -v
```
Expected: 8 tests PASSED

- [ ] **Step 6: Commit**

```bash
git add src/engines/report_engine/disease_survey/__init__.py src/engines/report_engine/disease_survey/models.py tests/test_disease_survey_models.py
git commit -m "feat(disease-survey): add Pydantic data models"
```

---

## Task 2: 聚合器 (aggregator.py)

**Files:**
- Create: `src/engines/report_engine/disease_survey/aggregator.py`
- Create: `tests/test_disease_survey_aggregator.py`

- [ ] **Step 1: 编写 aggregator 测试**

```python
# tests/test_disease_survey_aggregator.py
"""Tests for disease survey aggregator functions."""
import pytest

from src.engines.report_engine.disease_survey.aggregator import (
    aggregate_survey_data,
    build_chart_data,
    compute_cns_benchmark,
    compute_publication_trend,
    group_by_phase,
    group_by_sponsor,
    group_by_target,
)
from src.engines.report_engine.disease_survey.models import (
    DiseaseSurveyState,
    DrugAsset,
    LiteratureRecord,
    TrialRecord,
)


# ── Fixtures ──────────────────────────────────────────────────────────

SAMPLE_PUBMED_ROW = {
    "source": "PubMed",
    "pmid": "38001234",
    "title": "BACE1 inhibitor trial results in early Alzheimer's",
    "summary": "A Phase 2 trial of verubecestat targeting BACE1 showed no efficacy.",
    "journal": "NEJM",
    "year": 2023,
    "authors": "Smith J et al.",
    "doi": "10.1000/test",
}

SAMPLE_TRIAL_ROW = {
    "source": "ClinicalTrials",
    "nct_id": "NCT05310071",
    "title": "Lecanemab Phase 3 Extension Study",
    "summary": "Open-label extension of Clarity AD evaluating long-term safety.",
    "metadata": {
        "intervention": "Lecanemab (BAN2401), anti-Aβ monoclonal antibody",
        "sponsor": "Eisai",
        "phase": "Phase 3",
        "status": "Recruiting",
        "enrollment": "1500",
        "primary_endpoint": "CDR-SB change from baseline",
        "ae_grade3plus": "ARIA-E 12.6%",
    },
}

SAMPLE_TRIAL_ROW_2 = {
    "source": "ClinicalTrials",
    "nct_id": "NCT04468659",
    "title": "Donanemab TRAILBLAZER-ALZ 2",
    "summary": "Phase 3 trial of donanemab targeting N3pG-Aβ in early AD.",
    "metadata": {
        "intervention": "Donanemab, anti-Aβ monoclonal antibody",
        "sponsor": "Eli Lilly",
        "phase": "Phase 3",
        "status": "Completed",
        "enrollment": "1736",
        "primary_endpoint": "iADRS change",
    },
}


# ── aggregate_survey_data ─────────────────────────────────────────────

def test_aggregate_empty_rows():
    state = aggregate_survey_data([], "AD pipeline")
    assert isinstance(state, DiseaseSurveyState)
    assert state.disease_name == "AD pipeline"
    assert state.drug_assets == []
    assert state.trials == []
    assert state.literature == []


def test_aggregate_pubmed_row():
    state = aggregate_survey_data([SAMPLE_PUBMED_ROW], "AD pipeline")
    assert len(state.literature) == 1
    assert state.literature[0].pmid == "38001234"
    assert state.literature[0].journal == "NEJM"


def test_aggregate_trial_row():
    state = aggregate_survey_data([SAMPLE_TRIAL_ROW], "AD pipeline")
    assert len(state.trials) == 1
    assert state.trials[0].nct_id == "NCT05310071"
    assert state.trials[0].sponsor == "Eisai"
    assert len(state.drug_assets) >= 1
    assert len(state.sponsors) >= 1


def test_aggregate_mixed_rows():
    rows = [SAMPLE_PUBMED_ROW, SAMPLE_TRIAL_ROW, SAMPLE_TRIAL_ROW_2]
    state = aggregate_survey_data(rows, "AD drug pipeline survey")
    assert len(state.literature) == 1
    assert len(state.trials) == 2
    assert len(state.drug_assets) >= 2
    assert len(state.sponsors) >= 2
    assert state.query == "AD drug pipeline survey"


def test_aggregate_deduplicates_sponsors():
    row_a = {**SAMPLE_TRIAL_ROW}
    row_b = {**SAMPLE_TRIAL_ROW, "nct_id": "NCT99999999", "title": "Another Eisai trial"}
    row_b["metadata"] = {**SAMPLE_TRIAL_ROW["metadata"]}
    state = aggregate_survey_data([row_a, row_b], "test")
    eisai_sponsors = [s for s in state.sponsors if s.company_name == "Eisai"]
    assert len(eisai_sponsors) == 1
    assert eisai_sponsors[0].pipeline_count >= 1


# ── group_by helpers ──────────────────────────────────────────────────

def test_group_by_target():
    assets = [
        DrugAsset(asset_name="A", targets=["Aβ", "Tau"], sponsor="X"),
        DrugAsset(asset_name="B", targets=["Aβ"], sponsor="Y"),
        DrugAsset(asset_name="C", targets=["TREM2"], sponsor="Z"),
    ]
    groups = group_by_target(assets)
    assert len(groups["Aβ"]) == 2
    assert len(groups["Tau"]) == 1
    assert len(groups["TREM2"]) == 1


def test_group_by_phase():
    trials = [
        TrialRecord(nct_id="A", title="T1", phase="Phase 1"),
        TrialRecord(nct_id="B", title="T2", phase="Phase 3"),
        TrialRecord(nct_id="C", title="T3", phase="Phase 3"),
        TrialRecord(nct_id="D", title="T4", phase=None),
    ]
    groups = group_by_phase(trials)
    assert groups["Phase 1"] == 1
    assert groups["Phase 3"] == 2
    assert groups["Unknown"] == 1


def test_group_by_sponsor():
    assets = [
        DrugAsset(asset_name="A", sponsor="Eisai"),
        DrugAsset(asset_name="B", sponsor="Eisai"),
        DrugAsset(asset_name="C", sponsor="Lilly"),
    ]
    sponsors = group_by_sponsor(assets)
    assert sponsors["Eisai"].pipeline_count == 2
    assert sponsors["Lilly"].pipeline_count == 1


# ── compute helpers ───────────────────────────────────────────────────

def test_compute_publication_trend():
    lit = [
        LiteratureRecord(pmid="1", title="A", year=2022),
        LiteratureRecord(pmid="2", title="B", year=2022),
        LiteratureRecord(pmid="3", title="C", year=2024),
        LiteratureRecord(pmid="4", title="D", year=None),
    ]
    trend = compute_publication_trend(lit, window=5)
    assert trend[2022] == 2
    assert trend[2024] == 1
    assert None not in trend


def test_compute_cns_benchmark():
    lit = [
        LiteratureRecord(pmid="1", title="Aβ clearance study", journal="Nature Neuroscience", year=2023),
        LiteratureRecord(pmid="2", title="Tau PET imaging", journal="Lancet Neurology", year=2022),
        LiteratureRecord(pmid="3", title="Random paper", journal="Some Journal", year=2023),
    ]
    targets = ["Aβ", "Tau", "TREM2"]
    benchmark = compute_cns_benchmark(lit, targets)
    assert len(benchmark) == 3
    ab_entry = next(e for e in benchmark if e.target_name == "Aβ")
    assert ab_entry.top_journal_citations >= 1
    assert ab_entry.matched is True
    trem2_entry = next(e for e in benchmark if e.target_name == "TREM2")
    assert trem2_entry.top_journal_citations == 0


# ── build_chart_data ──────────────────────────────────────────────────

def test_build_chart_data_pie():
    group = {"Aβ": 5, "Tau": 3, "TREM2": 1}
    chart = build_chart_data(group, "pie")
    assert "labels" in chart
    assert "datasets" in chart
    assert len(chart["labels"]) == 3
    assert chart["datasets"][0]["data"] == [5, 3, 1]


def test_build_chart_data_bar():
    group = {"Phase 1": 2, "Phase 2": 5, "Phase 3": 3}
    chart = build_chart_data(group, "bar")
    assert chart["labels"] == ["Phase 1", "Phase 2", "Phase 3"]
    assert len(chart["datasets"]) == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
"C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe" -m pytest tests/test_disease_survey_aggregator.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'src.engines.report_engine.disease_survey.aggregator'`

- [ ] **Step 3: 编写 aggregator.py**

```python
# src/engines/report_engine/disease_survey/aggregator.py
"""Pure-function aggregator: harvest rows → DiseaseSurveyState."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
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

# Chart.js 调色板
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
        generated_at=datetime.utcnow(),
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
    current_year = datetime.utcnow().year
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
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```bash
"C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe" -m pytest tests/test_disease_survey_aggregator.py -v
```
Expected: 全部 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/engines/report_engine/disease_survey/aggregator.py tests/test_disease_survey_aggregator.py
git commit -m "feat(disease-survey): add harvest aggregator with grouping and CNS benchmark"
```

---

## Task 3: 渲染器 (renderer.py)

**Files:**
- Create: `src/engines/report_engine/disease_survey/renderer.py`
- Create: `tests/test_disease_survey_renderer.py`

- [ ] **Step 1: 编写 renderer 测试**

```python
# tests/test_disease_survey_renderer.py
"""Tests for disease survey IR renderer."""
from datetime import datetime

import pytest

from src.engines.report_engine.disease_survey.models import (
    CNSBenchmarkEntry,
    DiseaseSurveyState,
    DrugAsset,
    LiteratureRecord,
    SponsorProfile,
    TrialRecord,
)
from src.engines.report_engine.disease_survey.renderer import render_to_ir_chapters


def _make_state(**overrides) -> DiseaseSurveyState:
    defaults = dict(
        disease_name="Alzheimer's Disease",
        query="AD drug pipeline",
        drug_assets=[
            DrugAsset(asset_name="Lecanemab", targets=["Aβ"], sponsor="Eisai", modality="Monoclonal Antibody", phase="Phase 3"),
            DrugAsset(asset_name="Donanemab", targets=["Aβ"], sponsor="Lilly", modality="Monoclonal Antibody", phase="Phase 3"),
            DrugAsset(asset_name="BACE-inhibitor-X", targets=["BACE1"], sponsor="Merck", modality="Small Molecule", phase="Phase 2"),
        ],
        trials=[
            TrialRecord(nct_id="NCT05310071", title="Clarity AD Extension", sponsor="Eisai", phase="Phase 3", status="Recruiting", enrollment="1500", primary_endpoint="CDR-SB"),
            TrialRecord(nct_id="NCT04468659", title="TRAILBLAZER-ALZ 2", sponsor="Lilly", phase="Phase 3", status="Completed", enrollment="1736", primary_endpoint="iADRS"),
        ],
        literature=[
            LiteratureRecord(pmid="1", title="Aβ clearance", journal="NEJM", year=2023),
            LiteratureRecord(pmid="2", title="Tau imaging", journal="Lancet Neurology", year=2022),
        ],
        sponsors=[
            SponsorProfile(company_name="Eisai", pipeline_count=1, lead_phase="Phase 3"),
            SponsorProfile(company_name="Lilly", pipeline_count=1, lead_phase="Phase 3"),
            SponsorProfile(company_name="Merck", pipeline_count=1, lead_phase="Phase 2"),
        ],
        cns_benchmark=[
            CNSBenchmarkEntry(target_name="Aβ", publication_count_5yr=50, trial_count_5yr=20, top_journal_citations=15, trend="rising", matched=True),
            CNSBenchmarkEntry(target_name="BACE1", publication_count_5yr=10, trial_count_5yr=3, top_journal_citations=2, trend="declining", matched=True),
        ],
        generated_at=datetime(2026, 4, 18),
    )
    defaults.update(overrides)
    return DiseaseSurveyState(**defaults)


def test_render_returns_9_chapters():
    state = _make_state()
    chapters = render_to_ir_chapters(state)
    assert len(chapters) == 9
    for ch in chapters:
        assert "order" in ch
        assert "title" in ch
        assert "blocks" in ch
        assert isinstance(ch["blocks"], list)
        assert len(ch["blocks"]) > 0


def test_chapter_0_executive_summary():
    state = _make_state()
    chapters = render_to_ir_chapters(state)
    ch0 = chapters[0]
    assert ch0["order"] == 0
    block_types = [b["type"] for b in ch0["blocks"]]
    assert "heading" in block_types
    assert "kpiGrid" in block_types


def test_chapter_2_drug_assets_has_charts():
    state = _make_state()
    chapters = render_to_ir_chapters(state)
    ch2 = chapters[2]
    block_types = [b["type"] for b in ch2["blocks"]]
    assert "table" in block_types
    assert "widget" in block_types
    widgets = [b for b in ch2["blocks"] if b["type"] == "widget"]
    widget_types = {w["widgetType"] for w in widgets}
    assert "chart.js/pie" in widget_types


def test_chapter_3_clinical_matrix_has_charts():
    state = _make_state()
    chapters = render_to_ir_chapters(state)
    ch3 = chapters[3]
    block_types = [b["type"] for b in ch3["blocks"]]
    assert "table" in block_types
    assert "widget" in block_types


def test_chapter_5_cns_benchmark_has_radar():
    state = _make_state()
    chapters = render_to_ir_chapters(state)
    ch5 = chapters[5]
    widgets = [b for b in ch5["blocks"] if b["type"] == "widget"]
    assert any(w["widgetType"] == "chart.js/radar" for w in widgets)


def test_empty_data_produces_callout():
    state = _make_state(drug_assets=[], trials=[], literature=[], sponsors=[], cns_benchmark=[])
    chapters = render_to_ir_chapters(state)
    ch2 = chapters[2]
    callouts = [b for b in ch2["blocks"] if b["type"] == "callout"]
    assert len(callouts) >= 1
    assert callouts[0]["tone"] == "info"


def test_widget_block_format():
    state = _make_state()
    chapters = render_to_ir_chapters(state)
    for ch in chapters:
        for block in ch["blocks"]:
            if block["type"] == "widget":
                assert "widgetId" in block
                assert "widgetType" in block
                assert block["widgetType"].startswith("chart.js/")
                assert "data" in block
                assert "labels" in block["data"]
                assert "datasets" in block["data"]
                assert "props" in block
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
"C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe" -m pytest tests/test_disease_survey_renderer.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'src.engines.report_engine.disease_survey.renderer'`

- [ ] **Step 3: 编写 renderer.py — 辅助函数和前4章**

```python
# src/engines/report_engine/disease_survey/renderer.py
"""Render DiseaseSurveyState → IR chapter dicts for DocumentComposer."""
from __future__ import annotations

from typing import Any, Dict, List

from .aggregator import (
    build_chart_data,
    compute_publication_trend,
    group_by_phase,
    group_by_target,
)
from .models import DiseaseSurveyState

_PALETTE = [
    "#4A90E2", "#E85D75", "#50C878", "#F5A623", "#9B59B6",
    "#1ABC9C", "#E74C3C", "#3498DB", "#2ECC71", "#F39C12",
]


def _heading(level: int, text: str, anchor: str = "") -> Dict[str, Any]:
    return {"type": "heading", "level": level, "text": text, "anchor": anchor or text.lower().replace(" ", "-")}


def _paragraph(text: str) -> Dict[str, Any]:
    return {"type": "paragraph", "inlines": [{"text": text}]}


def _callout(tone: str, title: str, text: str) -> Dict[str, Any]:
    return {
        "type": "callout",
        "tone": tone,
        "title": title,
        "blocks": [_paragraph(text)],
    }


def _empty_callout(section_name: str) -> Dict[str, Any]:
    return _callout("info", section_name, "当前 harvest 数据中未检测到相关记录。")


def _kpi_grid(items: List[Dict[str, str]], cols: int = 4) -> Dict[str, Any]:
    return {"type": "kpiGrid", "items": items, "cols": cols}


def _table(headers: List[str], rows: List[List[str]]) -> Dict[str, Any]:
    header_cells = [{"type": "paragraph", "inlines": [{"text": h}]} for h in headers]
    body = []
    for row in rows:
        body.append([{"type": "paragraph", "inlines": [{"text": str(c)}]} for c in row])
    return {"type": "table", "rows": [header_cells] + body}


def _widget(widget_id: str, chart_type: str, title: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "widget",
        "widgetId": widget_id,
        "widgetType": f"chart.js/{chart_type}",
        "data": data,
        "props": {"title": title, "type": chart_type},
    }


def render_to_ir_chapters(state: DiseaseSurveyState) -> List[Dict[str, Any]]:
    return [
        _render_executive_summary(state),
        _render_disease_landscape(state),
        _render_drug_assets(state),
        _render_clinical_matrix(state),
        _render_literature(state),
        _render_cns_benchmark(state),
        _render_competitive(state),
        _render_sponsors(state),
        _render_references(state),
    ]


def _render_executive_summary(state: DiseaseSurveyState) -> Dict[str, Any]:
    all_targets = set()
    for a in state.drug_assets:
        all_targets.update(a.targets)

    kpi_items = [
        {"label": "Harvest 记录总数", "value": str(len(state.trials) + len(state.literature))},
        {"label": "覆盖靶点数", "value": str(len(all_targets))},
        {"label": "临床试验数", "value": str(len(state.trials))},
        {"label": "主流药物数", "value": str(len(state.drug_assets))},
    ]

    blocks: List[Dict[str, Any]] = [
        _heading(2, "Executive Summary", "executive-summary"),
        _kpi_grid(kpi_items),
    ]

    if state.summary_text:
        blocks.append(_paragraph(state.summary_text))
    else:
        parts = []
        parts.append(f"本报告基于 {len(state.trials) + len(state.literature)} 条 harvest 记录，")
        parts.append(f"覆盖 {len(state.drug_assets)} 个药物资产和 {len(all_targets)} 个靶点。")
        if state.trials:
            phases = group_by_phase(state.trials)
            top_phase = max(phases.items(), key=lambda x: x[1])[0] if phases else "N/A"
            parts.append(f"临床试验以 {top_phase} 为主（{phases.get(top_phase, 0)} 项）。")
        blocks.append(_paragraph("".join(parts)))

    return {"order": 0, "title": "Executive Summary", "chapterId": "S0", "blocks": blocks}


def _render_disease_landscape(state: DiseaseSurveyState) -> Dict[str, Any]:
    blocks: List[Dict[str, Any]] = [
        _heading(2, "疾病图谱", "disease-landscape"),
        _paragraph(f"目标疾病：{state.disease_name}。原始查询：「{state.query}」。"),
    ]
    if not state.drug_assets and not state.trials:
        blocks.append(_callout("info", "数据不足", "当前 harvest 数据量较少，疾病图谱信息有限。"))
    else:
        blocks.append(_callout("info", "未满足需求",
            f"当前 {state.disease_name} 领域共检索到 {len(state.drug_assets)} 个在研药物，"
            f"{len(state.trials)} 项临床试验。靶点多样性和管线密度反映了该领域的活跃程度。"))
    return {"order": 1, "title": "疾病图谱", "chapterId": "S1", "blocks": blocks}


def _render_drug_assets(state: DiseaseSurveyState) -> Dict[str, Any]:
    blocks: List[Dict[str, Any]] = [_heading(2, "药物资产全景", "drug-assets")]

    if not state.drug_assets:
        blocks.append(_empty_callout("药物资产全景"))
        return {"order": 2, "title": "药物资产全景", "chapterId": "S2", "blocks": blocks}

    headers = ["药物名称", "模态", "靶点", "Sponsor", "Phase", "状态"]
    rows = []
    for a in state.drug_assets:
        rows.append([
            a.asset_name,
            a.modality or "—",
            ", ".join(a.targets) if a.targets else "—",
            a.sponsor or "—",
            a.phase or "—",
            a.status or "—",
        ])
    blocks.append(_table(headers, rows))

    target_groups = group_by_target(state.drug_assets)
    target_counts = {k: len(v) for k, v in target_groups.items()}
    if target_counts:
        chart_data = build_chart_data(target_counts, "pie")
        blocks.append(_widget("chart-target-distribution", "pie", "药物靶点分布", chart_data))

    modality_counts: Dict[str, int] = {}
    for a in state.drug_assets:
        mod = a.modality or "Unspecified"
        modality_counts[mod] = modality_counts.get(mod, 0) + 1
    if modality_counts:
        chart_data = build_chart_data(modality_counts, "bar")
        blocks.append(_widget("chart-modality-distribution", "bar", "药物模态分布", chart_data))

    return {"order": 2, "title": "药物资产全景", "chapterId": "S2", "blocks": blocks}


def _render_clinical_matrix(state: DiseaseSurveyState) -> Dict[str, Any]:
    blocks: List[Dict[str, Any]] = [_heading(2, "临床管线矩阵", "clinical-matrix")]

    if not state.trials:
        blocks.append(_empty_callout("临床管线矩阵"))
        return {"order": 3, "title": "临床管线矩阵", "chapterId": "S3", "blocks": blocks}

    headers = ["NCT ID", "药物名", "Sponsor", "Phase", "Status", "Enrollment", "Primary Endpoint", "AE Grade 3+"]
    rows = []
    for t in state.trials:
        rows.append([
            t.nct_id,
            t.asset_name or "—",
            t.sponsor or "—",
            t.phase or "—",
            t.status or "—",
            t.enrollment or "—",
            t.primary_endpoint or "—",
            t.ae_grade3plus or "—",
        ])
    blocks.append(_table(headers, rows))

    phase_counts = group_by_phase(state.trials)
    if phase_counts:
        blocks.append(_widget("chart-phase-distribution", "bar", "Phase 分布", build_chart_data(phase_counts, "bar")))

    status_counts: Dict[str, int] = {}
    for t in state.trials:
        s = t.status or "Unknown"
        status_counts[s] = status_counts.get(s, 0) + 1
    if status_counts:
        blocks.append(_widget("chart-trial-status", "doughnut", "试验状态分布", build_chart_data(status_counts, "doughnut")))

    return {"order": 3, "title": "临床管线矩阵", "chapterId": "S3", "blocks": blocks}
```

- [ ] **Step 4: 编写 renderer.py — 后5章（文献/CNS/竞争/公司/参考文献）**

在 `renderer.py` 末尾追加以下函数：

```python
def _render_literature(state: DiseaseSurveyState) -> Dict[str, Any]:
    blocks: List[Dict[str, Any]] = [_heading(2, "文献证据分析", "literature")]

    if not state.literature:
        blocks.append(_empty_callout("文献证据分析"))
        return {"order": 4, "title": "文献证据分析", "chapterId": "S4", "blocks": blocks}

    headers = ["PMID", "标题", "期刊", "年份", "作者"]
    rows = []
    for rec in state.literature:
        rows.append([
            rec.pmid,
            rec.title,
            rec.journal or "—",
            str(rec.year) if rec.year else "—",
            rec.authors or "—",
        ])
    blocks.append(_table(headers, rows))

    trend = compute_publication_trend(state.literature)
    if trend:
        sorted_trend = dict(sorted(trend.items()))
        chart_data = build_chart_data(sorted_trend, "line")
        blocks.append(_widget("chart-pub-trend", "line", "发表年份趋势", chart_data))

    journal_counts: Dict[str, int] = {}
    for rec in state.literature:
        j = rec.journal or "Unknown"
        journal_counts[j] = journal_counts.get(j, 0) + 1
    if journal_counts:
        blocks.append(_widget("chart-journal-distribution", "pie", "来源期刊分布", build_chart_data(journal_counts, "pie")))

    return {"order": 4, "title": "文献证据分析", "chapterId": "S4", "blocks": blocks}


def _render_cns_benchmark(state: DiseaseSurveyState) -> Dict[str, Any]:
    blocks: List[Dict[str, Any]] = [_heading(2, "CNS 靶点基准对照", "cns-benchmark")]

    if not state.cns_benchmark:
        blocks.append(_empty_callout("CNS 靶点基准对照"))
        return {"order": 5, "title": "CNS 靶点基准对照", "chapterId": "S5", "blocks": blocks}

    headers = ["靶点", "近5年发表数", "近5年试验数", "顶刊引用", "趋势", "匹配"]
    rows = []
    for e in state.cns_benchmark:
        rows.append([
            e.target_name,
            str(e.publication_count_5yr),
            str(e.trial_count_5yr),
            str(e.top_journal_citations),
            e.trend,
            "✓" if e.matched else "—",
        ])
    blocks.append(_table(headers, rows))

    radar_labels = [e.target_name for e in state.cns_benchmark]
    radar_data = {
        "labels": radar_labels,
        "datasets": [
            {
                "label": "发表数量",
                "data": [e.publication_count_5yr for e in state.cns_benchmark],
                "backgroundColor": "rgba(74, 144, 226, 0.2)",
                "borderColor": "#4A90E2",
            },
            {
                "label": "顶刊引用",
                "data": [e.top_journal_citations for e in state.cns_benchmark],
                "backgroundColor": "rgba(232, 93, 117, 0.2)",
                "borderColor": "#E85D75",
            },
        ],
    }
    blocks.append(_widget("chart-cns-radar", "radar", "靶点研究热度雷达图", radar_data))

    matched = [e for e in state.cns_benchmark if e.matched]
    if matched:
        top = max(matched, key=lambda e: e.top_journal_citations)
        blocks.append(_callout("success", "顶刊背书",
            f"靶点 {top.target_name} 在近5年获得 {top.top_journal_citations} 次顶刊引用，研究趋势为 {top.trend}。"))

    return {"order": 5, "title": "CNS 靶点基准对照", "chapterId": "S5", "blocks": blocks}


def _render_competitive(state: DiseaseSurveyState) -> Dict[str, Any]:
    blocks: List[Dict[str, Any]] = [_heading(2, "竞争格局", "competitive")]

    if not state.drug_assets:
        blocks.append(_empty_callout("竞争格局"))
        return {"order": 6, "title": "竞争格局", "chapterId": "S6", "blocks": blocks}

    headers = ["公司", "药物", "靶点", "模态", "Phase"]
    rows = []
    for a in state.drug_assets:
        rows.append([
            a.sponsor or "—",
            a.asset_name,
            ", ".join(a.targets) if a.targets else "—",
            a.modality or "—",
            a.phase or "—",
        ])
    blocks.append(_table(headers, rows))

    _PHASE_NUM = {"Preclinical": 0, "Phase 1": 1, "Phase 1/2": 1.5, "Phase 2": 2, "Phase 2/3": 2.5, "Phase 3": 3, "Phase 4": 4}
    bubble_points = []
    for a in state.drug_assets:
        bubble_points.append({
            "x": _PHASE_NUM.get(a.phase or "", 0),
            "y": len(a.trial_ids),
            "r": max(5, len(a.trial_ids) * 5),
            "label": f"{a.sponsor}: {a.asset_name}",
        })

    if bubble_points:
        sponsors_unique = list({a.sponsor for a in state.drug_assets if a.sponsor})
        datasets = []
        for idx, sponsor in enumerate(sponsors_unique):
            pts = [p for p in bubble_points if p["label"].startswith(sponsor)]
            datasets.append({
                "label": sponsor,
                "data": [{"x": p["x"], "y": p["y"], "r": p["r"]} for p in pts],
                "backgroundColor": _PALETTE[idx % len(_PALETTE)],
            })
        bubble_data = {
            "labels": list(_PHASE_NUM.keys()),
            "datasets": datasets,
        }
        blocks.append(_widget("chart-competitive-bubble", "bubble", "公司-资产竞争气泡图", bubble_data))

    return {"order": 6, "title": "竞争格局", "chapterId": "S6", "blocks": blocks}


def _render_sponsors(state: DiseaseSurveyState) -> Dict[str, Any]:
    blocks: List[Dict[str, Any]] = [_heading(2, "公司概览", "sponsors")]

    if not state.sponsors:
        blocks.append(_empty_callout("公司概览"))
        return {"order": 7, "title": "公司概览", "chapterId": "S7", "blocks": blocks}

    headers = ["公司", "管线数", "最高阶段", "Ticker", "市值", "现金跑道(月)"]
    rows = []
    for s in state.sponsors:
        rows.append([
            s.company_name,
            str(s.pipeline_count),
            s.lead_phase or "—",
            s.ticker or "—",
            f"${s.market_cap/1e9:.1f}B" if s.market_cap else "—",
            str(int(s.cash_runway_months)) if s.cash_runway_months else "—",
        ])
    blocks.append(_table(headers, rows))

    return {"order": 7, "title": "公司概览", "chapterId": "S7", "blocks": blocks}


def _render_references(state: DiseaseSurveyState) -> Dict[str, Any]:
    blocks: List[Dict[str, Any]] = [_heading(2, "参考文献", "references")]

    if not state.literature:
        blocks.append(_empty_callout("参考文献"))
        return {"order": 8, "title": "参考文献", "chapterId": "S8", "blocks": blocks}

    headers = ["PMID", "标题", "期刊", "年份", "DOI"]
    rows = []
    for rec in state.literature:
        rows.append([
            rec.pmid,
            rec.title,
            rec.journal or "—",
            str(rec.year) if rec.year else "—",
            rec.doi or "—",
        ])
    blocks.append(_table(headers, rows))

    return {"order": 8, "title": "参考文献", "chapterId": "S8", "blocks": blocks}
```

- [ ] **Step 5: 运行测试确认通过**

Run:
```bash
"C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe" -m pytest tests/test_disease_survey_renderer.py -v
```
Expected: 7 tests PASSED

- [ ] **Step 6: Commit**

```bash
git add src/engines/report_engine/disease_survey/renderer.py tests/test_disease_survey_renderer.py
git commit -m "feat(disease-survey): add IR chapter renderer with 9 chapters and charts"
```

---

## Task 4: 模块入口 (__init__.py) + DocumentComposer 集成

**Files:**
- Modify: `src/engines/report_engine/disease_survey/__init__.py`

- [ ] **Step 1: 编写 __init__.py 入口函数**

将 `src/engines/report_engine/disease_survey/__init__.py` 替换为：

```python
# src/engines/report_engine/disease_survey/__init__.py
"""Disease survey report module.

Public API:
    generate_disease_survey_report(rows, query, ...) → IR document dict
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from .aggregator import aggregate_survey_data
from .models import DiseaseSurveyState
from .renderer import render_to_ir_chapters


def generate_disease_survey_report(
    rows: List[Dict[str, Any]],
    query: str,
    report_id: Optional[str] = None,
    title: Optional[str] = None,
) -> Dict[str, Any]:
    """End-to-end: harvest rows → aggregated state → IR chapters → stitched document.

    Returns a complete IR document dict ready for HTML/PDF rendering.
    """
    from src.engines.report_engine.core.stitcher import DocumentComposer

    state = aggregate_survey_data(rows, query)
    logger.info(
        f"Disease survey aggregated: {len(state.drug_assets)} assets, "
        f"{len(state.trials)} trials, {len(state.literature)} literature"
    )

    chapters = render_to_ir_chapters(state)

    composer = DocumentComposer()
    metadata = {
        "title": title or f"{state.disease_name} — 疾病综合调研报告",
        "subtitle": query,
        "generatedAt": datetime.utcnow().isoformat() + "Z",
    }

    document = composer.build_document(
        report_id=report_id or f"disease-survey-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        metadata=metadata,
        chapters=chapters,
    )
    return document


__all__ = [
    "DiseaseSurveyState",
    "aggregate_survey_data",
    "generate_disease_survey_report",
    "render_to_ir_chapters",
]
```

- [ ] **Step 2: 快速验证导入**

Run:
```bash
"C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe" -c "from src.engines.report_engine.disease_survey import generate_disease_survey_report; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/engines/report_engine/disease_survey/__init__.py
git commit -m "feat(disease-survey): add module entry point with DocumentComposer integration"
```

---

## Task 5: ReportWriterAgent 路由集成

**Files:**
- Modify: `src/agents/report_writer.py:186-192`

- [ ] **Step 1: 在 ReportWriterAgent 中添加路由判断方法**

在 `src/agents/report_writer.py` 的 `_compose_context_text` 方法之前（约第 253 行前）插入：

```python
    @staticmethod
    def _is_disease_survey(rows: List[Dict[str, Any]]) -> bool:
        """Detect whether harvest rows represent a disease survey dataset."""
        if len(rows) < 5:
            return False
        survey_count = 0
        for row in rows:
            if row.get("nct_id") or row.get("pmid"):
                survey_count += 1
        return survey_count / len(rows) > 0.5

    def _write_disease_survey_report(
        self,
        rows: List[Dict[str, Any]],
        user_query: str,
        output_dir: str,
        project_name: str,
    ) -> ReportOutput:
        """Generate a structured disease survey report via the new IR pipeline."""
        from src.engines.report_engine.disease_survey import generate_disease_survey_report

        ir_document = generate_disease_survey_report(
            rows=rows,
            query=user_query,
            title=f"{project_name} — 疾病综合调研报告",
        )

        import json
        from pathlib import Path

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        ir_path = out_dir / f"{sanitize_filename(project_name)}_disease_survey_ir.json"
        ir_path.write_text(json.dumps(ir_document, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"Disease survey IR saved: {ir_path}")

        summary = ir_document.get("metadata", {}).get("title", project_name)
        return ReportOutput(
            markdown_content=f"# {summary}\n\nIR document generated: {ir_path}",
            markdown_path=str(ir_path),
            analysis_position="DISEASE_SURVEY",
            data_confidence=8.0,
            signal_severity_score=0.0,
        )
```

- [ ] **Step 2: 修改 write_report() 添加路由**

找到 `src/agents/report_writer.py` 中的现有代码（约第 186-192 行）：

```python
        markdown_content = self._render_markdown(
            report_data=report_data,
            rows=rows,
            analysis_position=analysis_position,
            data_confidence=data_confidence,
            signal_score=signal_score,
        )
```

替换为：

```python
        if self._is_disease_survey(rows):
            logger.info(f"Disease survey detected ({len(rows)} rows), routing to new pipeline")
            return self._write_disease_survey_report(
                rows=rows,
                user_query=_safe_text(user_query, 500),
                output_dir=output_dir,
                project_name=resolved_project_name,
            )

        markdown_content = self._render_markdown(
            report_data=report_data,
            rows=rows,
            analysis_position=analysis_position,
            data_confidence=data_confidence,
            signal_score=signal_score,
        )
```

- [ ] **Step 3: 验证路由逻辑**

Run:
```bash
"C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe" -c "
import sys; sys.path.insert(0, '.')
from src.agents.report_writer import ReportWriterAgent

agent = ReportWriterAgent.__new__(ReportWriterAgent)

survey_rows = [{'nct_id': f'NCT{i}', 'title': f'Trial {i}', 'source': 'ClinicalTrials'} for i in range(10)]
assert agent._is_disease_survey(survey_rows) is True

non_survey = [{'title': f'Item {i}'} for i in range(10)]
assert agent._is_disease_survey(non_survey) is False

small = [{'nct_id': 'NCT1', 'title': 'T1'}]
assert agent._is_disease_survey(small) is False

print('Routing logic OK')
"
```
Expected: `Routing logic OK`

- [ ] **Step 4: Commit**

```bash
git add src/agents/report_writer.py
git commit -m "feat(disease-survey): add routing in ReportWriterAgent to disease survey pipeline"
```

---

## Task 6: 端到端集成测试

**Files:**
- Create: `tests/test_disease_survey_integration.py`

- [ ] **Step 1: 编写集成测试**

```python
# tests/test_disease_survey_integration.py
"""End-to-end integration test for disease survey report generation."""
import json

import pytest

from src.engines.report_engine.disease_survey import generate_disease_survey_report


SAMPLE_ROWS = [
    {
        "source": "PubMed",
        "pmid": "38001234",
        "title": "BACE1 inhibitor trial results in early Alzheimer's",
        "summary": "A Phase 2 trial of verubecestat targeting BACE1 showed no efficacy.",
        "journal": "NEJM",
        "year": 2023,
        "authors": "Smith J et al.",
    },
    {
        "source": "PubMed",
        "pmid": "38005678",
        "title": "Tau PET imaging advances in AD diagnosis",
        "summary": "Novel tau PET tracers improve early detection of Alzheimer's.",
        "journal": "Lancet Neurology",
        "year": 2024,
    },
    {
        "source": "ClinicalTrials",
        "nct_id": "NCT05310071",
        "title": "Lecanemab Phase 3 Extension Study",
        "summary": "Open-label extension evaluating long-term safety of lecanemab.",
        "metadata": {
            "intervention": "Lecanemab (BAN2401), anti-Aβ monoclonal antibody",
            "sponsor": "Eisai",
            "phase": "Phase 3",
            "status": "Recruiting",
            "enrollment": "1500",
            "primary_endpoint": "CDR-SB change from baseline",
            "ae_grade3plus": "ARIA-E 12.6%",
        },
    },
    {
        "source": "ClinicalTrials",
        "nct_id": "NCT04468659",
        "title": "Donanemab TRAILBLAZER-ALZ 2",
        "summary": "Phase 3 trial of donanemab targeting N3pG-Aβ in early AD.",
        "metadata": {
            "intervention": "Donanemab, anti-Aβ monoclonal antibody",
            "sponsor": "Eli Lilly",
            "phase": "Phase 3",
            "status": "Completed",
            "enrollment": "1736",
            "primary_endpoint": "iADRS change",
        },
    },
    {
        "source": "ClinicalTrials",
        "nct_id": "NCT05108922",
        "title": "Remternetug Phase 2 in Early AD",
        "summary": "Evaluating remternetug anti-amyloid antibody in early Alzheimer's.",
        "metadata": {
            "intervention": "Remternetug, anti-Aβ monoclonal antibody",
            "sponsor": "Eli Lilly",
            "phase": "Phase 2",
            "status": "Active",
            "enrollment": "400",
            "primary_endpoint": "Amyloid PET change",
        },
    },
]


def test_generate_full_ir_document():
    doc = generate_disease_survey_report(SAMPLE_ROWS, "Alzheimer's disease drug pipeline survey")

    assert doc["version"] is not None
    assert doc["reportId"].startswith("disease-survey-")
    assert "Alzheimer" in doc["metadata"]["title"]
    assert len(doc["chapters"]) == 9

    chapter_titles = [ch["title"] for ch in doc["chapters"]]
    assert "Executive Summary" in chapter_titles
    assert "药物资产全景" in chapter_titles
    assert "临床管线矩阵" in chapter_titles
    assert "文献证据分析" in chapter_titles
    assert "CNS 靶点基准对照" in chapter_titles
    assert "竞争格局" in chapter_titles
    assert "公司概览" in chapter_titles
    assert "参考文献" in chapter_titles


def test_ir_document_has_widgets():
    doc = generate_disease_survey_report(SAMPLE_ROWS, "AD pipeline")
    all_blocks = []
    for ch in doc["chapters"]:
        all_blocks.extend(ch.get("blocks", []))

    widgets = [b for b in all_blocks if b.get("type") == "widget"]
    assert len(widgets) >= 4

    for w in widgets:
        assert w["widgetType"].startswith("chart.js/")
        assert "data" in w
        assert "labels" in w["data"]
        assert "datasets" in w["data"]


def test_ir_document_has_tables():
    doc = generate_disease_survey_report(SAMPLE_ROWS, "AD pipeline")
    all_blocks = []
    for ch in doc["chapters"]:
        all_blocks.extend(ch.get("blocks", []))

    tables = [b for b in all_blocks if b.get("type") == "table"]
    assert len(tables) >= 4


def test_ir_document_has_kpi_grid():
    doc = generate_disease_survey_report(SAMPLE_ROWS, "AD pipeline")
    ch0 = doc["chapters"][0]
    kpis = [b for b in ch0["blocks"] if b.get("type") == "kpiGrid"]
    assert len(kpis) == 1
    assert len(kpis[0]["items"]) == 4


def test_ir_document_serializable():
    doc = generate_disease_survey_report(SAMPLE_ROWS, "AD pipeline")
    serialized = json.dumps(doc, ensure_ascii=False, indent=2)
    assert len(serialized) > 500
    roundtrip = json.loads(serialized)
    assert roundtrip["chapters"][0]["title"] == doc["chapters"][0]["title"]


def test_empty_rows_still_produces_document():
    doc = generate_disease_survey_report([], "empty query")
    assert len(doc["chapters"]) == 9
    for ch in doc["chapters"]:
        assert len(ch["blocks"]) > 0
```

- [ ] **Step 2: 运行集成测试**

Run:
```bash
"C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe" -m pytest tests/test_disease_survey_integration.py -v
```
Expected: 6 tests PASSED

- [ ] **Step 3: 运行全部 disease survey 测试**

Run:
```bash
"C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe" -m pytest tests/test_disease_survey_models.py tests/test_disease_survey_aggregator.py tests/test_disease_survey_renderer.py tests/test_disease_survey_integration.py -v
```
Expected: 全部 PASSED（约 28+ tests）

- [ ] **Step 4: Commit**

```bash
git add tests/test_disease_survey_integration.py
git commit -m "test(disease-survey): add end-to-end integration tests"
```

---

## Task 7: 端到端验证

**Files:**
- 无新文件变更，纯验证步骤

- [ ] **Step 1: 运行现有测试套件确认无回归**

Run:
```bash
"C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe" -m pytest tests/test_dataflow_integrity.py tests/test_report_engine_sanitization.py -v
```
Expected: 所有现有测试 PASSED

- [ ] **Step 2: 验证路由不影响 legacy 报告**

Run:
```bash
"C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe" -c "
import sys; sys.path.insert(0, '.')
from src.agents.report_writer import ReportWriterAgent

agent = ReportWriterAgent.__new__(ReportWriterAgent)

legacy_rows = [{'title': f'Item {i}', 'summary': 'text'} for i in range(20)]
assert agent._is_disease_survey(legacy_rows) is False
print('Legacy routing preserved')
"
```
Expected: `Legacy routing preserved`

- [ ] **Step 3: 验证完整 IR 文档可被 chart_to_svg 消费**

Run:
```bash
"C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe" -c "
import sys, json; sys.path.insert(0, '.')
from src.engines.report_engine.disease_survey import generate_disease_survey_report

rows = [
    {'source': 'ClinicalTrials', 'nct_id': 'NCT001', 'title': 'Trial A', 'metadata': {'intervention': 'DrugA, mAb', 'sponsor': 'Co1', 'phase': 'Phase 3', 'status': 'Active'}},
    {'source': 'ClinicalTrials', 'nct_id': 'NCT002', 'title': 'Trial B', 'metadata': {'intervention': 'DrugB, small molecule', 'sponsor': 'Co2', 'phase': 'Phase 2', 'status': 'Recruiting'}},
    {'source': 'PubMed', 'pmid': '111', 'title': 'Amyloid study', 'journal': 'NEJM', 'year': 2023},
    {'source': 'PubMed', 'pmid': '222', 'title': 'Tau imaging', 'journal': 'Brain', 'year': 2024},
    {'source': 'ClinicalTrials', 'nct_id': 'NCT003', 'title': 'Trial C', 'metadata': {'intervention': 'DrugC', 'sponsor': 'Co1', 'phase': 'Phase 1', 'status': 'Completed'}},
]
doc = generate_disease_survey_report(rows, 'AD pipeline')
widgets = []
for ch in doc['chapters']:
    for b in ch.get('blocks', []):
        if b.get('type') == 'widget':
            widgets.append(b)

print(f'Generated {len(doc[\"chapters\"])} chapters, {len(widgets)} widgets')
for w in widgets:
    assert w['widgetType'].startswith('chart.js/')
    assert 'data' in w
    print(f'  {w[\"widgetId\"]}: {w[\"widgetType\"]}')
print('All widgets valid for chart_to_svg')
"
```
Expected: 输出章节数、widget 数量，所有 widget 格式正确

- [ ] **Step 4: 最终 Commit（如有遗漏修复）**

```bash
git status
# 如果有变更：
git add -A
git commit -m "fix: final adjustments from end-to-end verification"
```
