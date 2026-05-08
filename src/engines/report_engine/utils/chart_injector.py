"""Chart Injector — 自动为 IR 文档注入统计图表。

当 LLM 生成的章节缺少可视化元素时，本模块可以：
1. 从 harvest 数据中提取可量化指标
2. 自动生成 chart / table blocks 注入到合适位置

用法:
    injector = ChartInjector()
    enriched_doc = injector.enrich(ir_document, harvest_data)
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger

from src.tools.biomedical_normalization import (
    normalize_drug_class,
    extract_normalized_targets,
)

from ..ir.schema import (
    IRDocument, Chapter, ChapterBlock, BlockType,
)


# ─────────────────────────────────────────────────────────────────────────────
# Color palette
# ─────────────────────────────────────────────────────────────────────────────
PALETTE = ["#4A90E2", "#E85D75", "#50C878", "#FFB347", "#9B59B6", "#3498DB",
           "#E67E22", "#16A085", "#F39C12", "#D35400"]


class ChartInjector:
    """从 harvest 数据自动创建图表/表格 block 并注入 IR 章节。"""

    def enrich(
        self,
        doc: IRDocument,
        harvest_data: Optional[Dict[str, Any]] = None,
    ) -> IRDocument:
        """
        主入口：扫描文档，根据证据数据补充图表。

        Args:
            doc: IR 文档
            harvest_data: 结构化 harvest 数据
        """
        harvest_data = harvest_data or {}

        for chapter in doc.chapters:
            has_visual = any(
                b.type in (BlockType.CHART, BlockType.TABLE, BlockType.IMAGE, BlockType.WORDCLOUD)
                for b in chapter.blocks
            )
            if not has_visual:
                self._auto_inject_visuals(chapter, harvest_data)

        # 生成全局统计仪表盘（如果存在 harvest 汇总数据）
        if harvest_data:
            self._inject_summary_dashboard(doc, harvest_data)
            self._inject_core_biomedical_charts(doc, harvest_data)

        return doc

    # ─── 自动注入可视化元素 ────────────────────────────────────────────────

    def _auto_inject_visuals(
        self,
        chapter: Chapter,
        evidence: Dict[str, Any],
    ) -> None:
        """为缺少图表的章节自动注入"""
        title_lower = chapter.title.lower()

        # 根据章节标题匹配适合的图表类型
        if any(kw in title_lower for kw in ["drug class", "modality", "class landscape"]):
            class_chart = self._make_drug_class_chart(evidence)
            if class_chart:
                chapter.blocks.append(class_chart)

        elif any(kw in title_lower for kw in ["asset catalog", "drug asset", "catalog"]):
            asset_table = self._make_asset_catalog_table(evidence)
            if asset_table:
                chapter.blocks.append(asset_table)

            stage_chart = self._make_phase_chart(evidence)
            if stage_chart:
                chapter.blocks.append(stage_chart)

        elif any(kw in title_lower for kw in ["target and mechanism", "target map", "mechanism"]):
            target_chart = self._make_target_signal_chart(evidence)
            if target_chart:
                chapter.blocks.append(target_chart)

        elif any(kw in title_lower for kw in ["company", "sponsor landscape", "sponsor"]):
            sponsor_chart = self._make_sponsor_chart(evidence)
            if sponsor_chart:
                chapter.blocks.append(sponsor_chart)

            sponsor_table = self._make_company_overview_table(evidence)
            if sponsor_table:
                chapter.blocks.append(sponsor_table)

        elif any(kw in title_lower for kw in ["clinical progress", "trial data matrix", "clinical matrix"]):
            phase_chart = self._make_phase_chart(evidence)
            if phase_chart:
                chapter.blocks.append(phase_chart)

            trial_matrix = self._make_trial_matrix_table(evidence)
            if trial_matrix:
                chapter.blocks.append(trial_matrix)

        elif any(kw in title_lower for kw in ["clinical trial", "trial audit", "trial"]):
            chart = self._make_trial_chart(evidence)
            if chart:
                chapter.blocks.append(chart)

        elif any(kw in title_lower for kw in ["safety", "adverse", "toxicity", "side effect"]):
            chart = self._make_safety_chart(evidence)
            if chart:
                chapter.blocks.append(chart)

        elif any(kw in title_lower for kw in ["efficacy", "endpoint", "outcome"]):
            chart = self._make_efficacy_chart(evidence)
            if chart:
                chapter.blocks.append(chart)

        elif any(kw in title_lower for kw in ["risk", "assessment", "score"]):
            chart = self._make_risk_radar(evidence)
            if chart:
                chapter.blocks.append(chart)

        elif any(kw in title_lower for kw in ["literature", "publication", "evidence"]):
            table = self._make_literature_table(evidence)
            if table:
                chapter.blocks.append(table)

        logger.debug(f"Auto-inject done for chapter: {chapter.title}")

    # ─── 图表生成器 ─────────────────────────────────────────────────────────

    def _iter_harvest_records(self, evidence: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Return normalized harvested records list."""
        records = evidence.get("harvested_data", [])
        if isinstance(records, dict):
            records = records.get("results", [])
        if not isinstance(records, list):
            return []
        return [r for r in records if isinstance(r, dict)]

    def _pick_field(self, record: Dict[str, Any], keys: List[str], default: str = "") -> str:
        """Pick a scalar field from record or nested metadata."""
        metadata = record.get("metadata", {}) if isinstance(record.get("metadata"), dict) else {}
        for key in keys:
            value = record.get(key)
            if value in (None, ""):
                value = metadata.get(key)
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value if v)
            if value not in (None, ""):
                return str(value)
        return default

    def _infer_drug_class(self, record: Dict[str, Any]) -> str:
        """Infer drug class/modality from intervention text using conservative heuristics."""
        text = " ".join(
            [
                self._pick_field(record, ["interventions", "intervention", "asset_name", "compound_name", "title"]),
                self._pick_field(record, ["mechanism", "moa", "modality", "platform"]),
            ]
        )
        explicit = self._pick_field(record, ["drug_class", "modality", "platform"], default="")
        return normalize_drug_class(text, explicit_label=explicit)

    def _make_drug_class_chart(self, evidence: Dict) -> Optional[ChapterBlock]:
        """Drug class/modality distribution chart for disease-oriented review."""
        records = self._iter_harvest_records(evidence)
        if not records:
            return None

        counts: Dict[str, int] = {}
        for rec in records:
            cls = self._infer_drug_class(rec)
            counts[cls] = counts.get(cls, 0) + 1

        labels = [k for k, v in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:8] if v > 0]
        data = [counts[k] for k in labels]
        if len(labels) < 2:
            return None

        return ChapterBlock(
            type=BlockType.CHART,
            content={
                "type": "doughnut",
                "title": "Drug Class / Modality Distribution",
                "caption": f"Disease-oriented class distribution across {sum(data)} harvested records",
                "labels": labels,
                "datasets": [{
                    "label": "Assets",
                    "data": data,
                    "backgroundColor": PALETTE[:len(labels)],
                }],
            },
            metadata={"auto_generated": True},
        )

    def _normalize_baseline_name(self, raw_name: str) -> str:
        """Normalize intervention/asset names into concise baseline labels."""
        text = (raw_name or "").strip()
        if not text:
            return "Unknown"

        # Keep only the first intervention item to avoid long concatenations.
        parts = [p.strip() for p in re.split(r"[;,|]", text) if p.strip()]
        text = parts[0] if parts else text

        # Remove dosage/form noise and bracketed details.
        text = re.sub(r"\([^)]*\)", "", text)
        text = re.sub(r"\b\d+(?:\.\d+)?\s*(?:mg|g|ml|mcg|μg|ug|iu)\b", "", text, flags=re.I)
        text = re.sub(r"\b(?:iv|po|qd|bid|tid|q\d+h)\b", "", text, flags=re.I)
        text = re.sub(r"\s+", " ", text).strip(" -_/")

        if not text:
            return "Unknown"

        return text[:42]

    def _make_drug_baseline_chart(self, evidence: Dict) -> Optional[ChapterBlock]:
        """Top intervention/asset baselines chart for concise report overview."""
        records = self._iter_harvest_records(evidence)
        if not records:
            return None

        counter: Dict[str, int] = {}
        for rec in records:
            baseline_raw = self._pick_field(
                rec,
                ["interventions", "intervention", "asset_name", "compound_name", "title"],
                "Unknown",
            )
            baseline = self._normalize_baseline_name(baseline_raw)
            if baseline:
                counter[baseline] = counter.get(baseline, 0) + 1

        ranked = [(k, v) for k, v in sorted(counter.items(), key=lambda x: x[1], reverse=True)[:8] if v > 0]
        if len(ranked) < 2:
            return None

        labels = [name for name, _ in ranked]
        data = [count for _, count in ranked]

        return ChapterBlock(
            type=BlockType.CHART,
            content={
                "type": "bar",
                "title": "Top Drug Baselines",
                "caption": "Most frequent intervention/asset baselines in harvested evidence",
                "labels": labels,
                "datasets": [{
                    "label": "Record Count",
                    "data": data,
                    "backgroundColor": PALETTE[:len(labels)],
                }],
            },
            metadata={"auto_generated": True},
        )

    def _make_asset_catalog_table(self, evidence: Dict) -> Optional[ChapterBlock]:
        """Asset catalog table with baseline fields requested by disease-oriented review."""
        records = self._iter_harvest_records(evidence)
        if not records:
            return None

        rows: List[List[str]] = []
        for rec in records[:14]:
            asset = self._pick_field(rec, ["interventions", "intervention", "asset_name", "compound_name", "title"], "Unknown")
            target_terms = extract_normalized_targets(
                " ; ".join(
                    [
                        self._pick_field(rec, ["target", "targets", "target_description"], ""),
                        self._pick_field(rec, ["mechanism", "moa"], ""),
                    ]
                )
            )
            target = ", ".join(target_terms[:3]) if target_terms else "Insufficient data"
            sponsor = self._pick_field(rec, ["sponsor", "company", "developer"], "Insufficient data")
            phase = self._pick_field(rec, ["phase", "phases", "clinical_phase", "development_stage"], "Insufficient data")
            status = self._pick_field(rec, ["status", "study_status", "overall_status"], "Insufficient data")
            ref_id = self._pick_field(rec, ["nct_id", "nct_number", "pmid", "pmcid"], "N/A")

            rows.append([
                asset[:52],
                self._infer_drug_class(rec),
                target[:42],
                sponsor[:32],
                phase[:16],
                status[:18],
                ref_id[:20],
            ])

        if not rows:
            return None

        return ChapterBlock(
            type=BlockType.TABLE,
            content={
                "headers": ["Asset", "Class/Modality", "Target", "Sponsor", "Phase", "Status", "NCT/PMID"],
                "rows": rows,
                "caption": "Disease-focused asset catalog (baseline fields)",
            },
            metadata={"auto_generated": True},
        )

    def _make_target_signal_chart(self, evidence: Dict) -> Optional[ChapterBlock]:
        """Target mention frequency chart."""
        records = self._iter_harvest_records(evidence)
        if not records:
            return None

        counts: Dict[str, int] = {}
        for rec in records:
            target_text = " ; ".join(
                [
                    self._pick_field(rec, ["target", "targets", "target_description"], ""),
                    self._pick_field(rec, ["mechanism", "moa"], ""),
                    self._pick_field(rec, ["interventions", "intervention"], ""),
                ]
            )
            for term in extract_normalized_targets(target_text):
                counts[term] = counts.get(term, 0) + 1

        if not counts:
            return None

        ranked = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:8]
        labels = [name for name, _ in ranked]
        data = [count for _, count in ranked]

        if len(labels) < 2:
            return None

        return ChapterBlock(
            type=BlockType.CHART,
            content={
                "type": "bar",
                "title": "Target Evidence Frequency",
                "caption": "Top target mentions across harvested disease evidence",
                "labels": labels,
                "datasets": [{
                    "label": "Mention Count",
                    "data": data,
                    "backgroundColor": PALETTE[:len(labels)],
                }],
            },
            metadata={"auto_generated": True},
        )

    def _make_sponsor_chart(self, evidence: Dict) -> Optional[ChapterBlock]:
        """Sponsor distribution chart."""
        records = self._iter_harvest_records(evidence)
        if not records:
            return None

        counts: Dict[str, int] = {}
        for rec in records:
            sponsor = self._pick_field(rec, ["sponsor", "company", "developer"], "Insufficient data")
            counts[sponsor] = counts.get(sponsor, 0) + 1

        ranked = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:8]
        labels = [name for name, _ in ranked]
        data = [count for _, count in ranked]

        if len(labels) < 2:
            return None

        return ChapterBlock(
            type=BlockType.CHART,
            content={
                "type": "bar",
                "title": "Sponsor / Company Distribution",
                "caption": "Count of disease-relevant records by sponsor",
                "labels": labels,
                "datasets": [{
                    "label": "Records",
                    "data": data,
                    "backgroundColor": PALETTE[:len(labels)],
                }],
            },
            metadata={"auto_generated": True},
        )

    def _make_company_overview_table(self, evidence: Dict) -> Optional[ChapterBlock]:
        """Compact company overview table using available sponsor signals."""
        records = self._iter_harvest_records(evidence)
        if not records:
            return None

        by_sponsor: Dict[str, Dict[str, Any]] = {}
        for rec in records:
            sponsor = self._pick_field(rec, ["sponsor", "company", "developer"], "Insufficient data")
            slot = by_sponsor.setdefault(sponsor, {"count": 0, "phases": set(), "statuses": set()})
            slot["count"] += 1
            phase = self._pick_field(rec, ["phase", "phases", "clinical_phase", "development_stage"], "")
            status = self._pick_field(rec, ["status", "study_status", "overall_status"], "")
            if phase:
                slot["phases"].add(phase)
            if status:
                slot["statuses"].add(status)

        rows: List[List[str]] = []
        for sponsor, info in sorted(by_sponsor.items(), key=lambda x: x[1]["count"], reverse=True)[:10]:
            rows.append([
                sponsor[:36],
                str(info["count"]),
                ", ".join(sorted(info["phases"]))[:38] or "Insufficient data",
                ", ".join(sorted(info["statuses"]))[:38] or "Insufficient data",
                "Evidence-derived sponsor footprint",
            ])

        if not rows:
            return None

        return ChapterBlock(
            type=BlockType.TABLE,
            content={
                "headers": ["Company/Sponsor", "Records", "Observed Phases", "Observed Statuses", "Company Snapshot"],
                "rows": rows,
                "caption": "Sponsor landscape and pipeline footprint (evidence-derived)",
            },
            metadata={"auto_generated": True},
        )

    def _make_phase_chart(self, evidence: Dict) -> Optional[ChapterBlock]:
        """Clinical phase distribution chart."""
        records = self._iter_harvest_records(evidence)
        if not records:
            return None

        counts: Dict[str, int] = {}
        for rec in records:
            phase = self._pick_field(rec, ["phase", "phases", "clinical_phase", "development_stage"], "Unspecified")
            counts[phase] = counts.get(phase, 0) + 1

        ranked = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:8]
        labels = [name for name, _ in ranked]
        data = [count for _, count in ranked]
        if len(labels) < 2:
            return None

        return ChapterBlock(
            type=BlockType.CHART,
            content={
                "type": "bar",
                "title": "Clinical Development Stage Distribution",
                "caption": "Distribution of assets/trials by observed clinical stage",
                "labels": labels,
                "datasets": [{
                    "label": "Count",
                    "data": data,
                    "backgroundColor": PALETTE[:len(labels)],
                }],
            },
            metadata={"auto_generated": True},
        )

    def _make_trial_matrix_table(self, evidence: Dict) -> Optional[ChapterBlock]:
        """Clinical trial matrix with key fields requested by disease-oriented framework."""
        records = self._iter_harvest_records(evidence)
        if not records:
            return None

        rows: List[List[str]] = []
        for rec in records[:12]:
            nct_id = self._pick_field(rec, ["nct_id", "nct_number"], "N/A")
            if nct_id == "N/A" and self._pick_field(rec, ["source"], "") != "ClinicalTrials.gov":
                continue

            rows.append([
                nct_id[:16],
                self._pick_field(rec, ["title"], "Unknown")[:46],
                self._pick_field(rec, ["phase", "phases"], "Insufficient data")[:16],
                self._pick_field(rec, ["status", "study_status", "overall_status"], "Insufficient data")[:20],
                self._pick_field(rec, ["enrollment"], "Insufficient data")[:12],
                self._pick_field(rec, ["primary_outcome_measures"], "Insufficient data")[:34],
                self._pick_field(rec, ["secondary_outcome_measures"], "Insufficient data")[:28],
                self._pick_field(rec, ["sponsor", "company", "developer"], "Insufficient data")[:24],
            ])

        if not rows:
            return None

        return ChapterBlock(
            type=BlockType.TABLE,
            content={
                "headers": ["NCT", "Title", "Phase", "Status", "Enroll", "Primary EP", "Secondary EP", "Sponsor"],
                "rows": rows,
                "caption": "Clinical trial data matrix (field-level overview)",
            },
            metadata={"auto_generated": True},
        )

    def _make_trial_chart(self, evidence: Dict) -> Optional[ChapterBlock]:
        """临床试验状态分布柱状图"""
        trials = evidence.get("trials", evidence.get("harvested_data", []))
        if not trials:
            return None

        status_counts: Dict[str, int] = {}
        for trial in trials:
            status = trial.get("status", trial.get("overall_status", "Unknown"))
            status_counts[status] = status_counts.get(status, 0) + 1

        if len(status_counts) < 2:
            return None

        labels = list(status_counts.keys())
        data = list(status_counts.values())
        colors = PALETTE[:len(labels)]

        return ChapterBlock(
            type=BlockType.CHART,
            content={
                "type": "bar",
                "title": "Clinical Trial Status Distribution",
                "caption": f"Distribution of {sum(data)} clinical trials by status",
                "labels": labels,
                "datasets": [{
                    "label": "Number of Trials",
                    "data": data,
                    "backgroundColor": colors,
                }],
            },
            metadata={"auto_generated": True},
        )

    def _make_safety_chart(self, evidence: Dict) -> Optional[ChapterBlock]:
        """不良反应等级饼图"""
        risk_flags = evidence.get("risk_flags", [])
        if not risk_flags:
            return None

        # 按严重程度分类
        severity = {"High": 0, "Moderate": 0, "Low": 0}
        for flag in risk_flags:
            flag_str = str(flag).lower()
            if any(w in flag_str for w in ["severe", "fatal", "death", "grade 4", "grade 5", "sae"]):
                severity["High"] += 1
            elif any(w in flag_str for w in ["moderate", "grade 3", "discontinu"]):
                severity["Moderate"] += 1
            else:
                severity["Low"] += 1

        labels = [k for k, v in severity.items() if v > 0]
        data = [v for v in severity.values() if v > 0]
        if not data:
            return None

        return ChapterBlock(
            type=BlockType.CHART,
            content={
                "type": "doughnut",
                "title": "Safety Signal Severity Distribution",
                "caption": f"Classification of {sum(data)} identified safety signals",
                "labels": labels,
                "datasets": [{
                    "label": "Safety Signals",
                    "data": data,
                    "backgroundColor": ["#E85D75", "#FFB347", "#50C878"][:len(labels)],
                }],
            },
            metadata={"auto_generated": True},
        )

    def _make_efficacy_chart(self, evidence: Dict) -> Optional[ChapterBlock]:
        """疗效数据柱状图"""
        papers = evidence.get("text_evidence", evidence.get("pubmed_papers", []))
        if not papers:
            return None

        return ChapterBlock(
            type=BlockType.CHART,
            content={
                "type": "bar",
                "title": "Evidence Source Distribution",
                "caption": "Number of evidence items by category",
                "labels": ["PubMed Papers", "Clinical Trials", "Risk Flags", "PMC Full-Text"],
                "datasets": [{
                    "label": "Count",
                    "data": [
                        len(evidence.get("text_evidence", [])),
                        len(evidence.get("harvested_data", evidence.get("trials", []))),
                        len(evidence.get("risk_flags", [])),
                        len(evidence.get("pmc_articles", [])),
                    ],
                    "backgroundColor": PALETTE[:4],
                }],
            },
            metadata={"auto_generated": True},
        )

    def _make_risk_radar(self, evidence: Dict) -> Optional[ChapterBlock]:
        """风险评估雷达图"""
        risk_flags = evidence.get("risk_flags", [])
        if len(risk_flags) < 3:
            return None

        # 构造维度
        dimensions = {
            "Clinical Safety": 0,
            "Efficacy Concern": 0,
            "Data Integrity": 0,
            "Regulatory Risk": 0,
            "Market Risk": 0,
        }
        for flag in risk_flags:
            flag_str = str(flag).lower()
            if any(w in flag_str for w in ["safety", "adverse", "toxicity", "death"]):
                dimensions["Clinical Safety"] += 1
            if any(w in flag_str for w in ["efficacy", "endpoint", "fail", "miss"]):
                dimensions["Efficacy Concern"] += 1
            if any(w in flag_str for w in ["integrity", "fraud", "retract", "manipulat"]):
                dimensions["Data Integrity"] += 1
            if any(w in flag_str for w in ["fda", "ema", "regulat", "approv", "reject"]):
                dimensions["Regulatory Risk"] += 1
            if any(w in flag_str for w in ["market", "compet", "patent", "generic"]):
                dimensions["Market Risk"] += 1

        # 归一化到 0-10 评分
        max_val = max(dimensions.values()) or 1
        scores = [round(v / max_val * 10, 1) for v in dimensions.values()]

        return ChapterBlock(
            type=BlockType.CHART,
            content={
                "type": "radar",
                "title": "Multi-Dimensional Risk Assessment",
                "caption": f"Risk profile based on {len(risk_flags)} identified signals",
                "labels": list(dimensions.keys()),
                "datasets": [{
                    "label": "Risk Score",
                    "data": scores,
                    "backgroundColor": "rgba(74, 144, 226, 0.15)",
                    "borderColor": "#4A90E2",
                }],
            },
            metadata={"auto_generated": True},
        )

    def _make_literature_table(self, evidence: Dict) -> Optional[ChapterBlock]:
        """文献证据汇总表"""
        papers = evidence.get("text_evidence", evidence.get("pubmed_papers", []))
        if not papers:
            return None

        rows = []
        for p in papers[:10]:  # 最多 10 篇
            if isinstance(p, dict):
                rows.append([
                    str(p.get("title", p.get("source", "")))[:60],
                    str(p.get("journal", p.get("source_type", "")))[:30],
                    str(p.get("pub_date", p.get("year", "")))[:10],
                    str(p.get("key_finding", p.get("finding", "")))[:80],
                ])
            elif isinstance(p, str):
                rows.append([p[:60], "", "", ""])

        if not rows:
            return None

        return ChapterBlock(
            type=BlockType.TABLE,
            content={
                "headers": ["Title", "Source", "Date", "Key Finding"],
                "rows": rows,
                "caption": f"Summary of {len(rows)} key literature findings",
            },
            metadata={"auto_generated": True},
        )

    # ─── Summary Dashboard ─────────────────────────────────────────────────

    def _inject_summary_dashboard(
        self, doc: IRDocument, evidence: Dict[str, Any]
    ) -> None:
        """在 Executive Summary 章节注入 KPI 仪表盘"""
        # 寻找 Executive Summary 章节
        exec_ch = None
        for ch in doc.chapters:
            if any(kw in ch.title.lower() for kw in ["executive", "summary", "overview"]):
                exec_ch = ch
                break

        if exec_ch is None:
            return

        # 检查是否已有 dashboard
        if any(b.metadata.get("dashboard") for b in exec_ch.blocks):
            return

        harvested = evidence.get("harvested_data", evidence.get("trials", []))
        if not isinstance(harvested, list):
            harvested = []

        trials_count = sum(
            1
            for rec in harvested
            if isinstance(rec, dict)
            and (
                rec.get("source") == "ClinicalTrials.gov"
                or rec.get("nct_id")
                or (isinstance(rec.get("metadata"), dict) and rec.get("metadata", {}).get("nct_id"))
            )
        )
        assets_count = len(harvested)
        papers_count = len(evidence.get("text_evidence", evidence.get("pubmed_papers", [])))

        class_count = len({
            self._infer_drug_class(rec)
            for rec in harvested
            if isinstance(rec, dict)
        })

        sponsor_count = len(
            {
                self._pick_field(rec, ["sponsor", "company", "developer"], "")
                for rec in harvested
                if isinstance(rec, dict)
            }
            - {""}
        )

        if assets_count + papers_count + trials_count == 0:
            return

        # 用 HTML 模板注入 KPI 卡片（作为 paragraph + raw HTML）
        kpi_html = (
            '<div class="kpi-grid">'
            f'<div class="kpi-card"><div class="kpi-value">{assets_count}</div>'
            f'<div class="kpi-label">Total Assets/Records</div></div>'
            f'<div class="kpi-card"><div class="kpi-value">{class_count}</div>'
            f'<div class="kpi-label">Drug Classes</div></div>'
            f'<div class="kpi-card"><div class="kpi-value">{sponsor_count}</div>'
            f'<div class="kpi-label">Sponsors</div></div>'
            f'<div class="kpi-card"><div class="kpi-value">{trials_count}</div>'
            f'<div class="kpi-label">Clinical Trials</div></div>'
            '</div>'
        )

        dashboard_block = ChapterBlock(
            type=BlockType.PARAGRAPH,
            content=kpi_html,
            metadata={"dashboard": True, "raw_html": True, "auto_generated": True},
        )

        # 插入到章节开头（标题之后）
        insert_pos = 0
        for i, b in enumerate(exec_ch.blocks):
            if b.type == BlockType.HEADING:
                insert_pos = i + 1
                break

        exec_ch.blocks.insert(insert_pos, dashboard_block)
        logger.info(f"📊 Injected KPI dashboard into '{exec_ch.title}'")

    def _find_summary_chapter(self, doc: IRDocument) -> Optional[Chapter]:
        """Return the best chapter for concise biomedical summary charts."""
        for ch in doc.chapters:
            if any(kw in ch.title.lower() for kw in ["executive", "summary", "overview"]):
                return ch
        return doc.chapters[0] if doc.chapters else None

    def _inject_core_biomedical_charts(self, doc: IRDocument, evidence: Dict[str, Any]) -> None:
        """
        Ensure report always contains core concise charts:
        1) Drug class distribution
        2) Drug baseline distribution
        3) Target signal frequency
        """
        target_chapter = self._find_summary_chapter(doc)
        if target_chapter is None:
            return

        existing_chart_titles = {
            str((b.content or {}).get("title", "")).strip().lower()
            for b in target_chapter.blocks
            if b.type == BlockType.CHART and isinstance(b.content, dict)
        }

        builders = [
            self._make_drug_class_chart,
            self._make_drug_baseline_chart,
            self._make_target_signal_chart,
        ]

        inserted = 0
        for builder in builders:
            block = builder(evidence)
            if not block:
                continue
            chart_title = str((block.content or {}).get("title", "")).strip().lower()
            if chart_title and chart_title in existing_chart_titles:
                continue
            block.metadata = {**(block.metadata or {}), "summary_chart": True, "auto_generated": True}
            target_chapter.blocks.append(block)
            if chart_title:
                existing_chart_titles.add(chart_title)
            inserted += 1

        if inserted:
            logger.info(f"📈 Injected {inserted} core biomedical summary charts into '{target_chapter.title}'")
