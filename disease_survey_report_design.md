# Disease Survey Report Redesign — Design Document

> Date: 2026-04-17
> Author: Cassandra Engineering
> Status: Draft — Pending Review

## 1. Problem Statement

当前 `ReportWriterAgent._render_markdown()` 生成的疾病综合调研报告存在严重可读性问题：
- 97 条 harvest 记录以标题 + raw JSON metadata 平铺展示，无结构化汇总
- 缺少按药物/靶点/公司/临床阶段等维度的聚合分析
- 未生成任何统计图表（项目已有 chart_to_svg 能力）
- 关键信息（主流药物、靶点、研发公司、临床数据）不直观

## 2. Design Goals

- **科研导向**：服务科研人群，弱化金融/投资色彩，强化药物机制、靶点通路、临床数据
- **多维度表格 + 全量图表**：每个分析维度配备结构化表格和对应统计图
- **CNS 基准对照**：将当前疾病靶点放到 CNS 领域近5年大背景下做 benchmark，顶刊背书
- **疾病无关**：通用框架，AD 只是实例，适用于任意疾病查询
- **低耦合高内聚**：新模块与现有代码最小接触面
- **轻量化**：新增文件控制在 4 个，不引入重型框架
- **PokieTicker 预留**：财务字段按完整结构设计，当前渲染只消费已有数据

## 3. Architecture

### 3.1 Module Structure

```
src/engines/report_engine/disease_survey/
├── __init__.py          # 导出 generate_disease_survey_report()
├── models.py            # DiseaseSurveyState + 全新数据模型
├── aggregator.py        # 纯函数：harvest rows → 结构化聚合
└── renderer.py          # state → IR chapters (blocks: table/kpiGrid/widget-chart)
```

### 3.2 Data Flow

```
harvest_payload (dict)
    → aggregator.aggregate_survey_data(rows, query)
        → DiseaseSurveyState (Pydantic model)
    → renderer.render_to_ir_chapters(state)
        → List[Chapter IR dicts]
    → DocumentComposer.build_document(...)
        → 现有渲染管线 (HTML/PDF + chart_to_svg)
```

### 3.3 Dependency Rules

- `disease_survey` 只依赖 IR schema 的 block 类型定义和 `chart_to_svg` 的 widget 数据格式
- `aggregator.py` 零外部依赖（纯 Python + Pydantic），可独立单测
- `renderer.py` 只依赖 `models.py` 和 IR block 常量，不依赖 `aggregator.py`
- 与 `ReportWriterAgent` 的唯一接触点是 `__init__.py` 导出的 `generate_disease_survey_report()`

## 4. Data Models (models.py)

### 4.1 DrugAsset

| Field | Type | Description |
|-------|------|-------------|
| asset_name | str | 药物名称 |
| aliases | List[str] | 别名列表 |
| modality | str | 药物模态（小分子/抗体/基因治疗等） |
| targets | List[str] | 作用靶点列表 |
| sponsor | str | 研发公司 |
| phase | Optional[str] | 最高临床阶段 |
| status | Optional[str] | 开发状态 |
| trial_ids | List[str] | 关联 NCT ID |
| indication_subtype | Optional[str] | 适应症亚型 |

### 4.2 TrialRecord

| Field | Type | Description |
|-------|------|-------------|
| nct_id | str | ClinicalTrials.gov ID |
| title | str | 试验标题 |
| asset_name | Optional[str] | 试验药物 |
| sponsor | Optional[str] | 申办方 |
| phase | Optional[str] | 临床阶段 |
| status | Optional[str] | 试验状态 |
| enrollment | Optional[str] | 入组人数 |
| primary_endpoint | Optional[str] | 主要终点 |
| secondary_endpoint | Optional[str] | 次要终点 |
| ae_grade3plus | Optional[str] | ≥3级不良事件 |
| sae | Optional[str] | 严重不良事件 |

### 4.3 SponsorProfile

| Field | Type | Description |
|-------|------|-------------|
| company_name | str | 公司名称 |
| pipeline_count | int | 管线数量 |
| lead_phase | Optional[str] | 最高阶段管线 |
| ticker | Optional[str] | 股票代码（PokieTicker 预留） |
| market_cap | Optional[float] | 市值（预留） |
| cash_runway_months | Optional[float] | 现金跑道（预留） |
| rd_ratio | Optional[float] | 研发占比（预留） |

### 4.4 CNSBenchmarkEntry

