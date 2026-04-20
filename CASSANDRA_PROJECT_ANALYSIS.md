# Cassandra 项目全面分析报告

> 分析日期：2026-04-17 | 分析范围：架构耦合度、内聚性、优化进度、新节点扩展可行性

---

## 一、项目架构总览

### 1.1 当前流水线拓扑

```
START → harvester → extension_handoff → writer → END
```

三节点线性主链，由 LangGraph `StateGraph` 编排，`AgentState`（TypedDict）作为全局共享状态在节点间传递。

### 1.2 分层结构

```
┌─────────────────────────────────────────────────┐
│  app.py (Flask + SocketIO)        ← 应用层       │
├─────────────────────────────────────────────────┤
│  WorkflowService                  ← 反腐层       │
├─────────────────────────────────────────────────┤
│  supervisor.py                    ← 编排门面     │
├─────────────────────────────────────────────────┤
│  workflow.py + nodes/             ← 图拓扑+节点  │
├─────────────────────────────────────────────────┤
│  engines/harvest/ + engines/report_engine/       │
│                                   ← 领域引擎层   │
├─────────────────────────────────────────────────┤
│  tools/ + llms/                   ← 外部集成层   │
├─────────────────────────────────────────────────┤
│  contracts.py + state.py + profile.py            │
│                                   ← 合约与状态层 │
└─────────────────────────────────────────────────┘
```

---

## 二、耦合度与内聚性分析

### 2.1 低耦合评估 ✅ 达标

| 维度 | 评估 | 说明 |
|------|------|------|
| 节点间耦合 | ✅ 低 | 三个节点仅通过 `AgentState` 字典通信，无直接函数调用 |
| 引擎与节点 | ✅ 低 | `harvester_node` 仅调用 `BioHarvestAgent.run()`，`writer_node` 仅调用 `create_report_agent().write_report()`，接口边界清晰 |
| 服务层隔离 | ✅ 低 | `WorkflowService` 作为反腐层，`app.py` 不直接接触图内部 |
| 合约驱动 | ✅ 低 | `contracts.py` 定义 JSON Schema，节点边界有结构校验 |
| 配置隔离 | ✅ 低 | `config.py` 使用 Pydantic Settings，环境变量注入，无硬编码 |

关键证据：
- `workflow.py` 仅 29 行，职责单一：定义拓扑，不含业务逻辑
- `supervisor.py` 是纯编排门面，不持有引擎实例
- 节点通过 `from src.engines.xxx import` 引入引擎，但仅调用顶层工厂方法

### 2.2 高内聚评估 ✅ 基本达标（有小幅改进空间）

| 模块 | 内聚性 | 说明 |
|------|--------|------|
| `engines/harvest/` | ✅ 高 | 采集逻辑完全自包含：query解析→多源检索→聚合→PDF下载→数据分层 |
| `engines/report_engine/` | ✅ 高 | 报告生成自包含：渲染→输出→质量校验 |
| `graph/nodes/` | ✅ 高 | 每个节点文件职责单一，平均 < 70 行 |
| `graph/profile.py` | ⚠️ 中高 | 聚合逻辑内聚，但 `build_biomedical_profile` 函数体量偏大（~150行），可考虑拆分子聚合器 |
| `agents/report_writer.py` | ⚠️ 中高 | 同时承担信号评分、置信度计算、Markdown渲染三项职责，可进一步拆分 |
| `tools/` | ✅ 高 | 每个外部API客户端独立文件，互不依赖 |

### 2.3 架构亮点

1. **状态透传设计**：`extension_handoff_node` 仅 17 行有效代码，完美的插槽模式
2. **合约版本化**：`CONTRACT_VERSION = "2026-04-14.v3"` 支持演进
3. **累加器语义**：`Annotated[List, operator.add]` 和自定义 `add_or_replace_list` 支持并行节点安全写入
4. **优雅降级**：harvester/writer 均有 try/except 兜底，失败不阻断状态流转
5. **日志解耦**：`_resolve_logger()` 模式统一处理 loguru/stdlib 回退

### 2.4 待改进项

