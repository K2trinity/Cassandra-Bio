# Cassandra 数据流架构（当前实现）

更新日期：2026-04-15

## 1. 当前主流程

系统已统一为连通的线性主链：

```text
START -> harvester -> extension_handoff -> writer -> END
```

说明：

- `harvester` 负责结构化采集与统一字段映射。
- `extension_handoff` 为保留插槽节点，默认透传，不中断主链。
- `writer` 负责最终报告生成与输出路径回写。

## 2. 设计目标

本轮重构的目标是：

- 保证节点端到端连通，避免 writer 被断开。
- 禁止默认人为中断，保持连续执行。
- 在不增加耦合的前提下预留未来节点接入点。
- 统一前后端步骤语义，减少文档与实现漂移。

## 3. 状态对象（核心字段）

主状态定义见 `src/graph/state.py`，关键字段包括：

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

其中：

- `extension_payloads` 由 `extension_handoff` 节点写入或透传。
- `writer` 可消费 `extension_payloads` 作为后续扩展输入。

## 4. 编排与执行

编排入口：`src/graph/workflow.py`

- 使用 LangGraph `StateGraph` 构建节点与边。
- 主边固定为：`START -> harvester -> extension_handoff -> writer -> END`。

执行入口：`src/agents/supervisor.py`

- 对外暴露 Cassandra 命名接口：
  - `create_cassandra_workflow`
  - `run_cassandra_workflow`
  - `stream_cassandra_workflow`
- 编译阶段默认无中断执行。
- 如传入中断参数，系统记录告警并忽略，以保证主流程连续性。

## 5. 服务层与应用层

服务层：`src/services/workflow_service.py`

- 封装 run/stream/resume/get_state。
- 作为 `app.py` 与 supervisor 之间的稳定接口。

应用层：`app.py`

- Web 进度步骤统一为：
  - `harvest`
  - `handoff`
  - `writing`
- 流式事件通过 Socket.IO 推送到前端。

前端：`templates/index.html`

- Stepper 已对齐三段流程。
- 日志面板和进度条均按三段步骤更新。

## 6. 合约与一致性

合约文件：`src/graph/contracts.py`

- 对采集输出和写入输入做结构校验。
- 约束字段语义，减少跨模块解释偏差。

一致性要求：

- 代码中的节点名、前端步骤名、文档步骤名保持同构。
- 扩展节点接入时优先走 `extension_handoff`，避免直接改动主链。

## 7. 扩展接入建议

未来新增节点建议采用以下模式：

1. 在 `extension_handoff` 中挂载路由策略。
2. 新节点产出写入 `extension_payloads`。
3. `writer` 按需读取对应扩展分支数据。
4. 若扩展失败，回退为透传，不阻断主流程。

该策略可以在保持稳定主链的同时，支持渐进式能力演化。

## 8. 验证建议

推荐至少执行：

```bash
python -m pytest tests/test_dataflow_integrity.py
python -m pytest tests/test_report_engine_sanitization.py
```

重点检查：

- 流程边是否完整连通。
- `writer` 是否可达且无中断阻塞。
- 前端步骤与后端事件是否一致。
