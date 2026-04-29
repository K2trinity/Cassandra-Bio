# Cassandra 数据流架构（Phase 11 校对版）

更新日期：2026-04-26

## 1. 当前结论

当前 Cassandra 后端主链已经不是旧的 `harvester -> extension_handoff -> writer` 直通链，也不是旧的六节点链。真实 LangGraph 拓扑为：

```text
START -> harvester -> disease_survey_intelligence -> extension_handoff -> evidence_synthesizer -> clinical_analyzer -> quality_assessor -> writer -> END
```

核心变化是：disease-survey 报告现在有一个第一类、槽位权威的结构化主路径。`disease_survey_intelligence` 是 harvest 之后第一个智能节点；对明确的疾病综述意图，它会先调用 `aggregate_survey_data()`，再构造 `extension_payloads["slot_disease_survey"]`。writer 的主职责是消费、校验、总结和渲染已有结构化数据。

Web 前端仍可把进度展示为 `harvest / handoff / writing` 这样的粗粒度阶段；这只是 UI 抽象，不代表后端拓扑。

## 2. 主链节点职责

编排入口：`src/graph/workflow.py`

- `harvester`
  调用 `BioHarvestAgent.run()`，写入 `harvested_data`、`harvest_data_layers`、`harvest_source_payloads`、`harvest_frontend_payload` 等 harvest 输出。
- `disease_survey_intelligence`
  对显式 disease-survey 查询构建 `slot_disease_survey`。该节点是 disease-survey 报告的第一条结构化智能处理边界，`aggregate_survey_data()` 现在在这里作为主路径运行。
- `extension_handoff`
  初始化并保留扩展槽位，包括 `slot_a`、`slot_b`、`slot_c`、`slot_kline`、`slot_disease_survey`。
- `evidence_synthesizer`
  生成证据综合结果，写入 `extension_payloads["slot_a"]`。
- `clinical_analyzer`
  生成临床分析结果，写入 `extension_payloads["slot_b"]`。
- `quality_assessor`
  生成质量评估结果，写入 `extension_payloads["slot_c"]`。
- `writer`
  校验 writer 输入，优先消费 `slot_disease_survey`，否则按旧 disease-survey fallback 或通用 harvest 报告路径渲染 Markdown / HTML / PDF。

## 3. 共享状态与关键载荷

共享状态定义：`src/graph/state.py`

当前与数据流相关的关键字段包括：

- `user_query`
- `pdf_paths`
- `harvested_data`
- `harvest_data_layers`
- `harvest_source_payloads`
- `harvest_frontend_payload`
- `extension_payloads`
- `disease_survey_slot`
- `dataflow_contract_version`
- `final_report`
- `final_report_path`
- `final_report_markdown`
- `final_report_html_path`
- `final_report_pdf_path`
- `analysis_status`
- `project_name`
- `status`
- `errors`

### 3.1 Harvester 输出

`src/graph/nodes/harvester_node.py`

`harvester` 主要写入：

```python
{
    "harvested_data": results["results"],
    "harvest_data_layers": results["data_layers"],
    "harvest_source_payloads": results["source_payloads"],
    "harvest_frontend_payload": results["frontend_payload"],
    "dataflow_contract_version": CONTRACT_VERSION,
    "pdf_paths": pdf_paths,
    "project_name": ...,
    "status": "harvest_complete",
}
```

四层 harvest 输出语义：

- `harvested_data`：规范化后的主记录数组。
- `harvest_data_layers`：disease / target / pipeline / company 等聚合视图。
- `harvest_source_payloads`：多源原始 payload 快照。
- `harvest_frontend_payload`：面向前端的投影视图。

### 3.2 Disease Survey Intelligence 输出

`src/graph/nodes/disease_survey_intelligence_node.py`

当查询同时满足疾病词和 survey / comprehensive / landscape / overview 等显式综述意图时，该节点执行：

```text
harvested_data
  -> build_disease_survey_slot(...)
  -> aggregate_survey_data(rows, query)
  -> extension_payloads["slot_disease_survey"]
```

并写回：

```python
{
    "extension_payloads": {
        ...,
        "slot_disease_survey": slot,
    },
    "disease_survey_slot": slot,
    "status": "disease_survey_intelligence_complete",
}
```

如果不是明确 disease-survey 意图，节点不生成该槽位，只保留已有 `extension_payloads` 并返回 skipped 状态。

### 3.3 Extension 与分析槽位

`src/graph/nodes/extension_handoff_node.py` 会保证扩展槽位存在，并保留上游已经生成的 `slot_disease_survey`。后续三个分析节点继续写入：