| 项目 | 优先级 | 说明 |
|------|--------|------|
| `report_writer.py` 职责拆分 | P2 | 信号评分、置信度计算可抽为独立模块 |
| `profile.py` 函数拆分 | P3 | `build_biomedical_profile` 可拆为 `_aggregate_diseases`、`_aggregate_drugs`、`_aggregate_targets` 子函数 |
| 合约覆盖不完整 | P2 | `extension_handoff` 输出无合约校验，新节点接入时应补充 |
| 缺少集成测试 | P2 | 仅有 `test_dataflow_integrity.py`，缺少端到端 mock 测试 |

---

## 三、优化进度评估

### 3.1 已完成的优化（基于代码与文档对照）

| 优化项 | 状态 | 证据 |
|--------|------|------|
| 主链连通性修复 | ✅ 完成 | `workflow.py` 三条 `add_edge` 无条件连通 |
| 禁止默认中断 | ✅ 完成 | `supervisor.py:66-71` 忽略 interrupt_before 参数 |
| 前后端步骤对齐 | ✅ 完成 | 后端三节点 → 前端三步骤 (harvest/handoff/writing) |
| 合约驱动校验 | ✅ 完成 | `contracts.py` v3 版本，harvester输出+writer输入双向校验 |
| 扩展插槽预留 | ✅ 完成 | `extension_handoff_node` slot_a/slot_b 就位 |
| 反腐层封装 | ✅ 完成 | `WorkflowService` 隔离图内部 |
| 生物医学归一化 | ✅ 完成 | 药物分类、靶点标准化、疾病术语归一 |
| 多源数据采集 | ✅ 完成 | PubMed + EuroPMC + ClinicalTrials + OpenFDA + NCBI |
| 流式进度推送 | ✅ 完成 | SocketIO + ticker 线程平滑动画 |

### 3.2 成熟度评分

```
架构清晰度:    ████████░░  8/10
代码质量:      ████████░░  8/10
可扩展性:      █████████░  9/10  ← extension_handoff 设计优秀
可测试性:      ██████░░░░  6/10  ← 集成测试覆盖不足
文档完整度:    ████████░░  8/10
生产就绪度:    ███████░░░  7/10
```

**总体判断：项目已进入可扩展阶段，架构基础扎实，可以进行新节点接入。**

---

## 四、新增 Agent 节点可行性分析

### 4.1 当前扩展机制

`extension_handoff_node` 已预留 `slot_a` / `slot_b`，`writer_node` 已具备消费 `extension_payloads` 的能力（`writer_node.py:71`）。这意味着新节点可以：

1. 在 `extension_handoff` 中路由到新 agent
2. 新 agent 产出写入 `extension_payloads` 对应 slot
3. `writer` 读取扩展数据，融合进报告

### 4.2 目标：输出高置信度、疾病导向的药物综述报告

要从当前的"采集+基础报告"升级为"信息充足、置信度高、客观的疾病导向药物综述"，需要在 `extension_handoff` 中接入以下新 agent 节点：

```
推荐扩展拓扑：

START → harvester → extension_handoff ──┬── evidence_synthesizer (slot_a)
                                        ├── clinical_analyzer (slot_b)
                                        └── quality_assessor (新增 slot_c)
                                              │
                                              ▼
                                           writer → END
```

### 4.3 建议新增的三个 Agent 节点

#### Agent 1: `evidence_synthesizer`（证据综合器）— slot_a

**职责**：对 harvested_data 进行深度证据综合，而非简单罗列

- 按证据等级分层（Meta-analysis > RCT > Cohort > Case Report）
- 提取关键疗效终点（OS、PFS、ORR、CR）并结构化
- 识别矛盾证据并标注冲突点
- 生成证据强度评分（基于 GRADE 框架简化版）

**输入**：`state["harvested_data"]` + `state["harvest_data_layers"]`
**输出**：`extension_payloads["slot_a"] = { evidence_synthesis: {...} }`

#### Agent 2: `clinical_analyzer`（临床数据分析器）— slot_b

**职责**：深度解析临床试验数据，生成管线全景

- 按适应症×药物×阶段构建管线矩阵
- 计算各阶段转化率（Phase I→II→III→Approval）
- 识别 First-in-class vs Me-too 药物
- 提取安全性信号（SAE、停药率、黑框警告）
- 竞争格局分析（同靶点/同适应症药物对比）

**输入**：`state["harvested_data"]` + `state["harvest_source_payloads"]`
**输出**：`extension_payloads["slot_b"] = { clinical_analysis: {...} }`