| Field | Type | Description |
|-------|------|-------------|
| target_name | str | 靶点名称 |
| publication_count_5yr | int | 近5年发表数量 |
| trial_count_5yr | int | 近5年临床试验数 |
| top_journal_citations | int | 顶刊引用数 |
| trend | str | rising / stable / declining |
| matched | bool | 是否与当前疾病靶点匹配 |

### 4.5 LiteratureRecord

| Field | Type | Description |
|-------|------|-------------|
| pmid | str | PubMed ID |
| title | str | 文献标题 |
| journal | Optional[str] | 期刊名 |
| year | Optional[int] | 发表年份 |
| authors | Optional[str] | 作者 |
| doi | Optional[str] | DOI |
| relevance_tag | Optional[str] | 相关性标签 |

### 4.6 DiseaseSurveyState (Top-level Container)

| Field | Type | Description |
|-------|------|-------------|
| disease_name | str | 疾病名称 |
| query | str | 原始查询 |
| drug_assets | List[DrugAsset] | 药物资产列表 |
| trials | List[TrialRecord] | 临床试验列表 |
| sponsors | List[SponsorProfile] | 公司列表 |
| literature | List[LiteratureRecord] | 文献列表 |
| cns_benchmark | List[CNSBenchmarkEntry] | CNS 基准对照 |
| summary_text | Optional[str] | 5句话总结 |
| generated_at | datetime | 生成时间 |
| metadata | Dict[str, Any] | 扩展元数据 |

## 5. Report Chapter Structure

| # | Chapter | Block Types | Charts |
|---|---------|-------------|--------|
| 0 | Executive Summary | kpiGrid + paragraph | 无（5句话 + 4个KPI卡片） |
| 1 | 疾病图谱 | paragraph + callout | 无（文字 + callout 标注未满足需求） |
| 2 | 药物资产全景 | table + widget(pie) + widget(bar) | 靶点分布饼图 + 药物模态分布柱状图 |
| 3 | 临床管线矩阵 | table + widget(bar) + widget(doughnut) | Phase 分布柱状图 + 试验状态圆环图 |
| 4 | 文献证据分析 | table + widget(line) + widget(pie) | 发表年份趋势折线图 + 来源分布饼图 |
| 5 | CNS 靶点基准对照 | table + widget(radar) + callout | 靶点匹配度雷达图 + 顶刊背书标注 |
| 6 | 竞争格局 | table + widget(bubble) | 公司-资产气泡图(x=phase, y=trial数, r=管线规模) |
| 7 | 公司概览 | table | 无（简要表格，财务字段预留） |
| 8 | 参考文献 | table | 无 |

### 5.1 KPI Cards (Chapter 0)

- Harvest 记录总数
- 覆盖靶点数
- 临床试验数
- 主流药物数

### 5.2 5-Sentence Summary Strategy

1. `aggregator.py` 从统计数据中提取关键事实（top 靶点、top phase、试验数量等）
2. 如果 LLM client 可用，调用 LLM 精炼为5句话自然语言摘要
3. Fallback：用模板拼接确定性摘要

### 5.3 CNS Benchmark Data Source

- 从 harvest 数据中已有的 PubMed 记录提取（journal 字段判断是否顶刊）
- `aggregator.py` 维护 `TOP_CNS_JOURNALS` 常量列表：
  - Nature Neuroscience, Lancet Neurology, NEJM, Brain, Annals of Neurology,
    Molecular Neurodegeneration, Acta Neuropathologica, Neuron, Cell Stem Cell 等
- 时间窗口：publication year >= 2021（近5年）

### 5.4 Empty Data Handling

某章节数据列表为空时，生成 callout block（tone: "info"）提示"当前 harvest 数据中未检测到相关记录"，不跳过章节。

## 6. Aggregator Functions (aggregator.py)

```python
def aggregate_survey_data(rows: List[Dict], query: str) -> DiseaseSurveyState
def group_by_target(assets: List[DrugAsset]) -> Dict[str, List[DrugAsset]]
def group_by_phase(trials: List[TrialRecord]) -> Dict[str, int]
def group_by_sponsor(assets: List[DrugAsset]) -> Dict[str, SponsorProfile]
def compute_publication_trend(literature: List[LiteratureRecord], window: int = 5) -> Dict[int, int]
def compute_cns_benchmark(literature: List[LiteratureRecord], targets: List[str]) -> List[CNSBenchmarkEntry]
def build_chart_data(group_data: Dict, chart_type: str) -> Dict  # 返回 Chart.js data 格式 {labels, datasets}
```

