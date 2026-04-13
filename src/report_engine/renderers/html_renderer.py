"""
HTML Renderer v2.0

从 IR (Intermediate Representation) 生成富 HTML 报告。

特性：
- ✅ 全量 BlockType 支持（heading/paragraph/list/quote/table/chart/formula/wordcloud/image/callout/code/divider）
- ✅ Chart.js 图表（bar/line/pie/doughnut/scatter/radar/bubble 等）
- ✅ MathJax LaTeX 数学公式渲染
- ✅ WordCloud2 词云图
- ✅ 自动目录（TOC）生成
- ✅ 章节自动编号
- ✅ 响应式布局，支持打印样式
- ✅ 内嵌所有依赖（CDN），无需本地安装
"""

import json
import html
import re
import uuid
from typing import Any, Dict, List, Optional
from loguru import logger

# Internal IR types
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from src.report_engine.ir.schema import (
    IRDocument, Chapter, ChapterBlock, BlockType
)


# ─────────────────────────────────────────────────────────────────────────────
# Inline Markdown renderer (lightweight, no external deps)
# ─────────────────────────────────────────────────────────────────────────────
_INLINE_MD_PATTERNS = [
    (re.compile(r'\*\*\*(.+?)\*\*\*'), r'<strong><em>\1</em></strong>'),
    (re.compile(r'\*\*(.+?)\*\*'),     r'<strong>\1</strong>'),
    (re.compile(r'\*(.+?)\*'),         r'<em>\1</em>'),
    (re.compile(r'`(.+?)`'),           r'<code class="inline-code">\1</code>'),
    (re.compile(r'\[(.+?)\]\((.+?)\)'), r'<a href="\2" target="_blank" rel="noopener">\1</a>'),
    (re.compile(r'~~(.+?)~~'),         r'<del>\1</del>'),
]

def _render_inline(text: str) -> str:
    """渲染内联 Markdown 标记（粗体/斜体/代码/链接/删除线）"""
    text = html.escape(text, quote=False)
    for pattern, repl in _INLINE_MD_PATTERNS:
        text = pattern.sub(repl, text)
    return text


# ─────────────────────────────────────────────────────────────────────────────
# Block renderers
# ─────────────────────────────────────────────────────────────────────────────

def _render_heading(block: ChapterBlock) -> str:
    level = min(max(int(block.level or 2), 1), 4)
    anchor = block.block_id or f"h-{uuid.uuid4().hex[:8]}"
    text = _render_inline(str(block.content))
    cls_map = {
        1: "report-h1",
        2: "report-h2",
        3: "report-h3",
        4: "report-h4",
    }
    return f'<h{level} id="{anchor}" class="{cls_map[level]}">{text}</h{level}>\n'


def _render_paragraph(block: ChapterBlock) -> str:
    # 支持 raw HTML 直通（用于 KPI Dashboard 等注入内容）
    if block.metadata.get("raw_html"):
        return f'<div class="report-raw-block">{str(block.content)}</div>\n'
    text = _render_inline(str(block.content))
    return f'<p class="report-paragraph">{text}</p>\n'


def _render_list(block: ChapterBlock) -> str:
    items = block.content
    ordered = block.metadata.get("ordered", False)
    tag = "ol" if ordered else "ul"
    lines = [f'<{tag} class="report-list">\n']
    for item in items:
        if isinstance(item, dict):
            txt = _render_inline(str(item.get("text", item)))
            sub = item.get("sub_items", [])
            if sub:
                sub_html = "".join(
                    f'<li class="report-list-item">{_render_inline(str(s))}</li>\n' for s in sub
                )
                lines.append(f'<li class="report-list-item">{txt}<ul class="report-list nested">\n{sub_html}</ul></li>\n')
            else:
                lines.append(f'<li class="report-list-item">{txt}</li>\n')
        else:
            lines.append(f'<li class="report-list-item">{_render_inline(str(item))}</li>\n')
    lines.append(f'</{tag}>\n')
    return "".join(lines)


