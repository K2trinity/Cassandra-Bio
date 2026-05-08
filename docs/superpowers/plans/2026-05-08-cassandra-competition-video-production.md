# Cassandra Competition Video Production Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce Chinese-language script, shot list, and subtitle assets for a sub-five-minute Cassandra competition video based on the approved `Evidence -> Hypothesis -> Validation` narrative.

**Architecture:** Keep the production package docs-only and separate from application code. The script leads with product pain, proves credibility with Cassandra's structured workflow, then transitions from disease-level research to ticker-level event validation without claiming that disease reports are backtest event sources.

**Tech Stack:** Markdown production documents, Chinese subtitle draft, existing Flask Investigation UI, existing K-line workspace, optional screen recording/editing outside the repo.

---

## Source Spec

Use `docs/superpowers/specs/2026-05-08-cassandra-competition-video-narrative-design.md` as the authority.

Non-negotiable constraints:

- Chinese is the production language for subtitles, screen annotations, and voiceover drafts.
- The disease survey report creates a research hypothesis; it is not a ticker-level event feed.
- K-line/backtest is framed as ticker-level trusted event validation.
- A positive curve or polished backtest outcome may appear only as demo/mock experience, not as real research performance.
- The video must not imply guaranteed returns, investment advice, or an autonomous trading system.

## File Structure

Create:

- `docs/competition/video/2026-cassandra-competition-script.zh.md`
  - Chinese voiceover, Chinese subtitle text, and per-scene screen direction.
- `docs/competition/video/2026-cassandra-shot-list.md`
  - Capture checklist, UI targets, recording order, and boundary labels.
- `docs/competition/video/2026-cassandra-subtitles.zh.srt`
  - Chinese subtitle draft aligned to the target 4:45 timeline.

Modify:

- `docs/competition/video/README.md`
  - Add a short index pointing to the three production assets.

Do not modify application code for this production package.

## Fixed Production Defaults

- Video length: 4 minutes 45 seconds.
- Query shown in Investigation: `Alzheimer's disease therapeutic landscape and pipeline competition`
- Ticker transition for K-line: `LLY`
- Main Chinese anchor line: `报告负责形成假设，事件层负责验证假设。`
- K-line boundary label: `ticker 级可信事件验证`
- Demo curve boundary label: `演示路径，不代表真实研究收益`
- End-card positioning: `Cassandra：从生物医药证据到可验证研究假设的工作台`

---

### Task 1: Create The Chinese Master Script

**Files:**

- Create: `docs/competition/video/2026-cassandra-competition-script.zh.md`

- [ ] **Step 1: Create the video directory**

Run:

```powershell
New-Item -ItemType Directory -Force -Path docs\competition\video
```

Expected: the directory exists and the command prints a directory object or no error.

- [ ] **Step 2: Write the master script file**

Create `docs/competition/video/2026-cassandra-competition-script.zh.md` with this content:

```markdown
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
在 evidence 阶段，Cassandra 把分散来源整理成 disease-level 的结构化输出。它不是只生成一段好看的文字，而是把资产、公司、靶点、临床阶段、文献范围、风险标签和证据引用组织到同一个报告边界里。评委看到的不是一次聊天回复，而是一条可以复核的数据链。

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
`演示路径，不代表真实研究收益`

旁白：
在 validation 阶段，Cassandra 使用 ticker 级 trusted events 做验证：事件必须有来源、范围、归属和可进入回测的资格。K-line 和 backtest 展示的是市场验证工作流，而不是疾病报告直接生成的交易信号。这里的短曲线用于展示产品体验；真实研究结论仍然要依赖可信事件和明确的数据边界。

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
```

- [ ] **Step 3: Verify required Chinese boundary lines are present**

Run:

```powershell
rg -n "报告负责形成假设|ticker 级可信事件|不把疾病综述当作交易信号|演示路径，不代表真实研究收益" docs\competition\video\2026-cassandra-competition-script.zh.md
```

Expected: at least four matching lines.

- [ ] **Step 4: Commit the script draft**

Run:

```powershell
git add docs\competition\video\2026-cassandra-competition-script.zh.md
git commit -m "docs: add cassandra competition video chinese script"
```

Expected: one docs commit.

---

### Task 2: Create The Shot List And Capture Checklist

**Files:**

- Create: `docs/competition/video/2026-cassandra-shot-list.md`

