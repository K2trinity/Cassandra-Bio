# Cassandra 竞赛技术方案文档

更新日期：2026-05-11

参赛定位：面向生物医药科研、产业分析与外部事件验证的 evidence-to-decision workbench

核心主线：

```text
Evidence -> Hypothesis -> Validation
```

核心边界：

```text
报告负责形成假设，事件层负责验证假设。
```

## 1. 当前版本摘要

Cassandra 当前版本不是一个通用聊天机器人，也不是单一金融回测工具，而是一个把生物医药公开证据组织成可追溯研究判断的结构化工作台。它从疾病或公司级问题出发，采集 ClinicalTrials.gov 证据，经过实体解析、条件发现、试验归一化、相关性过滤、风险规则、报告 IR 和多格式渲染，形成可复核的研究报告；当报告中的假设关联到上市公司、临床 readout、监管节点或外部市场反应时，K-line trusted event layer 再提供 ticker 级验证视角。

当前可展示能力分为四个层次：

1. Investigation Workspace：面向疾病或公司问题，支持 `auto / disease / company` 分析目标，输出实时阶段、报告预览和 Markdown / HTML / PDF / IR artifacts。
2. Disease / Company Report：疾病模式强调 ClinicalTrials evidence synthesis；公司模式强调 `Catalyst Tracker / Expansion Map / Track Record`，但不推断疗效、安全性、审批成功率或市场表现。
3. K-line Validation Workspace：从报告中的公司或资产假设过渡到 ticker，展示 OHLC、可信事件、source status、event metadata、range context 和最近回测。
4. Backtest Lab Surface：支持真实多因子策略、可编辑 strategy builder、单 ticker 回测、Tiingo data snapshot、biotech universe portfolio backtest、focus ticker attribution，以及 mock/research 数据模式隔离。

这套设计让 Cassandra 同时满足参赛评审最关心的五件事：技术架构可解释、AI 输出有边界、报告可追溯、交互有闭环、演示有冲击力。

## 2. 评分准则映射

| 评分项 | Cassandra 当前版本对应设计 |
| --- | --- |
| 创新性 | 把生物医药 evidence synthesis、转化假设和外部事件验证拆成三层；LLM 只做受控叙事，事实、风险、事件资格、策略权限和 mock/research 边界由确定性代码治理。 |
| 效率 | Investigation 以 `WorkflowService` 和 `DiseaseReportOrchestrator.stream()` 组织流式阶段；ClinicalTrials 记录并行归一化；K-line 先渲染 shell，再通过 workspace API 异步加载；默认 cache-only 避免点击后阻塞外部刷新。 |
| 鲁棒性 | Pydantic 模型 `extra="forbid"`；ClinicalTrials 条件发现和 relevance gate 控制误召回；事件进入回测前必须满足 trust predicate；策略配置和数据源模式在 API 层校验。 |
| 实用价值 | 科研人员可直接获得疾病全景；BD / 医学策略人员可识别公司、资产、临床节点和竞争风险；投研人员可在需要时继续做 ticker 级事件验证和探索性回测。 |
| 人机交互 | Web Investigation、实时阶段、报告预览、报告列表、K-line layers、strategy builder、chart display mode、portfolio diagnostics 和 focus ticker attribution 形成连续工作流。 |
| 展示效果 | 4:45 视频可按 “证据分散痛点 -> 结构化报告 -> 确定性引擎 -> 假设过渡 -> K-line 验证” 完成；如出现正收益曲线，必须标注 mock/demo-only。 |

## 3. 问题背景与用户价值

生物医药研究不是缺少信息，而是信息散落在不同系统里：

- ClinicalTrials.gov 提供临床试验事实，但需要处理条件匹配、NCT 去重、phase/status/results、终点和关键日期。
- PubMed、Europe PMC、公司管线、监管公告和新闻事件提供补充证据，但格式、可信度和可引用性不一致。
- 科研问题常常是 disease-level，但产业和市场验证又会落到 company / asset / ticker 节点。
- 如果直接让 LLM 写结论，容易把事实、推断、市场解释和演示效果混在一起。

Cassandra 的价值是把这条链路结构化：

```text
用户问题
  -> 疾病或公司目标解析
  -> ClinicalTrials 证据采集和归一化
  -> 相关性过滤、分层、风险规则和 source audit
  -> 受控 LLM 章节摘要
  -> 报告 IR 与多格式渲染
  -> 研究假设
  -> ticker 级可信事件验证
  -> 单 ticker / universe backtest
```