def _render_quote(block: ChapterBlock) -> str:
    source = block.metadata.get("source", "")
    source_html = f'<cite class="quote-source">— {html.escape(source)}</cite>' if source else ""
    text = _render_inline(str(block.content))
    return f'<blockquote class="report-quote"><p>{text}</p>{source_html}</blockquote>\n'


def _render_callout(block: ChapterBlock) -> str:
    variant = block.metadata.get("variant", "info")  # info/warning/success/error
    title = block.metadata.get("title", "")
    icon_map = {"info": "ℹ️", "warning": "⚠️", "success": "✅", "error": "❌"}
    icon = icon_map.get(variant, "ℹ️")
    title_html = f'<div class="callout-title">{icon} {html.escape(title)}</div>' if title else f'<div class="callout-title">{icon}</div>'
    text = _render_inline(str(block.content))
    return f'<div class="report-callout callout-{variant}">{title_html}<div class="callout-body">{text}</div></div>\n'


def _render_code(block: ChapterBlock) -> str:
    lang = block.metadata.get("language", "")
    caption = block.metadata.get("caption", "")
    escaped = html.escape(str(block.content))
    cap_html = f'<div class="code-caption">{html.escape(caption)}</div>' if caption else ""
    return (
        f'<div class="report-code-block">'
        f'{cap_html}'
        f'<pre><code class="language-{lang}">{escaped}</code></pre>'
        f'</div>\n'
    )


def _render_divider(_block: ChapterBlock) -> str:
    return '<hr class="report-divider" />\n'


def _render_image(block: ChapterBlock) -> str:
    src = str(block.content)
    caption = block.metadata.get("caption", "")
    alt = block.metadata.get("alt", caption or "figure")
    css_class = block.metadata.get("css_class", "")
    source = block.metadata.get("source", "")

    # 文献图表使用特殊布局
    if css_class == "literature-figure":
        source_html = (
            f'<div class="lit-fig-source">Source: {html.escape(source)}</div>'
            if source else ""
        )
        cap_html = (
            f'<div class="lit-fig-caption">{html.escape(caption)}{source_html}</div>'
            if caption else ""
        )
        return (
            f'<div class="literature-figure">'
            f'<img src="{html.escape(src, quote=True)}" alt="{html.escape(alt, quote=True)}" />'
            f'{cap_html}'
            f'</div>\n'
        )

    cap_html = f'<figcaption class="figure-caption">{html.escape(caption)}</figcaption>' if caption else ""
    return (
        f'<figure class="report-figure">'
        f'<img src="{html.escape(src, quote=True)}" alt="{html.escape(alt, quote=True)}" class="report-image" />'
        f'{cap_html}'
        f'</figure>\n'
    )


def _render_formula(block: ChapterBlock) -> str:
    latex = str(block.content)
    display = block.metadata.get("display", True)
    if display:
        return f'<div class="report-formula display-formula">\\[{latex}\\]</div>\n'
    else:
        return f'<span class="report-formula inline-formula">\\({latex}\\)</span>'


def _render_table(block: ChapterBlock) -> str:
    data = block.content
    if not isinstance(data, dict):
        return f'<p class="report-paragraph">{html.escape(str(data))}</p>\n'
    headers: List[str] = data.get("headers", [])
    rows: List[List[str]] = data.get("rows", [])
    caption: str = data.get("caption", "")
    col_widths: List[str] = data.get("col_widths", [])

    cap_html = f'<caption class="table-caption">{html.escape(caption)}</caption>' if caption else ""
    
    # Column group
    colgroup = ""
    if col_widths:
        cols = "".join(f'<col style="width:{w}" />' for w in col_widths)
        colgroup = f'<colgroup>{cols}</colgroup>'

    # Header
    header_html = ""
    if headers:
        ths = "".join(f'<th class="table-th">{_render_inline(str(h))}</th>' for h in headers)
        header_html = f'<thead><tr>{ths}</tr></thead>'

    # Body
    body_rows = []
    for row in rows:
        tds = "".join(f'<td class="table-td">{_render_inline(str(cell))}</td>' for cell in row)
        body_rows.append(f'<tr>{tds}</tr>')
    body_html = f'<tbody>{"".join(body_rows)}</tbody>'

    return (
        f'<div class="table-responsive">'
        f'<table class="report-table">{cap_html}{colgroup}{header_html}{body_html}</table>'
        f'</div>\n'
    )


