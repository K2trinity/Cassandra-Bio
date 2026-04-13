"""
Report Engine Renderers

提供多格式渲染能力：
- HTMLRenderer: 从 IR 生成富HTML（含 Chart.js /MathJax / WordCloud2 组件）
- PDFRenderer:  WeasyPrint 专业 PDF 生成（CSS Paged Media 标准）
- MarkdownRenderer: 回退到纯 Markdown 文本
"""

from .html_renderer import HTMLRenderer
from .pdf_renderer import PDFRenderer
from .markdown_renderer import MarkdownRenderer

__all__ = ["HTMLRenderer", "PDFRenderer", "MarkdownRenderer"]
