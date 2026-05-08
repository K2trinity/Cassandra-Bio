# Cassandra 参赛视频录屏清单

目标片长：4:45

## 录制前设置

- 浏览器缩放：100%
- 窗口比例：16:9
- UI 语言：保留现有产品界面；视频字幕和注释统一中文
- 录屏分辨率：1920x1080
- 鼠标动作：慢速、少抖动、每次点击后停留 1-2 秒
- 禁止展示 API keys、`.env`、终端 secrets、个人账户凭据

## Shot 1：痛点素材，0:00-0:35

目的：制造行业问题张力。

画面元素：

- 准备好的 montage 素材，不要求现场实时搜索
- PubMed 搜索结果或医学文献页面；默认示例：Alzheimer's disease therapeutic pipeline
- ClinicalTrials 页面或 trial 表格；默认示例：Alzheimer disease Phase 3 trial
- FDA/监管关键词素材；默认示例：FDA Alzheimer's drug approval label 或 advisory committee 页面
- 公司管线表格；默认示例：Eli Lilly / donanemab pipeline 或 annual report pipeline 表格
- 价格/K-line 图；默认示例：LLY K-line workspace
- 手工表格或多窗口切换

中文屏幕注释：

`证据分散`
`来源难追溯`
`临床事实和市场判断割裂`

## Shot 2：Investigation 输入，0:35-1:15

目的：展示 Cassandra 的真实产品入口。

操作：

1. 打开 Cassandra Investigation Workspace。
2. 在输入框中输入：
   `Alzheimer's disease therapeutic landscape and pipeline competition`
3. 展示 optional PDF evidence 区域。
4. 点击运行。
5. 停留在实时进度区域。

中文屏幕注释：

`输入疾病研究问题`
`启动结构化证据工作流`

## Shot 3：Disease Survey 报告，1:15-2:20

目的：证明输出不是泛泛生成文本，而是结构化研究结果。

必须捕捉的报告区域：

- pipeline assets
- trial landscape
- literature review
- company technical routes
- pipeline timeline and competition risk
- evidence registry 或 references
- quality assessment

中文屏幕注释：

`疾病级研究输出`
`证据、资产、试验、公司路线可追溯`

## Shot 4：Agent 工作流，2:20-3:05

目的：给技术评委证明 Cassandra 不是黑盒聊天。

画面选项：

- 首选：简化架构图
  `harvester -> disease_survey_intelligence -> extension_handoff -> evidence_synthesizer -> clinical_analyzer -> quality_assessor -> writer`
- 辅助：实时运行状态或日志
- 辅助：槽位契约的文档或 UI 摘要

准备说明：

录制前准备 docs/competition/video/assets/agent-workflow.png 或同等架构图素材。

中文屏幕注释：

`结构化 Agent 工作流`
`槽位契约`
`质量门禁`

## Shot 5：从报告到假设，3:05-3:45

目的：清楚表达边界：报告形成假设，不直接进入回测。

操作：

1. 在报告里高亮 Eli Lilly / donanemab / LLY 相关位置。
2. 切换到 K-line workspace。
3. 转场字幕显示：
   `报告负责形成假设，事件层负责验证假设`

中文屏幕注释：

`疾病报告不是 ticker 回测事件源`
`选择一个公司或资产进入验证`

## Shot 6：K-line / Backtest 验证，3:45-4:35

目的：展示 ticker-level trusted event validation。

操作：

1. 打开 LLY K-line workspace。
2. 展示事件层。
3. 展示 Backtest 面板。
4. 只要画面中出现 mock/demo 曲线，角落全程固定显示：
   `模拟演示路径，不代表真实研究收益`

中文屏幕注释：

`ticker 级可信事件验证`
`来源、范围、归属、回测资格`
`不是投资建议`

## Shot 7：结束卡，4:35-4:45

目的：收束产品定位。

画面：

- Cassandra 名称
- Investigation、报告、workflow、K-line montage

中文结束语：

`Cassandra：从生物医药证据到可验证研究假设的工作台`

## 边界检查

录制和剪辑完成后逐项检查：

- 没有说 disease report 直接生成交易信号。
- 没有说 Cassandra 预测市场。
- 没有说 Cassandra 提供投资建议。
- 没有说 Cassandra 保证收益或保证正收益。
- 没有说 Cassandra 自动下单、自动交易或替代人工研究判断。
- 没有说正收益曲线是真实研究结论。
- K-line 部分出现 mock/demo 曲线时，画面标注了 `模拟演示路径，不代表真实研究收益`。
- 字幕、注释和章节标题为中文。
