# Cassandra Agent 竞赛技术文档（代码校对版）

更新日期：2026-04-26

## 1. 项目定位

Cassandra 是一个面向生物医药证据整理与报告生成的多模块系统。

核心定位：

- 从公开来源采集结构化医学数据
- 将采集结果映射为统一状态对象
- 通过稳定工作流生成可追溯报告

本项目的重点不在开放对话，而在可复现、可扩展、可观测的任务执行链。

## 2. 当前系统真实主链

当前生产后端链路为：

```text
START -> harvester -> disease_survey_intelligence -> extension_handoff -> evidence_synthesizer -> clinical_analyzer -> quality_assessor -> writer -> END
```

各节点职责如下：

- `harvester`：采集与结构化映射
- `disease_survey_intelligence`：对明确 disease-survey 意图构建 `slot_disease_survey`
- `extension_handoff`：初始化并保留扩展插槽与 K-line 槽位
- `evidence_synthesizer`：生成证据综合结果并写入 `slot_a`
- `clinical_analyzer`：生成临床分析结果并写入 `slot_b`
- `quality_assessor`：生成质量评估结果并写入 `slot_c`
- `writer`：组装 writer payload、校验合约并生成最终报告

这里需要强调两点：

- 后端真实执行是七个业务节点的线性主链。
- 前端步骤条仍是三段式 UI 抽象，不等价于后端节点数量。

## 3. 架构分层

### 3.1 编排层

路径：`src/graph/`

- `workflow.py`：定义七节点与边
- `state.py`：定义共享状态结构
- `contracts.py`：定义采集、扩展槽位、writer 输入的校验规则

### 3.2 协调层

路径：`src/agents/supervisor.py`

- 提供 workflow 的创建、同步执行、流式执行
- 对外接口统一为 Cassandra 命名
- 编译阶段默认连续执行，不启用人工中断

### 3.3 服务层

路径：`src/services/workflow_service.py`

- 作为应用层与编排层之间的稳定适配层
- 屏蔽内部 LangGraph 细节，降低上层耦合

### 3.4 应用层

路径：`app.py` 与 `templates/`

- Flask + Socket.IO 提供 Web API 与流式事件
- 前端步骤条当前展示 `harvest / handoff / writing`
- 中间三个分析节点目前不会以独立步骤名显示在 Stepper 上

## 4. 状态设计

状态对象采用 TypedDict 风格共享结构，关键字段包括：

- `user_query`
- `pdf_paths`
- `harvested_data`
- `harvest_data_layers`
- `harvest_source_payloads`
- `harvest_frontend_payload`
- `extension_payloads`
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

其中：

- `harvested_data` 是 writer 的主事实层输入
- `harvest_data_layers` 是 disease / target / pipeline / company 等聚合视图
- `harvest_source_payloads` 保留多源原始 payload
- `extension_payloads` 用于承接中间分析节点结果

## 5. 扩展插槽机制

`extension_handoff` 负责初始化以下扩展槽位：

```python
{
    "slot_a": {},
    "slot_b": {},
    "slot_c": {},
    "slot_kline": {},
    "slot_disease_survey": {},
}
```

当前写入策略：

- `slot_disease_survey`：由 `disease_survey_intelligence` 在 harvest 后、handoff 前构建；`extension_handoff` 负责保留它
- `slot_a`：证据综合结果
- `slot_b`：临床分析结果
- `slot_c`：质量评估结果
- `slot_kline`：K-line 异常信号等量化附加载荷

这保证了图上的中间分析节点可以在不污染 `harvested_data` 的前提下挂接结果。

## 6. Writer 真实输入边界

`writer_node` 会组装并校验如下输入结构：

- `user_query`
- `harvest_data`
  - `query`
  - `results`
  - `data_layers`
  - `source_payloads`
  - `frontend_payload`
- `synthesis_sections`
- `compiled_context_text`
- `analysis_status`
- `contract_version`

当前 writer 入口边界是：

- `writer_node` 会把 `extension_payloads` 作为 `synthesis_sections` 传入
- `ReportWriterAgent.write_report()` 会读取 `extra_payload["synthesis_sections"]`
- 当 `slot_disease_survey` 存在且校验通过时，writer 优先走槽位权威的 disease-survey 渲染路径
- 当槽位缺失或无效时，writer 才回退到旧的 harvest-row disease-survey 聚合路径或通用报告路径