在这个链路中，Investigation report 自身已经是科研和产业分析产物。K-line 不是必经终点，而是在用户需要验证上市公司、监管节点、临床 readout 或外部反应时接入的下游视角。疾病报告不会被直接伪装成交易信号。

## 4. 产品工作区

### 4.1 Investigation Workspace

Investigation 是 Cassandra 的主工作区。它接受疾病或公司级自然语言问题，可在后端通过 `analysis_target_type` 自动识别或显式指定目标类型。

典型输入：

```text
Alzheimer's disease therapeutic landscape and pipeline competition
```

或：

```text
Eli Lilly clinical pipeline catalyst tracker
```

输出包括：

- 实时阶段：`harvester -> extension_handoff -> writer`
- 结构化报告包：ClinicalTrials records、risk records、source audit、narratives
- 报告 artifacts：Markdown、HTML、PDF、IR JSON
- 报告预览和历史报告列表

前端展示三个阶段是为了降低用户认知负担。后端并不是简单三步脚本，而是由一组明确组件完成事实处理、报告组织和渲染。

### 4.2 Disease Report 与 Company Report

疾病模式和公司模式共享同一套报告基础设施，但叙事目标不同。

| 模式 | 目标 | 关键输出 | 禁止事项 |
| --- | --- | --- | --- |
| Disease | 形成 disease-level 全景 | Clinical trial landscape、phase/status/results、pipeline risk、disease evidence synthesis、source audit | 不引入公司模式标签，不把疾病结论改写成交易信号 |
| Company | 形成 sponsor/company pipeline 视角 | Catalyst Tracker、Expansion Map、Track Record、company clinical pipeline summary | 不推断成功率、审批概率、疗效、安全性或市场收益 |

公司模式的三个章节含义：

- `Catalyst Tracker`：围绕近期 readout 或事件驱动节点的试验视图。
- `Expansion Map`：围绕 recruiting R&D allocation 的疾病和适应症扩展视图。
- `Track Record`：围绕 result-bearing historical evidence 的历史证据视图，不等于成功率判断。

这让 Cassandra 可以同时服务科研综述和公司管线分析，但不会把公司管线摘要伪装成投研结论。

### 4.3 K-line Validation Workspace

K-line 是下游验证工作区。它只有在报告中的假设已经关联公司、ticker、临床 readout、监管事件或其他外部可观察节点时才自然接入。

K-line 工作区提供：

- ticker / company 解析
- candles、catalysts、news、macro、backtest 分层
- event tooltip：source tier、confidence、impact、backtest eligibility
- chart display mode：Candles + Backtest、Backtest Only、Candles Only
- range context 和事件高亮
- 单 ticker 回测与 universe portfolio backtest

这个工作区的核心不是“预测市场”，而是用可信事件和可审计回测观察一个研究假设在外部世界中的时间轴反应。

## 5. 系统架构

### 5.1 应用层与编排层

当前 Investigation 主路径：

```text
/investigation
  -> WorkflowService
  -> DiseaseReportOrchestrator.stream()
  -> harvester state
  -> extension_handoff state
  -> writer state
  -> report artifacts
```

`WorkflowService` 是应用层 facade，负责对 Web 层提供稳定接口。`DiseaseReportOrchestrator` 是报告编排核心，按流式状态向前端暴露阶段，同时把后端复杂度隐藏在组件边界内。

### 5.2 报告生成组件链

后端真实组件链可以概括为：

```text
resolve_analysis_target()
  -> DiseaseResolver / company target resolver
  -> ClinicalTrialsConditionDiscovery
  -> ClinicalTrialsDiseaseHarvester / ClinicalTrialsCompanyHarvester
  -> normalize_trial_payload
  -> DiseaseRelevanceGate
  -> assign_landscape_strata
  -> RuleBasedRiskEngine
  -> DiseaseReportPackageBuilder
  -> DiseaseReportNarrativeService
  -> DiseaseReportIRBuilder
  -> DiseaseReportRendererAdapter
```

关键设计：

