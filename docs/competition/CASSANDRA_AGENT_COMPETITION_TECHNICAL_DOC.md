# Cassandra Agent 竞赛技术文档（更新版）

更新日期：2026-04-15

## 1. 项目定位

Cassandra 是一个面向生物医药证据整理与报告生成的多模块系统。

核心定位：

- 从公开来源采集结构化医学数据
- 将采集结果映射为统一状态对象
- 通过稳定工作流生成可追溯报告

本项目的重点不在开放对话，而在可复现、可扩展、可观测的任务执行链。

## 2. 当前系统主链

当前生产链路为：

```text
START -> harvester -> extension_handoff -> writer -> END
```

三个节点职责分别是：

- `harvester`：采集与结构化映射
- `extension_handoff`：扩展插槽与透传
- `writer`：报告生成与输出

该主链确保 writer 节点始终连通且可达。

## 3. 架构分层

### 3.1 编排层

路径：`src/graph/`

- `workflow.py`：定义节点与边
- `state.py`：定义共享状态结构
- `contracts.py`：定义输入输出校验规则

### 3.2 协调层

路径：`src/agents/supervisor.py`

- 提供 workflow 的创建、同步执行、流式执行
- 对外接口已统一为 Cassandra 命名
- 编译阶段默认连续执行，不启用中断

### 3.3 服务层

路径：`src/services/workflow_service.py`

- 作为应用层与编排层之间的稳定适配层
- 屏蔽内部编排细节，降低上层耦合

### 3.4 应用层

路径：`app.py` 与 `templates/`

- Flask + Socket.IO 提供 Web API 与流式事件
- 前端步骤条对齐后端实际步骤：`harvest / handoff / writing`

## 4. 状态设计

状态对象采用 TypedDict 风格共享结构，关键字段包括：

- `user_query`
- `harvested_data`
- `harvest_data_layers`
- `harvest_source_payloads`
- `extension_payloads`
- `final_report`
- `report_path`
- `html_report_path`
- `status`
- `errors`

设计原则：

- 字段清晰、低耦合、可序列化
- 写入阶段只消费所需字段，避免隐式依赖
- 扩展数据统一进入 `extension_payloads`

## 5. 扩展插槽机制

`extension_handoff` 节点是本轮结构升级的核心：

- 默认行为为无副作用透传
- 可作为未来节点接入前的标准入口
- 新能力可通过 `extension_payloads` 回写到状态
- 失败可回退透传，不阻断 writer

这保证了“现在稳定运行”和“未来可平滑扩展”同时成立。

## 6. 连续执行策略

在 `supervisor.compile_workflow(...)` 中，系统对中断参数采取忽略策略：

- 外部若传入 interrupt 配置，记录警告
- 实际编译仍以 uninterrupted 模式执行

该策略用于避免生产流程出现人为断链。

## 7. 前后端一致性

### 7.1 后端步骤映射

`app.py` 中后端事件步骤映射已统一为：

- `harvester -> harvest`
- `extension_handoff -> handoff`
- `writer -> writing`

### 7.2 前端步骤条

`templates/index.html` 中：

- 步骤节点调整为三段
- 状态徽标与百分比同步按三段刷新
- 旧的四段命名已移除

## 8. 数据合约与健壮性

合约模块 `src/graph/contracts.py` 用于：

- 校验采集输出是否满足 writer 输入预期
- 减少字段漂移导致的运行时错误

此外，服务层和应用层通过显式错误字段返回，保证异常可追踪。

## 9. 工程优势

与单脚本流水线相比，当前实现有三点优势：

1. 可维护：职责边界清晰，变更影响面可控。
2. 可扩展：扩展节点有标准接入点。
3. 可观测：执行步骤、进度、日志可实时追踪。

## 10. 当前边界与后续方向

当前边界：

- 主链已稳定，但扩展节点仍为占位透传。
- 兼容层中保留了历史模块命名，便于渐进迁移。

后续方向：

1. 在 `extension_handoff` 接入可选规则节点。
2. 为扩展负载定义独立 schema。
3. 增加更多端到端一致性测试，覆盖 Web 事件流。

## 11. 验证建议

建议作为最小回归集执行：

```bash
python -m pytest tests/test_dataflow_integrity.py
python -m pytest tests/test_report_engine_sanitization.py
python -m pytest tests/test_chart_rendering.py
```

判定标准：

- writer 可达且执行完成
- 步骤状态无断链
- 输出报告路径与前端展示一致

## 12. 结论

Cassandra 当前版本完成了从“历史多分支叙事”向“连通主链 + 扩展插槽”架构的收敛。

在竞赛语境下，这体现为：

- 明确的任务边界
- 稳定的工程落地能力
- 面向未来扩展的结构设计

该版本已经具备持续迭代基础，可在不破坏主流程的前提下继续增加专业能力模块。
