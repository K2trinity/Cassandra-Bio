"""
PDF Renderer v3.0

从 IRDocument 生成专业级 PDF 报告。

渲染策略（多层降级）：
1. WeasyPrint   — 首选：CSS Paged Media 标准，纯 Python，支持中文字体
2. pdfkit       — 次选：wkhtmltopdf 引擎，兼容性更广
3. 纯文本备用    — 降级：reportlab 生成基础 PDF，确保不失败

特性:
- ✅ CSS Paged Media 页眉/页脚/页码
- ✅ 孤行/寡行处理 (orphans/widows)
- ✅ 避免标题后跨页断开
- ✅ 表格/图表 page-break-inside: avoid
- ✅ 内嵌字体子集（Noto Sans SC 用于中文，via Google Fonts）
- ✅ 自动布局优化
- ✅ Chart.js → matplotlib SVG 预渲染（PDF 无需 JavaScript）
- ✅ 图表自动编号与交叉引用
"""

import io
import os
import json
import base64
import tempfile
import re
from pathlib import Path
from typing import Optional, Union
from loguru import logger

from .html_renderer import HTMLRenderer
from src.report_engine.ir.schema import IRDocument


# ─────────────────────────────────────────────────────────────────────────────
# Layout Optimizer（HTML 后处理）
# ─────────────────────────────────────────────────────────────────────────────

class LayoutOptimizer:
    """
    对生成的 HTML 进行后处理以优化 PDF 分页布局。
    - 注入 page-break-before 到每章
    - 环境孤行/寡行 CSS
    - 防止表格/图表被分页截断
    """

    _CHAPTER_RE = re.compile(r'<section class="report-chapter"', re.IGNORECASE)

    def optimize(self, html: str) -> str:
        # 每章强制新页（第一章除外）
        first = [True]

        def _inject_pb(m):
            if first[0]:
                first[0] = False
                return m.group(0)
            return '<section class="report-chapter" style="page-break-before: always;"'

        html = self._CHAPTER_RE.sub(_inject_pb, html)

        # 注入额外打印 CSS
        extra_css = """
<style>
@media print {
    .report-chapter { page-break-before: always; }
    .report-h1, .report-h2, .report-h3, .report-h4 {
        page-break-after: avoid !important;
    }
    .report-table, .report-figure, .report-chart-figure,
    .report-wordcloud-figure, .report-callout, .report-code-block {
        page-break-inside: avoid !important;
    }
    /* Orphans & Widows */
    .report-paragraph { orphans: 3; widows: 3; }
    /* Cover page */
    .report-cover { page-break-after: always !important; }
    /* TOC page */
    .toc-container { page-break-after: always !important; }
}
</style>"""
        html = html.replace("</head>", extra_css + "\n</head>", 1)
        return html


# ─────────────────────────────────────────────────────────────────────────────
# Chart Preprocessor（将 Canvas 图表替换为 SVG/PNG 内嵌图片）
# ─────────────────────────────────────────────────────────────────────────────

