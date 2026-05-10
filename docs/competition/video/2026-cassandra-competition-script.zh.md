# Cassandra 参赛视频中文脚本

目标片长：4:45

主线：Evidence -> Hypothesis -> Validation

核心台词：报告负责形成假设，事件层负责验证假设。

演示问题：`Alzheimer's disease therapeutic landscape and pipeline competition`

K-line 过渡 ticker：`LLY`

可选补充镜头：`Eli Lilly clinical pipeline catalyst tracker`

## 0:00-0:30 痛点

画面：
PubMed、ClinicalTrials、FDA/监管页面、公司管线表、LLY K-line、手工 spreadsheet 快速 montage。屏幕中文注释依次出现：

`证据分散`
`来源难追溯`
`临床事实和外部反应割裂`

旁白：
生物医药研究从来不缺信息。真正的问题是，论文、临床试验、监管记录、公司管线和市场反应分散在不同系统里。研究员需要手工拼接证据、来源、公司和时间线，过程慢、难复核，也很容易把临床事实和外部市场判断混在一起。

字幕：
生物医药研究不缺信息，缺的是可追溯的证据到决策链。

## 0:30-1:15 Investigation 入口

画面：
打开 Cassandra Investigation Workspace。输入：

`Alzheimer's disease therapeutic landscape and pipeline competition`

展示 analysis target 自动识别、optional PDF evidence、运行按钮、实时阶段：

`harvester -> extension_handoff -> writer`

旁白：
Cassandra 的定位不是通用聊天机器人，而是面向生物医药研究的 evidence-to-decision workbench。用户输入一个疾病或公司级问题，系统会启动结构化工作流：先采集 ClinicalTrials 证据，再组织报告包，最后生成可预览、可下载、可复核来源的研究报告。

字幕：
Cassandra 是生物医药 evidence-to-decision workbench，不是黑盒聊天。

## 1:15-2:10 结构化报告

画面：
展示 disease report：executive summary、clinical trial and pipeline landscape、phase/status/results、pipeline timeline and competition risk、source audit、Markdown / HTML / PDF / IR artifacts。可快速插入一屏 company report，显示 Catalyst Tracker、Expansion Map、Track Record。

旁白：
在 Evidence 阶段，Cassandra 把分散证据整理成 disease-level 或 company-level 的结构化输出。疾病模式关注 clinical landscape、phase、status、results 和竞争风险；公司模式关注 Catalyst Tracker、Expansion Map 和 Track Record。LLM 只总结已经提供的结构化 JSON，不能创造试验、日期、结果、风险标签或成功率。

字幕：
Evidence：把临床试验、公司管线、风险和来源组织成可复核报告。

## 2:10-2:50 技术引擎

画面：
展示当前版本架构图：

`WorkflowService -> DiseaseReportOrchestrator -> deterministic evidence pipeline -> bounded LLM -> IR renderer`

再切到报告 IR 或 renderer artifacts。

旁白：
技术上，Cassandra 采用 deterministic pipeline 加 bounded LLM。`WorkflowService` 提供稳定入口，`DiseaseReportOrchestrator` 编排目标解析、ClinicalTrials 采集、Pydantic 归一化、相关性过滤、风险规则、章节摘要、IR 构建和多格式渲染。事实字段和风险信号由代码生成，LLM 只负责在边界内解释这些数据。

字幕：
Engine：事实由确定性代码处理，LLM 只在结构化证据边界内叙事。

## 2:50-3:25 从报告到假设

画面：
在报告中高亮 Eli Lilly / donanemab / LLY，转场到 K-line workspace。转场字幕固定显示：

`报告负责形成假设，事件层负责验证假设`

旁白：
这里是 Cassandra 的关键边界：疾病报告不会被伪装成单 ticker 的交易事件。报告负责形成研究假设，例如某个公司、资产或临床 readout 值得进一步观察。真正进入 K-line 的，是另一层 ticker 级 trusted events。

字幕：
报告形成研究假设；ticker 级可信事件负责验证假设。

## 3:25-4:25 K-line 与回测验证

画面：
打开 LLY K-line workspace。依次展示：

- candles / catalysts / news / macro / backtest layers
- 事件 tooltip：source tier、confidence、impact、backtest eligible
- chart display mode
- strategy builder：trend、momentum、liquidity、volatility、event weights
- Tiingo data snapshot
- Run Backtest 与 Run Universe Backtest
- portfolio metrics、constituent leaderboard、focus ticker attribution

若画面出现 mock/demo 曲线，角落全程固定标注：

`模拟演示路径，不代表真实研究收益`

旁白：
在 Validation 阶段，Cassandra 使用 ticker 级 trusted events 做外部验证。事件必须有来源、范围、归属和回测资格；真实多因子策略可以调整权重、窗口和阈值；组合回测要求 Tiingo data snapshot。K-line 和 backtest 展示的是验证工作流，不是疾病报告直接生成的交易信号。如果出现正收益或精修曲线，它只属于 mock/demo 路径，不代表真实研究收益。

字幕：
Validation：用可信事件、策略配置和数据快照验证假设，不提供投资建议。

## 4:25-4:45 收束

画面：
快速 montage：Investigation 输入、报告预览、IR artifacts、架构图、LLY K-line、strategy builder、portfolio diagnostics。结束卡：

`Cassandra`

`从生物医药证据到可验证研究假设的工作台`

旁白：
Cassandra 把分散的生物医药证据转化为可追溯报告，再从报告中形成研究假设，并用 ticker 级可信事件做外部验证。它连接证据、假设和验证，但不混淆三者。

字幕：
Cassandra：从生物医药证据到可验证研究假设的工作台。