- `resolve_analysis_target()` 决定 disease / company 目标，避免把公司查询误当成疾病查询。
- Disease 模式走条件发现、disease harvester 和 relevance gate。
- Company 模式走 sponsor/company harvester，并提升记录上限以覆盖公司 pipeline。
- `normalize_trial_payload` 将 ClinicalTrials API v2 payload 转成 Pydantic record。
- `RuleBasedRiskEngine` 只根据已有字段生成 timeline / competition 信号。
- `DiseaseReportNarrativeService` 使用 response schema 约束 LLM 输出。
- `DiseaseReportIRBuilder` 生成单一 IR，再由 renderer adapter 输出 Markdown / HTML / PDF / IR JSON。

### 5.3 Bounded LLM 设计

LLM 在 Cassandra 中不是事实生产者，而是受控叙事层。系统提示明确要求：

- 只根据 supplied JSON 写章节摘要。
- 不创建 trial、sponsor、日期、结果、endpoint、risk label 或数值。
- 不覆盖 ClinicalTrials.gov 源字段。
- 不推断 efficacy、safety、approval odds 或 market impact。
- 证据稀疏时必须说 data insufficient。

因此 Cassandra 的 AI 能力不是“自由生成”，而是“在结构化证据边界内解释”。

### 5.4 报告 IR 与多格式渲染

报告不直接拼接 Markdown 字符串，而是先构建 document IR。IR 的作用是：

- 固定章节、表格、source audit、risk records 和 metadata 的结构。
- 让 Markdown / HTML / PDF 使用同一份中间表示。
- 支持测试、审计和后续 API 输出。
- 避免不同格式之间出现内容漂移。

## 6. K-line 与回测设计

### 6.1 Workspace 加载路径

K-line 页面使用异步加载：

```text
/kline/<symbol> -> render shell
/api/kline/workspace/<symbol> -> fetch workspace JSON
```

默认 workspace API 采用 `cache_only=true`。用户点击进入 K-line 时先看到可交互 shell；只有主动 refresh 或回测操作才触发更重的数据刷新。这直接解决了 K-line 点击后首屏等待过长的问题。

`KlineWorkspaceService` 聚合：

- `OHLCProvider`：价格序列和缓存状态。
- `CatalystEventProvider`：临床、监管、公司、新闻和宏观事件。
- `BacktestResultProvider`：最近回测结果和诊断摘要。

### 6.2 Trusted Event Layer

图表事件和回测事件不是同一个宽松集合。进入回测的事件必须通过 trust predicate：

```text
ticker_scope matches ticker
AND trust_status in trusted statuses
AND schema_version >= trusted schema version
AND ownership_status in backtest-trusted ownership statuses
AND metadata.backtest_eligible == true
```

事件 payload 保留：

- source / source_url / source_ids
- source_entity / source_tier / source_kind
- confidence_score / impact_score
- backtest_eligible
- metadata

这保证 K-line 上“可观察的事件”和回测中“可量化的事件”有明确边界。

### 6.3 Strategy Builder 与单 ticker 回测

当前真实多因子策略支持可编辑配置：

```text
alpha =
  trend_weight * trend(fast, slow)
  + momentum_weight * momentum(window)
  + liquidity_weight * liquidity(volume_window)
  + volatility_weight * volatility(window)
  + event_weight * event_score

long  if alpha > long_threshold
short if alpha < short_threshold
```

前端 strategy builder 可以调整：

- trend / momentum / liquidity / volatility / event 权重
- fast / slow / momentum / volatility / volume 窗口
- long / short threshold

后端通过 `normalize_real_multifactor_strategy_config()` 校验配置：

- 不允许未知 section 和未知 key。
- `fast` 必须小于 `slow`。
- `short` 必须小于 `long`。
- `long` 必须为正，`short` 必须为负。
- 权重、窗口和阈值必须是有限数值并在允许范围内。

策略公式会作为公开诊断输出，但内部 mock 字段、data mode、positive demo metadata 不会泄漏到公共结果面板。

### 6.4 Universe Portfolio Backtest

当前版本支持 biotech universe portfolio backtest。组合回测要求：

- 使用 Tiingo snapshot prices。
- 必须提供 `data_snapshot_id`。
- 默认选择 `biotech_us_v1` 的 Tiingo snapshot。
- 每个 constituent 运行真实多因子策略，不再使用旧的四 ticker mock portfolio。
- 输出 portfolio equity curve、portfolio metrics、constituent leaderboard 和 focus ticker attribution。

如果 focus ticker 不在 snapshot coverage 中，系统会明确显示 focus ticker unavailable，而不是制造缺失数据。

