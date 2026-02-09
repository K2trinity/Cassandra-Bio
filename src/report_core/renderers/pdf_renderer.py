"""
Cassandra PDF Renderer - WeasyPrint-based PDF Generation
Converts HTML to professional PDF reports with full CSS styling and Unicode support.
Optimized for biomedical scientific documentation.
"""

from __future__ import annotations

import base64
import copy
import os
import sys
import io
import re
from pathlib import Path
from typing import Any, Dict
from datetime import datetime
from loguru import logger
from ReportEngine.utils.dependency_check import (
    prepare_pango_environment,
    check_pango_available,
)

# macOS: Automatically add Homebrew library paths for Pango/Cairo dependencies
# to resolve DYLD_LIBRARY_PATH issues before importing WeasyPrint
if sys.platform == 'darwin':
    mac_libs = [Path('/opt/homebrew/lib'), Path('/usr/local/lib')]
    current = os.environ.get('DYLD_LIBRARY_PATH', '')
    inserts = []
    for lib in mac_libs:
        if lib.exists() and str(lib) not in current.split(':'):
            inserts.append(str(lib))
    if inserts:
        os.environ['DYLD_LIBRARY_PATH'] = ":".join(inserts + ([current] if current else []))

# Windows: Automatically add GTK/Pango runtime paths to prevent DLL loading failures
if sys.platform.startswith('win'):
    added = prepare_pango_environment()
    if added:
        logger.debug(f"Automatically added GTK runtime path: {added}")

try:
    from weasyprint import HTML, CSS
    from weasyprint.text.fonts import FontConfiguration
    WEASYPRINT_AVAILABLE = True
    PDF_DEP_STATUS = "OK"
except (ImportError, OSError) as e:
    WEASYPRINT_AVAILABLE = False
    # Determine error type to provide helpful diagnostic messages and output missing dependency details
    try:
        _, dep_message = check_pango_available()
    except Exception:
        dep_message = None

    if isinstance(e, OSError):
        msg = dep_message or (
            "PDF export dependencies missing (system libraries not installed or environment variables not set). "
            "PDF export functionality will be unavailable. Other features are not affected."
        )
        logger.warning(msg)
        PDF_DEP_STATUS = msg
    else:
        msg = dep_message or "WeasyPrint not installed. PDF export functionality will be unavailable."
        logger.warning(msg)
        PDF_DEP_STATUS = msg
except Exception as e:
    WEASYPRINT_AVAILABLE = False
    PDF_DEP_STATUS = f"WeasyPrint failed to load: {e}. PDF export functionality will be unavailable."
    logger.warning(PDF_DEP_STATUS)

from .html_renderer import HTMLRenderer
from .pdf_layout_optimizer import PDFLayoutOptimizer, PDFLayoutConfig
from .chart_to_svg import create_chart_converter
from .math_to_svg import MathToSVG
from ReportEngine.utils.chart_review_service import get_chart_review_service
try:
    from wordcloud import WordCloud
    WORDCLOUD_AVAILABLE = True
except ImportError:
    WORDCLOUD_AVAILABLE = False
    logger = logger  # ensure logger exists even before declaration