def _render_chart(block: ChapterBlock, chart_index: int) -> str:
    """渲染 Chart.js 图表（内联 <canvas> + 初始化脚本）"""
    data = block.content
    if not isinstance(data, dict):
        logger.warning(f"Chart block content is not a dict: {type(data)}")
        return f'<p class="report-paragraph chart-error">[Chart data error]</p>\n'

    chart_id = f"chart-{chart_index}-{uuid.uuid4().hex[:6]}"
    chart_type = data.get("type", "bar")
    title = html.escape(data.get("title", ""))
    caption = html.escape(data.get("caption", ""))

    # Build Chart.js config
    chart_config = {
        "type": chart_type,
        "data": {
            "labels": data.get("labels", []),
            "datasets": data.get("datasets", []),
        },
        "options": {
            "responsive": True,
            "maintainAspectRatio": True,
            "plugins": {
                "title": {
                    "display": bool(title),
                    "text": data.get("title", ""),
                    "font": {"size": 14, "weight": "bold"},
                },
                "legend": {"position": "bottom"},
            },
            **data.get("options", {}),
        },
    }
    config_json = json.dumps(chart_config, ensure_ascii=False)

    title_html = f'<div class="chart-title">{title}</div>' if title else ""
    cap_html = f'<figcaption class="chart-caption">{caption}</figcaption>' if caption else ""

    return (
        f'<figure class="report-chart-figure">'
        f'{title_html}'
        f'<div class="chart-container">'
        f'<canvas id="{chart_id}" aria-label="{title or "chart"}" role="img"></canvas>'
        f'</div>'
        f'{cap_html}'
        f'<script>window.__cassandraCharts = window.__cassandraCharts || [];\n'
        f'window.__cassandraCharts.push({{"id": "{chart_id}", "config": {config_json}}});</script>'
        f'</figure>\n'
    )


