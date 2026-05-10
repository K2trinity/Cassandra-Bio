# Cassandra 参赛视频录屏清单

目标片长：4:45

主线：Evidence -> Hypothesis -> Validation

## 录制前设置

- 浏览器缩放：100%
- 窗口比例：16:9
- 录屏分辨率：1920x1080
- UI 语言：保留产品原界面；字幕、注释和转场标题统一中文
- 鼠标动作：慢速、少抖动，每次点击后停留 1-2 秒
- 禁止展示 API keys、`.env`、终端 secrets、个人账户凭据
- K-line 若展示 mock/demo 曲线，画面角落必须固定显示：`模拟演示路径，不代表真实研究收益`

## Shot 1：行业痛点，0:00-0:30

目的：建立真实业务问题。

画面元素：

- PubMed 或医学文献检索页
- ClinicalTrials 页面或 trial 表格
- FDA / 监管公告素材
- 公司管线表格，建议 Eli Lilly / donanemab 相关素材
- LLY K-line 或价格时间轴
- 手工 spreadsheet / 多窗口切换

中文屏幕注释：

`证据分散`
`来源难追溯`
`临床事实和外部反应割裂`

检查点：

- 不要让痛点镜头超过 30 秒。
- 不需要实时搜索，可使用准备好的浏览器标签或截图素材。

## Shot 2：Investigation 入口，0:30-1:15

目的：展示 Cassandra 的真实产品入口。

操作：

1. 打开 Cassandra Investigation Workspace。
2. 在输入框中输入：
   `Alzheimer's disease therapeutic landscape and pipeline competition`
3. 展示 optional PDF evidence 区域。
4. 如 UI 有 analysis target 控件，保持 `auto` 或展示 disease/company 可选能力。
5. 点击运行。
6. 停留在实时阶段区域，展示：
   `harvester -> extension_handoff -> writer`

中文屏幕注释：

`输入疾病研究问题`
`启动结构化证据工作流`
`实时阶段可观察`

检查点：

- 口播不要说“模型直接写答案”。
- 重点强调工作台和 workflow，而不是聊天框。

## Shot 3：结构化报告，1:15-2:10

目的：证明输出是可复核研究报告，不是泛泛文本。

必须捕捉的区域：

- Executive Summary
- Clinical Trial and Pipeline Landscape
- Phase / Status / Results 字段
- Pipeline Timeline and Competition Risk
- Source Audit / rejected records / references
- Markdown / HTML / PDF / IR artifacts

可选 5 秒插入镜头：

- Company report 的 Catalyst Tracker、Expansion Map、Track Record

中文屏幕注释：

`疾病级结构化报告`
`Phase / Status / Results 保留源字段`
`公司模式：Catalyst Tracker / Expansion Map / Track Record`

检查点：

- 不说 Cassandra 推断疗效、安全性或审批成功率。
- 不说 report 直接生成交易信号。

## Shot 4：当前技术引擎，2:10-2:50

目的：给技术评委证明 Cassandra 不是黑盒聊天。

画面选项：

- 首选架构图：
  `WorkflowService -> DiseaseReportOrchestrator -> deterministic evidence pipeline -> bounded LLM -> IR renderer`
- 辅助截图：
  - report IR JSON
  - Markdown / HTML / PDF artifacts
  - 简化组件链图

组件链建议展示：

```text
resolve_analysis_target()
  -> ClinicalTrials harvester
  -> normalize_trial_payload
  -> relevance / strata / risk rules
  -> narrative schema
  -> report IR
  -> Markdown / HTML / PDF
```

中文屏幕注释：

`确定性证据管线`
`受控 LLM 叙事`
`IR-first 多格式渲染`

检查点：

- 不要把历史 LangGraph 节点链作为视频主叙事。
- 可以保留前端三阶段，但要说明它是 UI 抽象。

## Shot 5：从报告到假设，2:50-3:25

目的：清楚表达核心边界。

操作：

1. 在报告中高亮 Eli Lilly / donanemab / LLY。
2. 屏幕转场字幕：
   `报告负责形成假设，事件层负责验证假设`
3. 切换到 LLY K-line workspace。

中文屏幕注释：

`疾病报告不是 ticker 回测事件源`
`选择公司 / 资产 / readout 进入外部验证`

检查点：

- 这段必须明确“报告形成假设”，不要说“报告生成交易信号”。

## Shot 6：K-line Trusted Events，3:25-3:50

目的：展示 ticker 级可信事件验证。

操作：

1. 打开 LLY K-line workspace。
2. 展示 candles / catalysts / news / macro / backtest layers。
3. 点击一个事件 tooltip，展示 source tier、confidence、impact、backtest eligible。
4. 切换 chart display mode，展示 Backtest Only 或 Candles Only。

中文屏幕注释：

`ticker 级可信事件`
`来源、范围、归属、回测资格`
`K-line 是外部验证视角`

检查点：

- 不说 Cassandra 预测市场。
- 不说事件层替代人工判断。

## Shot 7：Strategy Builder 与 Backtest，3:50-4:25

目的：展示当前版本 K-line/backtest 升级。

操作：

1. 展示 strategy builder。
2. 调整或高亮 trend、momentum、liquidity、volatility、event weights。
3. 展示 strategy formula preview。
4. 选择 Tiingo data snapshot。
5. 点击 Run Backtest。
6. 点击 Run Universe Backtest。
7. 展示 portfolio metrics、constituents、focus ticker attribution。

中文屏幕注释：

`真实多因子策略配置`
`Tiingo data snapshot`
`单 ticker + universe portfolio backtest`
`不是投资建议`

mock/demo 检查：

- 如果使用 `mock_multifactor_demo` 或展示正收益 polished curve，画面角落必须显示：
  `模拟演示路径，不代表真实研究收益`
- 如果展示真实探索性回测，不要使用“保证收益”“预测收益”等措辞。

## Shot 8：结束卡，4:25-4:45

目的：收束产品定位。

画面：

- Investigation 输入
- 报告预览
- report artifacts
- 当前架构图
- LLY K-line
- strategy builder
- portfolio diagnostics
- 结束卡：
  `Cassandra`
  `从生物医药证据到可验证研究假设的工作台`

中文结束语：

`连接证据、假设和验证，但不混淆三者`

## 全片边界检查

录制和剪辑完成后逐项检查：

- 没有说 disease report 直接生成交易信号。
- 没有说 Cassandra 预测市场。
- 没有说 Cassandra 提供投资建议。
- 没有说 Cassandra 保证收益或保证正收益。
- 没有说 Cassandra 自动下单、自动交易或替代人工研究判断。
- 没有说正收益曲线是真实研究结论。
- K-line 部分出现 mock/demo 曲线时，画面标注了 `模拟演示路径，不代表真实研究收益`。
- 字幕、注释和章节标题为中文。
- 技术架构口径使用当前版本：`WorkflowService -> DiseaseReportOrchestrator -> deterministic evidence pipeline -> bounded LLM -> IR renderer`。