- [ ] **Step 1: Write the shot list**

Create `docs/competition/video/2026-cassandra-shot-list.md` with this content:

```markdown
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

- PubMed 搜索结果或医学文献页面
- ClinicalTrials 页面或 trial 表格
- FDA/监管关键词素材
- 公司管线表格
- 价格/K-line 图
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
- 辅助：slot/contract 的文档或 UI 摘要

中文屏幕注释：

`结构化 Agent 工作流`
`slot contract`
`quality gate`

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
4. 若使用 mock/demo 曲线，角落固定显示：
   `演示路径，不代表真实研究收益`

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
- 没有说正收益曲线是真实研究结论。
- K-line 部分出现 mock/demo 曲线时，画面标注了 `演示路径，不代表真实研究收益`。
- 字幕、注释和章节标题为中文。
```

- [ ] **Step 2: Verify shot list covers all seven story sections**

Run:

```powershell
rg -n "Shot 1|Shot 2|Shot 3|Shot 4|Shot 5|Shot 6|Shot 7" docs\competition\video\2026-cassandra-shot-list.md
```

Expected: seven matching shot headings.

- [ ] **Step 3: Commit the shot list**

Run:

```powershell
git add docs\competition\video\2026-cassandra-shot-list.md
git commit -m "docs: add cassandra competition video shot list"
```

Expected: one docs commit.

---

### Task 3: Create The Chinese Subtitle Draft

**Files:**

- Create: `docs/competition/video/2026-cassandra-subtitles.zh.srt`

- [ ] **Step 1: Write the subtitle file**

Create `docs/competition/video/2026-cassandra-subtitles.zh.srt` with this content:

```srt
1
00:00:00,000 --> 00:00:08,000
生物医药研究从来不缺信息。

2
00:00:08,000 --> 00:00:18,000
真正的问题是，证据分散在论文、临床试验、监管记录、公司公告和市场反应里。

3
00:00:18,000 --> 00:00:27,000
研究员需要在几十个页面之间来回切换，手工拼接证据、来源、公司和时间线。

4
00:00:27,000 --> 00:00:35,000
这个过程慢、难复核，也容易把临床事实和市场判断混在一起。

5
00:00:35,000 --> 00:00:45,000
Cassandra 不是通用聊天机器人，而是面向生物医药研究的 evidence-to-decision workbench。

6
00:00:45,000 --> 00:00:56,000
用户输入一个疾病研究问题，系统开始执行结构化工作流。

7
00:00:56,000 --> 00:01:15,000
它采集证据、组织疾病视图、分析临床和质量边界，最后生成可追溯来源的研究报告。

8
00:01:15,000 --> 00:01:28,000
在 Evidence 阶段，Cassandra 把分散来源整理成 disease-level 的结构化输出。

9
00:01:28,000 --> 00:01:42,000
它不是只生成一段好看的文字，而是把资产、公司、靶点、临床阶段、文献范围和风险标签组织起来。

10
00:01:42,000 --> 00:02:00,000
每个结论都尽量保留证据引用和质量边界，让输出成为可以复核的数据链。

11
00:02:00,000 --> 00:02:20,000
评委看到的不是一次聊天回复，而是一条从公开证据到结构化报告的研究链路。

12
00:02:20,000 --> 00:02:32,000
这背后是一条结构化 Agent 工作流。

13
00:02:32,000 --> 00:02:45,000
harvester 负责采集，disease survey intelligence 生成疾病综述槽位。

14
00:02:45,000 --> 00:03:05,000
后续节点分别做证据综合、临床分析和质量评估，writer 只消费已经结构化的数据。

15
00:03:05,000 --> 00:03:18,000
这里有一个关键边界：疾病报告不会被 Cassandra 伪装成单 ticker 的回测事件。

16
00:03:18,000 --> 00:03:30,000
报告负责形成研究假设，例如某个公司、资产或临床节点值得进一步观察。

17
00:03:30,000 --> 00:03:45,000
真正进入 K-line 的，是另一层 ticker 级可信事件数据。

18
00:03:45,000 --> 00:03:58,000
在 Validation 阶段，Cassandra 使用 ticker 级 trusted events 做验证。

19
00:03:58,000 --> 00:04:12,000
事件必须有来源、范围、归属和可进入回测的资格。

20
00:04:12,000 --> 00:04:25,000
K-line 和 backtest 展示的是市场验证工作流，而不是疾病报告直接生成的交易信号。

21
00:04:25,000 --> 00:04:35,000
如果画面出现演示曲线，它只代表产品体验，不代表真实研究收益。

22
00:04:35,000 --> 00:04:45,000
Cassandra 把分散的生物医药证据转化为可追溯的研究假设，再用 ticker 级可信事件做验证。
```