#### Agent 3: `quality_assessor`（质量评估器）— 新增 slot_c

**职责**：对整体数据质量和报告置信度进行独立评估

- 数据完整性检查（关键字段覆盖率）
- 来源多样性评分（单一来源 vs 多源交叉验证）
- 时效性评估（文献年份分布，是否包含最新数据）
- 偏倚风险评估（发表偏倚、资助方偏倚）
- 生成最终置信度评级（A/B/C/D）及理由

**输入**：`state["harvested_data"]` + `extension_payloads["slot_a"]` + `extension_payloads["slot_b"]`
**输出**：`extension_payloads["slot_c"] = { quality_assessment: {...} }`

### 4.4 实施路径

```
Phase 1: 状态扩展
  - AgentState 新增 slot_c 相关字段（或直接复用 extension_payloads 字典）
  - contracts.py 新增 EXTENSION_OUTPUT_SCHEMA

Phase 2: 节点实现
  - src/graph/nodes/evidence_synthesizer_node.py
  - src/graph/nodes/clinical_analyzer_node.py
  - src/graph/nodes/quality_assessor_node.py

Phase 3: 拓扑改造
  - extension_handoff_node 改为路由器，串行或并行调度三个子 agent
  - 或直接在 workflow.py 中将三个节点显式编排

Phase 4: Writer 升级
  - report_writer.py 消费三个 slot 的结构化数据
  - 报告模板升级为完整药物综述格式

Phase 5: 合约与测试
  - 补充扩展节点的输入/输出合约
  - 端到端集成测试
```

### 4.5 拓扑改造方案对比

| 方案 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| A: 在 extension_handoff 内部路由 | 不改主链，向后兼容 | handoff 节点膨胀，内部耦合增加 | ⭐⭐⭐ |
| B: 显式编排为新节点 | 清晰可观测，独立失败隔离 | 需改 workflow.py 拓扑 | ⭐⭐⭐⭐⭐ |
| C: 并行分支后汇合 | 最大化吞吐 | LangGraph 并行编排复杂度高 | ⭐⭐⭐⭐ |

**推荐方案 B**，改造后拓扑：

```
START → harvester → evidence_synthesizer → clinical_analyzer
      → quality_assessor → writer → END
```

或采用混合方案（B+C），evidence_synthesizer 和 clinical_analyzer 并行，quality_assessor 等待两者完成后执行：

```
START → harvester ─┬→ evidence_synthesizer ─┐
                   └→ clinical_analyzer    ─┤→ quality_assessor → writer → END
```

---

## 五、最终结论

### 架构健康度：良好

Cassandra 项目已经完成了从"原型"到"可扩展架构"的关键跃迁。低耦合高内聚的目标基本达成，核心体现在：

- 节点通过状态字典解耦，无交叉依赖
- 引擎层自包含，可独立测试和替换
- 合约层提供了跨模块的语义约束
- 扩展插槽设计为新节点接入提供了零摩擦入口

### 是否可以进行下一步扩展：可以

`extension_handoff` 的 slot 机制、`AgentState` 的累加器语义、`contracts.py` 的版本化校验，三者共同构成了稳固的扩展基座。建议按 Phase 1→5 的路径渐进实施，优先实现 `evidence_synthesizer`（对报告质量提升最大），再逐步接入 `clinical_analyzer` 和 `quality_assessor`。

### 达到"高置信度疾病导向药物综述"的差距

| 维度 | 当前能力 | 目标能力 | 差距 |
|------|----------|----------|------|
| 数据采集 | ✅ 多源采集已完备 | 多源采集 | 无 |
| 证据分层 | ❌ 仅罗列记录 | GRADE 框架分层 | 需 evidence_synthesizer |
| 临床管线分析 | ⚠️ 基础统计 | 管线矩阵+竞争格局 | 需 clinical_analyzer |
| 置信度评估 | ⚠️ 简单启发式 | 多维独立评估 | 需 quality_assessor |
| 报告深度 | ⚠️ 摘要级 | 综述级 | 需 writer 升级 |

三个新 agent 节点全部就位后，Cassandra 将具备输出专业级药物综述报告的能力。

---

*本报告由项目架构分析生成，基于 2026-04-17 代码快照。*