### 6.5 数据模式与策略权限

策略 registry 管理 research/mock 边界：

| strategy_id | 用途 | research_allowed | mock_only |
| --- | --- | ---: | ---: |
| `event_baseline` | 基础事件验证 | true | false |
| `multifactor_score` | 真实多因子探索策略 | true | false |
| `mock_multifactor_demo` | A 路径正收益演示 | false | true |
| `ml_probability` | 后续 ML 概率策略预留 | true | false |

`mock_multifactor_demo` 只能在以下条件同时满足时运行：

```text
data_mode == mock
mock_scope == biotech_mock_v1
ticker in MRNA / JNJ / LLY / ABBA
```

这条规则是参赛展示的安全边界：A 可以是 mock/demo 路径，可以展示正收益曲线；B/C research 路径不能继承 mock 造景逻辑。

画面出现 mock 或 polished curve 时必须标注：

```text
模拟演示路径，不代表真实研究收益
```

## 7. 数据与审计层

Cassandra 使用多层数据结构支撑可复现性：

- ClinicalTrials.gov API v2：当前 Investigation 报告主事实源。
- SQLite event store：保存 biotech ticker events、fetch log、trust metadata 和 eligibility。
- DuckDB research catalog：保存 universe、data snapshots、backtest runs、provider fetch log、ingestion checkpoints。
- Parquet snapshots：保存价格快照、event-price links 和离线回放数据。
- data snapshot manifest：记录 provider、coverage、fetch summary、skipped、source hashes，并脱敏 secret。
- IR JSON：报告渲染的单一中间表示。

这让 Cassandra 不只是做一次演示，而是能沉淀可复核的研究运行记录。

## 8. 效率与鲁棒性

### 8.1 效率设计

- Investigation 流式输出阶段，用户能看到系统进度。
- ClinicalTrials normalization 使用 `ThreadPoolExecutor(max_workers=4)`。
- Disease report 默认限制 `max_trials`，公司模式使用单独 record limit。
- K-line 默认先渲染 shell，再异步加载 workspace JSON。
- 默认 `cache_only=true` 避免点击时阻塞外部 API 刷新。
- OHLC 和事件层带 freshness / source status，避免无提示地等待慢源。
- LLM 只消费压缩后的结构化 JSON，不直接读取长网页和全量表格。

### 8.2 鲁棒性设计

- Pydantic 模型禁止未知字段。
- ClinicalTrials 条件发现优先使用 FullMatch 条件。
- Disease 模式通过 relevance gate 过滤偏离疾病主题的记录。
- 风险规则缺少字段时输出 `Data insufficient`，不硬编判断。
- Provider 失败以 status / warning / fetch log 暴露，不让页面整体崩溃。
- Tiingo portfolio backtest 缺少 snapshot 时拒绝运行。
- Mock 策略在 real / exploratory / research-grade 模式中被拒绝。

### 8.3 偏差控制

回测结果显式暴露：

- data_snapshot_id
- price_source
- backtest_mode
- bias_profile
- bias_warnings
- source_status_at_run
- event_filter
- event_attribution
- factor_attribution
- baseline

研究级回测如果数据源不支持 delisted securities、point-in-time universe 或 delisting returns，应被数据源策略拒绝。探索性回测可以运行，但必须带 bias warning。

## 9. 学习机制

Cassandra 当前的学习机制不是在线修改模型权重，而是把运行经验沉淀为可审计记录：

- source audit：记录 retained/rejected ClinicalTrials records 和 rejected NCT。
- provider fetch log：记录外部源请求、状态、retry、rate limit 和错误。
- ingestion checkpoints：记录下载任务 success / skipped / failed。
- data snapshot manifest：记录覆盖率、来源 hash 和缺失原因。
- backtest result payload：记录策略配置、metrics、equity curve、trades、事件归因和因子归因。

这些记录可以反向改进检索词、过滤规则、风险规则、数据覆盖和策略参数，但不能绕过 source contract 或 mock/research 权限。

## 10. 现场展示方案

推荐演示主问题：

```text
Alzheimer's disease therapeutic landscape and pipeline competition
```

推荐 K-line 过渡 ticker：

```text
LLY
```

可选公司模式演示问题：

```text
Eli Lilly clinical pipeline catalyst tracker
```

### 10.1 4:45 展示节奏

