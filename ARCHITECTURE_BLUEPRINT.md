# 🏗️ Cassandra 完整架构蓝图

**更新日期**: 2026-04-22  
**版本**: 2.0 (完整深度分析)

---

## 📌 快速导航

| 部分 | 内容 |
|------|------|
| [系统概览](#-系统概览) | 项目定位、核心特性 |
| [Engine模块全景](#-engine模块全景) | 5大Engines的职责和位置 |
| [工作流架构](#-工作流架构) | LangGraph编排、6层节点 |
| [数据模型](#-数据模型) | AgentState、各类Models结构 |
| [完整数据流](#-完整数据流示例) | 从用户查询到报告输出的全链路 |
| [函数速查表](#-函数速查表) | 所有主函数的签名和用途 |
| [调用关系图](#-调用关系图) | 各模块相互调用的关系 |

---

## 🎯 系统概览

### **项目定位**
Cassandra 是一个**多Agent工作流编排平台**，专门用于：
- 生物医学文献和临床试验的**自动化采集**
- 多维度证据**聚合与分析**
- 疾病导向型**综合报告生成**

### **核心技术栈**
| 组件 | 技术 | 用途 |
|------|------|------|
| 编排引擎 | LangGraph | 6层DAG工作流 |
| LLM后端 | Google Gemini Pro | 文本生成、分析 |
| 数据采集 | Biopython + 多API | PubMed、ClinicalTrials.gov等 |
| 知识图谱 | Neo4j | 生物医学关系存储 |
| 状态管理 | Redis | 工作流检查点 |
| PDF处理 | PyMuPDF + WeasyPrint | 文本提取、转换 |

---

## 📊 Engine模块全景

### **Engine 位置和层级**

```
src/engines/
├── harvest/                          # Engine 1: 数据采集
│   ├── agent.py                      # BioHarvestAgent 总入口
│   ├── retriever/
│   │   ├── pubmed.py                 # PubMedRetriever
│   │   ├── europmc.py                # EuropePMCRetriever
│   │   ├── trials.py                 # ClinicalTrialsRetriever
│   │   └── enrichment.py             # MultiSourceEnricher
│   ├── llm/
│   │   └── query_parser.py           # QueryParser
│   └── config.py
│
├── evidence_synthesizer/             # Engine 2: 证据综合
│   ├── agent.py                      # EvidenceSynthesizerAgent
│   ├── processors/
│   │   ├── evidence_classifier.py
│   │   ├── endpoint_extractor.py
│   │   └── grade_calculator.py
│   └── models.py
│
├── clinical_analyzer/                # Engine 3: 临床分析
│   ├── agent.py                      # ClinicalAnalyzerAgent
│   ├── processors/
│   │   ├── pipeline_matrix.py
│   │   ├── safety_signal_detector.py
│   │   └── competition_analyzer.py
│   └── models.py
│
├── quality_assessor/                 # Engine 4: 质量评估
│   ├── agent.py                      # QualityAssessorAgent
│   ├── metrics/
│   │   ├── completeness.py
│   │   ├── diversity.py
│   │   └── confidence_grader.py
│   └── models.py
│
└── report_engine/                    # Engine 5: 报告生成
    ├── agent.py                      # ReportWriterAgent 总入口
    ├── core/
    │   ├── composer.py               # DiseaseSurveyComposer
    │   └── chapter_storage.py
    ├── disease_survey/
    │   ├── models.py                 # DiseaseSurveyState, DrugAsset等
    │   ├── aggregator.py             # aggregate_survey_data()
    │   ├── composer.py               # disease_survey_to_markdown()
    │   └── renderer.py               # render_*() 函数集合
    ├── due_diligence/
    │   ├── models.py                 # DiseaseProfile, PipelineData等
    │   ├── renderer.py
    │   ├── graph.py                  # 子工作流
    │   └── prompts.py
    ├── renderers/
    │   ├── html_renderer.py          # Markdown → HTML
    │   ├── pdf_renderer.py           # HTML → PDF
    │   └── markdown_renderer.py
    └── ir/
        ├── schema.py
        └── validator.py
```

### **Engine 核心函数表**

| Engine | 类名 | 主函数 | 职责 |
|--------|------|--------|------|
| **BioHarvestEngine** | `BioHarvestAgent` | `run(user_query, max_results)` | 采集文献、试验、PDF |
| **EvidenceSynthesizerEngine** | `EvidenceSynthesizerAgent` | `synthesize(data, layers)` | 分层证据、提取终点 |
| **ClinicalAnalyzerEngine** | `ClinicalAnalyzerAgent` | `analyze(data, payloads)` | 管线分析、安全信号 |
| **QualityAssessorEngine** | `QualityAssessorAgent` | `assess(data, slots)` | 质量评分、信心分级 |
| **ReportWriterEngine** | `ReportWriterAgent` | `write_report(payload)` | 报告生成、多格式输出 |

---

## 🔄 工作流架构

### **LangGraph 6层节点拓扑**

```
┌─────────┐
│  START  │
└────┬────┘
     │
     ▼
┌──────────────────────────────┐
│  harvester_node              │  ← BioHarvestAgent.run()
│  采集文献、试验、后续PDF      │
└────┬─────────────────────────┘
     │ outputs: harvested_data, pdf_paths, data_layers
     │
     ▼
┌──────────────────────────────┐
│  extension_handoff_node      │  ← 初始化extension_payloads
│  准备扩展Agent插槽           │
└────┬─────────────────────────┘
     │ outputs: extension_payloads {slot_a, slot_b, slot_c}
     │
     ▼
┌──────────────────────────────┐
│  evidence_synthesizer_node   │  ← EvidenceSynthesizerAgent
│  证据分层、端点提取、GRADE     │
└────┬─────────────────────────┘
     │ outputs: extension_payloads[slot_a] filled
     │
     ▼
┌──────────────────────────────┐
│  clinical_analyzer_node      │  ← ClinicalAnalyzerAgent
│  管线矩阵、安全信号           │
└────┬─────────────────────────┘
     │ outputs: extension_payloads[slot_b] filled
     │
     ▼
┌──────────────────────────────┐
│  quality_assessor_node       │  ← QualityAssessorAgent
│  质量评分、信心分级           │
└────┬─────────────────────────┘
     │ outputs: extension_payloads[slot_c] filled
     │
     ▼
┌──────────────────────────────┐
│  writer_node                 │  ← ReportWriterAgent.write_report()
│  路由选择 → 报告生成          │
└────┬─────────────────────────┘
     │ outputs: final_report, report_paths
     │
     ▼
┌──────────────────────────────┐
│  END                         │
└──────────────────────────────┘
```

### **节点编排文件**

| 节点 | 文件 | 函数 |
|------|------|------|
| harvester | `src/graph/nodes/harvester_node.py` | `harvester_node(state)` |
| extension_handoff | `src/graph/nodes/extension_handoff_node.py` | `extension_handoff_node(state)` |
| evidence_synthesizer | `src/graph/nodes/evidence_synthesizer_node.py` | `evidence_synthesizer_node(state)` |
| clinical_analyzer | `src/graph/nodes/clinical_analyzer_node.py` | `clinical_analyzer_node(state)` |
| quality_assessor | `src/graph/nodes/quality_assessor_node.py` | `quality_assessor_node(state)` |
| writer | `src/graph/nodes/writer_node.py` | `writer_node(state)` |

### **编排入口**

```python
# src/agents/supervisor.py

create_cassandra_workflow() → StateGraph
    # 构建并返回6层DAG工作流
    
run_cassandra_workflow(user_query, pdf_paths, checkpointer, thread_id) 
    → Dict[str, Any]
    # 同步执行工作流
    
stream_cassandra_workflow(user_query, ..., progress_callback)
    # 流式执行工作流，实时推送进度
```

---

## 📋 数据模型

### **1. 全局共享状态：AgentState**

**位置**: `src/graph/state.py`

```python
class AgentState(TypedDict):
    # ━━━ 核心工作流 ━━━
    user_query: str                              # 用户输入
    pdf_paths: Annotated[List[str], operator.add]  # 下载的PDF路径
    harvested_data: Annotated[List[Dict], ...]  # 采集的150条记录
    harvest_data_layers: Optional[Dict]         # 多层数据视图
    harvest_source_payloads: Optional[Dict]     # 多源原始payload
    extension_payloads: Optional[Dict]          # 扩展分析结果
    
    # ━━━ 输出 ━━━
    final_report: Optional[str]                 # Markdown最终报告
    final_report_path: Optional[str]            # Markdown保存路径
    final_report_html_path: Optional[str]       # HTML保存路径
    final_report_pdf_path: Optional[str]        # PDF保存路径
    
    # ━━━ 元数据 ━━━
    project_name: Optional[str]
    status: Optional[str]                       # workflow_complete等
    analysis_status: Optional[str]              # FULL_PIPELINE或HARVEST_ONLY
    biomedical_profile: Optional[Dict]          # 生物医学概览
    errors: Annotated[List[str], operator.add]  # 错误消息
```

### **2. 数据采集层：HarvestReport**

**位置**: `src/engines/harvest/schemas/`

```python
class HarvestReport(BaseModel):
    results: List[Dict]  # [{pmid, nct_id, title, source, summary, ...}, ...]
    
    stats: Dict = {
        "total": int,           # 150
        "pubmed": int,          # 80
        "trials": int,          # 40
        "pdfs_downloaded": int  # 15
    }
    
    data_layers: Dict = {
        "disease_layer": {...},     # 疾病相关信息
        "target_layer": {...},      # 靶点提取
        "pipeline_layer": {...},    # 药物管线
        "company_layer": {...}      # 赞助商
    }
    
    source_payloads: Dict = {
        "ncbi": {...},
        "openfda": {...}
    }
```

### **3. 疾病调查层：DiseaseSurveyState**

**位置**: `src/engines/report_engine/disease_survey/models.py`

```python
class DiseaseSurveyState(BaseModel):
    disease_name: str                       # "Alzheimer's Disease"
    query: str
    
    drug_assets: List[DrugAsset]           # 药物列表
    trials: List[TrialRecord]              # 试验列表
    sponsors: List[SponsorProfile]         # 赞助商列表
    literature: List[LiteratureRecord]     # 文献列表
    cns_benchmark: List[CNSBenchmarkEntry] # CNS基准
    
    summary_text: Optional[str]
    generated_at: datetime
    metadata: Dict[str, Any]
```

**DrugAsset 结构**:
```python
class DrugAsset(BaseModel):
    asset_name: str              # "Aducanumab"
    modality: str                # "Monoclonal Antibody"
    targets: List[str]           # ["AMYLOID-BETA"]
    sponsor: str                 # "Biogen"
    phase: Optional[str]         # "Phase III"
    status: Optional[str]        # "Completed"
    trial_ids: List[str]         # ["NCT03382135", ...]
```

**TrialRecord 结构**:
```python
class TrialRecord(BaseModel):
    nct_id: str                  # "NCT03382135"
    title: str
    asset_name: Optional[str]
    sponsor: Optional[str]
    phase: Optional[str]         # "Phase III"
    status: Optional[str]        # "Completed"
    enrollment: Optional[str]
    ae_grade3plus: Optional[str] # 3级+不良反应
    sae: Optional[str]           # 严重不良反应
```

**CNSBenchmarkEntry 结构**:
```python
class CNSBenchmarkEntry(BaseModel):
    target_name: str              # "Aβ", "Tau"
    publication_count_5yr: int    # 近5年发表数
    top_journal_citations: int    # 顶刊引用数
    trend: str                    # "rising", "stable", "declining"
    matched: bool                 # 是否与已知靶点匹配
```

### **4. 尽职调查层：DiseaseProfile等**

**位置**: `src/engines/report_engine/due_diligence/models.py`

```python
class DiseaseProfile(BaseModel):
    disease_name: str
    burden_summary: str          # 疾病负担描述
    unmet_need_summary: str      # 未满足需求概述

class PipelineData(BaseModel):
    asset_name: str
    moa_description: str         # 作用机制
    target_description: str
    indications: List[...]

class CompanyProfile(BaseModel):
    company_name: str
    management_summary: str
    cash_runway_months: Optional[float]
    rd_spend_ratio: Optional[float]
```

---

## 📍 完整数据流示例

### **用户查询：** 
```
"Conduct a comprehensive survey on Alzheimer disease"
```

### **Step 1: HARVESTER_NODE**

**流程**:
```
user_query
    ↓
BioHarvestAgent.run(user_query, max_results=30)
    ├─ A. QueryParser.parse() 
    │   → intent = {entity: "Alzheimer", queries: [...]}
    ├─ B. EuropePMCRetriever.retrieve(queries)
    │   → europmc_papers = [80 records]
    ├─ C. ClinicalTrialsRetriever.retrieve(queries)
    │   → trial_results = [40 records]
    ├─ D. MultiSourceEnricher.collect()
    │   → ncbi_data, openfda_data, etc.
    ├─ E. aggregate_data(pubmed, trials)
    │   → combined = [150 records, deduplicated]
    ├─ F. PdfDownloader.download_for_candidates()
    │   → downloaded_count = 15
    └─ G. build_data_layers()
        → {disease_layer, target_layer, pipeline_layer, company_layer}

RETURN: HarvestReport
{
    results: [150 records],
    stats: {total: 150, pubmed: 80, trials: 40, pdfs: 15},
    data_layers: {...},
    source_payloads: {...}
}
```

**State 更新**:
```python
state["harvested_data"] = [150 records]
state["harvest_data_layers"] = {...}
state["harvest_source_payloads"] = {...}
state["pdf_paths"] = [pdf1, pdf2, ...]
state["status"] = "harvest_complete"
```

### **Step 2: EXTENSION_HANDOFF_NODE**

**流程**:
```
初始化扩展分析的插槽：

extension_payloads = {
    slot_a: {},      # Evidence Synthesis
    slot_b: {},      # Clinical Analysis
    slot_c: {},      # Quality Assessment
}
```

**State 更新**:
```python
state["extension_payloads"] = {slot_a: {}, slot_b: {}, slot_c: {}}
```

### **Step 3: EVIDENCE_SYNTHESIZER_NODE**

**流程**:
```
150 records
    ↓
EvidenceSynthesizerAgent.synthesize(harvested_data, data_layers)
    ├─ 分类研究类型
    │   ├─ ["meta-analysis"]: 5条
    │   ├─ ["rct"]: 12条
    │   ├─ ["clinical_trial"]: 25条
    │   └─ ["cohort", "case_report", ...]: 108条
    ├─ 提取efficacy endpoints
    │   ├─ OS (Overall Survival)
    │   ├─ PFS (Progression-Free Survival)
    │   └─ ORR (Overall Response Rate)
    ├─ 计算GRADE凭证等级
    │   └─ meta_analysis=5, rct=4, clinical_trial=3, ...
    └─ 检测冲突证据

RETURN:
{
    evidence_layers: {
        meta_analysis: [...],
        rct: [...],
        clinical_trial: [...],
        ...
    },
    efficacy_endpoints: [{type, value, unit}, ...],
    grade_scores: {score: 3.7, ...}
}
```

**State 更新**:
```python
state["extension_payloads"]["slot_a"] = {evidence_synthesis: {...}}
```

### **Step 4: CLINICAL_ANALYZER_NODE**

**流程**:
```
trial_results (40条)
    ↓
ClinicalAnalyzerAgent.analyze(harvested_data, source_payloads)
    ├─ 构建管线矩阵
    │   └─ [{indication, intervention, Phase I/II/III, status}, ...]
    ├─ 计算阶段分布
    │   └─ {Phase I: 5, Phase II: 10, Phase III: 8}
    ├─ 提取安全信号
    │   ├─ "serious adverse event"
    │   ├─ "dose limiting toxicity"
    │   └─ "discontinuation due to adverse"
    └─ 竞争格局分析
        └─ target area → competing drugs

RETURN:
{
    pipeline_matrix: [{indication, intervention, phases}, ...],
    phase_transitions: {Phase I: 5, Phase II: 10, ...},
    safety_signals: [{signal_type, source_title}, ...],
    competition_landscape: {target_area: "Amyloid", competitors: [...]}
}
```

**State 更新**:
```python
state["extension_payloads"]["slot_b"] = {clinical_analysis: {...}}
```

### **Step 5: QUALITY_ASSESSOR_NODE**

**流程**:
```
harvested_data (150条) + slot_a + slot_b
    ↓
QualityAssessorAgent.assess(harvested_data, slots)
    ├─ 完整性评分
    │   └─ 计算必需字段覆盖率
    │       └─ {title: 100%, source: 98%, summary: 90%} → avg: 0.96
    ├─ 多样性评分
    │   └─ {PubMed: 60%, ClinicalTrials: 30%, EuropePMC: 10%}
    │       → diversity_score: 0.75
    ├─ 时间性评估
    │   └─ 5年内发表占比: 0.85
    ├─ 复合信心评分
    │   └─ composite = 0.25*completeness + 0.25*diversity + ... = 0.78
    └─ 分级为 A/B/C/D/F

RETURN:
{
    completeness: {field_coverage: {...}, overall: 0.96},
    source_diversity_score: 0.75,
    confidence_grade: "A",
    confidence_score: 0.78,
    rationale: "Data quality metrics acceptable..."
}
```

**State 更新**:
```python
state["extension_payloads"]["slot_c"] = {quality_assessment: {...}}
```

### **Step 6: WRITER_NODE**

**流程**:
```
所有state数据 (harvested_data + slots)
    ↓
writer_node(state)
    ├─ 检测查询类型
    │   └─ "alzheimer" → 使用 DiseaseSurveyEngine
    ├─ DiseaseSurveyEngine 路线：
    │   ├─ aggregate_survey_data(150 records, "Alzheimer disease")
    │   │   ↓ 返回 DiseaseSurveyState {
    │   │       drug_assets: [Aducanumab, Lecanemab, ...],
    │   │       trials: [TrialRecord, ...],
    │   │       sponsors: [Biogen, EliLilly, ...],
    │   │       cns_benchmark: [...]
    │   │   }
    │   ├─ disease_survey_to_markdown(survey_state)
    │   │   ├─ render_executive_summary()
    │   │   ├─ render_drug_pipeline()
    │   │   ├─ render_trial_landscape()
    │   │   ├─ render_sponsor_analysis()
    │   │   ├─ render_target_biology()
    │   │   ├─ render_literature_review()
    │   │   ├─ render_cns_benchmark()
    │   │   ├─ render_safety_profile()
    │   │   └─ render_market_landscape()
    │   │   ↓ 返回完整的markdown dict
    │   └─ ReportWriterAgent.write_report()
    │       ├─ 调用 Google Gemini Pro LLM
    │       ├─ 生成论述性文本
    │       └─ 输出 markdown
    ├─ HtmlRenderer.render(markdown_content)
    │   └─ save as final_reports/[timestamp].html
    ├─ PdfRenderer.render(html)
    │   └─ save as final_reports/[timestamp].pdf
    └─ RETURN ReportOutput {
           final_report: "# Comprehensive Alzheimer Survey\n\n...",
           final_report_path: "final_reports/survey_20260417.md",
           final_report_html_path: "survey_20260417.html",
           final_report_pdf_path: "survey_20260417.pdf"
       }
```

**State 最终更新**:
```python
state["final_report"] = "# Comprehensive Alzheimer Survey\n\n..."
state["final_report_path"] = "final_reports/survey_20260417.md"
state["final_report_html_path"] = "survey_20260417.html"
state["final_report_pdf_path"] = "survey_20260417.pdf"
state["status"] = "workflow_complete"
```

---

## 🔍 函数速查表

### **A. 采集引擎函数**

| 类 | 函数 | 签名 | 返回 |
|----|------|------|------|
| **BioHarvestAgent** | `run()` | `(user_query: str, max_results: int=20)` | `Dict[str, Any]` |
| **QueryParser** | `parse()` | `(user_query: str)` | `QueryIntent` |
| **PubMedRetriever** | `retrieve()` | `(queries: List[str], max_results: int)` | `List[Dict]` |
| **EuropePMCRetriever** | `retrieve()` | `(queries: List[str], max_results: int)` | `List[Dict]` |
| **ClinicalTrialsRetriever** | `retrieve()` | `(queries: List[str], max_results: int)` | `List[Dict]` |
| **MultiSourceEnricher** | `collect()` | `(query: str, max_per_source: int)` | `Dict` |
| **PdfDownloader** | `download_for_candidates()` | `(candidates: List, output_dir: str)` | `int` |

### **B. 疾病调查函数**

| 模块 | 函数 | 签名 | 返回 |
|------|------|------|------|
| **disease_survey/aggregator.py** | `aggregate_survey_data()` | `(rows: List[Dict], query: str)` | `DiseaseSurveyState` |
| **disease_survey/composer.py** | `disease_survey_to_markdown()` | `(state: DiseaseSurveyState)` | `Dict` |
| **disease_survey/renderer.py** | `render_executive_summary()` | `(state)` | `str` |
| **disease_survey/renderer.py** | `render_drug_pipeline()` | `(state)` | `str` |
| **disease_survey/renderer.py** | `render_trial_landscape()` | `(state)` | `str` |
| **disease_survey/renderer.py** | `render_sponsor_analysis()` | `(state)` | `str` |
| **disease_survey/renderer.py** | `render_target_biology()` | `(state)` | `str` |
| **disease_survey/renderer.py** | `render_literature_review()` | `(state)` | `str` |
| **disease_survey/renderer.py** | `render_cns_benchmark()` | `(state)` | `str` |
| **disease_survey/renderer.py** | `render_safety_profile()` | `(state)` | `str` |
| **disease_survey/renderer.py** | `render_market_landscape()` | `(state)` | `str` |

### **C. 报告生成函数**

| 类 | 函数 | 签名 | 返回 |
|----|------|------|------|
| **ReportWriterAgent** | `write_report()` | `(user_query, harvested_data, extension_payloads, ...)` | `ReportOutput` |
| **HtmlRenderer** | `render()` | `(markdown_content: str)` | `str` |
| **PdfRenderer** | `render()` | `(html_content: str)` | `bytes` |

### **D. 工作流编排函数**

| 模块 | 函数 | 签名 | 返回 |
|------|------|------|------|
| **src/agents/supervisor.py** | `create_cassandra_workflow()` | `()` | `StateGraph` |
| **src/agents/supervisor.py** | `run_cassandra_workflow()` | `(user_query, pdf_paths, ...)` | `Dict` |
| **src/agents/supervisor.py** | `stream_cassandra_workflow()` | `(user_query, pdf_paths, ...)` | `Generator` |
| **src/graph/workflow.py** | `create_workflow()` | `()` | `StateGraph` |

---

## 📡 调用关系图

### **主入口流程**

```
main.py 或 app.py
    │
    ├─ CLI: run_cassandra_workflow(user_query)
    └─ Web: POST /api/run_analysis
            ↓
        src/services/workflow_service.py
        │   
        ├─ (或 src/agents/supervisor.py)
        │
        └─ create_cassandra_workflow()
            ├─ src/graph/workflow.py::create_workflow()
            │   └─ 构建6层DAG
            │       ├─ harvester_node
            │       ├─ extension_handoff_node
            │       ├─ evidence_synthesizer_node
            │       ├─ clinical_analyzer_node
            │       ├─ quality_assessor_node
            │       └─ writer_node
            │
            └─ compile_workflow()
                └─ StateGraph.compile(checkpointer=Redis)
```

### **Harvester 节点详细调用树**

```
harvester_node(state)
    │
    └─ BioHarvestAgent.run(state.user_query)
        ├─ QueryParser.parse()
        │   └─ llm_client.generate_queries() [Gemini Pro]
        │
        ├─ EuropePMCRetriever.retrieve(queries, max_results=30)
        │   └─ requests.get("https://www.ebi.ac.uk/europepmc/webservices/rest")
        │       ├─ filter by MEDLINE
        │       └─ extract: pmid, title, abstract, published year
        │
        ├─ ClinicalTrialsRetriever.retrieve(queries, max_results=30)
        │   └─ requests.get("https://clinicaltrials.gov/api/v2/studies")
        │       ├─ filter by status
        │       └─ extract: nct_id, title, phase, status, enrollment
        │
        ├─ MultiSourceEnricher.collect()
        │   ├─ NCBIEUtilsClient.search("gene", term)
        │   ├─ NCBIEUtilsClient.search("protein", term)
        │   ├─ OpenFDAClient.search()
        │   └─ GDELTClient.search()
        │
        ├─ aggregate_data() 
        │   └─ Deduplicate & merge from multiple sources
        │
        ├─ PdfDownloader.download_for_candidates()
        │   ├─ PMC API
        │   ├─ Unpaywall API
        │   ├─ preprint servers
        │   └─ Fallback: urllib.request
        │
        └─ build_data_layers()
            ├─ disease_layer: group by conditions
            ├─ target_layer: extract drug targets
            ├─ pipeline_layer: group by asset & phase
            └─ company_layer: group by sponsor
```

### **Writer 节点详细调用树**

```
writer_node(state)
    │
    ├─ is_disease_survey_query(state.user_query)
    │   └─ keyword_match(["alzheimer", "parkinson", ...])
    │
    ├─ DiseaseSurveyEngine Route:
    │   │
    │   ├─ aggregate_survey_data(state.harvested_data, query)
    │   │   ├─ parse_trial_records() → List[TrialRecord]
    │   │   ├─ extract_drug_assets() → List[DrugAsset]
    │   │   ├─ group_sponsors() → List[SponsorProfile]
    │   │   ├─ collect_literature() → List[LiteratureRecord]
    │   │   ├─ compute_cns_benchmark() → List[CNSBenchmarkEntry]
    │   │   └─ return DiseaseSurveyState
    │   │
    │   ├─ disease_survey_to_markdown(survey_state)
    │   │   ├─ render_executive_summary(state) → str
    │   │   ├─ render_drug_pipeline(state) → str
    │   │   ├─ render_trial_landscape(state) → str
    │   │   ├─ render_sponsor_analysis(state) → str
    │   │   ├─ render_target_biology(state) → str
    │   │   ├─ render_literature_review(state) → str
    │   │   ├─ render_cns_benchmark(state) → str
    │   │   ├─ render_safety_profile(state) → str
    │   │   ├─ render_market_landscape(state) → str
    │   │   └─ return Dict {sections}
    │   │
    │   └─ ReportWriterAgent.write_report(payload)
    │       ├─ llm_client.generate_sections() [Gemini Pro]
    │       ├─ format_to_markdown()
    │       └─ return markdown_content
    │
    ├─ HtmlRenderer.render(markdown_content)
    │   ├─ markdown.markdown().__html__()
    │   └─ save as [timestamp].html
    │
    ├─ PdfRenderer.render(html_content)
    │   ├─ weasyprint.HTML().write_pdf() 
    │   │   或 Puppeteer.goto_html()
    │   └─ save as [timestamp].pdf
    │
    └─ return ReportOutput
```

---

## 🎨 架构设计模式

### **1. 工厂模式** ✓
```python
# src/engines/harvest/agent.py
def create_harvest_agent(config) → BioHarvestAgent

# src/engines/report_engine/agent.py
def create_report_agent() → ReportWriterAgent
```

### **2. 管道模式** ✓
```python
# 6层DAG通过LangGraph实现
START → harvester → handoff → synthesizer → analyzer 
    → assessor → writer → END
```

### **3. 适配器模式** ✓
```python
# 所有Retriever统一接口
class BaseRetriever(ABC):
    def retrieve(queries, max_results) → List[Dict]

class PubMedRetriever(BaseRetriever): ...
class EuropePMCRetriever(BaseRetriever): ...
class ClinicalTrialsRetriever(BaseRetriever): ...
```

### **4. 策略模式** ✓
```python
# writer_node 中根据查询类型选择策略
if is_disease_survey_query(query):
    engine = DiseaseSurveyEngine()  # 策略1
else:
    engine = GenericReportEngine()   # 策略2
```

### **5. 状态模式** ✓
```python
# AgentState 作为全局共享的可变状态
class AgentState(TypedDict):
    user_query: str
    harvested_data: List[Dict]  # 各节点读写
    final_report: Optional[str]
    status: Optional[str]       # 状态机
```

---

## 📁 核心配置和工具

### **配置文件**

| 文件 | 位置 | 用途 |
|------|------|------|
| `.env` | 项目根 | API密钥、URLs |
| `config.py` | 项目根 | 应用配置 |
| `requirements.txt` | 项目根 | Python包依赖 |

### **工具Clients**

| Tool | 库 | 功能 |
|------|-----|------|
| PubMedClient | Biopython | PubMed查询 |
| ClinicalTrialsClient | requests | ClinicalTrials.gov API |
| EuropePMCClient | requests | EuropePMC查询 |
| OpenFDAClient | requests | FDA不良事件 |
| PdfDownloader | requests + PyMuPDF | PDF下载 |
| ScispaCyNER | scispacy | 生物医学NER |

---

## 🚀 快速开发参考

### **启动完整工作流**
```python
from src.agents.supervisor import run_cassandra_workflow

final_state = run_cassandra_workflow(
    user_query="Alzheimer disease comprehensive survey",
    pdf_paths=["paper1.pdf", "paper2.pdf"]
)

print(final_state["final_report_path"])
print(final_state["final_report_pdf_path"])
```

### **获取中间分析结果**
```python
# 采集数据
harvested = final_state["harvested_data"]  # 150个记录

# 扩展分析结果
evidence = final_state["extension_payloads"]["slot_a"]
clinical = final_state["extension_payloads"]["slot_b"]
quality = final_state["extension_payloads"]["slot_c"]

# 生物医学概览
profile = final_state["biomedical_profile"]
```

### **流式执行（用于WebSocket推送）**
```python
from src.agents.supervisor import stream_cassandra_workflow

for node_name, state_snapshot in stream_cassandra_workflow(
    user_query="...",
    progress_callback=lambda n, s: print(f"{n}: progress")
):
    # 推送到前端
    socketio.emit("progress", {"node": node_name, "status": "running"})
```

---

## 📊 关键数据流量

| 流各段 | 数据量 | 类型 |
|--------|--------|------|
| harvested_data | ~150条 | List[Dict] |
| pdf_paths | ~15个 | List[str] |
| data_layers | 4个维度 | Dict |
| extension_payloads | 3个slots | Dict |
| final_report | ~5-10 MB | str |
| final_report_html | ~2-5 MB | str |
| final_report_pdf | ~1-3 MB | bytes |

---

## ✅ 关键设计原则

| 原则 | 实现方式 |
|------|---------|
| **端到端连通** | 固定主链：START→harvester→...→writer→END |
| **低耦合** | 通过AgentState进行节点间通信，而非直接依赖 |
| **可扩展** | 通过extension_payloads预留扩展点 |
| **故障回退** | PDF下载5层fallback；多源retrieve互为容错 |
| **检查点持久化** | Redis存储中间状态，支持恢复 |
| **多格式输出** | Markdown→HTML→PDF自动转换 |

---

## 📞 后续问题索引

- **想了解具体CNS基准计算？** → 查看计算函数细节
- **想了解PDF下载Fallback流程？** → 查看enhanced_pdf_downloader.py
- **想了解LLM提示词？** → 查看各engine的prompts.py
- **想扩展新的分析模块？** → 使用extension_payloads机制