class PDFRenderer:
    """
    WeasyPrint-based PDF Renderer for Biomedical Reports

    - Converts HTML to PDF while preserving all CSS styling
    - Full Unicode and international font support
    - Automatic pagination and layout optimization
    """

    def __init__(
        self,
        config: Dict[str, Any] | None = None,
        layout_optimizer: PDFLayoutOptimizer | None = None
    ):
        """
        Initialize PDF Renderer with configuration.

        Args:
            config: Renderer configuration dictionary
            layout_optimizer: PDF layout optimizer instance (optional)
        """
        self.config = config or {}
        self.html_renderer = HTMLRenderer(config)
        self.layout_optimizer = layout_optimizer or PDFLayoutOptimizer()

        if not WEASYPRINT_AVAILABLE:
            raise RuntimeError(
                PDF_DEP_STATUS
                if 'PDF_DEP_STATUS' in globals() else
                "WeasyPrint not installed. Run: pip install weasyprint"
            )

        # Initialize chart converter
        try:
            font_path = self._get_font_path()
            self.chart_converter = create_chart_converter(font_path=str(font_path))
            logger.info("Chart SVG converter initialized successfully")
        except Exception as e:
            logger.warning(f"Chart SVG converter initialization failed: {e}, falling back to table rendering")

        # Initialize mathematical formula converter
        try:
            self.math_converter = MathToSVG(font_size=16, color='black')
            logger.info("Mathematical formula SVG converter initialized successfully")
        except Exception as e:
            logger.warning(f"Mathematical formula SVG converter initialization failed: {e}, formulas will display as plain text")
            self.math_converter = None

    @staticmethod
    def _get_font_path() -> Path:
        """Retrieve Unicode font file path for international character support"""
        # Prioritize full font files to ensure comprehensive character coverage
        fonts_dir = Path(__file__).parent / "assets" / "fonts"

        # Check for full font file
        full_font = fonts_dir / "SourceHanSerifSC-Medium.otf"
        if full_font.exists():
            logger.info(f"Using full font file: {full_font}")
            return full_font

        # Check for TTF subset font
        subset_ttf = fonts_dir / "SourceHanSerifSC-Medium-Subset.ttf"
        if subset_ttf.exists():
            logger.info(f"Using TTF subset font: {subset_ttf}")
            return subset_ttf

        # Check for OTF subset font
        subset_otf = fonts_dir / "SourceHanSerifSC-Medium-Subset.otf"
        if subset_otf.exists():
            logger.info(f"Using OTF subset font: {subset_otf}")
            return subset_otf

        raise FileNotFoundError(f"Font file not found, please verify directory: {fonts_dir}")

    def _preprocess_charts(
        self,
        document_ir: Dict[str, Any],
        ir_file_path: str | None = None
    ) -> Dict[str, Any]:
        """
        Preprocess charts: validate and repair all chart data using ChartReviewService.

        Uses unified ChartReviewService for chart validation, with repairs written back to the IR.
        If ir_file_path is provided, repairs are automatically saved to file.

        Args:
            document_ir: Document IR data structure
            ir_file_path: Optional IR file path; when provided, repairs are auto-saved

        Returns:
            Dict[str, Any]: Repaired Document IR (deep copy)
        """
        # Use unified ChartReviewService
        # review_document returns session-specific statistics (thread-safe)
        chart_service = get_chart_review_service()
        review_stats = chart_service.review_document(
            document_ir,
            ir_file_path=ir_file_path,
            reset_stats=True,
            save_on_repair=bool(ir_file_path)
        )

        # Use returned ReviewStats object rather than shared chart_service.stats
        if review_stats.total > 0:
            logger.info(
                f"PDF chart preprocessing completed: "
                f"Total {review_stats.total} charts, "
                f"Repaired {review_stats.repaired_total}, "
                f"Failed {review_stats.failed}"
            )

        # Return deep copy to prevent SVG conversion process from affecting written-back original IR
        return copy.deepcopy(document_ir)

    def _convert_charts_to_svg(self, document_ir: Dict[str, Any]) -> Dict[str, str]:
        """
        Convert all charts in document_ir to SVG format

        Args:
            document_ir: Document IR data structure

        Returns:
            Dict[str, str]: Mapping of widgetId to SVG string
        """
        svg_map = {}

        if not hasattr(self, 'chart_converter') or not self.chart_converter:
            logger.warning("Chart converter not initialized, skipping chart conversion")
            return svg_map

        # Iterate through all chapters
        chapters = document_ir.get('chapters', [])
        for chapter in chapters:
            blocks = chapter.get('blocks', [])
            self._extract_and_convert_widgets(blocks, svg_map)

        logger.info(f"Successfully converted {len(svg_map)} charts to SVG")
        return svg_map

    def _convert_wordclouds_to_images(self, document_ir: Dict[str, Any]) -> Dict[str, str]:
        """
        Convert wordcloud widgets in document_ir to PNG format and return data URI mapping
        """
        img_map: Dict[str, str] = {}

        if not WORDCLOUD_AVAILABLE:
            logger.debug("wordcloud library not installed, wordclouds will fall back to table rendering")
            return img_map

        # Iterate through all chapters
        chapters = document_ir.get('chapters', [])
        for chapter in chapters:
            blocks = chapter.get('blocks', [])
            self._extract_wordcloud_widgets(blocks, img_map)

        if img_map:
            logger.info(f"Successfully converted {len(img_map)} wordclouds to images")
        return img_map

    def _extract_and_convert_widgets(
        self,
        blocks: list,
        svg_map: Dict[str, str]
    ) -> None:
        """
        Recursively traverse blocks to locate and convert all widgets to SVG

        Args:
            blocks: List of block elements
            svg_map: Dictionary for storing conversion results
        """
        for block in blocks:
            if not isinstance(block, dict):
                continue

            block_type = block.get('type')

            # Process widget type blocks
            if block_type == 'widget':
                widget_id = block.get('widgetId')
                widget_type = block.get('widgetType', '')

                # Only process chart.js type widgets
                if widget_id and widget_type.startswith('chart.js'):
                    widget_type_lower = widget_type.lower()
                    props = block.get('props')
                    props_type = str(props.get('type') or '').lower() if isinstance(props, dict) else ''
                    if 'wordcloud' in widget_type_lower or 'wordcloud' in props_type:
                        logger.debug(f"Detected wordcloud {widget_id}, skipping SVG conversion and using image injection")
                        continue

                    failed, fail_reason = self.html_renderer._has_chart_failure(block)
                    if block.get("_chart_renderable") is False or failed:
                        logger.debug(
                            f"Skipping failed chart {widget_id}"
                            f"{f', reason: {fail_reason}' if fail_reason else ''}"
                        )
                        continue
                    try:
                        svg_content = self.chart_converter.convert_widget_to_svg(
                            block,
                            width=800,
                            height=500,
                            dpi=100
                        )
                        if svg_content:
                            svg_map[widget_id] = svg_content
                            logger.debug(f"Chart {widget_id} converted to SVG successfully")
                        else:
                            logger.warning(f"Chart {widget_id} SVG conversion failed")
                    except Exception as e:
                        logger.error(f"Error converting chart {widget_id}: {e}")

            # Recursively process nested blocks
            nested_blocks = block.get('blocks')
            if isinstance(nested_blocks, list):
                self._extract_and_convert_widgets(nested_blocks, svg_map)

            # Process list items
            if block_type == 'list':
                items = block.get('items', [])
                for item in items:
                    if isinstance(item, list):
                        self._extract_and_convert_widgets(item, svg_map)

            # Process table cells
            if block_type == 'table':
                rows = block.get('rows', [])
                for row in rows:
                    cells = row.get('cells', [])
                    for cell in cells:
                        cell_blocks = cell.get('blocks', [])
                        if isinstance(cell_blocks, list):
                            self._extract_and_convert_widgets(cell_blocks, svg_map)

    def _extract_wordcloud_widgets(
        self,
        blocks: list,
        img_map: Dict[str, str]
    ) -> None:
        """
        Recursively traverse blocks to locate wordcloud widgets and generate images
        """
        for block in blocks:
            if not isinstance(block, dict):
                continue

            block_type = block.get('type')
            if block_type == 'widget':
                widget_id = block.get('widgetId')
                widget_type = block.get('widgetType', '')

                props = block.get('props')
                props_type = str(props.get('type') or '') if isinstance(props, dict) else ''
                is_wordcloud = (
                    isinstance(widget_type, str) and 'wordcloud' in widget_type.lower()
                ) or ('wordcloud' in props_type.lower())

                if widget_id and is_wordcloud:
                    try:
                        data_uri = self._generate_wordcloud_image(block)
                        if data_uri:
                            img_map[widget_id] = data_uri
                            logger.debug(f"Wordcloud {widget_id} converted to image successfully")
                    except Exception as exc:
                        logger.warning(f"Wordcloud image generation failed for {widget_id}: {exc}")

            nested_blocks = block.get('blocks')
            if isinstance(nested_blocks, list):
                self._extract_wordcloud_widgets(nested_blocks, img_map)

            if block_type == 'list':
                items = block.get('items', [])
                for item in items:
                    if isinstance(item, list):
                        self._extract_wordcloud_widgets(item, img_map)

            if block_type == 'table':
                rows = block.get('rows', [])
                for row in rows:
                    cells = row.get('cells', [])
                    for cell in cells:
                        cell_blocks = cell.get('blocks', [])
                        if isinstance(cell_blocks, list):
                            self._extract_wordcloud_widgets(cell_blocks, img_map)

    def _normalize_wordcloud_items(self, block: Dict[str, Any]) -> list:
        """
        Extract wordcloud data from widget block
        """
        props = block.get('props') or {}
        raw_items = props.get('data')
        if not isinstance(raw_items, list):
            return []
        normalized = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            word = item.get('word') or item.get('text') or item.get('label')
            if not word:
                continue
            weight = item.get('weight')
            try:
                weight_val = float(weight)
                if weight_val <= 0:
                    weight_val = 1.0
            except (TypeError, ValueError):
                weight_val = 1.0
            category = (item.get('category') or '').lower()
            normalized.append({'word': str(word), 'weight': weight_val, 'category': category})
        return normalized

    def _generate_wordcloud_image(self, block: Dict[str, Any]) -> str | None:
        """
        Generate wordcloud PNG image and return data URI
        """
        items = self._normalize_wordcloud_items(block)
        if not items:
            return None

        # Convert to frequency format for wordcloud library
        frequencies = {}
        for item in items:
            weight = item['weight']
            # Scale decimal weights (0-1 range) to enhance visual differentiation
            freq = weight * 100 if 0 < weight <= 1.5 else weight
            frequencies[item['word']] = max(1, freq)

        font_path = str(self._get_font_path())
        wc = WordCloud(
            width=1000,
            height=360,
            background_color="white",
            font_path=font_path,
            prefer_horizontal=0.98,
            random_state=42,
            max_words=180,
            collocations=False,
        )
        wc.generate_from_frequencies(frequencies)

        buffer = io.BytesIO()
        wc.to_image().save(buffer, format='PNG')
        encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
        return f"data:image/png;base64,{encoded}"

    def _convert_math_to_svg(self, document_ir: Dict[str, Any]) -> Dict[str, str]:
        """
        Convert all mathematical formulas in document_ir to SVG format

        Args:
            document_ir: Document IR data structure

        Returns:
            Dict[str, str]: Mapping of formula block ID to SVG string
        """
        svg_map = {}

        if not hasattr(self, 'math_converter') or not self.math_converter:
            logger.warning("Mathematical formula converter not initialized, skipping formula conversion")
            return svg_map

        # Iterate through all chapters with global counter to prevent ID duplication
        block_counter = [0]
        chapters = document_ir.get('chapters', [])
        for chapter in chapters:
            blocks = chapter.get('blocks', [])
            self._extract_and_convert_math_blocks(blocks, svg_map, block_counter)

        logger.info(f"Successfully converted {len(svg_map)} mathematical formulas to SVG")
        return svg_map

    def _extract_and_convert_math_blocks(
        self,
        blocks: list,
        svg_map: Dict[str, str],
        block_counter: list = None
    ) -> None:
        """
        Recursively traverse blocks to locate and convert all math blocks to SVG

        Args:
            blocks: List of block elements
            svg_map: Dictionary for storing conversion results
            block_counter: Counter for generating unique IDs
        """
        if block_counter is None:
            block_counter = [0]

        def _extract_inline_math_from_inlines(inlines: list):
            """Extract mathematical formulas from paragraph inline nodes"""
            if not isinstance(inlines, list):
                return
            for run in inlines:
                if not isinstance(run, dict):
                    continue
                marks = run.get('marks') or []
                math_mark = next((m for m in marks if m.get('type') == 'math'), None)

                if math_mark:
                    # Single math mark only
                    raw = math_mark.get('value') or run.get('text') or ''
                    latex = self._normalize_latex(raw)
                    # Treat inline marks uniformly as inline to prevent misclassifying as display formulas
                    is_display = False
                    if not latex:
                        continue
                    block_counter[0] += 1
                    math_id = run.get('mathId') or f"math-inline-{block_counter[0]}"
                    run['mathId'] = math_id
                    try:
                        svg_content = (
                            self.math_converter.convert_display_to_svg(latex)
                            if is_display else
                            self.math_converter.convert_inline_to_svg(latex)
                        )
                        if svg_content:
                            svg_map[math_id] = svg_content
                            logger.debug(f"Formula {math_id} converted to SVG successfully")
                        else:
                            logger.warning(f"Formula {math_id} SVG conversion failed: {latex[:50]}...")
                    except Exception as exc:
                        logger.error(f"Error converting inline formula {latex[:50]}...: {exc}")
                    continue

                # No math mark, attempt to parse multiple formulas from text
                text_val = run.get('text')
                if not isinstance(text_val, str):
                    continue
                segments = self._find_all_math_in_text(text_val)
                if not segments:
                    continue
                ids_for_html: list[str] = []
                for idx, (latex, is_display) in enumerate(segments, start=1):
                    if not latex:
                        continue
                    block_counter[0] += 1
                    math_id = f"auto-math-{block_counter[0]}"
                    ids_for_html.append(math_id)
                    try:
                        svg_content = (
                            self.math_converter.convert_display_to_svg(latex)
                            if is_display else
                            self.math_converter.convert_inline_to_svg(latex)
                        )
                        if svg_content:
                            svg_map[math_id] = svg_content
                            logger.debug(f"Formula {math_id} converted to SVG successfully")
                        else:
                            logger.warning(f"Formula {math_id} SVG conversion failed: {latex[:50]}...")
                    except Exception as exc:
                        logger.error(f"Error converting inline formula {latex[:50]}...: {exc}")
                if ids_for_html:
                    # Write ID list back to run for HTML rendering to use matching IDs (order corresponds to segments)
                    run['mathIds'] = ids_for_html

        for block in blocks:
            if not isinstance(block, dict):
                continue

            block_type = block.get('type')

            # Process math block type
            if block_type == 'math':
                latex = self._normalize_latex(block.get('latex', ''))
                if latex:
                    block_counter[0] += 1
                    math_id = f"math-block-{block_counter[0]}"
                    try:
                        svg_content = self.math_converter.convert_display_to_svg(latex)
                        if svg_content:
                            svg_map[math_id] = svg_content
                            # Add ID to block for subsequent injection identification
                            block['mathId'] = math_id
                            logger.debug(f"Formula {math_id} converted to SVG successfully")
                        else:
                            logger.warning(f"Formula {math_id} SVG conversion failed: {latex[:50]}...")
                    except Exception as e:
                        logger.error(f"Error converting formula {latex[:50]}...: {e}")
            else:
                # Extract inline formulas from paragraphs, tables, etc.
                inlines = block.get('inlines')
                if inlines:
                    _extract_inline_math_from_inlines(inlines)

            # Recursively process nested blocks
            nested_blocks = block.get('blocks')
            if isinstance(nested_blocks, list):
                self._extract_and_convert_math_blocks(nested_blocks, svg_map, block_counter)

            # Process list items
            if block_type == 'list':
                items = block.get('items', [])
                for item in items:
                    if isinstance(item, list):
                        self._extract_and_convert_math_blocks(item, svg_map, block_counter)

            # Process table cells
            if block_type == 'table':
                rows = block.get('rows', [])
                for row in rows:
                    cells = row.get('cells', [])
                    for cell in cells:
                        cell_blocks = cell.get('blocks', [])
                        if isinstance(cell_blocks, list):
                            self._extract_and_convert_math_blocks(cell_blocks, svg_map, block_counter)

            # Process blocks within callouts
            if block_type == 'callout':
                callout_blocks = block.get('blocks', [])
                if isinstance(callout_blocks, list):
                    self._extract_and_convert_math_blocks(callout_blocks, svg_map, block_counter)

    def _inject_svg_into_html(self, html: str, svg_map: Dict[str, str]) -> str:
        """
        Inject SVG content directly into HTML (without JavaScript)

        Args:
            html: Original HTML content
            svg_map: Mapping of widgetId to SVG content

        Returns:
            str: HTML with injected SVG
        """
        if not svg_map:
            return html

        import re

        # Locate corresponding canvas for each widgetId and replace with SVG
        for widget_id, svg_content in svg_map.items():
            # Clean SVG content (remove XML declaration since SVG will be embedded in HTML)
            svg_content = re.sub(r'<\?xml[^>]+\?>', '', svg_content)
            svg_content = re.sub(r'<!DOCTYPE[^>]+>', '', svg_content)
            svg_content = svg_content.strip()

            # Create SVG container HTML
            svg_html = f'<div class="chart-svg-container">{svg_content}</div>'

            # Locate config script containing this widgetId (restricted within same </script> to prevent cross-tag mismatches)
            config_pattern = rf'<script[^>]+id="([^"]+)"[^>]*>(?:(?!</script>).)*?"widgetId"\s*:\s*"{re.escape(widget_id)}"(?:(?!</script>).)*?</script>'
            match = re.search(config_pattern, html, re.DOTALL)

            if match:
                config_id = match.group(1)

                # Locate corresponding canvas element
                # Format: <canvas id="chart-N" data-config-id="chart-config-N"></canvas>
                canvas_pattern = rf'<canvas[^>]+data-config-id="{re.escape(config_id)}"[^>]*></canvas>'

                # Fix: Replace canvas with SVG using lambda to avoid backslash escaping issues
                html, replaced = re.subn(canvas_pattern, lambda m: svg_html, html, count=1)
                if replaced:
                    logger.debug(f"Replaced canvas with SVG for chart {widget_id}")
                else:
                    logger.warning(f"Canvas not found for chart {widget_id} replacement")

                # Mark corresponding fallback as hidden to prevent duplicate tables in PDF
                fallback_pattern = rf'<div class="chart-fallback"([^>]*data-widget-id="{re.escape(widget_id)}"[^>]*)>'

                def _hide_fallback(m: re.Match) -> str:
                    """Add hidden class to matched chart fallback to prevent duplicate rendering in PDF"""
                    tag = m.group(0)
                    if 'svg-hidden' in tag:
                        return tag
                    return tag.replace('chart-fallback"', 'chart-fallback svg-hidden"', 1)

                html = re.sub(fallback_pattern, _hide_fallback, html, count=1)
            else:
                logger.warning(f"Configuration script not found for chart {widget_id}")

        return html

    @staticmethod
    def _normalize_latex(raw: Any) -> str:
        """Remove outer math delimiters, supporting $...$, $$...$$, \\(\\), \\[\\] formats"""
        if not isinstance(raw, str):
            return ""
        latex = raw.strip()
        patterns = [
            r'^\$\$(.*)\$\$$',
            r'^\$(.*)\$$',
            r'^\\\[(.*)\\\]$',
            r'^\\\((.*)\\\)$',
        ]
        for pat in patterns:
            m = re.match(pat, latex, re.DOTALL)
            if m:
                latex = m.group(1).strip()
                break
        # Clean control characters to prevent mathtext parsing failures
        latex = re.sub(r'[\x00-\x1f\x7f]', '', latex)
        # Common compatibility: \tfrac/\dfrac -> \frac
        latex = latex.replace(r'\tfrac', r'\frac').replace(r'\dfrac', r'\frac')
        return latex

    @staticmethod
    def _find_first_math_in_text(text: Any) -> tuple[str, bool] | None:
        """Extract first mathematical fragment from plain text, returns (content, is_display)"""
        if not isinstance(text, str):
            return None
        pattern = re.compile(r'\$\$(.+?)\$\$|\$(.+?)\$|\\\((.+?)\\\)|\\\[(.+?)\\\]', re.S)
        matches = list(pattern.finditer(text))
        if not matches:
            return None
        m = matches[0]
        raw = next(g for g in m.groups() if g is not None)
        latex = raw.strip()
        is_display_raw = bool(m.group(1) or m.group(4))  # $$ or \[ \]
        is_standalone = (
            len(matches) == 1 and
            not text[:m.start()].strip() and
            not text[m.end():].strip()
        )
        return latex, bool(is_display_raw and is_standalone)

    @staticmethod
    def _find_all_math_in_text(text: Any) -> list[tuple[str, bool]]:
        """Extract all mathematical fragments from plain text, returns [(content, is_display)]"""
        if not isinstance(text, str):
            return []
        pattern = re.compile(r'\$\$(.+?)\$\$|\$(.+?)\$|\\\((.+?)\\\)|\\\[(.+?)\\\]', re.S)
        results = []
        matches = list(pattern.finditer(text))
        if not matches:
            return results
        total = len(matches)

        for m in matches:
            raw = next(g for g in m.groups() if g is not None)
            latex = raw.strip()
            is_display_raw = bool(m.group(1) or m.group(4))
            is_standalone = (
                total == 1 and
                not text[:m.start()].strip() and
                not text[m.end():].strip()
            )
            is_display = is_display_raw and is_standalone
            results.append((latex, is_display))
        return results

    def _inject_wordcloud_images(self, html: str, img_map: Dict[str, str]) -> str:
        """
        Inject wordcloud PNG data URIs into HTML, replacing corresponding canvas elements
        """
        if not img_map:
            return html

        import re

        for widget_id, data_uri in img_map.items():
            img_html = (
                f'<div class="chart-svg-container wordcloud-img">'
                f'<img src="{data_uri}" alt="Word Cloud" />'
                f'</div>'
            )

            config_pattern = rf'<script[^>]+id="([^"]+)"[^>]*>(?:(?!</script>).)*?"widgetId"\s*:\s*"{re.escape(widget_id)}"(?:(?!</script>).)*?</script>'
            match = re.search(config_pattern, html, re.DOTALL)
            if not match:
                logger.debug(f"Configuration script not found for wordcloud {widget_id}, skipping injection")
                continue

            config_id = match.group(1)
            canvas_pattern = rf'<canvas[^>]+data-config-id="{re.escape(config_id)}"[^>]*></canvas>'

            html, replaced = re.subn(canvas_pattern, lambda m: img_html, html, count=1)
            if replaced:
                logger.debug(f"Replaced canvas with PNG image for wordcloud {widget_id}")
            else:
                logger.warning(f"Canvas not found for wordcloud {widget_id} replacement")

            fallback_pattern = rf'<div class="chart-fallback"([^>]*data-widget-id="{re.escape(widget_id)}"[^>]*)>'

            def _hide_fallback(m: re.Match) -> str:
                """Match wordcloud table fallback and mark as hidden to prevent duplicate SVG/image rendering"""
                tag = m.group(0)
                if 'svg-hidden' in tag:
                    return tag
                return tag.replace('chart-fallback"', 'chart-fallback svg-hidden"', 1)

            html = re.sub(fallback_pattern, _hide_fallback, html, count=1)

        return html

    def _inject_math_svg_into_html(self, html: str, svg_map: Dict[str, str]) -> str:
        """
        Inject mathematical formula SVG content into HTML

        Args:
            html: Original HTML content
            svg_map: Mapping of formula ID to SVG content

        Returns:
            str: HTML with injected SVG
        """
        if not svg_map:
            return html

        import re

        # Prioritize inline formula replacement, then block formulas, maintaining consistent order
        for math_id, svg_content in svg_map.items():
            # Clean SVG content (remove XML declaration since SVG will be embedded in HTML)
            svg_content = re.sub(r'<\?xml[^>]+\?>', '', svg_content)
            svg_content = re.sub(r'<!DOCTYPE[^>]+>', '', svg_content)
            svg_content = svg_content.strip()

            svg_block_html = f'<div class="math-svg-container">{svg_content}</div>'
            svg_inline_html = f'<span class="math-svg-inline">{svg_content}</span>'

            replaced = False
            # Prioritize exact replacement by data-math-id
            inline_pattern = rf'<span class="math-inline"[^>]*data-math-id="{re.escape(math_id)}"[^>]*>.*?</span>'
            if re.search(inline_pattern, html, re.DOTALL):
                html = re.sub(inline_pattern, lambda m: svg_inline_html, html, count=1)
                replaced = True
            else:
                block_pattern = rf'<div class="math-block"[^>]*data-math-id="{re.escape(math_id)}"[^>]*>.*?</div>'
                if re.search(block_pattern, html, re.DOTALL):
                    html = re.sub(block_pattern, lambda m: svg_block_html, html, count=1)
                    replaced = True

            # If specific ID not found, fallback to sequential replacement by order of appearance
            if not replaced:
                html, sub_inline = re.subn(r'<span class="math-inline">[^<]*</span>', lambda m: svg_inline_html, html, count=1)
                if sub_inline:
                    replaced = True
                else:
                    html, sub_block = re.subn(r'<div class="math-block">\$\$[^$]*\$\$</div>', lambda m: svg_block_html, html, count=1)
                    if sub_block:
                        replaced = True

            if replaced:
                logger.debug(f"Replaced formula {math_id} with SVG")

        return html

    def _get_pdf_html(
        self,
        document_ir: Dict[str, Any],
        optimize_layout: bool = True,
        ir_file_path: str | None = None
    ) -> str:
        """
        Generate PDF-optimized HTML content

        - Remove interactive elements (buttons, navigation, etc.)
        - Add PDF-specific styles
        - Embed font files
        - Apply layout optimizations
        - Convert charts to SVG vector graphics

        Args:
            document_ir: Document IR data structure
            optimize_layout: Whether to enable layout optimization
            ir_file_path: Optional IR file path; when provided, repairs are auto-saved

        Returns:
            str: Optimized HTML content
        """
        # If layout optimization is enabled, analyze document and generate optimization config
        if optimize_layout:
            logger.info("Enabling PDF layout optimization...")
            layout_config = self.layout_optimizer.optimize_for_document(document_ir)

            # Save optimization log
            log_dir = Path('logs/pdf_layouts')
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"layout_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

            # Save configuration and optimization log
            optimization_log = self.layout_optimizer._log_optimization(
                self.layout_optimizer._analyze_document(document_ir),
                layout_config
            )
            self.layout_optimizer.config = layout_config
            self.layout_optimizer.save_config(log_file, optimization_log)
        else:
            layout_config = self.layout_optimizer.config

        # Critical fix: preprocess charts first to ensure data validity
        logger.info("Preprocessing chart data...")
        preprocessed_ir = self._preprocess_charts(document_ir, ir_file_path)

        # Convert charts to SVG (using preprocessed IR)
        logger.info("Converting charts to SVG vector graphics...")
        svg_map = self._convert_charts_to_svg(preprocessed_ir)

        # Convert wordclouds to PNG
        logger.info("Converting wordclouds to images...")
        wordcloud_map = self._convert_wordclouds_to_images(preprocessed_ir)

        # Convert mathematical formulas to SVG
        logger.info("Converting mathematical formulas to SVG vector graphics...")
        math_svg_map = self._convert_math_to_svg(preprocessed_ir)

        # Use HTML renderer to generate base HTML (using preprocessed IR to reuse mathId and other markers)
        html = self.html_renderer.render(preprocessed_ir, ir_file_path=ir_file_path)

        # Inject chart SVG
        if svg_map:
            html = self._inject_svg_into_html(html, svg_map)
            logger.info(f"Injected {len(svg_map)} SVG charts")

        if wordcloud_map:
            html = self._inject_wordcloud_images(html, wordcloud_map)
            logger.info(f"Injected {len(wordcloud_map)} wordcloud images")

        # Inject mathematical formula SVG
        if math_svg_map:
            html = self._inject_math_svg_into_html(html, math_svg_map)
            logger.info(f"Injected {len(math_svg_map)} SVG formulas")

        # Retrieve font path and convert to base64 (for embedding)
        font_path = self._get_font_path()
        font_data = font_path.read_bytes()
        font_base64 = base64.b64encode(font_data).decode('ascii')

        # Determine font format
        font_format = 'opentype' if font_path.suffix == '.otf' else 'truetype'

        # Generate optimized CSS
        optimized_css = self.layout_optimizer.generate_pdf_css()

        # Add PDF-specific CSS
        pdf_css = f"""
<style>
/* PDF-specific font embedding */
@font-face {{
    font-family: 'SourceHanSerif';
    src: url(data:font/{font_format};base64,{font_base64}) format('{font_format}');
    font-weight: normal;
    font-style: normal;
}}

/* Force all text to use Source Han Serif font */
body, h1, h2, h3, h4, h5, h6, p, li, td, th, div, span {{
    font-family: 'SourceHanSerif', serif !important;
}}

/* PDF-specific style adjustments */
.report-header {{
    display: none !important;
}}

.no-print {{
    display: none !important;
}}

body {{
    background: white !important;
}}

/* ========== Fix WeasyPrint CSS Variable Gradient Compatibility ========== */
/* WeasyPrint does not support var() in linear-gradient, requiring static value overrides */

/* Override button gradients */
.action-btn {{
    background: linear-gradient(135deg, #4a90e2 0%, #17a2b8 100%) !important;
}}

/* Override progress bar gradients */
.export-progress::after {{
    background: linear-gradient(90deg, #4a90e2, #17a2b8) !important;
}}

/* Override PEST card title gradients */
.pest-card__title {{
    background: linear-gradient(135deg, #8e44ad, #2980b9) !important;
    -webkit-background-clip: text !important;
    -webkit-text-fill-color: transparent !important;
    background-clip: text !important;
}}

/* Override PEST strip indicator gradients */
.pest-strip__indicator.political {{
    background: linear-gradient(180deg, #8e44ad, rgba(142,68,173,0.8)) !important;
}}
.pest-strip__indicator.economic {{
    background: linear-gradient(180deg, #16a085, rgba(22,160,133,0.8)) !important;
}}
.pest-strip__indicator.social {{
    background: linear-gradient(180deg, #e84393, rgba(232,67,147,0.8)) !important;
}}
.pest-strip__indicator.technological {{
    background: linear-gradient(180deg, #2980b9, rgba(41,128,185,0.8)) !important;
}}

/* Override PEST strip backgrounds (originally used var(--pest-strip-*-bg) containing gradients and variables) */
.pest-strip {{
    background: #ffffff !important;
}}
.pest-strip.political {{
    background: linear-gradient(90deg, rgba(142,68,173,0.08), rgba(255,255,255,0.85)), #ffffff !important;
    border-color: rgba(142,68,173,0.4) !important;
}}
.pest-strip.economic {{
    background: linear-gradient(90deg, rgba(22,160,133,0.08), rgba(255,255,255,0.85)), #ffffff !important;
    border-color: rgba(22,160,133,0.4) !important;
}}
.pest-strip.social {{
    background: linear-gradient(90deg, rgba(232,67,147,0.08), rgba(255,255,255,0.85)), #ffffff !important;
    border-color: rgba(232,67,147,0.4) !important;
}}
.pest-strip.technological {{
    background: linear-gradient(90deg, rgba(41,128,185,0.08), rgba(255,255,255,0.85)), #ffffff !important;
    border-color: rgba(41,128,185,0.4) !important;
}}

/* Override SWOT card backgrounds (originally used var(--swot-card-bg) containing gradients and variables) */
.swot-card {{
    background: linear-gradient(135deg, rgba(76,132,255,0.04), rgba(28,127,110,0.06)), #ffffff !important;
}}

/* Override SWOT cell backgrounds (originally used var(--swot-cell-*-bg) containing gradients and variables) */
.swot-cell {{
    background: linear-gradient(135deg, rgba(255,255,255,0.9), rgba(255,255,255,0.5)) !important;
}}
.swot-cell.strength {{
    background: linear-gradient(135deg, rgba(28,127,110,0.07), rgba(255,255,255,0.78)), #ffffff !important;
    border-color: rgba(28,127,110,0.35) !important;
}}
.swot-cell.weakness {{
    background: linear-gradient(135deg, rgba(192,57,43,0.07), rgba(255,255,255,0.78)), #ffffff !important;
    border-color: rgba(192,57,43,0.35) !important;
}}
.swot-cell.opportunity {{
    background: linear-gradient(135deg, rgba(31,90,179,0.07), rgba(255,255,255,0.78)), #ffffff !important;
    border-color: rgba(31,90,179,0.35) !important;
}}
.swot-cell.threat {{
    background: linear-gradient(135deg, rgba(179,107,22,0.07), rgba(255,255,255,0.78)), #ffffff !important;
    border-color: rgba(179,107,22,0.35) !important;
}}

/* Override SWOT legend items and pills (using static colors) */
.swot-legend__item.strength, .swot-pill.strength {{
    background: #1c7f6e !important;
}}
.swot-legend__item.weakness, .swot-pill.weakness {{
    background: #c0392b !important;
}}
.swot-legend__item.opportunity, .swot-pill.opportunity {{
    background: #1f5ab3 !important;
}}
.swot-legend__item.threat, .swot-pill.threat {{
    background: #b36b16 !important;
}}

/* Override other elements using var() */
.swot-item {{
    background: rgba(255,255,255,0.92) !important;
}}
.swot-tag {{
    background: rgba(0,0,0,0.04) !important;
}}
.swot-empty {{
    border-color: #e0e0e0 !important;
}}

/* Override PEST card background */
.pest-card {{
    background: linear-gradient(145deg, rgba(142,68,173,0.03), rgba(22,160,133,0.04)), #ffffff !important;
}}

/* Override chart card error state gradients */
.chart-card.chart-card--error {{
    background: linear-gradient(135deg, rgba(0,0,0,0.015), rgba(0,0,0,0.04)) !important;
}}

/* Override wordcloud badge gradients */
.wordcloud-badge {{
    background: linear-gradient(135deg, rgba(74, 144, 226, 0.14) 0%, rgba(74, 144, 226, 0.24) 100%) !important;
}}

/* Override hero section gradients */
.hero-section {{
    background: linear-gradient(135deg, rgba(0,123,255,0.1), rgba(23,162,184,0.1)) !important;
}}

/* ========== Override hero-actions Button Styles (Borderless Style) ========== */
.hero-actions {{
    display: flex !important;
    flex-wrap: wrap !important;
    gap: 8px !important;
    margin-top: 14px !important;
    padding: 0 !important;
}}

.hero-actions button,
.hero-actions .ghost-btn,
button.ghost-btn {{
    display: inline-flex !important;
    align-items: center !important;
    justify-content: flex-start !important;
    background: none !important;
    background-color: #f3f4f6 !important;
    background-image: none !important;
    border: none !important;
    border-width: 0 !important;
    border-style: none !important;
    border-radius: 999px !important;
    padding: 5px 10px !important;
    font-size: 12px !important;
    color: #222 !important;
    white-space: normal !important;
    line-height: 1.5 !important;
    text-align: left !important;
    box-shadow: none !important;
    -webkit-appearance: none !important;
    -moz-appearance: none !important;
    appearance: none !important;
    outline: none !important;
    outline-width: 0 !important;
    word-break: break-word !important;
    max-width: 100% !important;
    box-sizing: border-box !important;
    margin: 0 !important;
    font-family: inherit !important;
}}

/* SVG chart container styles */
.chart-svg-container {{
    width: 100%;
    height: auto;
    display: flex;
    justify-content: center;
    align-items: center;
}}

.chart-svg-container svg {{
    max-width: 100%;
    height: auto;
}}
.chart-svg-container img {{
    max-width: 100%;
    height: auto;
}}

/* Mathematical formula SVG container styles */
.math-svg-container {{
    width: 100%;
    height: auto;
    display: flex;
    justify-content: center;
    align-items: center;
    margin: 20px 0;
}}

.math-svg-container svg {{
    max-width: 100%;
    height: auto;
}}

/* Hide original math-block (already replaced with SVG) */
.math-block {{
    display: none !important;
}}

/* Hide fallback tables when corresponding SVG successfully injected, continue showing fallback data on failure */
.chart-fallback.svg-hidden {{
    display: none !important;
}}

/* Ensure chart-container displays (for placing SVG) */
.chart-container {{
    display: block !important;
    min-height: 400px;
}}

/* ========== SWOT PDF Table Layout ========== */
/* Core strategy: Use table format in PDF instead of card format, better suited for pagination */

/* Hide HTML card layout, display PDF table layout */
.swot-card--html {{
    display: none !important;
}}

.swot-pdf-wrapper {{
    display: block !important;
    margin: 24px 0;
}}

/* PDF table overall styles */
.swot-pdf-table {{
    width: 100% !important;
    border-collapse: collapse !important;
    font-size: 11px !important;
    table-layout: fixed !important;
    background: white;
}}

/* Table caption */
.swot-pdf-caption {{
    caption-side: top !important;
    text-align: left !important;
    font-size: 16px !important;
    font-weight: 700 !important;
    padding: 12px 0 !important;
    color: #1a1a1a !important;
    border-bottom: 2px solid #333 !important;
    margin-bottom: 8px !important;
}}

/* Table header styles */
.swot-pdf-thead {{
    break-after: avoid !important;
    page-break-after: avoid !important;
}}

.swot-pdf-thead th {{
    background: #f0f0f0 !important;
    padding: 10px 8px !important;
    text-align: left !important;
    font-weight: 600 !important;
    border: 1px solid #ccc !important;
    color: #333 !important;
    font-size: 11px !important;
}}

.swot-pdf-th-quadrant {{ width: 70px !important; }}
.swot-pdf-th-num {{ width: 40px !important; text-align: center !important; }}
.swot-pdf-th-title {{ width: 20% !important; }}
.swot-pdf-th-detail {{ width: auto !important; }}
.swot-pdf-th-tags {{ width: 80px !important; text-align: center !important; }}

/* Summary row */
.swot-pdf-summary {{
    padding: 10px 12px !important;
    background: #f8f8f8 !important;
    color: #555 !important;
    font-style: italic !important;
    border: 1px solid #ccc !important;
    font-size: 11px !important;
}}

/* Each quadrant block - core pagination control */
.swot-pdf-quadrant {{
    break-inside: avoid !important;
    page-break-inside: avoid !important;
}}

/* Allow page breaks between different quadrants */
.swot-pdf-quadrant + .swot-pdf-quadrant {{
    break-before: auto;
    page-break-before: auto;
}}

/* Quadrant label cells */
.swot-pdf-quadrant-label {{
    text-align: center !important;
    vertical-align: middle !important;
    padding: 12px 6px !important;
    font-weight: 700 !important;
    border: 1px solid #ccc !important;
    width: 70px !important;
}}

/* Color themes for four quadrants */
.swot-pdf-quadrant-label.swot-pdf-strength {{
    background: #e8f5f2 !important;
    color: #1c7f6e !important;
    border-left: 4px solid #1c7f6e !important;
}}
.swot-pdf-quadrant-label.swot-pdf-weakness {{
    background: #fdeaea !important;
    color: #c0392b !important;
    border-left: 4px solid #c0392b !important;
}}
.swot-pdf-quadrant-label.swot-pdf-opportunity {{
    background: #e8f0fa !important;
    color: #1f5ab3 !important;
    border-left: 4px solid #1f5ab3 !important;
}}
.swot-pdf-quadrant-label.swot-pdf-threat {{
    background: #fdf3e6 !important;
    color: #b36b16 !important;
    border-left: 4px solid #b36b16 !important;
}}

/* Quadrant code letters */
.swot-pdf-code {{
    display: block !important;
    font-size: 20px !important;
    font-weight: 800 !important;
    margin-bottom: 2px !important;
}}

/* Quadrant label text */
.swot-pdf-label-text {{
    display: block !important;
    font-size: 9px !important;
    font-weight: 600 !important;
    letter-spacing: 0.02em !important;
}}

/* Data rows */
.swot-pdf-item-row td {{
    padding: 8px 6px !important;
    border: 1px solid #ddd !important;
    vertical-align: top !important;
    font-size: 11px !important;
    line-height: 1.4 !important;
}}

/* Row background colors */
.swot-pdf-item-row.swot-pdf-strength td {{ background: #f7fbfa !important; }}
.swot-pdf-item-row.swot-pdf-weakness td {{ background: #fef9f9 !important; }}
.swot-pdf-item-row.swot-pdf-opportunity td {{ background: #f7f9fc !important; }}
.swot-pdf-item-row.swot-pdf-threat td {{ background: #fdfbf7 !important; }}

/* Number cells */
.swot-pdf-item-num {{
    text-align: center !important;
    font-weight: 600 !important;
    color: #888 !important;
    width: 40px !important;
}}

/* Point titles */
.swot-pdf-item-title {{
    font-weight: 600 !important;
    color: #222 !important;
}}

/* Detailed descriptions */
.swot-pdf-item-detail {{
    color: #444 !important;
    line-height: 1.5 !important;
}}

/* Tag cells */
.swot-pdf-item-tags {{
    text-align: center !important;
}}

/* Tag styles */
.swot-pdf-tag {{
    display: inline-block !important;
    padding: 2px 6px !important;
    border-radius: 3px !important;
    font-size: 9px !important;
    background: #e9ecef !important;
    color: #495057 !important;
    margin: 1px !important;
}}

.swot-pdf-tag--score {{
    background: #fff3cd !important;
    color: #856404 !important;
}}

/* Empty data indicator */
.swot-pdf-empty {{
    text-align: center !important;
    color: #999 !important;
    font-style: italic !important;
}}

/* ========== PEST PDF Table Layout ========== */
/* Core strategy: Use table format in PDF instead of card format, better suited for pagination */

/* Hide HTML card layout, display PDF table layout */
.pest-card--html {{
    display: none !important;
}}

.pest-pdf-wrapper {{
    display: block !important;
    margin: 24px 0;
}}

/* PDF table overall styles */
.pest-pdf-table {{
    width: 100% !important;
    border-collapse: collapse !important;
    font-size: 11px !important;
    table-layout: fixed !important;
    background: white;
}}

/* Table caption */
.pest-pdf-caption {{
    caption-side: top !important;
    text-align: left !important;
    font-size: 16px !important;
    font-weight: 700 !important;
    padding: 12px 0 !important;
    color: #333 !important;
    border-bottom: 2px solid #333 !important;
    margin-bottom: 8px !important;
}}

/* Table header styles */
.pest-pdf-thead {{
    break-after: avoid !important;
    page-break-after: avoid !important;
}}

.pest-pdf-thead th {{
    background: #f5f3f7 !important;
    padding: 10px 8px !important;
    text-align: left !important;
    font-weight: 600 !important;
    border: 1px solid #ccc !important;
    color: #4a4458 !important;
    font-size: 11px !important;
}}

.pest-pdf-th-dimension {{ width: 70px !important; }}
.pest-pdf-th-num {{ width: 40px !important; text-align: center !important; }}
.pest-pdf-th-title {{ width: 20% !important; }}
.pest-pdf-th-detail {{ width: auto !important; }}
.pest-pdf-th-tags {{ width: 80px !important; text-align: center !important; }}

/* Summary row */
.pest-pdf-summary {{
    padding: 10px 12px !important;
    background: #f8f6fa !important;
    color: #555 !important;
    font-style: italic !important;
    border: 1px solid #ccc !important;
    font-size: 11px !important;
}}

/* Each dimension block - core pagination control */
.pest-pdf-dimension {{
    break-inside: avoid !important;
    page-break-inside: avoid !important;
}}

/* Allow page breaks between different dimensions */
.pest-pdf-dimension + .pest-pdf-dimension {{
    break-before: auto;
    page-break-before: auto;
}}

/* Dimension label cells */
.pest-pdf-dimension-label {{
    text-align: center !important;
    vertical-align: middle !important;
    padding: 12px 6px !important;
    font-weight: 700 !important;
    border: 1px solid #ccc !important;
    width: 70px !important;
}}

/* Color themes for four dimensions */
.pest-pdf-dimension-label.pest-pdf-political {{
    background: #f5eef8 !important;
    color: #8e44ad !important;
    border-left: 4px solid #8e44ad !important;
}}
.pest-pdf-dimension-label.pest-pdf-economic {{
    background: #e8f6f3 !important;
    color: #16a085 !important;
    border-left: 4px solid #16a085 !important;
}}
.pest-pdf-dimension-label.pest-pdf-social {{
    background: #fdecf4 !important;
    color: #e84393 !important;
    border-left: 4px solid #e84393 !important;
}}
.pest-pdf-dimension-label.pest-pdf-technological {{
    background: #ebf3f9 !important;
    color: #2980b9 !important;
    border-left: 4px solid #2980b9 !important;
}}

/* Dimension code letters */
.pest-pdf-code {{
    display: block !important;
    font-size: 20px !important;
    font-weight: 800 !important;
    margin-bottom: 2px !important;
}}

/* Dimension label text */
.pest-pdf-label-text {{
    display: block !important;
    font-size: 9px !important;
    font-weight: 600 !important;
    letter-spacing: 0.02em !important;
}}

/* Data rows */
.pest-pdf-item-row td {{
    padding: 8px 6px !important;
    border: 1px solid #ddd !important;
    vertical-align: top !important;
    font-size: 11px !important;
    line-height: 1.4 !important;
}}

/* Row background colors */
.pest-pdf-item-row.pest-pdf-political td {{ background: #faf7fc !important; }}
.pest-pdf-item-row.pest-pdf-economic td {{ background: #f5fbfa !important; }}
.pest-pdf-item-row.pest-pdf-social td {{ background: #fef8fb !important; }}
.pest-pdf-item-row.pest-pdf-technological td {{ background: #f7fafd !important; }}

/* Number cells */
.pest-pdf-item-num {{
    text-align: center !important;
    font-weight: 600 !important;
    color: #888 !important;
    width: 40px !important;
}}

/* Point titles */
.pest-pdf-item-title {{
    font-weight: 600 !important;
    color: #222 !important;
}}

/* Detailed descriptions */
.pest-pdf-item-detail {{
    color: #444 !important;
    line-height: 1.5 !important;
}}

/* Tag cells */
.pest-pdf-item-tags {{
    text-align: center !important;
}}

/* Tag styles */
.pest-pdf-tag {{
    display: inline-block !important;
    padding: 2px 6px !important;
    border-radius: 3px !important;
    font-size: 9px !important;
    background: #ece9f1 !important;
    color: #5a4f6a !important;
    margin: 1px !important;
}}

/* Empty data indicator */
.pest-pdf-empty {{
    text-align: center !important;
    color: #999 !important;
    font-style: italic !important;
}}

{optimized_css}
</style>
"""

        # Insert PDF-specific CSS before </head>
        html = html.replace('</head>', f'{pdf_css}\n</head>')

        return html

    def render_to_pdf(
        self,
        document_ir: Dict[str, Any],
        output_path: str | Path,
        optimize_layout: bool = True,
        ir_file_path: str | None = None
    ) -> Path:
        """
        Render Document IR to PDF file

        Args:
            document_ir: Document IR data structure
            output_path: PDF output file path
            optimize_layout: Whether to enable layout optimization (default True)
            ir_file_path: Optional IR file path; when provided, repairs are auto-saved

        Returns:
            Path: Generated PDF file path
        """
        output_path = Path(output_path)

        logger.info(f"Starting PDF generation: {output_path}")

        # Generate HTML content
        html_content = self._get_pdf_html(document_ir, optimize_layout, ir_file_path)

        # Configure fonts
        font_config = FontConfiguration()

        # Create WeasyPrint HTML object from HTML string
        html_doc = HTML(string=html_content, base_url=str(Path.cwd()))

        # Generate PDF
        try:
            html_doc.write_pdf(
                output_path,
                font_config=font_config,
                presentational_hints=True  # Preserve HTML presentational hints
            )
            logger.info(f"✓ PDF generation successful: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"PDF generation failed: {e}")
            raise

    def render_to_bytes(
        self,
        document_ir: Dict[str, Any],
        optimize_layout: bool = True,
        ir_file_path: str | None = None
    ) -> bytes:
        """
        Render Document IR to PDF byte stream

        Args:
            document_ir: Document IR data structure
            optimize_layout: Whether to enable layout optimization (default True)
            ir_file_path: Optional IR file path; when provided, repairs are auto-saved

        Returns:
            bytes: PDF file byte content
        """
        html_content = self._get_pdf_html(document_ir, optimize_layout, ir_file_path)
        font_config = FontConfiguration()
        html_doc = HTML(string=html_content, base_url=str(Path.cwd()))

        return html_doc.write_pdf(
            font_config=font_config,
            presentational_hints=True
        )


__all__ = ["PDFRenderer"]