| 时间 | 内容 | 评委感知 |
| --- | --- | --- |
| 0:00-0:30 | PubMed、ClinicalTrials、监管、公司管线、市场图表 montage | 行业痛点真实 |
| 0:30-1:15 | 打开 Investigation，输入疾病级问题，展示实时阶段 | 产品入口明确 |
| 1:15-2:10 | 展示报告：phase/status/results、risk、source audit、IR artifacts；可插入公司模式三栏截图 | 不是泛文本生成，而是结构化报告 |
| 2:10-2:50 | 展示引擎图：deterministic pipeline + bounded LLM + IR renderer | 技术可信、边界清楚 |
| 2:50-3:25 | 从报告高亮 Eli Lilly / donanemab / LLY | 报告形成研究假设 |
| 3:25-4:25 | 打开 LLY K-line，展示 trusted events、strategy builder、Tiingo snapshot、single/portfolio backtest | 事件层验证假设，不是直接生成交易信号 |
| 4:25-4:45 | 收束：Cassandra 连接证据、假设和验证，但不混淆三者 | 产品定位完整 |

### 10.2 展示必须保留的口径

```text
Cassandra 的核心不是金融预测，而是生物医药证据工作台。
```

```text
报告负责形成假设，事件层负责验证假设。
```

```text
K-line 和 backtest 是 ticker 级外部事件验证视角，不是疾病报告直接生成的交易信号。
```

```text
如果画面中出现正收益曲线，该曲线仅为 mock/demo 路径，不代表真实研究收益。
```

## 11. 工程验证建议

竞赛前建议至少执行以下验证：

```powershell
New-Item -ItemType Directory -Force -Path '.pytest_tmp' | Out-Null
pytest tests/reports/disease tests/test_kline_workspace_service.py tests/test_kline_web_integration.py tests/test_kline_backtest_runner.py tests/test_backtest_mock_dataset.py -q --basetemp .pytest_tmp\competition-tech
npm run build --prefix src/kline
```

重点检查：

- Investigation disease/company 两类问题都能生成报告。
- Markdown / HTML / PDF / IR artifacts 路径存在。
- K-line shell 可以快速渲染，workspace JSON 异步加载。
- Backtest options 能返回 Tiingo snapshots 和 portfolio defaults。
- strategy builder 请求包含 `strategy_config`，无效配置被拒绝。
- Portfolio backtest 要求 Tiingo `data_snapshot_id`。
- mock disclosure 不泄漏到 real / portfolio diagnostics。
- 视频画面中任何 mock 曲线都有中文边界标注。

## 12. 当前版本边界与后续方向

当前可展示能力：

- Disease report：ClinicalTrials disease-level evidence synthesis、phase/status/results、risk records、source audit、多格式报告。
- Company report：company sponsor pipeline 视角、Catalyst Tracker、Expansion Map、Track Record。
- K-line workspace：异步加载、可信事件层、chart display mode、range context、事件 metadata。
- Backtest：真实多因子 strategy builder、单 ticker run、Tiingo snapshot、universe portfolio run、focus ticker attribution。
- Governance：event trust predicate、strategy registry、data source policy、mock/research 隔离。

近期增强方向：

- 继续完善 ClinicalTrials landscape 的 Foundation / Frontier / Evidence 分层展示。
- 扩展公司管线来源，把 company route provider 从 noop 扩展到更多公开 pipeline 页面。
- 将 research-grade backtest 的 point-in-time universe、delisting returns 和数据覆盖报告做成更完整的 UI。
- 在不破坏 mock/research 边界的前提下，为 B/C research path 接入 ML probability strategy。

## 13. 结论

Cassandra 的参赛优势不是“用了大模型”，而是把大模型放在正确的位置：事实由数据源和确定性代码处理，边界由模型和策略合约约束，叙事由 bounded LLM 完成，报告由 IR 渲染，外部验证由 ticker 级可信事件和回测层承担。

它给评委看到的是一个完整而克制的 AI 系统：

- 能处理真实生物医药证据。
- 能输出可追溯报告。
- 能从报告自然过渡到产业和外部事件验证。
- 能展示策略配置和组合回测能力。
- 能明确区分 mock demo、exploratory research 和 future research-grade path。

因此 Cassandra 同时回应技术创新、效率、鲁棒性、实用价值和展示效果：它不是黑盒聊天，也不是投资建议工具，而是从生物医药证据到可验证研究假设的工作台。
