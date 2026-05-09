# Cassandra 参赛视频中文脚本

目标片长：4:45

主线：Evidence -> Hypothesis -> Validation

核心台词：报告负责形成假设，事件层负责验证假设。

演示问题：Alzheimer's disease therapeutic landscape and pipeline competition

K-line 过渡 ticker：LLY

## 0:00-0:35 痛点

画面：
多个来源快速切入：PubMed、ClinicalTrials、FDA/监管、公司管线、价格图表、手工表格。

旁白：
生物医药研究从来不缺信息。真正的问题是，证据分散在论文、临床试验、监管记录、公司公告和市场反应里。研究员需要在几十个页面之间来回切换，把证据、来源、公司和时间线手工拼起来。这个过程慢、难复核，也很容易把临床事实和市场判断混在一起。

字幕：
生物医药研究不缺信息，缺的是一条可追溯的证据到决策链。

## 0:35-1:15 产品定位

画面：
打开 Cassandra Investigation Workspace。输入：
`Alzheimer's disease therapeutic landscape and pipeline competition`
展示可选 PDF 证据、运行按钮、实时进度。

旁白：
Cassandra 的定位不是一个通用聊天机器人，而是一个面向生物医药研究的 evidence-to-decision workbench。用户输入一个疾病研究问题，系统开始执行结构化工作流：采集证据、组织疾病视图、分析临床和质量边界，最后生成可以追溯来源的研究报告。

字幕：
Cassandra 是生物医药 evidence-to-decision workbench，不是黑盒聊天。

## 1:15-2:20 Evidence

画面：
展示 disease survey 报告：pipeline assets、trial landscape、literature review、company technical routes、quality assessment、evidence registry。

旁白：
在 evidence 阶段，Cassandra 把分散来源整理成 disease-level 的结构化输出。它不是只生成一段好看的文字，而是把资产、公司、靶点、临床阶段、文献范围、风险标签和证据引用组织到同一个报告边界里。用户看到的不是一次聊天回复，而是一条可以复核的数据链。

字幕：
Evidence：把疾病、资产、试验、文献和公司路线组织成可追溯报告。

## 2:20-3:05 Engine

画面：
显示简化架构图：
`harvester -> disease_survey_intelligence -> extension_handoff -> evidence_synthesizer -> clinical_analyzer -> quality_assessor -> writer`
再切回 UI 的实时执行状态。

旁白：
这背后是一条结构化 Agent 工作流。harvester 负责采集，disease survey intelligence 生成疾病综述槽位，后续节点分别做证据综合、临床分析和质量评估，writer 只消费已经结构化的数据。slot contract 和质量边界让 Cassandra 的执行过程可观察、可测试、可扩展。

字幕：
Engine：结构化 Agent 工作流、slot contract 和 quality gate，让 AI 执行可观察。

## 3:05-3:45 Hypothesis

画面：
从报告中高亮一个公司/资产，例如 Eli Lilly / donanemab / LLY。画面转向 K-line workspace。

旁白：
这里有一个关键边界：疾病报告不会被 Cassandra 伪装成单 ticker 的回测事件。报告负责形成研究假设，例如某个公司、资产或临床节点值得进一步观察。真正进入 K-line 的，是另一层 ticker 级可信事件数据。

字幕：
报告负责形成假设，事件层负责验证假设。

## 3:45-4:35 Validation

画面：
打开 LLY 的 K-line workspace。展示事件层、Backtest 面板、事件可信边界。若出现正收益或 polished curve，画面角落标注：
`模拟演示路径，不代表真实研究收益`

旁白：
在 validation 阶段，Cassandra 使用 ticker 级 trusted events 做验证：事件必须有来源、范围、归属和可进入回测的资格。K-line 和 backtest 展示的是市场验证工作流，而不是疾病报告直接生成的交易信号。这里如果出现正收益或 polished curve，只限于 mock/demo 路径，用于展示产品体验，不代表真实研究表现；真实研究结论仍然要依赖可信事件和明确的数据边界。

字幕：
Validation：用 ticker 级可信事件验证假设，不把疾病综述当作交易信号。

## 4:35-4:45 收束

画面：
快速 montage：Investigation、报告、工作流图、K-line、backtest。结束卡：
`Cassandra`
`从生物医药证据到可验证研究假设的工作台`

旁白：
Cassandra 把分散的生物医药证据转化为可追溯的研究假设，再用 ticker 级可信事件做验证。它连接研究和验证，但不混淆两者。

字幕：
Cassandra：从生物医药证据到可验证研究假设的工作台。