def _render_wordcloud(block: ChapterBlock, wc_index: int) -> str:
    """渲染词云图（WordCloud2.js）"""
    data = block.content
    title = html.escape(block.metadata.get("title", ""))
    
    # Normalize to list of [word, weight]
    if isinstance(data, dict):
        word_list = [[k, float(v)] for k, v in data.items()]
    elif isinstance(data, list):
        word_list = []
        for item in data:
            if isinstance(item, dict):
                word_list.append([str(item.get("word", "")), float(item.get("weight", 1.0))])
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                word_list.append([str(item[0]), float(item[1])])
    else:
        word_list = []

    wc_id = f"wordcloud-{wc_index}-{uuid.uuid4().hex[:6]}"
    word_list_json = json.dumps(word_list, ensure_ascii=False)
    title_html = f'<div class="chart-title">{title}</div>' if title else ""

    return (
        f'<figure class="report-wordcloud-figure">'
        f'{title_html}'
        f'<div class="wordcloud-container"><canvas id="{wc_id}" width="600" height="300"></canvas></div>'
        f'<script>window.__cassandraWordclouds = window.__cassandraWordclouds || [];\n'
        f'window.__cassandraWordclouds.push({{id: "{wc_id}", words: {word_list_json}}});</script>'
        f'</figure>\n'
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main HTMLRenderer
# ─────────────────────────────────────────────────────────────────────────────

class HTMLRenderer:
    """
    从 IRDocument 生成完整 HTML 报告。

    用法::

        renderer = HTMLRenderer()
        html_str = renderer.render(ir_document)
        # 或直接从 Markdown 快速转换
        html_str = renderer.render_from_markdown(markdown_text, title="Report")
    """

    # ── CSS ──────────────────────────────────────────────────────────────────
    REPORT_CSS = """\
/* ===== Cassandra Report Styles v2 ===== */
:root {
    --primary: #0f4c81;
    --accent:  #1a73e8;
    --text:    #1a1a2e;
    --text-light: #4a5568;
    --bg:      #ffffff;
    --bg-alt:  #f8f9fa;
    --border:  #dee2e6;
    --success: #28a745;
    --warning: #ffc107;
    --danger:  #dc3545;
    --info:    #17a2b8;
    --shadow:  0 2px 8px rgba(0,0,0,0.08);
    --font-body: 'Segoe UI', 'Noto Sans SC', sans-serif;
    --font-mono: 'Fira Code', 'Consolas', monospace;
    --font-serif: 'Georgia', 'Noto Serif SC', serif;
}

*, *::before, *::after { box-sizing: border-box; }

body {
    font-family: var(--font-body);
    font-size: 15px;
    line-height: 1.8;
    color: var(--text);
    background: var(--bg);
    margin: 0;
    padding: 0;
}

/* ── Report Container ── */
.report-container {
    max-width: 900px;
    margin: 0 auto;
    padding: 40px 48px;
}

/* ── Cover ── */
.report-cover {
    text-align: center;
    padding: 80px 20px 50px;
    border-bottom: 4px double var(--primary);
    margin-bottom: 50px;
    position: relative;
}
.report-cover-title {
    font-size: 2.4rem;
    font-weight: 700;
    color: var(--primary);
    margin: 0 0 16px;
    line-height: 1.3;
    letter-spacing: -0.02em;
}
.report-cover-subtitle {
    font-size: 1.15rem;
    color: var(--text-light);
    margin: 0 0 28px;
    font-family: var(--font-serif);
}
.report-cover-meta {
    font-size: 0.85rem;
    color: var(--text-light);
    display: flex;
    justify-content: center;
    gap: 16px;
    flex-wrap: wrap;
}
.meta-badge {
    background: var(--bg-alt);
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 5px 16px;
    font-size: 0.82rem;
}

/* ── TOC ── */
.toc-container {
    background: linear-gradient(135deg, #f8f9fa 0%, #fff 100%);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 28px 36px;
    margin-bottom: 48px;
    box-shadow: 0 1px 6px rgba(0,0,0,0.04);
}
.toc-title {
    font-size: 0.9rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .12em;
    color: var(--primary);
    margin: 0 0 18px;
    padding-bottom: 10px;
    border-bottom: 2px solid var(--accent);
}
.toc-list { list-style: none; padding: 0; margin: 0; }
.toc-item { margin: 8px 0; }
.toc-item a {
    color: var(--text);
    text-decoration: none;
    font-size: 0.9rem;
    display: flex;
    align-items: baseline;
    gap: 8px;
    transition: color 0.15s;
}
.toc-item a:hover { color: var(--accent); }
.toc-item-h2 { padding-left: 0; font-weight: 600; }
.toc-item-h3 { padding-left: 24px; font-size: 0.85rem; color: var(--text-light); }

/* ── Chapter ── */
.report-chapter { margin-bottom: 56px; }
.chapter-number {
    font-size: 0.75rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .15em;
    color: var(--accent);
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    gap: 8px;
}
.chapter-number::after {
    content: "";
    flex: 1;
    height: 1px;
    background: var(--border);
}

/* ── Headings ── */
.report-h1 {
    font-size: 2rem; font-weight: 700;
    color: var(--primary);
    margin: 0 0 12px;
    padding-bottom: 10px;
    border-bottom: 2px solid var(--primary);
}
.report-h2 {
    font-size: 1.45rem; font-weight: 700;
    color: var(--primary);
    margin: 32px 0 12px;
    padding-bottom: 6px;
    border-bottom: 1px solid var(--border);
}
.report-h3 {
    font-size: 1.15rem; font-weight: 600;
    color: var(--text);
    margin: 24px 0 8px;
}
.report-h4 {
    font-size: 1rem; font-weight: 600;
    color: var(--text-light);
    margin: 18px 0 6px;
}

/* ── Paragraph ── */
.report-paragraph {
    margin: 0 0 16px;
    text-align: justify;
    hyphens: auto;
}

/* ── List ── */
.report-list {
    margin: 0 0 16px;
    padding-left: 24px;
}
.report-list.nested { margin-bottom: 0; }
.report-list-item { margin-bottom: 6px; }

/* ── Quote ── */
.report-quote {
    border-left: 4px solid var(--accent);
    margin: 20px 0;
    padding: 12px 20px;
    background: var(--bg-alt);
    border-radius: 0 6px 6px 0;
    font-style: italic;
    color: var(--text-light);
}
.report-quote p { margin: 0; }
.quote-source {
    display: block;
    font-size: 0.85rem;
    margin-top: 8px;
    color: var(--text-light);
    font-style: normal;
}

/* ── Callout ── */
.report-callout {
    border-radius: 8px;
    padding: 16px 20px;
    margin: 20px 0;
    border-left: 4px solid;
}
.callout-info    { background: #e8f4fd; border-color: var(--info);    }
.callout-warning { background: #fff8e1; border-color: var(--warning);  }
.callout-success { background: #e8f5e9; border-color: var(--success);  }
.callout-error   { background: #fdecea; border-color: var(--danger);   }
.callout-title { font-weight: 700; margin-bottom: 8px; font-size: 0.95rem; }
.callout-body  { font-size: 0.9rem; }

/* ── Code ── */
.report-code-block {
    margin: 20px 0;
    border-radius: 8px;
    overflow: hidden;
    box-shadow: var(--shadow);
}
.code-caption {
    background: #2d3748;
    color: #a0aec0;
    font-size: 0.8rem;
    padding: 6px 16px;
    font-family: var(--font-mono);
}
.report-code-block pre {
    background: #1a202c;
    color: #e2e8f0;
    margin: 0;
    padding: 20px;
    overflow-x: auto;
    font-family: var(--font-mono);
    font-size: 0.85rem;
    line-height: 1.6;
}
.inline-code {
    background: #f1f5f9;
    color: #c0392b;
    padding: 1px 6px;
    border-radius: 4px;
    font-family: var(--font-mono);
    font-size: 0.88em;
}

/* ── Divider ── */
.report-divider {
    border: none;
    border-top: 1px solid var(--border);
    margin: 32px 0;
}

/* ── Image ── */
.report-figure {
    margin: 24px 0;
    text-align: center;
}
.report-image {
    max-width: 100%;
    height: auto;
    border-radius: 8px;
    box-shadow: var(--shadow);
}
.figure-caption {
    font-size: 0.85rem;
    color: var(--text-light);
    margin-top: 8px;
    font-style: italic;
}

/* ── Formula ── */
.report-formula { margin: 16px 0; overflow-x: auto; }
.display-formula { display: block; text-align: center; }

/* ── Table ── */
.table-responsive { overflow-x: auto; margin: 28px 0; }
.report-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.88rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
}
.table-caption {
    caption-side: top;
    text-align: left;
    font-weight: 600;
    color: var(--text-light);
    font-size: 0.85rem;
    margin-bottom: 10px;
    padding-bottom: 6px;
}
.table-th {
    background: linear-gradient(135deg, var(--primary), #1a5a9e);
    color: #fff;
    padding: 11px 16px;
    text-align: left;
    font-weight: 600;
    font-size: 0.85rem;
    border-bottom: 2px solid #0b3660;
}
.table-td {
    padding: 10px 16px;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
    line-height: 1.5;
}
.report-table tbody tr:nth-child(even) td { background: var(--bg-alt); }
.report-table tbody tr:hover td { background: #e8f4fd; transition: background 0.15s; }

/* ── Chart ── */
.report-chart-figure {
    margin: 32px auto;
    text-align: center;
    page-break-inside: avoid;
}
.chart-title {
    font-size: 0.95rem;
    font-weight: 700;
    color: var(--primary);
    margin-bottom: 14px;
}
.chart-container {
    position: relative;
    max-width: 720px;
    margin: 0 auto;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 20px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.05);
}
.chart-caption {
    font-size: 0.82rem;
    color: var(--text-light);
    margin-top: 10px;
    font-style: italic;
}
.chart-error { color: var(--danger); font-style: italic; }

/* ── WordCloud ── */
.report-wordcloud-figure {
    margin: 28px 0;
    text-align: center;
}
.wordcloud-container {
    display: inline-block;
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
    box-shadow: var(--shadow);
}

/* ── Print Styles (CSS Paged Media) ── */
@media print {
    body { font-size: 11pt; }
    .report-container { max-width: 100%; padding: 0; }
    .report-h1, .report-h2, .report-h3 { page-break-after: avoid; }
    .report-table, .report-chart-figure, .report-figure { page-break-inside: avoid; }
    .report-cover { page-break-after: always; }
    a { color: var(--text) !important; text-decoration: none; }
    /* Orphans & Widows */
    p { orphans: 3; widows: 3; }
    /* 打印时隐藏CDN脚本加载指示器 */
    .chart-container canvas { display: none; }
    .pdf-chart img { display: block !important; }
}

@page {
    size: A4;
    margin: 2.5cm 2cm;
    @bottom-center {
        content: "— " counter(page) " / " counter(pages) " —";
        font-size: 10pt;
        color: #888;
    }
}

/* ── Literature Figure Embed ── */
.literature-figure {
    border: 2px solid #e0e0e0;
    border-radius: 8px;
    overflow: hidden;
    margin: 28px auto;
    max-width: 85%;
    page-break-inside: avoid;
    background: #fff;
    box-shadow: 0 1px 6px rgba(0,0,0,0.06);
}
.literature-figure img {
    width: 100%;
    height: auto;
    display: block;
}
.literature-figure .lit-fig-caption {
    padding: 10px 16px;
    background: #f8f9fa;
    font-size: 0.82rem;
    color: #555;
    border-top: 1px solid #e8e8e8;
}
.literature-figure .lit-fig-source {
    font-size: 0.75rem;
    color: #999;
    margin-top: 4px;
}

/* ── KPI Dashboard Cards ── */
.kpi-grid {
    display: flex;
    gap: 16px;
    margin: 24px 0;
    flex-wrap: wrap;
}
.kpi-card {
    flex: 1;
    min-width: 130px;
    background: linear-gradient(135deg, #f8f9fa, #fff);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 18px 14px;
    text-align: center;
    box-shadow: 0 1px 4px rgba(0,0,0,0.04);
}
.kpi-value {
    font-size: 1.8rem;
    font-weight: 700;
    color: var(--primary);
    line-height: 1.2;
}
.kpi-label {
    font-size: 0.78rem;
    color: #6b7280;
    margin-top: 6px;
}
.kpi-card.kpi-danger .kpi-value { color: var(--danger); }
.kpi-card.kpi-warning .kpi-value { color: var(--warning); }
.kpi-card.kpi-success .kpi-value { color: var(--success); }
"""

    # ── CDN scripts injected in <head> ──────────────────────────────────────
    CDN_SCRIPTS = """\
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/wordcloud@1.2.2/src/wordcloud2.js"></script>
<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js" id="MathJax-script" async></script>
<script>
MathJax = {
    tex: { inlineMath: [['\\\\(','\\\\)'], ['$','$']] },
    options: { skipHtmlTags: ['script','noscript','style','textarea'] }
};
</script>"""

    # ── Chart init script injected at end of <body> ──────────────────────────
    CHART_INIT_SCRIPT = """\
<script>
(function() {
    'use strict';
    function initCharts() {
        var charts = window.__cassandraCharts || [];
        charts.forEach(function(c) {
            var el = document.getElementById(c.id);
            if (!el) return;
            try { new Chart(el, c.config); }
            catch(e) { console.warn('Chart init failed:', c.id, e); }
        });
    }
    function initWordclouds() {
        var wcs = window.__cassandraWordclouds || [];
        wcs.forEach(function(wc) {
            var el = document.getElementById(wc.id);
            if (!el) return;
            try {
                WordCloud(el, {
                    list: wc.words,
                    gridSize: 8,
                    weightFactor: function(s) { return Math.max(s * 24, 12); },
                    fontFamily: 'Segoe UI, sans-serif',
                    color: function() {
                        var palette = ['#0f4c81','#1a73e8','#28a745','#e83e1a','#9b59b6','#f39c12'];
                        return palette[Math.floor(Math.random() * palette.length)];
                    },
                    rotateRatio: 0.3,
                    backgroundColor: '#ffffff',
                });
            } catch(e) { console.warn('WordCloud init failed:', wc.id, e); }
        });
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() { initCharts(); initWordclouds(); });
    } else {
        initCharts(); initWordclouds();
    }
})();
</script>"""

    # ─────────────────────────────────────────────────────────────────────────
    def render(self, doc: IRDocument, standalone: bool = True) -> str:
        """
        将 IRDocument 渲染为 HTML 字符串。

        Args:
            doc:        IRDocument 实例
            standalone: True = 完整 HTML 文档（含 <html><head>）；
                        False = 仅返回 <body> 内容片段
        Returns:
            str: HTML 字符串
        """
        body_parts: List[str] = []

        # Cover
        body_parts.append(self._render_cover(doc))

        # TOC
        toc_html = self._render_toc(doc)
        if toc_html:
            body_parts.append(toc_html)

        # Chapters
        chart_index = 0
        wc_index = 0
        for chapter in sorted(doc.chapters, key=lambda c: c.order):
            chapter_html, chart_index, wc_index = self._render_chapter(
                chapter, chart_index, wc_index
            )
            body_parts.append(chapter_html)

        content = (
            f'<div class="report-container">\n'
            + "\n".join(body_parts)
            + "\n</div>\n"
        )

        if not standalone:
            return content

        return self._wrap_html(doc, content)

    # ─────────────────────────────────────────────────────────────────────────
    def render_from_markdown(
        self,
        markdown_text: str,
        title: str = "Report",
        subtitle: str = "",
        query: str = "",
        standalone: bool = True,
    ) -> str:
        """
        直接从 Markdown 文本生成 HTML，无需预构建 IRDocument。
        适用于快速回退渲染。
        """
        try:
            import markdown as md_lib
            extensions = ["tables", "fenced_code", "codehilite", "toc", "nl2br"]
            html_body = md_lib.markdown(markdown_text, extensions=extensions)
        except ImportError:
            html_body = f"<pre>{html.escape(markdown_text)}</pre>"

        content = f'<div class="report-container"><div class="prose">{html_body}</div></div>'

        if not standalone:
            return content

        # Build minimal IRDocument for cover
        from src.report_engine.ir.schema import IRDocument as _IR
        from datetime import datetime
        doc = _IR(
            title=title,
            subtitle=subtitle or None,
            query=query,
            metadata={"generated_at": datetime.now().isoformat()},
        )
        return self._wrap_html(doc, f'<div class="report-container">{html_body}</div>')

    # ─────────────────────────────────────────────────────────────────────────
    def _render_cover(self, doc: IRDocument) -> str:
        from datetime import datetime
        title = html.escape(doc.title or "Cassandra Report")
        subtitle = html.escape(doc.subtitle or "") if doc.subtitle else ""
        query = html.escape(doc.query or "")
        gen_at = doc.metadata.get("generated_at", datetime.now().isoformat())[:10]
        analysis_focus = doc.metadata.get("analysis_focus", "")
        focus_badge = (
            f'<span class="meta-badge">Focus: {html.escape(str(analysis_focus))}</span>'
            if analysis_focus else ""
        )
        sub_html = f'<p class="report-cover-subtitle">{subtitle}</p>' if subtitle else ""
        q_html = (
            f'<span class="meta-badge">Query: {query[:80]}{"…" if len(query)>80 else ""}</span>'
            if query else ""
        )
        return f"""<div class="report-cover">
  <h1 class="report-cover-title">{title}</h1>
  {sub_html}
  <div class="report-cover-meta">
    <span class="meta-badge">Generated: {gen_at}</span>
        {focus_badge}
    {q_html}
  </div>
</div>\n"""

    def _render_toc(self, doc: IRDocument) -> str:
        chapters = sorted(doc.chapters, key=lambda c: c.order)
        if not chapters:
            return ""
        items: List[str] = []
        for i, ch in enumerate(chapters, 1):
            anchor = ch.id or f"ch-{i}"
            items.append(
                f'<li class="toc-item toc-item-h2">'
                f'<a href="#{anchor}">{i}. {html.escape(ch.title)}</a>'
                f'</li>'
            )
            for block in ch.blocks:
                if block.type == BlockType.HEADING and block.level in (2, 3):
                    sub_anchor = block.block_id or ""
                    if sub_anchor:
                        items.append(
                            f'<li class="toc-item toc-item-h3">'
                            f'<a href="#{sub_anchor}">{html.escape(str(block.content))}</a>'
                            f'</li>'
                        )
        return (
            f'<nav class="toc-container" aria-label="Table of Contents">'
            f'<div class="toc-title">Table of Contents</div>'
            f'<ul class="toc-list">{"".join(items)}</ul>'
            f'</nav>\n'
        )

    def _render_chapter(
        self, chapter: Chapter, chart_index: int, wc_index: int
    ):
        anchor = chapter.id or f"ch-{chapter.order}"
        blocks_html: List[str] = []

        for block in chapter.blocks:
            try:
                bhtml = self._render_block(block, chart_index, wc_index)
                if block.type == BlockType.CHART:
                    chart_index += 1
                elif block.type == BlockType.WORDCLOUD:
                    wc_index += 1
                blocks_html.append(bhtml)
            except Exception as e:
                logger.error(f"Block render error ({block.type}): {e}")
                blocks_html.append(
                    f'<div class="report-callout callout-error">'
                    f'<div class="callout-title">❌ Render Error</div>'
                    f'<div class="callout-body">{html.escape(str(e))}</div>'
                    f'</div>\n'
                )

        chapter_title = html.escape(chapter.title)
        chapter_num = f'<div class="chapter-number">Chapter {chapter.order}</div>'
        chapter_h = f'<h2 id="{anchor}" class="report-h1">{chapter_title}</h2>'

        return (
            f'<section class="report-chapter" id="{anchor}">'
            f'{chapter_num}'
            f'{chapter_h}'
            f'{"".join(blocks_html)}'
            f'</section>\n',
            chart_index,
            wc_index,
        )

    def _render_block(self, block: ChapterBlock, chart_index: int, wc_index: int) -> str:
        t = block.type
        if t == BlockType.HEADING:
            return _render_heading(block)
        elif t == BlockType.PARAGRAPH:
            return _render_paragraph(block)
        elif t == BlockType.LIST:
            return _render_list(block)
        elif t == BlockType.QUOTE:
            return _render_quote(block)
        elif t == BlockType.CALLOUT:
            return _render_callout(block)
        elif t == BlockType.CODE:
            return _render_code(block)
        elif t == BlockType.DIVIDER:
            return _render_divider(block)
        elif t == BlockType.IMAGE:
            return _render_image(block)
        elif t == BlockType.FORMULA:
            return _render_formula(block)
        elif t == BlockType.TABLE:
            return _render_table(block)
        elif t == BlockType.CHART:
            return _render_chart(block, chart_index)
        elif t == BlockType.WORDCLOUD:
            return _render_wordcloud(block, wc_index)
        else:
            logger.warning(f"Unknown block type: {t}")
            return _render_paragraph(block)

    def _wrap_html(self, doc: IRDocument, content: str) -> str:
        title = html.escape(doc.title or "Cassandra Report")
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="description" content="Cassandra Biomedical Due Diligence Report" />
  <title>{title}</title>
  {self.CDN_SCRIPTS}
  <style>{self.REPORT_CSS}</style>
</head>
<body>
{content}
{self.CHART_INIT_SCRIPT}
</body>
</html>"""