class ChartPreprocessor:
    """
    将 HTML 中的 Chart.js <canvas> 元素预渲染为 <img> 内嵌 SVG/PNG。

    PDF 引擎（WeasyPrint / pdfkit / PyMuPDF）都不执行 JavaScript，
    因此 Chart.js <canvas> 无法直接渲染。本类使用 matplotlib 后端
    将图表数据转换为矢量 SVG 并以 data-URI 内嵌，保证 PDF 输出完整。
    """

    # 匹配 window.__cassandraCharts.push({id: "...", config: {...}});
    _CHART_PUSH_RE = re.compile(
        r'window\.__cassandraCharts\.push\((\{.*?\})\);',
        re.DOTALL,
    )

    def __init__(self):
        self._converter = None

    def _get_converter(self):
        """延迟加载 ChartToSVGConverter（绕过 report_core __init__ 的坏依赖）"""
        if self._converter is None:
            try:
                import importlib.util
                _svg_path = Path(__file__).resolve().parent.parent.parent / "report_core" / "renderers" / "chart_to_svg.py"
                spec = importlib.util.spec_from_file_location("chart_to_svg", _svg_path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                self._converter = mod.ChartToSVGConverter()
                logger.debug("ChartToSVGConverter loaded for PDF chart pre-rendering")
            except Exception as e:
                logger.warning(f"ChartToSVGConverter unavailable: {e}")
        return self._converter

    def preprocess(self, html: str) -> str:
        """
        扫描 HTML 中的 Chart.js push 脚本，提取 config，
        用 matplotlib 渲染为 SVG，替换对应 <canvas> + <script> 为 <img>。
        """
        converter = self._get_converter()
        if converter is None:
            logger.info("Matplotlib not available — charts will not appear in PDF")
            return html

        chart_count = 0

        for match in self._CHART_PUSH_RE.finditer(html):
            try:
                raw_json = match.group(1)
                # JS 对象字面量的键可能无引号，补上双引号再解析
                fixed_json = re.sub(r'(?<=[{,])\s*(\w+)\s*:', r' "\1":', raw_json)
                chart_meta = json.loads(fixed_json)
                chart_id = chart_meta.get("id", "")
                config = chart_meta.get("config", {})

                chart_type = config.get("type", "bar")
                chart_data = config.get("data", {})
                chart_options = config.get("options", {})
                title = (
                    chart_options.get("plugins", {}).get("title", {}).get("text", "")
                    or ""
                )

                # 转为 chart_to_svg 期望的 widget_data 格式
                widget_data = {
                    "widgetType": f"chart.js/{chart_type}",
                    "data": chart_data,
                    "props": {
                        "type": chart_type,
                        "options": chart_options,
                    },
                }

                svg_str = converter.convert_widget_to_svg(widget_data, width=720, height=420, dpi=120)

                if svg_str:
                    # 编码为 data URI
                    svg_b64 = base64.b64encode(svg_str.encode("utf-8")).decode("ascii")
                    data_uri = f"data:image/svg+xml;base64,{svg_b64}"

                    chart_count += 1
                    fig_label = f"Figure {chart_count}"
                    caption_text = title or fig_label

                    img_html = (
                        f'<figure class="report-chart-figure pdf-chart">'
                        f'<img src="{data_uri}" alt="{caption_text}" '
                        f'style="max-width:100%;height:auto;display:block;margin:0 auto;" />'
                        f'<figcaption class="chart-caption">{fig_label}. {caption_text}</figcaption>'
                        f'</figure>'
                    )

                    # 替换整个 <figure> 块
                    canvas_pattern = re.compile(
                        rf'<figure class="report-chart-figure">.*?'
                        rf'<canvas id="{re.escape(chart_id)}".*?</figure>',
                        re.DOTALL,
                    )
                    html = canvas_pattern.sub(img_html, html)
                    logger.debug(f"✅ Chart '{chart_id}' → SVG for PDF ({fig_label})")

            except Exception as e:
                logger.warning(f"Chart pre-render failed for a chart: {e}")

        if chart_count:
            logger.info(f"📊 Pre-rendered {chart_count} chart(s) to SVG for PDF")

        # 清理残留的 Chart.js init 脚本（PDF 中不需要）
        html = re.sub(
            r'<script>\s*\(function\(\)\s*\{.*?initCharts.*?</script>',
            '', html, flags=re.DOTALL,
        )

        return html


# ─────────────────────────────────────────────────────────────────────────────
# PDF Renderer
# ─────────────────────────────────────────────────────────────────────────────

class PDFRenderer:
    """
    将 IRDocument 渲染为 PDF bytes。

    用法::

        renderer = PDFRenderer()
        pdf_bytes = renderer.render_to_bytes(ir_document)

        # 或直接从 Markdown 文本
        pdf_bytes = renderer.render_markdown_to_bytes(markdown_text, title="Report")
    """

    # Google Fonts CSS for CJK support (loaded from CDN in WeasyPrint)
    _FONT_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;700&family=Noto+Serif+SC:wght@400;700&display=swap');
body { font-family: 'Noto Sans SC', 'Segoe UI', sans-serif; }
"""

    def __init__(self):
        self.html_renderer = HTMLRenderer()
        self.layout_optimizer = LayoutOptimizer()
        self.chart_preprocessor = ChartPreprocessor()
        self._weasyprint_available = self._check_weasyprint()
        self._pdfkit_available = self._check_pdfkit()
        self._pymupdf_available = self._check_pymupdf()

    # ─── availability checks ─────────────────────────────────────────────────
    @staticmethod
    def _check_weasyprint() -> bool:
        try:
            import weasyprint  # noqa: F401
            return True
        except ImportError:
            logger.debug("WeasyPrint not installed, will try pdfkit fallback")
            return False
        except OSError as e:
            # Windows: GTK/GLib DLLs (libgobject-2.0-0 等) 未安装时抛 OSError
            logger.debug(f"WeasyPrint DLL load failed ({e}), will try pdfkit fallback")
            return False
        except Exception as e:
            logger.debug(f"WeasyPrint check failed ({e}), will try pdfkit fallback")
            return False

    @staticmethod
    def _check_pdfkit() -> bool:
        try:
            import pdfkit  # noqa: F401
            return True
        except ImportError:
            logger.debug("pdfkit not installed, will use reportlab fallback")
            return False

    @staticmethod
    def _check_pymupdf() -> bool:
        try:
            import fitz  # noqa: F401
            return hasattr(fitz, 'Story')
        except ImportError:
            logger.debug("PyMuPDF not installed, will use reportlab fallback")
            return False
        except Exception:
            return False

    # ─── public API ──────────────────────────────────────────────────────────

    def render_to_bytes(self, doc: IRDocument) -> bytes:
        """从 IRDocument 生成 PDF bytes。"""
        html = self.html_renderer.render(doc, standalone=True)
        html = self._inject_pdf_font_css(html)
        html = self._inject_pdf_enhanced_css(html)
        html = self.chart_preprocessor.preprocess(html)
        html = self.layout_optimizer.optimize(html)
        return self._html_to_pdf_bytes(html)

    def render_to_file(self, doc: IRDocument, output_path: Union[str, Path]) -> Path:
        """从 IRDocument 生成 PDF 文件。"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_bytes = self.render_to_bytes(doc)
        output_path.write_bytes(pdf_bytes)
        logger.success(f"✅ PDF saved: {output_path} ({len(pdf_bytes)//1024} KB)")
        return output_path

    def render_markdown_to_bytes(
        self,
        markdown_text: str,
        title: str = "Report",
        subtitle: str = "",
        query: str = "",
    ) -> bytes:
        """直接从 Markdown 文本生成 PDF bytes（快速路径）。"""
        html = self.html_renderer.render_from_markdown(
            markdown_text,
            title=title,
            subtitle=subtitle,
            query=query,
            standalone=True,
        )
        html = self._inject_pdf_font_css(html)
        html = self._inject_pdf_enhanced_css(html)
        html = self.chart_preprocessor.preprocess(html)
        html = self.layout_optimizer.optimize(html)
        return self._html_to_pdf_bytes(html)

    def render_markdown_to_file(
        self,
        markdown_text: str,
        output_path: Union[str, Path],
        title: str = "Report",
        subtitle: str = "",
        query: str = "",
    ) -> Path:
        """直接从 Markdown 文本生成 PDF 文件。"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_bytes = self.render_markdown_to_bytes(
            markdown_text, title=title, subtitle=subtitle, query=query
        )
        output_path.write_bytes(pdf_bytes)
        logger.success(f"✅ PDF saved: {output_path} ({len(pdf_bytes)//1024} KB)")
        return output_path

    # ─── private helpers ─────────────────────────────────────────────────────

    def _inject_pdf_font_css(self, html: str) -> str:
        """注入字体 CSS（CJK 支持）"""
        font_style = f"<style>{self._FONT_CSS}</style>"
        return html.replace("</head>", font_style + "\n</head>", 1)

    def _inject_pdf_enhanced_css(self, html: str) -> str:
        """注入 PDF 专属增强样式（双栏摘要、图表编号、表格美化等）"""
        enhanced_css = """
<style>
/* ===== PDF Enhanced Styles v3.0 ===== */

/* ── 封面增强 ── */
.report-cover {
    padding: 80px 40px 60px;
    border-bottom: 4px double var(--primary, #0f4c81);
    margin-bottom: 50px;
    position: relative;
}
.report-cover::after {
    content: "CASSANDRA BIOMEDICAL DUE DILIGENCE";
    display: block;
    font-size: 0.7rem;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: #999;
    margin-top: 30px;
}

/* ── 图表居中 & 编号 ── */
.report-chart-figure.pdf-chart {
    margin: 28px auto;
    text-align: center;
    page-break-inside: avoid;
    border: 1px solid #e0e0e0;
    border-radius: 8px;
    padding: 16px;
    background: #fafbfc;
}
.report-chart-figure.pdf-chart img {
    max-width: 100%;
    height: auto;
}
.report-chart-figure .chart-caption {
    font-size: 0.82rem;
    color: #555;
    margin-top: 10px;
    font-style: italic;
    text-align: center;
}

/* ── 图片编号增强 ── */
.report-figure {
    counter-increment: figure-counter;
    margin: 24px auto;
    text-align: center;
    page-break-inside: avoid;
}
.report-figure .figure-caption::before {
    content: "Fig. " counter(figure-counter) ". ";
    font-weight: 600;
    color: var(--primary, #0f4c81);
}

/* ── 表格增强 ── */
body { counter-reset: figure-counter table-counter; }
.table-responsive {
    counter-increment: table-counter;
}
.table-caption::before {
    content: "Table " counter(table-counter) ". ";
    font-weight: 700;
    color: var(--primary, #0f4c81);
}
.report-table {
    font-size: 0.85rem;
    border: 1px solid #dee2e6;
}
.report-table thead tr {
    background: linear-gradient(135deg, #0f4c81, #1a73e8);
}
.table-th {
    border-bottom: 2px solid #0b3660;
    white-space: normal;
    font-size: 0.83rem;
}
.table-td {
    font-size: 0.83rem;
    line-height: 1.5;
}

/* ── 引用块增强 ── */
.report-quote {
    position: relative;
    padding-left: 24px;
}
.report-quote::before {
    content: "\\201C";
    font-size: 3rem;
    color: var(--accent, #1a73e8);
    opacity: 0.2;
    position: absolute;
    left: -4px;
    top: -10px;
    font-family: Georgia, serif;
}

/* ── Callout 增强 ── */
.report-callout {
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
}

/* ── 段落首行缩进（中文排版习惯） ── */
.report-paragraph + .report-paragraph {
    text-indent: 2em;
}

/* ── PDF 打印页眉页脚 ── */
@page {
    size: A4;
    margin: 2.5cm 2cm 2.5cm 2cm;

    @top-left {
        content: "Cassandra Report";
        font-size: 8pt;
        color: #999;
    }
    @top-right {
        content: string(doc-title);
        font-size: 8pt;
        color: #999;
    }
    @bottom-center {
        content: "— " counter(page) " / " counter(pages) " —";
        font-size: 9pt;
        color: #888;
    }
}
@page :first {
    @top-left { content: none; }
    @top-right { content: none; }
    @bottom-center { content: none; }
}

.report-cover-title {
    string-set: doc-title content();
}

/* ── 分栏摘要（Executive Summary 双栏布局） ── */
.executive-summary-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
    margin: 16px 0;
}
.executive-summary-grid .summary-card {
    background: #f8f9fa;
    border: 1px solid #dee2e6;
    border-radius: 8px;
    padding: 16px;
}
.summary-card .card-title {
    font-weight: 700;
    font-size: 0.9rem;
    color: var(--primary, #0f4c81);
    margin-bottom: 8px;
}

/* ── KPI 指标卡片 ── */
.kpi-grid {
    display: flex;
    gap: 16px;
    margin: 20px 0;
    flex-wrap: wrap;
}
.kpi-card {
    flex: 1;
    min-width: 120px;
    background: linear-gradient(135deg, #f8f9fa, #fff);
    border: 1px solid #dee2e6;
    border-radius: 10px;
    padding: 16px;
    text-align: center;
    box-shadow: 0 1px 4px rgba(0,0,0,0.04);
}
.kpi-value {
    font-size: 1.8rem;
    font-weight: 700;
    color: var(--primary, #0f4c81);
}
.kpi-label {
    font-size: 0.78rem;
    color: #6b7280;
    margin-top: 4px;
}

/* ── 文献图片框 ── */
.literature-figure {
    border: 2px solid #e8e8e8;
    border-radius: 8px;
    overflow: hidden;
    margin: 24px auto;
    max-width: 85%;
    page-break-inside: avoid;
    background: #fff;
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
}
</style>"""
        return html.replace("</head>", enhanced_css + "\n</head>", 1)

    def _html_to_pdf_bytes(self, html: str) -> bytes:
        """HTML -> PDF bytes，多层降级策略"""
        # 策略 1: WeasyPrint
        if self._weasyprint_available:
            try:
                return self._weasyprint_render(html)
            except Exception as e:
                logger.warning(f"WeasyPrint failed ({e}), trying pdfkit...")

        # 策略 2: pdfkit（需要 wkhtmltopdf 已安装）
        if self._pdfkit_available:
            try:
                return self._pdfkit_render(html)
            except Exception as e:
                logger.warning(f"pdfkit failed ({e}), trying PyMuPDF...")

        # 策略 3: PyMuPDF Story（纯 Python，忽略 JS/Canvas，保留文字结构）
        if self._pymupdf_available:
            try:
                return self._pymupdf_render(html)
            except Exception as e:
                logger.warning(f"PyMuPDF failed ({e}), using reportlab fallback...")

        # 策略 4: reportlab 纯文本备用
        return self._reportlab_fallback(html)

    @staticmethod
    def _weasyprint_render(html: str) -> bytes:
        import weasyprint
        wp = weasyprint.HTML(string=html)
        return wp.write_pdf()

    @staticmethod
    def _pymupdf_render(html: str) -> bytes:
        """
        PyMuPDF (fitz.Story) HTML→PDF。
        不执行 JavaScript、不渲染 Canvas，但能正确保留文字结构与 Unicode，
        比 reportlab 纯文本降级输出质量高得多。
        """
        import re as _re
        import fitz

        # 移除 <script> / <style> 内联块及外部 CDN 引用，避免 JS/CSS 文字混入正文
        clean = _re.sub(r'<script[^>]*>[\s\S]*?</script>', '', html, flags=_re.IGNORECASE)
        clean = _re.sub(r'<style[^>]*>[\s\S]*?</style>', '', clean, flags=_re.IGNORECASE)
        clean = _re.sub(r'<link[^>]+>', '', clean, flags=_re.IGNORECASE)
        # 移除 Google Fonts @import（fitz 无法访问 CDN）
        clean = _re.sub(r'@import\s+url\([^)]+\);?', '', clean)

        user_css = (
            "body { font-family: serif; font-size: 11pt; line-height: 1.6; }"
            "h1,h2,h3,h4 { font-weight: bold; margin-top: 1em; }"
            "table { border-collapse: collapse; width: 100%; }"
            "th, td { border: 1px solid #ccc; padding: 4px 8px; }"
            "pre, code { font-family: monospace; font-size: 9pt; }"
        )
        story = fitz.Story(html=clean, user_css=user_css)
        buf = io.BytesIO()
        writer = fitz.DocumentWriter(buf, "pdf")
        mediabox = fitz.paper_rect("a4")
        more = 1
        while more:
            device = writer.begin_page(mediabox)
            more, _ = story.place(mediabox)
            story.draw(device)
            writer.end_page()
        writer.close()
        logger.info("✅ HTML→PDF via PyMuPDF Story")
        return buf.getvalue()

    @staticmethod
    def _pdfkit_render(html: str) -> bytes:
        import pdfkit
        options = {
            "page-size": "A4",
            "margin-top": "20mm",
            "margin-right": "20mm",
            "margin-bottom": "20mm",
            "margin-left": "20mm",
            "encoding": "UTF-8",
            "no-outline": None,
            "enable-local-file-access": None,
            "print-media-type": None,
            "footer-center": "[page]",
            "footer-font-size": "9",
            "quiet": "",
        }
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
            f.write(html)
            tmp_path = f.name
        try:
            pdf_bytes = pdfkit.from_file(tmp_path, False, options=options)
        finally:
            os.unlink(tmp_path)
        return pdf_bytes

    # ─── Unicode helpers for reportlab fallback ──────────────────────────────

    @staticmethod
    def _register_unicode_font() -> str:
        """尝试注册系统 TrueType 字体以支持 Unicode，返回字体名称。"""
        import platform
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        candidates: list[tuple[str, str]] = []
        if platform.system() == "Windows":
            win_fonts = os.environ.get("SystemRoot", r"C:\Windows") + r"\Fonts"
            candidates = [
                (os.path.join(win_fonts, "calibri.ttf"),  "Calibri"),
                (os.path.join(win_fonts, "arial.ttf"),    "Arial"),
                (os.path.join(win_fonts, "verdana.ttf"),  "Verdana"),
                (os.path.join(win_fonts, "tahoma.ttf"),   "Tahoma"),
                (os.path.join(win_fonts, "times.ttf"),    "TimesNew"),
            ]
        elif platform.system() == "Darwin":
            candidates = [
                ("/Library/Fonts/Arial.ttf",                                "Arial"),
                ("/System/Library/Fonts/Supplemental/Arial.ttf",            "Arial"),
                ("/System/Library/Fonts/Helvetica.ttc",                     "Helvetica-TTC"),
            ]
        else:  # Linux
            candidates = [
                ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",         "DejaVuSans"),
                ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "LiberationSans"),
                ("/usr/share/fonts/truetype/freefont/FreeSans.ttf",         "FreeSans"),
            ]

        for path, name in candidates:
            if os.path.isfile(path):
                try:
                    pdfmetrics.registerFont(TTFont(name, path))
                    logger.debug(f"Registered Unicode font: {name} ({path})")
                    return name
                except Exception:
                    continue

        # 内置字体兜底（仅 Latin-1，但至少不崩溃）
        return "Helvetica"

    @staticmethod
    def _sanitize_for_pdf(text: str) -> str:
        """将常见 Unicode 特殊字符替换为 ASCII 等价物，并 XML 转义 reportlab Paragraph 敏感字符。"""
        _UNICODE_MAP = {
            "\u2014": "--",    # em dash
            "\u2013": "-",     # en dash
            "\u2012": "-",     # figure dash
            "\u2018": "'",     # left single quotation mark
            "\u2019": "'",     # right single quotation mark
            "\u201a": ",",     # single low-9 quotation mark
            "\u201c": '"',     # left double quotation mark
            "\u201d": '"',     # right double quotation mark
            "\u201e": '"',     # double low-9 quotation mark
            "\u2022": "*",     # bullet
            "\u2023": "*",     # triangular bullet
            "\u2026": "...",   # horizontal ellipsis
            "\u00b0": " deg",  # degree sign
            "\u00b1": "+/-",   # plus-minus sign
            "\u00d7": "x",     # multiplication sign
            "\u00f7": "/",     # division sign
            "\u2264": "<=",    # less-than or equal to
            "\u2265": ">=",    # greater-than or equal to
            "\u2260": "!=",    # not equal to
            "\u2248": "~",     # almost equal to
            "\u03b1": "alpha", # Greek small alpha
            "\u03b2": "beta",  # Greek small beta
            "\u03b3": "gamma", # Greek small gamma
            "\u03b4": "delta", # Greek small delta
            "\u03bc": "mu",    # Greek small mu
            "\u03c3": "sigma", # Greek small sigma
            "\u03c7": "chi",   # Greek small chi
            "\u0391": "Alpha", # Greek capital Alpha
            "\u0392": "Beta",  # Greek capital Beta
            "\u00e9": "e",     # e with acute
            "\u00e8": "e",     # e with grave
            "\u00ea": "e",     # e with circumflex
            "\u00fc": "u",     # u with umlaut
            "\u00f6": "o",     # o with umlaut
            "\u00e4": "a",     # a with umlaut
            "\u00e0": "a",     # a with grave
            "\u00e2": "a",     # a with circumflex
            "\u00ae": "(R)",   # registered sign
            "\u00a9": "(C)",   # copyright sign
            "\u2122": "(TM)",  # trade mark sign
            "\u00a0": " ",     # non-breaking space
            "\u2009": " ",     # thin space
            "\u200b": "",      # zero-width space
            "\ufeff": "",      # BOM
        }
        for char, repl in _UNICODE_MAP.items():
            text = text.replace(char, repl)

        # XML-escape for reportlab Paragraph parser
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        # Final safety: strip remaining non-Latin-1 if font is Helvetica
        try:
            text.encode("latin-1")
        except UnicodeEncodeError:
            text = text.encode("latin-1", errors="replace").decode("latin-1")

        return text

    @staticmethod
    def _reportlab_fallback(html: str) -> bytes:
        """reportlab 降级备用：提取纯文本，用 Unicode TrueType 字体生成基础 PDF"""
        try:
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import mm
            from reportlab.lib.pagesizes import A4
            import re as _re

            # 注册 Unicode 字体
            font_name = PDFRenderer._register_unicode_font()

            # ── 先整块移除 <script> 和 <style> 内容（避免 JS/CSS 代码混入正文）──
            text = _re.sub(r'<script[^>]*>[\s\S]*?</script>', '', html, flags=_re.IGNORECASE)
            text = _re.sub(r'<style[^>]*>[\s\S]*?</style>', '', text, flags=_re.IGNORECASE)
            # 再去掉剩余 HTML 标签
            text = _re.sub(r'<[^>]+>', ' ', text)
            text = _re.sub(r'\s+', ' ', text).strip()

            buf = io.BytesIO()
            doc = SimpleDocTemplate(
                buf,
                pagesize=A4,
                leftMargin=25 * mm,
                rightMargin=25 * mm,
                topMargin=25 * mm,
                bottomMargin=25 * mm,
            )
            styles = getSampleStyleSheet()
            # 使用已注册的 Unicode 字体覆盖 Normal 样式
            normal_style = ParagraphStyle(
                "UnicodeNormal",
                parent=styles["Normal"],
                fontName=font_name,
                fontSize=10,
                leading=14,
            )

            story = []
            # 按双空格或段落分割
            for para in _re.split(r'\s{2,}', text):
                para = para.strip()
                if not para:
                    continue
                # 对每段做 Unicode → ASCII 映射 + XML 转义
                safe_para = PDFRenderer._sanitize_for_pdf(para[:3000])
                try:
                    story.append(Paragraph(safe_para, normal_style))
                    story.append(Spacer(1, 6))
                except Exception:
                    # 极端情况：直接用 ASCII 替换
                    ascii_para = para[:3000].encode("ascii", errors="replace").decode("ascii")
                    ascii_para = ascii_para.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    story.append(Paragraph(ascii_para, normal_style))
                    story.append(Spacer(1, 6))

            if not story:
                story.append(Paragraph("Report content unavailable.", normal_style))

            doc.build(story)
            return buf.getvalue()
        except Exception as e:
            logger.error(f"reportlab fallback also failed: {e}")
            # Absolute last resort: return a minimal PDF that says "error"
            return b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
