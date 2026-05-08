# Cassandra Competition Video Narrative Design

Date: 2026-05-08

## Purpose

This design defines the product narrative for a sub-five-minute Cassandra
competition video. The video should make Cassandra feel useful to product
judges and credible to technical judges without overstating what the current
system does.

The approved story structure is:

```text
Evidence -> Hypothesis -> Validation
```

The video target length is 4:30 to 4:50.

## Target Audience

The primary audience is a mixed product and technical judging panel:

- Product judges should quickly understand the industry pain, user workflow,
  and product value.
- Technical judges should see that Cassandra is not a black-box chatbot. It is
  a structured, observable, contract-driven agent workflow.

The narrative should avoid becoming either a pure architecture walkthrough or a
pure pitch deck. The product story leads, and the technical architecture proves
why the product is trustworthy.

## Narrative Thesis

Cassandra is a biomedical evidence-to-decision workbench.

It turns scattered disease, trial, literature, company, and market context into
traceable research outputs. It then helps users move from a disease-level
research summary to a ticker-level validation workflow without mixing those two
evidence boundaries.

The core line is:

```text
The report creates the hypothesis. The event layer tests it.
```

Primary subtitle and voiceover line:

```text
报告负责形成假设，事件层负责验证假设。
```

English may appear as a short visual accent, but Chinese is the production
language for subtitles, on-screen explanatory text, and voiceover scripts.

## Non-Negotiable Product Boundaries

The video must preserve these boundaries:

- The disease survey report is disease-level research output. It is not a
  single-ticker event feed.
- The K-line and backtest workflow must be framed as ticker-level event
  validation using trusted events, not as direct trading signals generated from
  the disease report.
- Cassandra may connect disease investigation to market validation, but it must
  not claim that broad disease summaries are valid backtest inputs.
- If a positive curve or polished backtest outcome appears, it must be treated
  as a demo/mock experience, not a real research performance claim.
- The video should not imply guaranteed returns, investment advice, or a
  production trading system.

## Approved Story Arc

### 0:00-0:35 - Pain

Message:

Biotech research is not short on information. It is short on a reliable chain
from biomedical evidence to decisions.

Show:

- PubMed papers, ClinicalTrials records, FDA/regulatory signals, company
  pipeline data, and price reactions as scattered inputs.
- A researcher or analyst manually moving across tabs, PDFs, tables, and market
  charts.

Judge takeaway:

Cassandra addresses a real workflow pain: evidence is fragmented, provenance is
hard to preserve, and clinical research is disconnected from market validation.

### 0:35-1:15 - Product Promise

Message:

Cassandra is not a general chat assistant. It is a biomedical research
workbench that executes a structured evidence workflow.

Show:

- The Investigation workspace.
- A disease-oriented query.
- Optional PDF evidence upload.
- Live progress or stage indicators.

Judge takeaway:

The product has a concrete user entry point and a focused domain.

### 1:15-2:20 - Evidence

Message:

Cassandra gathers, structures, and renders disease-level evidence into a
traceable disease survey.

Show:

- Multi-source biomedical harvesting.
- Disease survey report sections.
- Pipeline assets.
- Trial landscape.
- Literature review.
- Evidence registry or references.
- Quality assessment.

Judge takeaway:

The output is not just generated prose. It is based on structured upstream
evidence and report-ready data.

### 2:20-3:05 - Engine

Message:

The system is credible because the agent workflow is structured and observable.

Show:

The simplified backend chain:

```text
harvester
-> disease_survey_intelligence
-> extension_handoff
-> evidence_synthesizer
-> clinical_analyzer
-> quality_assessor
-> writer
```

Also show:

- Slot-based handoff.
- Contract boundaries.
- Quality assessment.
- Real-time execution state.

Judge takeaway:

Cassandra is not hiding everything behind a prompt. It has explicit workflow
steps, data contracts, and a quality boundary.

### 3:05-3:45 - Hypothesis

Message:

The report does not become a backtest event source. Instead, it helps the user
identify a company, asset, target, clinical milestone, or competitive pattern
that can become a ticker-level hypothesis.

Show:

- A disease report section that identifies relevant companies or assets.
- A transition from report context to selecting one company/ticker for further
  validation.

Required voiceover idea:

```text
disease report 负责形成研究假设，但它不会被伪装成交易信号。
```

Judge takeaway:

Cassandra has domain discipline. It connects research and validation while
keeping their evidence boundaries separate.

### 3:45-4:35 - Validation

Message:

K-line and backtest validate ticker-level events through a separate trusted
event layer.

Show:

- K-line workspace.
- Event layers.
- Trusted event metadata or eligibility.
- Backtest panel.
- A short demo/mock curve if needed for visual energy.

Required boundary:

The narration must distinguish real ticker-level event validation from any
mock/demo curve. The curve can show the intended product experience, but it
should not be described as real performance evidence.

Judge takeaway:

Cassandra can move beyond report generation into validation, but it does so
through a controlled event boundary.

### 4:35-4:50 - Close

Message:

Cassandra connects biomedical evidence, research hypotheses, and market
validation in one traceable workflow.

Show:

- Fast montage of Investigation, report, workflow graph, K-line, and backtest.
- End card with Cassandra name and one-sentence positioning.

Candidate closing line:

```text
Cassandra 把分散的生物医药证据转化为可追溯的研究假设，再用 ticker 级可信事件做验证，而不是把疾病综述混同为交易信号。
```

## Recommended Voiceover Tone

Use precise Chinese product language, not hype-heavy AI language. Subtitles,
screen annotations, section labels, and narration drafts should be Chinese by
default. English terms such as `Evidence`, `Hypothesis`, `Validation`,
`K-line`, and `ticker-level trusted events` may appear when they are product or
technical terms, but each must be understandable from the surrounding Chinese
caption.

Prefer:

- traceable
- structured
- evidence-backed
- workflow
- hypothesis
- validation
- provenance
- quality boundary

Avoid:

- guaranteed alpha
- predicts the market
- autonomous trading
- one-click investment decisions
- disease report becomes a trading signal
- replaces analysts

## Demo Capture Rules

The video may use a two-layer K-line sequence:

1. Real boundary explanation:
   - ticker-level trusted events
   - explicit event eligibility
   - provenance-aware backtest framing

2. Short visual demo:
   - a polished curve or mock path may be used for pacing
   - it must be framed as demo/mock experience
   - it must not be positioned as real B/C research evidence

The demo section should be brief, ideally under 25 seconds, so the video does
not appear to be selling performance instead of product capability.

## Visual Structure

The video should use a workbench feel, not a marketing hero page.

Recommended visual rhythm:

- start with fragmented evidence sources
- move into the Investigation UI
- show the structured report
- reveal the workflow graph and slots
- transition from disease-level report to ticker selection
- show K-line trusted events and backtest
- close with the full evidence-to-validation loop

## Success Criteria

The final video is successful if a judge can repeat these points after watching:

- Cassandra solves evidence fragmentation in biomedical research.
- Cassandra produces disease-level research output with traceable evidence.
- Cassandra's agent workflow is structured, observable, and contract-driven.
- Cassandra does not misuse disease reports as single-ticker backtest events.
- Cassandra connects disease research to ticker-level validation through a
  separate trusted event layer.
- Any positive demo curve is demo/mock-only and not a real research claim.

## Open Production Choices

The script and capture plan should still decide:

- exact disease query used in the video
- exact ticker used for the K-line transition
- whether the K-line curve is real event validation, mock demo, or both
- whether to keep any short English anchor words as visual accents alongside
  Chinese subtitles
- whether to include a short architecture diagram or only UI footage