```python
extension_payloads["slot_a"] = {"evidence_synthesis": synthesis}
extension_payloads["slot_b"] = {"clinical_analysis": analysis}
extension_payloads["slot_c"] = {"quality_assessment": assessment}
```

因此进入 writer 前的核心状态可抽象为：

```python
{
    "user_query": "...",
    "harvested_data": [...],
    "harvest_data_layers": {...},
    "harvest_source_payloads": {...},
    "harvest_frontend_payload": {...},
    "extension_payloads": {
        "slot_disease_survey": {...},
        "slot_a": {"evidence_synthesis": {...}},
        "slot_b": {"clinical_analysis": {...}},
        "slot_c": {"quality_assessment": {...}},
        "slot_kline": {...},
    },
}
```

## 4. `slot_disease_survey` 顶层形状

构造入口：`src/engines/report_engine/disease_survey/intelligence.py`

`slot_disease_survey` 是 disease-survey 主路径的 writer-ready 结构化载荷。当前顶层字段包括：

```python
{
    "intent": {...},
    "entity_profile": {...},
    "pipeline_assets": [...],
    "trial_landscape": [...],
    "literature_records": [...],
    "literature_review": {...},
    "company_technical_routes": [...],
    "pipeline_timeline_competition_risks": [...],
    "charts": {...},
    "metadata": {...},
    "field_audit": {...},
    "evidence_registry": [...],
    "cns_benchmark": [...],
}
```

字段要点：

- `intent`
  记录 `report_type="disease_survey"`、原始查询、疾病名和意图置信度。
- `entity_profile`
  记录实体类型、疾病名、主实体和源记录数量。
- `pipeline_assets`
  来自 `DiseaseSurveyState.drug_assets`，包含资产名、公司/ sponsor、modality、targets、phase、status、trial_ids、是否治疗性资产、`evidence_ids` 等。
- `trial_landscape`
  来自 `DiseaseSurveyState.trials`，保留 NCT、phase、status、enrollment、endpoint、AE/SAE、关键日期和 `evidence_ids`。
- `literature_records`
  保留聚合出的文献记录全集。
- `literature_review`
  是 writer 应优先使用的文献综述视图，当前约束为 `journal_scope="top_50_only"` 与 `year_scope="last_5_years"`；`records` 只保留 curated Top-50 journal 范围内的文献，`filtered_out_count` 记录被过滤数量。
- `company_technical_routes`
  记录药企/biotech sponsor 的代表资产、targets、modality、technical_route、route_summary、疾病适配理由和 `evidence_ids`。
- `pipeline_timeline_competition_risks`
  记录每个治疗性 pipeline 的时间线风险和竞争风险。
- `charts`
  结构化图表 payload，例如 phase、trial status、target、modality、company route、timeline risk、competition risk、Top-50 journal、CNS benchmark 等分布。
- `field_audit`
  记录字段质量与缺失情况。
- `evidence_registry`
  记录证据索引，供报告引用和审计。
- `cns_benchmark`
  记录 CNS target benchmark 对齐信息。

### 4.1 文献 Top-50 约束

`literature_review.records` 只应包含 `src/engines/report_engine/disease_survey/journal_scope.py` 中 curated Top-50 journal 集合或其别名命中的文献。非 Top-50 文献可以存在于 `literature_records` 全集中，但不应进入 `literature_review.records` 的主综述范围。

### 4.2 Pipeline 风险字段

每条 `pipeline_timeline_competition_risks` 记录至少应表达：

- `asset_name`
- `company`
- `phase`
- `status`
- `timeline_risk`
- `timeline_evidence`
- `competition_risk`
- `competition_evidence`
- `competition_buckets`
- `evidence_ids`

`timeline_risk` 和 `competition_risk` 的标签集合固定为：

```text
低 / 中 / 高 / 数据不足
```

风险判断必须有证据字段支撑。缺少关键日期、target、modality 或匹配 trial 时，应使用 `数据不足`，并在对应 evidence 字段说明缺失原因。

## 5. Writer 输入与边界

`src/graph/nodes/writer_node.py`

writer 节点会构造 contract payload 并校验：

```python
{
    "user_query": user_query,
    "harvest_data": {
        "query": user_query,
        "results": harvested_data,
        "data_layers": state["harvest_data_layers"],
        "source_payloads": state["harvest_source_payloads"],
        "frontend_payload": state["harvest_frontend_payload"],
    },
    "synthesis_sections": extension_payloads,
    "project_name": state["project_name"],
    "output_dir": "final_reports",
    "compiled_context_text": compiled_context,
    "analysis_status": analysis_status,
    "contract_version": CONTRACT_VERSION,
}
```

