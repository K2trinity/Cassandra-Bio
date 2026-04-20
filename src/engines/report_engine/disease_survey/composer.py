# src/engines/report_engine/disease_survey/composer.py
"""Assembles all disease survey sections into a report dict.

Also provides DocumentComposer integration via build_disease_survey_document.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict

from .models import DiseaseSurveyState
from .renderer import (
    render_cns_benchmark,
    render_drug_pipeline,
    render_executive_summary,
    render_literature_review,
    render_market_landscape,
    render_safety_profile,
    render_sponsor_analysis,
    render_target_biology,
    render_trial_landscape,
)


def _run(text: Any, *, bold: bool = False) -> dict:
    payload = {"text": str(text)}
    if bold:
        payload["marks"] = [{"type": "bold"}]
    return payload


def _inline(text: Any) -> list[dict]:
    value = str(text)
    if "**" not in value:
        return [_run(value)]

    runs: list[dict] = []
    cursor = 0
    while cursor < len(value):
        start = value.find("**", cursor)
        if start == -1:
            if cursor < len(value):
                runs.append(_run(value[cursor:]))
            break
        if start > cursor:
            runs.append(_run(value[cursor:start]))
        end = value.find("**", start + 2)
        if end == -1:
            runs.append(_run(value[start:]))
            break
        highlighted = value[start + 2:end]
        if highlighted:
            runs.append(_run(highlighted, bold=True))
        cursor = end + 2

    return runs or [_run(value)]


def _paragraph(text: Any, *, align: str | None = None) -> dict:
    block = {"type": "paragraph", "inlines": _inline(text)}
    if align:
        block["align"] = align
    return block


def _paragraphs(text: Any) -> list[dict]:
    raw = str(text or "").replace("\r\n", "\n").strip()
    if not raw:
        return []
    return [
        _paragraph(chunk.strip())
        for chunk in re.split(r"\n\s*\n", raw)
        if chunk.strip()
    ]


def _heading(level: int, text: str, anchor: str) -> dict:
    return {"type": "heading", "level": level, "text": text, "anchor": anchor}


def _widget(widget_id: str, chart_type: str, title: str, chart_data: Dict[str, Any] | None) -> dict | None:
    if not isinstance(chart_data, dict):
        return None
    labels = chart_data.get("labels")
    datasets = chart_data.get("datasets")
    if not labels or not datasets:
        return None
    return {
        "type": "widget",
        "widgetId": widget_id,
        "widgetType": f"chart.js/{chart_type}",
        "props": {"type": chart_type, "title": title},
        "data": {
            "labels": labels,
            "datasets": datasets,
        },
    }


def _table(headers: list[str], rows: list[list[Any]], caption: str | None = None) -> dict:
    table_rows = [
        {
            "cells": [
                {
                    "header": True,
                    "isHeader": True,
                    "blocks": [_paragraph(f"**{header}**")],
                }
                for header in headers
            ]
        }
    ]

    for row in rows:
        table_rows.append(
            {
                "cells": [
                    {"blocks": [_paragraph("—" if value in (None, "") else value)]}
                    for value in row
                ]
            }
        )

    block = {"type": "table", "rows": table_rows}
    if caption:
        block["caption"] = caption
    return block


def _format_distribution(data: Dict[str, Any], limit: int = 4) -> str:
    items = [
        (str(label), int(value))
        for label, value in (data or {}).items()
        if label not in (None, "") and value not in (None, "")
    ]
    if not items:
        return ""
    ranked = sorted(items, key=lambda item: (-item[1], item[0]))
    return "，".join(f"{label}: {value}" for label, value in ranked[:limit])


def _format_market_cap(value: Any) -> str:
    if value is None:
        return "—"
    return f"${float(value) / 1e9:.1f}B"


def _format_months(value: Any) -> str:
    if value in (None, "", 0):
        return "—"
    return f"{int(float(value))} mo"


def _format_ratio(value: Any) -> str:
    if value in (None, ""):
        return "—"
    return f"{float(value):.1%}"


def compose_disease_survey_report(state: DiseaseSurveyState) -> Dict[str, Any]:
    """Render all sections and return as a flat dict keyed by section name."""
    return {
        "executive_summary": render_executive_summary(state),
        "drug_pipeline": render_drug_pipeline(state),
        "trial_landscape": render_trial_landscape(state),
        "sponsor_analysis": render_sponsor_analysis(state),
        "target_biology": render_target_biology(state),
        "safety_profile": render_safety_profile(state),
        "literature_review": render_literature_review(state),
        "cns_benchmark": render_cns_benchmark(state),
        "market_landscape": render_market_landscape(state),
    }


def build_disease_survey_document(
    state: DiseaseSurveyState,
    report_id: str | None = None,
) -> Dict[str, Any]:
    """Wrap compose_disease_survey_report into a DocumentComposer IR document.

    Each section becomes a chapter with order, title, and a single data block.
    """
    from ..core import DocumentComposer

    if report_id is None:
        report_id = f"disease-survey-{state.disease_name.lower().replace(' ', '-')}"

    sections = compose_disease_survey_report(state)

    _SECTION_META = [
        ("executive_summary",  "Executive Summary",   10),
        ("drug_pipeline",      "Drug Pipeline",       20),
        ("trial_landscape",    "Trial Landscape",     30),
        ("sponsor_analysis",   "Sponsor Analysis",    40),
        ("target_biology",     "Target Biology",      50),
        ("safety_profile",     "Safety Profile",      60),
        ("literature_review",  "Literature Review",   70),
        ("cns_benchmark",      "CNS Benchmark",       80),
        ("market_landscape",   "Market Landscape",    90),
    ]

    chapters = []
    for key, title, order in _SECTION_META:
        section = sections[key]
        blocks = [_heading(2, title, key)]

        if key == "executive_summary":
            blocks.append(
                {
                    "type": "kpiGrid",
                    "items": [
                        {"label": "Assets", "value": str(section.get("total_assets", 0))},
                        {"label": "Trials", "value": str(section.get("total_trials", 0))},
                        {"label": "Sponsors", "value": str(section.get("total_sponsors", 0))},
                        {"label": "Literature", "value": str(section.get("total_literature", 0))},
                    ],
                    "cols": 4,
                }
            )
            summary_text = section.get("summary_text")
            if summary_text:
                blocks.extend(_paragraphs(summary_text))
            else:
                blocks.append(
                    _paragraph(
                        "The survey identified **"
                        f"{section.get('total_assets', 0)} assets**, **{section.get('total_trials', 0)} trials**, "
                        f"**{section.get('total_sponsors', 0)} sponsors**, and **{section.get('total_literature', 0)} literature records**."
                    )
                )
            phase_breakdown = _format_distribution(section.get("phase_breakdown") or {})
            if phase_breakdown:
                blocks.append(_paragraph(f"Clinical phase mix is led by **{phase_breakdown}**."))
            widget = _widget(
                f"{key}-phase-chart",
                "bar",
                "Phase Breakdown",
                section.get("phase_chart"),
            )
            if widget:
                blocks.append(widget)
        elif key == "drug_pipeline":
            assets = section.get("assets", [])
            blocks.append(_paragraph(f"Identified **{len(assets)} assets** in the active disease pipeline."))
            phase_summary = _format_distribution(section.get("by_phase") or {})
            if phase_summary:
                blocks.append(_paragraph(f"Most represented development stages: **{phase_summary}**."))
            target_summary = _format_distribution(section.get("by_target") or {})
            if target_summary:
                blocks.append(_paragraph(f"Most represented targets: **{target_summary}**."))
            for chart_name, chart_title, chart_type in (
                ("phase_chart", "Asset Phase Distribution", "bar"),
                ("target_chart", "Target Distribution", "pie"),
            ):
                widget = _widget(f"{key}-{chart_name}", chart_type, chart_title, section.get(chart_name))
                if widget:
                    blocks.append(widget)
            if assets:
                rows = [
                    [
                        asset.get("asset_name") or "—",
                        asset.get("modality") or "—",
                        ", ".join(asset.get("targets") or []) or "—",
                        asset.get("sponsor") or "—",
                        asset.get("phase") or "—",
                        asset.get("status") or "—",
                    ]
                    for asset in assets
                ]
                blocks.append(
                    _table(
                        ["Drug", "Modality", "Target", "Sponsor", "Phase", "Status"],
                        rows,
                        caption="Drug pipeline assets",
                    )
                )
            else:
                blocks.append(_paragraph("No structured drug assets were detected in the current harvest payload."))
        elif key == "trial_landscape":
            trials = section.get("trials", [])
            blocks.append(_paragraph(f"Included **{section.get('total', 0)} clinical trials** with sponsor and endpoint coverage where available."))
            phase_summary = _format_distribution(section.get("by_phase") or {})
            if phase_summary:
                blocks.append(_paragraph(f"Trial phase distribution: **{phase_summary}**."))
            status_summary = _format_distribution(section.get("by_status") or {})
            if status_summary:
                blocks.append(_paragraph(f"Trial status mix: **{status_summary}**."))
            widget = _widget(
                f"{key}-phase-chart",
                "bar",
                "Trial Phase Distribution",
                section.get("phase_chart"),
            )
            if widget:
                blocks.append(widget)
            if trials:
                rows = [
                    [
                        trial.get("nct_id") or "—",
                        trial.get("asset_name") or "—",
                        trial.get("sponsor") or "—",
                        trial.get("phase") or "—",
                        trial.get("status") or "—",
                        trial.get("enrollment") or "—",
                        trial.get("primary_endpoint") or "—",
                    ]
                    for trial in trials
                ]
                blocks.append(
                    _table(
                        ["NCT ID", "Asset", "Sponsor", "Phase", "Status", "Enrollment", "Primary Endpoint"],
                        rows,
                        caption="Clinical trial landscape",
                    )
                )
            else:
                blocks.append(_paragraph("No structured clinical trial rows were detected in the current dataset."))
        elif key == "literature_review":
            records = section.get("records", [])
            blocks.append(_paragraph(f"The literature review captured **{section.get('total', 0)} publications** relevant to the disease landscape."))
            top_journals = ", ".join(
                f"{entry.get('journal')}: {entry.get('count')}"
                for entry in (section.get("top_journals") or [])[:5]
                if entry.get("journal")
            )
            if top_journals:
                blocks.append(_paragraph(f"Top journals include **{top_journals}**."))
            widget = _widget(
                f"{key}-year-chart",
                "bar",
                "Publication Trend",
                section.get("year_chart"),
            )
            if widget:
                blocks.append(widget)
            if records:
                rows = [
                    [
                        record.get("pmid") or "—",
                        record.get("title") or "—",
                        record.get("journal") or "—",
                        record.get("year") or "—",
                        record.get("authors") or "—",
                    ]
                    for record in records[:50]
                ]
                blocks.append(
                    _table(
                        ["PMID", "Title", "Journal", "Year", "Authors"],
                        rows,
                        caption="Literature evidence review",
                    )
                )
            else:
                blocks.append(_paragraph("No literature records were available for the current query."))
        elif key == "sponsor_analysis":
            sponsors = section.get("sponsors", [])
            blocks.append(_paragraph(f"Identified **{section.get('total', 0)} sponsors** across the current asset and trial landscape."))
            if sponsors:
                sponsor_summary = ", ".join(
                    f"{entry.get('company_name')}: {entry.get('pipeline_count', 0)}"
                    for entry in sorted(
                        sponsors,
                        key=lambda item: (-int(item.get("pipeline_count") or 0), item.get("company_name") or ""),
                    )[:5]
                )
                if sponsor_summary:
                    blocks.append(_paragraph(f"Highest visible pipeline counts: **{sponsor_summary}**."))
                rows = [
                    [
                        sponsor.get("company_name") or "—",
                        sponsor.get("pipeline_count") or 0,
                        sponsor.get("lead_phase") or "—",
                        sponsor.get("ticker") or "—",
                        _format_market_cap(sponsor.get("market_cap")),
                    ]
                    for sponsor in sponsors
                ]
                blocks.append(
                    _table(
                        ["Sponsor", "Pipeline Count", "Lead Phase", "Ticker", "Market Cap"],
                        rows,
                        caption="Sponsor analysis",
                    )
                )
            else:
                blocks.append(_paragraph("No structured sponsor profiles were available for this survey."))
        elif key == "target_biology":
            targets = section.get("targets", [])
            blocks.append(_paragraph(f"Structured target mapping surfaced **{section.get('total_unique', 0)} unique targets** across the asset set."))
            if targets:
                benchmark_covered = sum(
                    1
                    for target in targets
                    if (target.get("publication_count_5yr") or 0) > 0 or (target.get("trial_count_5yr") or 0) > 0
                )
                blocks.append(_paragraph(f"CNS benchmark enrichment is available for **{benchmark_covered} targets**."))
                rows = [
                    [
                        target.get("target_name") or "—",
                        target.get("asset_count") or 0,
                        ", ".join(target.get("asset_names") or []) or "—",
                        target.get("publication_count_5yr") or 0,
                        target.get("trend") or "—",
                    ]
                    for target in sorted(
                        targets,
                        key=lambda item: (-int(item.get("asset_count") or 0), item.get("target_name") or ""),
                    )
                ]
                blocks.append(
                    _table(
                        ["Target", "Asset Count", "Representative Assets", "Publications (5y)", "Trend"],
                        rows,
                        caption="Target biology summary",
                    )
                )
            else:
                blocks.append(_paragraph("No target annotations were captured in the current asset payload."))
        elif key == "safety_profile":
            ae_entries = section.get("ae_entries", [])
            blocks.append(
                _paragraph(
                    f"Structured safety data is available for **{section.get('trials_with_ae_data', 0)} "
                    f"of {section.get('total_trials', 0)} trials**."
                )
            )
            if ae_entries:
                blocks.append(_paragraph("Reported fields focus on grade 3+ adverse events and serious adverse event summaries."))
                rows = [
                    [
                        entry.get("nct_id") or "—",
                        entry.get("asset_name") or "—",
                        entry.get("ae_grade3plus") or "—",
                        entry.get("sae") or "—",
                    ]
                    for entry in ae_entries
                ]
                blocks.append(
                    _table(
                        ["NCT ID", "Asset", "AE Grade 3+", "SAE"],
                        rows,
                        caption="Safety profile",
                    )
                )
            else:
                blocks.append(_paragraph("No structured AE or SAE values were populated for the current clinical trial set."))
        elif key == "cns_benchmark":
            entries = section.get("entries", [])
            matched_targets = section.get("matched_targets") or []
            blocks.append(
                _paragraph(
                    f"CNS benchmark mapping covers **{section.get('total', 0)} reference targets**, with "
                    f"**{len(matched_targets)} matched** to the active disease asset set."
                )
            )
            if matched_targets:
                blocks.append(_paragraph(f"Matched targets: **{', '.join(matched_targets)}**."))
            if entries:
                rows = [
                    [
                        entry.get("target_name") or "—",
                        entry.get("publication_count_5yr") or 0,
                        entry.get("trial_count_5yr") or 0,
                        entry.get("top_journal_citations") or 0,
                        entry.get("trend") or "—",
                        "✓" if entry.get("matched") else "—",
                    ]
                    for entry in entries
                ]
                blocks.append(
                    _table(
                        ["Target", "Publications (5y)", "Trials (5y)", "Top Journal Citations", "Trend", "Matched"],
                        rows,
                        caption="CNS benchmark comparison",
                    )
                )
            else:
                blocks.append(_paragraph("No CNS benchmark reference rows were available for comparison."))
        elif key == "market_landscape":
            financials = section.get("sponsors_with_financials", [])
            total_sponsors = section.get("total_sponsors", 0)
            blocks.append(
                _paragraph(
                    f"Financial disclosures are available for **{len(financials)} of {total_sponsors} sponsors** in the current survey."
                )
            )
            if financials:
                blocks.append(_paragraph("Tracked fields include market capitalization, cash runway, R&D intensity, and pipeline maturity."))
                rows = [
                    [
                        sponsor.get("company_name") or "—",
                        sponsor.get("ticker") or "—",
                        _format_market_cap(sponsor.get("market_cap")),
                        _format_months(sponsor.get("cash_runway_months")),
                        _format_ratio(sponsor.get("rd_ratio")),
                        sponsor.get("pipeline_count") or 0,
                        sponsor.get("lead_phase") or "—",
                    ]
                    for sponsor in financials
                ]
                blocks.append(
                    _table(
                        ["Company", "Ticker", "Market Cap", "Cash Runway", "R&D Ratio", "Pipeline Count", "Lead Phase"],
                        rows,
                        caption="Market landscape",
                    )
                )
            else:
                blocks.append(_paragraph("Sponsor financial fields remain sparse in the current harvest payload."))
        else:
            blocks.append(_paragraph(f"Structured data available for **{title.lower()}**."))

        chapters.append({
            "chapterId": key,
            "title": title,
            "order": order,
            "anchor": key,
            "blocks": blocks,
            "data": section,
        })

    metadata: Dict[str, Any] = {
        "title": f"{state.disease_name} Disease Survey",
        "disease_name": state.disease_name,
        "query": state.query,
        "generatedAt": state.generated_at.isoformat(),
    }

    composer = DocumentComposer()
    return composer.build_document(report_id, metadata, chapters)


def _md_table(headers: list, rows: list) -> str:
    """Render a GitHub-flavored markdown table."""
    sep = " | ".join("---" for _ in headers)
    head = " | ".join(str(h) for h in headers)
    lines = [f"| {head} |", f"| {sep} |"]
    for row in rows:
        lines.append("| " + " | ".join(str(c) if c is not None and c != "" else "—" for c in row) + " |")
    return "\n".join(lines)


def disease_survey_to_markdown(state: "DiseaseSurveyState") -> str:
    """Convert a DiseaseSurveyState into structured markdown for HTML/PDF rendering."""
    sections = compose_disease_survey_report(state)
    lines: list = []

    # ── Header ────────────────────────────────────────────────────────────
    lines.append(f"# {state.disease_name} — 疾病综合调研报告")
    lines.append(f"\n> 查询：{state.query}  \n> 生成时间：{state.generated_at.strftime('%Y-%m-%d %H:%M UTC')}")
    analysis_meta = state.metadata.get("analysis_metadata", {}) if isinstance(state.metadata, dict) else {}
    field_audit = state.metadata.get("field_audit", {}) if isinstance(state.metadata, dict) else {}
    if analysis_meta.get("summary_source"):
        lines.append(
            f"> 综合分析来源：{analysis_meta.get('summary_source')}  \n> 模型：{analysis_meta.get('model_name') or 'n/a'}"
        )
    if field_audit:
        lines.append(
            f"> 字段审计：missing_asset={field_audit.get('missing_asset_count', 0)}, "
            f"missing_sponsor={field_audit.get('missing_sponsor_count', 0)}"
        )

    # ── Executive Summary ─────────────────────────────────────────────────
    es = sections["executive_summary"]
    lines.append("\n## Executive Summary")
    lines.append(f"- 药物资产：**{es['total_assets']}** 个")
    lines.append(f"- 临床试验：**{es['total_trials']}** 项")
    lines.append(f"- 研发公司：**{es['total_sponsors']}** 家")
    lines.append(f"- 文献记录：**{es['total_literature']}** 篇")
    if es.get("summary_text"):
        lines.append(f"\n{es['summary_text']}")
    if es.get("phase_breakdown"):
        pb = es["phase_breakdown"]
        lines.append("\n**Phase 分布：** " + "，".join(f"{k}: {v}" for k, v in sorted(pb.items())))

    # ── Drug Pipeline ─────────────────────────────────────────────────────
    dp = sections["drug_pipeline"]
    lines.append("\n## 药物资产全景")
    if dp["assets"]:
        rows = [
            [a["asset_name"], a["modality"] or "—", ", ".join(a["targets"]) or "—",
             a["sponsor"] or "—", a["phase"] or "—", a["status"] or "—"]
            for a in dp["assets"]
        ]
        lines.append(_md_table(["药物名称", "模态", "靶点", "Sponsor", "Phase", "状态"], rows))
    else:
        lines.append("_当前 harvest 数据中未检测到药物资产记录。_")

    # ── Trial Landscape ───────────────────────────────────────────────────
    tl = sections["trial_landscape"]
    lines.append("\n## 临床管线矩阵")
    if tl["trials"]:
        rows = [
            [t["nct_id"], t["asset_name"] or "—", t["sponsor"] or "—",
             t["phase"] or "—", t["status"] or "—",
             t["enrollment"] or "—", t["primary_endpoint"] or "—"]
            for t in tl["trials"]
        ]
        lines.append(_md_table(["NCT ID", "药物名", "Sponsor", "Phase", "Status", "Enrollment", "Primary Endpoint"], rows))
        if tl.get("by_phase"):
            lines.append("\n**Phase 分布：** " + "，".join(f"{k}: {v}" for k, v in sorted(tl["by_phase"].items())))
    else:
        lines.append("_当前 harvest 数据中未检测到临床试验记录。_")

    # ── Sponsor Analysis ──────────────────────────────────────────────────
    sa = sections["sponsor_analysis"]
    lines.append("\n## 公司概览")
    if sa["sponsors"]:
        rows = [
            [s["company_name"], s["pipeline_count"], s["lead_phase"] or "—",
             s["ticker"] or "—",
             f"${s['market_cap']/1e9:.1f}B" if s["market_cap"] is not None else "—"]
            for s in sa["sponsors"]
        ]
        lines.append(_md_table(["公司", "管线数", "最高阶段", "Ticker", "市值"], rows))
    else:
        lines.append("_暂无公司数据。_")

    # ── Target Biology ────────────────────────────────────────────────────
    tb = sections["target_biology"]
    lines.append("\n## 靶点生物学")
    if tb["targets"]:
        rows = [
            [t["target_name"], t["asset_count"], ", ".join(t["asset_names"]),
             t["publication_count_5yr"], t["trend"]]
            for t in sorted(tb["targets"], key=lambda x: x["asset_count"], reverse=True)
        ]
        lines.append(_md_table(["靶点", "药物数", "代表药物", "近5年发表数", "趋势"], rows))
    else:
        lines.append("_暂无靶点数据。_")

    # ── Safety Profile ────────────────────────────────────────────────────
    sp = sections["safety_profile"]
    lines.append("\n## 安全性概览")
    if sp["ae_entries"]:
        rows = [
            [e["nct_id"], e["asset_name"] or "—", e["ae_grade3plus"] or "—", e["sae"] or "—"]
            for e in sp["ae_entries"]
        ]
        lines.append(_md_table(["NCT ID", "药物", "AE Grade 3+", "SAE"], rows))
    else:
        lines.append(f"_当前 {sp['total_trials']} 项试验中未检测到结构化安全性数据。_")

    # ── Literature Review ─────────────────────────────────────────────────
    lr = sections["literature_review"]
    lines.append("\n## 文献证据分析")
    lines.append(f"共检索到 **{lr['total']}** 篇文献。")
    if lr.get("top_journals"):
        lines.append("\n**Top 期刊：**")
        for j in lr["top_journals"][:5]:
            lines.append(f"- {j['journal']}（{j['count']} 篇）")
    if lr["records"]:
        rows = [
            [r["pmid"], r["title"][:80] + ("…" if len(r["title"]) > 80 else ""),
             r["journal"] or "—", str(r["year"]) if r["year"] else "—", r["authors"] or "—"]
            for r in lr["records"][:50]
        ]
        lines.append(_md_table(["PMID", "标题", "期刊", "年份", "作者"], rows))

    # ── CNS Benchmark ─────────────────────────────────────────────────────
    cb = sections["cns_benchmark"]
    lines.append("\n## CNS 靶点基准对照")
    if cb["entries"]:
        rows = [
            [e["target_name"], e["publication_count_5yr"], e["trial_count_5yr"],
             e["top_journal_citations"], e["trend"], "✓" if e["matched"] else "—"]
            for e in cb["entries"]
        ]
        lines.append(_md_table(["靶点", "近5年发表数", "近5年试验数", "顶刊引用", "趋势", "匹配"], rows))
        if cb["matched_targets"]:
            lines.append(f"\n**匹配靶点：** {', '.join(cb['matched_targets'])}")
    else:
        lines.append("_暂无 CNS 基准数据。_")

    # ── Market Landscape ──────────────────────────────────────────────────
    ml = sections["market_landscape"]
    lines.append("\n## 市场格局")
    if ml["sponsors_with_financials"]:
        rows = [
            [s["company_name"], s["ticker"] or "—",
             f"${s['market_cap']/1e9:.1f}B" if s["market_cap"] is not None else "—",
             str(int(s["cash_runway_months"])) + " mo" if s["cash_runway_months"] else "—",
             f"{s['rd_ratio']:.1%}" if s["rd_ratio"] else "—",
             s["pipeline_count"], s["lead_phase"] or "—"]
            for s in ml["sponsors_with_financials"]
        ]
        lines.append(_md_table(["公司", "Ticker", "市值", "现金跑道", "R&D占比", "管线数", "最高阶段"], rows))
    else:
        lines.append(f"_共 {ml['total_sponsors']} 家公司，暂无财务数据（PokieTicker 预留字段）。_")

    return "\n".join(lines)


def compose_disease_survey_report_bundle(
    state: "DiseaseSurveyState",
    llm_client: Any | None = None,
) -> Dict[str, Any]:
    sections = compose_disease_survey_report(state)

    summary_text = state.summary_text or ""
    summary_source = "deterministic"
    model_name = None

    if llm_client is not None:
        try:
            prompt_payload = json.dumps(
                {
                    "disease_name": state.disease_name,
                    "query": state.query,
                    "executive_summary": sections.get("executive_summary", {}),
                    "field_audit": state.metadata.get("field_audit", {}),
                },
                ensure_ascii=False,
            )
            summary_text = llm_client.invoke(
                (
                    "You are a biomedical analyst. Write a concise executive summary in 2 short paragraphs. "
                    "Use plain prose and wrap 2-4 key metrics or critical facts in **bold**."
                ),
                prompt_payload,
            ).strip()
            summary_source = "llm"
            model_info = getattr(llm_client, "get_model_info", lambda: {})() or {}
            model_name = model_info.get("model_name") or getattr(llm_client, "model_name", None)
        except Exception:
            summary_text = state.summary_text or ""
            summary_source = "deterministic"

    if summary_text:
        state.summary_text = summary_text
        sections["executive_summary"]["summary_text"] = summary_text

    state.metadata["analysis_metadata"] = {
        "summary_source": summary_source,
        "model_name": model_name,
    }

    document_ir = build_disease_survey_document(state)
    markdown = disease_survey_to_markdown(state)
    return {
        "sections": sections,
        "document_ir": document_ir,
        "markdown": markdown,
        "analysis_metadata": {
            "summary_source": summary_source,
            "model_name": model_name,
            "field_audit": state.metadata.get("field_audit", {}),
        },
    }


__all__ = [
    "compose_disease_survey_report",
    "build_disease_survey_document",
    "compose_disease_survey_report_bundle",
    "disease_survey_to_markdown",
]