- [ ] **Step 2: Verify the SRT is Chinese-first and includes the core boundary**

Run:

```powershell
rg -n "疾病报告不会|ticker 级可信事件|不代表真实研究收益|Cassandra" docs\competition\video\2026-cassandra-subtitles.zh.srt
```

Expected: at least four matching subtitle entries.

- [ ] **Step 3: Commit the subtitle draft**

Run:

```powershell
git add docs\competition\video\2026-cassandra-subtitles.zh.srt
git commit -m "docs: add cassandra competition video chinese subtitles"
```

Expected: one docs commit.

---

### Task 4: Add The Video Asset Index

**Files:**

- Create: `docs/competition/video/README.md`

- [ ] **Step 1: Write the index file**

Create `docs/competition/video/README.md` with this content:

```markdown
# Cassandra Competition Video Assets

This folder contains the Chinese-language production assets for the sub-five-minute Cassandra competition video.

## Files

- `2026-cassandra-competition-script.zh.md`
  Chinese master script with scene timing, voiceover, subtitles, and screen direction.
- `2026-cassandra-shot-list.md`
  Recording checklist and capture plan.
- `2026-cassandra-subtitles.zh.srt`
  Chinese subtitle draft aligned to the target 4:45 timeline.

## Required Narrative Boundary

The video must preserve this line:

```text
报告负责形成假设，事件层负责验证假设。
```

The disease survey report is disease-level research output. It is not a single-ticker event feed. K-line/backtest should be framed as ticker-level trusted event validation. Any demo/mock curve must be labeled as demo experience, not real research performance.
```

- [ ] **Step 2: Verify all asset links are indexed**

Run:

```powershell
rg -n "script.zh|shot-list|subtitles.zh.srt|报告负责形成假设" docs\competition\video\README.md
```

Expected: four matching lines.

- [ ] **Step 3: Commit the index**

Run:

```powershell
git add docs\competition\video\README.md
git commit -m "docs: index cassandra competition video assets"
```

Expected: one docs commit.

---

### Task 5: Final Production Package Review

**Files:**

- Review: `docs/competition/video/2026-cassandra-competition-script.zh.md`
- Review: `docs/competition/video/2026-cassandra-shot-list.md`
- Review: `docs/competition/video/2026-cassandra-subtitles.zh.srt`
- Review: `docs/competition/video/README.md`

- [ ] **Step 1: Verify no forbidden claims appear**

Run:

```powershell
rg -n "保证收益|预测市场|自动交易|投资建议|报告直接生成交易信号|真实研究收益" docs\competition\video
```

Expected:

- Any matches must be boundary warnings or negations such as `不是投资建议`,
  `没有说 Cassandra 预测市场`, or `不代表真实研究收益`.
- There must be no positive claim that Cassandra guarantees returns, predicts
  the market, performs autonomous trading, gives investment advice, turns a
  disease report directly into a trading signal, or shows a demo curve as real
  research performance.

- [ ] **Step 2: Verify Chinese subtitle requirement**

Run:

```powershell
rg -n "字幕|中文|Chinese|English|bilingual" docs\competition\video docs\superpowers\specs\2026-05-08-cassandra-competition-video-narrative-design.md
```

Expected:

- Video production assets specify Chinese subtitles or Chinese production language.
- The spec no longer lists Chinese/English/bilingual as an unresolved choice.

- [ ] **Step 3: Verify the working tree only contains intended docs changes**

Run:

```powershell
git status --short
```

Expected:

- Video asset files may be staged or committed.
- `.superpowers/` may remain untracked from the brainstorming visual companion.
- No application code files changed.

- [ ] **Step 4: Commit any final review corrections**

If Step 1 or Step 2 required edits, commit only the corrected docs:

```powershell
git add docs\competition\video docs\superpowers\specs\2026-05-08-cassandra-competition-video-narrative-design.md
git commit -m "docs: refine cassandra competition video production assets"
```

Expected: one docs commit only if corrections were needed.