随后传给 `ReportWriterAgent.write_report()` 的 payload 包含同一组 `synthesis_sections`。`ReportWriterAgent.write_report()` 现在会读取 `extra_payload["synthesis_sections"]`，优先查找并校验 `slot_disease_survey`。

writer 边界：

```text
Writer may summarize/render existing structured data.
Writer must not generate assets, companies, technical routes, risk labels, evidence, or chart payloads.
```

也就是说，writer 可以把 `slot_disease_survey` 中已有的结构化内容组织成 Markdown / HTML / PDF，可以做摘要和呈现；但资产清单、公司技术路线、风险标签、证据引用和图表 payload 必须由上游结构化节点生成。

## 6. Disease Survey 路由

当前 disease-survey 有两条路径：

1. 主路径：slot-authoritative

```text
harvester
  -> disease_survey_intelligence
  -> build_disease_survey_slot()
  -> aggregate_survey_data()
  -> extension_payloads["slot_disease_survey"]
  -> writer
  -> validate_disease_survey_slot()
  -> compose_disease_survey_slot_report_bundle()
```

这是当前实现的首选路径。只要 `slot_disease_survey` 存在且校验通过，writer 就按槽位渲染 disease-survey 报告，不再重新生成资产、公司、路线、风险或图表。

2. fallback 路径：legacy writer-side aggregation

```text
writer
  -> _is_disease_survey(rows)
  -> _write_disease_survey_report()
  -> aggregate_survey_data(rows, user_query)
  -> compose_disease_survey_report_bundle()
```

这个 legacy fallback 仍然存在，用于缺少 `slot_disease_survey`、槽位无效或旧入口直接调用 writer 的场景。它不再是 disease-survey 的主路径。

## 7. 通用报告路由

非 disease-survey 或未命中 disease-survey fallback 的查询仍走通用 harvest-first 路径：

```text
harvest_data + compiled_context_text -> generic markdown/html/pdf writer
```

通用路径依赖：

- `user_query`
- `harvest_data`
- `compiled_context_text`
- `analysis_status`
- `failed_count / total_files / failed_files`
- `contract_version`

`slot_a / slot_b / slot_c` 仍通过 `synthesis_sections` 到达 writer 输入边界；是否在具体报告中呈现，应遵守同一 writer 边界：writer 只能总结或渲染已有结构化内容。

## 8. 前端展示链与后端执行链

应用入口：`app.py`

Web UI 的进度映射仍可能只展示少数粗粒度阶段，例如：

- `harvest`
- `handoff`
- `writing`

这不表示后端只有这些节点。后端真实执行链应以 `src/graph/workflow.py` 为准：

```text
START -> harvester -> disease_survey_intelligence -> extension_handoff -> evidence_synthesizer -> clinical_analyzer -> quality_assessor -> writer -> END
```

## 9. 合约与验证建议

建议使用以下文件作为回归检查入口：

- `tests/test_disease_survey_intelligence_node.py`
- `tests/test_disease_survey_intelligence_slot.py`
- `tests/test_writer_slot_consumption.py`
- `tests/test_disease_survey_aggregator.py`
- `tests/test_disease_survey_composer.py`
- `tests/test_disease_survey_e2e.py`
- `tests/test_literature_top50_scope.py`
- `tests/test_pipeline_risk.py`

推荐命令：

```bash
python -m pytest tests/test_disease_survey_intelligence_node.py
python -m pytest tests/test_disease_survey_intelligence_slot.py tests/test_literature_top50_scope.py tests/test_pipeline_risk.py
python -m pytest tests/test_writer_slot_consumption.py tests/test_disease_survey_composer.py tests/test_disease_survey_e2e.py
```

重点验证：

- 主链包含 `disease_survey_intelligence`，且位于 `harvester` 与 `extension_handoff` 之间。
- `extension_handoff` 不覆盖上游 `slot_disease_survey`。
- `aggregate_survey_data()` 在 disease-survey 主路径中由 post-harvest intelligence 节点触发。
- writer 对有效 `slot_disease_survey` 走 slot-based structured pipeline。
- 缺少或无效 `slot_disease_survey` 时，legacy writer-side aggregation fallback 仍可工作。
- `literature_review.records` 遵守 Top-50 journal 约束。
- 每条 pipeline 风险记录包含 `timeline_risk`、`competition_risk` 和对应 evidence 字段。

## 10. 一句话结构图

```text
harvested_data
  -> disease_survey_intelligence
  -> slot_disease_survey
  -> extension_payloads
  -> writer_payload["synthesis_sections"]
  -> ReportWriterAgent slot-first render
  -> legacy writer-side aggregation only as fallback
```