### 6.1 aggregate_survey_data 主流程

1. 遍历 harvest rows，按 source 分流：PubMed → LiteratureRecord，ClinicalTrials → TrialRecord
2. 从 trial metadata 提取药物资产 → DrugAsset（解析 intervention 字段）
3. 从 DrugAsset 聚合 sponsor → SponsorProfile
4. 调用 compute_cns_benchmark() 生成基准对照
5. 组装 DiseaseSurveyState

### 6.2 Target Extraction

- 靶点从 title + summary 用关键词匹配提取
- 维护 `KNOWN_CNS_TARGETS` 字典（Aβ, Tau, BACE1, mGluR5, NMDA, α-synuclein, TREM2, CD33, SV2A 等）
- 优先调用项目已有的 `biomedical_normalization.py` 或 `scispacy_ner_service.py` 做实体识别（如果可用）

### 6.3 Fault Tolerance

所有聚合函数对缺失字段返回空集合/None，不抛异常。

## 7. Renderer Design (renderer.py)

```python
def render_to_ir_chapters(state: DiseaseSurveyState) -> List[Dict]:
    """主入口"""

def _render_executive_summary(state) -> Dict    # kpiGrid + paragraph
def _render_disease_landscape(state) -> Dict    # paragraph + callout
def _render_drug_assets(state) -> Dict          # table + pie + bar
def _render_clinical_matrix(state) -> Dict      # table + bar + doughnut
def _render_literature(state) -> Dict           # table + line + pie
def _render_cns_benchmark(state) -> Dict        # table + radar + callout
def _render_competitive(state) -> Dict          # table + bubble
def _render_sponsors(state) -> Dict             # table
def _render_references(state) -> Dict           # table
```

### 7.1 Widget Block Format

```json
{
    "type": "widget",
    "widgetId": "chart-target-distribution",
    "widgetType": "chart.js/pie",
    "data": {
        "labels": ["Aβ", "Tau", "Neuroinflammation"],
        "datasets": [{"data": [12, 8, 5], "backgroundColor": ["#4A90E2", "#E85D75", "#50C878"]}]
    },
    "props": {"title": "药物靶点分布"}
}
```

直接被 `chart_to_svg.py` 的 `convert_widget_to_svg()` 消费，无需适配层。

### 7.2 Table Block Convention

- 第一行为 header
- 每个 cell 内嵌 paragraph block 的 inlines
- 临床矩阵表列：NCT ID / 药物名 / Sponsor / Phase / Status / Enrollment / Primary Endpoint / AE Grade 3+

## 8. Integration & Cleanup

### 8.1 Pipeline Routing

`ReportWriterAgent.write_report()` 增加路由：

```python
if self._is_disease_survey(rows):
    return self._write_disease_survey_report(rows, user_query, output_dir, ...)
# legacy fallback
return self._write_legacy_report(rows, user_query, ...)
```

`_is_disease_survey()` 判断：rows 中存在 nct_id 或 pmid 字段的记录占比 > 50%，且 rows 总数 >= 5。低于 5 条记录时 fallback 到 legacy 管线，避免小样本误判。

### 8.2 Cleanup Plan

| Item | Action | Timing |
|------|--------|--------|
| `_render_markdown()` harvest 平铺逻辑 | 新管线稳定后删除，保留 legacy fallback | Phase 2 |
| `_extract_signal_highlights()` | 迁移到 aggregator 后标记 deprecated | Phase 2 |
| `_compose_context_text()` raw JSON dump | legacy 路径仍用，暂保留 | Phase 3 |
| due_diligence.models 重叠模型 | 如 due_diligence 独立运行则不动 | 视合并情况 |

**原则：** 不做预防性删除。每个清理项在新代码实际替代旧逻辑后才执行。

## 9. PokieTicker Integration Readiness

`SponsorProfile` 模型预留完整财务字段（ticker, market_cap, cash_runway_months, rd_ratio），当前渲染时 Optional 字段为 null 则跳过展示。PokieTicker 清洗接入后，同一套模型直接填充，不需要改 schema。

## 10. Constraints

- 新增文件 ≤ 4 个
- 低耦合高内聚：模块间通过函数签名和 Pydantic 模型通信，不共享内部状态
- 图表类型限定为 chart_to_svg.py 已支持的类型（bar/line/pie/doughnut/radar/scatter/bubble）
- 近5年时间窗口（>= 2021）用于 CNS benchmark
- 5句话总结上限
- 疾病无关通用框架