writer 可以总结和渲染已有结构化数据，但不能生成新的资产、公司、技术路线、风险标签、证据或图表 payload。

所以线上真实 writer 主要依赖的是：

- `user_query`
- `harvest_data`
- `synthesis_sections`
- `compiled_context_text`

## 7. Disease Survey 路由

在 disease survey 场景下，首选链路是：

```text
harvest_data["results"]
  -> disease_survey_intelligence
  -> build_disease_survey_slot()
  -> aggregate_survey_data()
  -> DiseaseSurveyState
  -> slot_disease_survey
  -> validate_disease_survey_slot()
  -> compose_disease_survey_slot_report_bundle()
```

对应文件：

- `src/engines/report_engine/disease_survey/aggregator.py`
- `src/engines/report_engine/disease_survey/intelligence.py`
- `src/engines/report_engine/disease_survey/models.py`
- `src/engines/report_engine/disease_survey/composer.py`

这意味着：

- disease survey 主路径现在直接消费 `extension_payloads["slot_disease_survey"]`
- `aggregate_survey_data()` 仍然存在，但在主路径中由 post-harvest intelligence 节点调用
- writer-side `aggregate_survey_data() -> DiseaseSurveyState -> composer` 仍作为 legacy fallback 保留

## 8. 前后端一致性

### 8.1 后端实际执行

后端工作流按七个业务节点执行，且 supervisor 在 compile 阶段默认忽略外部 interrupt 请求，保持连续运行。

### 8.2 前端步骤条

`app.py` 中 `_NODE_PROGRESS` 当前只映射：

- `harvester -> harvest`
- `extension_handoff -> handoff`
- `writer -> writing`

因此前端展示和后端图结构之间是“粗映射”关系，而不是“一节点一步骤”关系。

## 9. 当前边界与后续方向

当前边界：

- 主链已稳定扩展到 `disease_survey_intelligence` 在内的七个业务节点。
- `slot_disease_survey` 是 disease-survey 的首选 writer-ready 结构化载荷。
- writer 已消费有效 `slot_disease_survey`，并保留旧聚合链作为 fallback。

后续方向：

1. 扩展其他专业槽位时，保持“上游生成结构化数据，writer 只总结和渲染”的边界。
2. 如果新增 `Clinical Success Outlook` 一类能力，优先明确其 writer-ready 槽位形状与证据字段。
3. 若能力挂在 `clinical_analyzer -> slot_b`，需要同步补齐 writer 对该槽位的消费逻辑。

## 10. 工程优势

与单脚本流水线相比，当前实现有三点优势：

1. 可维护：采集、聚合、评估、写作分层更清晰。
2. 可扩展：中间分析能力已有标准槽位承接。
3. 可观测：状态对象、合约校验、Socket.IO 进度流都可追踪。

## 11. 验证建议

建议作为最小回归集执行：

```bash
python -m pytest tests/test_dataflow_integrity.py
python -m pytest tests/test_writer_slot_consumption.py
python -m pytest tests/test_report_writer_agent.py
python -m pytest tests/test_disease_survey_aggregator.py
```

判定标准：

- 七节点主链保持线性连通，且 `disease_survey_intelligence` 位于 `harvester` 与 `extension_handoff` 之间
- `harvester` 四层输出完整进入 writer 输入
- `writer_node` 仍然透传 `synthesis_sections`
- `extension_handoff` 保留上游 `slot_disease_survey`
- writer 优先消费有效 `slot_disease_survey`，缺失或无效时 legacy disease-survey fallback 仍可工作

## 12. 结论

Cassandra 当前版本的真实形态，不再是“harvest -> handoff -> writer”的简化三节点故事，而是：

- 七节点后端执行主链
- 三段式前端展示抽象
- 两条 writer 路由
  - 通用 writer：基于 `harvest_data + compiled_context_text`
  - disease survey：首选 `slot_disease_survey`，fallback 为 `harvest_data["results"] -> DiseaseSurveyState`

在竞赛语境下，这更准确地体现了系统已经具备：

- 明确的数据边界
- 可验证的执行链
- 面向后续专业模块接入的扩展点
