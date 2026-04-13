"""
Verify figure generation and injection into final PDF.

This check covers:
1) Generate a synthetic PNG image file.
2) Inject it into IR document via ChartInjector as literature figure.
3) Render HTML and ensure injected image is present.
4) Run the same inline-image trimming logic used by report writer.
5) Render PDF and verify the PDF actually contains image XObjects.

Usage:
    python scripts/dev_checks/check_figure_injection_to_pdf.py
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import fitz

from src.agents.report_writer import ReportWriterAgent
from src.report_engine.ir.schema import IRDocument, Chapter, ChapterBlock, BlockType
from src.report_engine.renderers import HTMLRenderer, PDFRenderer
from src.report_engine.utils.chart_injector import ChartInjector


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    payload = tag + data
    return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)


def _make_test_png(width: int = 280, height: int = 180) -> bytes:
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            r = 45 if (x // 16 + y // 16) % 2 == 0 else 85
            g = 122 if (x // 16 + y // 16) % 2 == 0 else 160
            b = 180
            if abs(x - width // 2) < 2 or abs(y - height // 2) < 2:
                r, g, b = 255, 255, 255
            rows.extend([r, g, b])

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(bytes(rows), 6)
    return b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", idat) + _png_chunk(b"IEND", b"")


def _count_pdf_images(pdf_bytes: bytes) -> int:
    image_count = 0
    with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf_doc:
        for page_index in range(pdf_doc.page_count):
            page = pdf_doc.load_page(page_index)
            image_count += len(page.get_images(full=True))
    return image_count


def main() -> int:
    out_dir = PROJECT_ROOT / "scripts" / "dev_checks" / "_outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    figure_path = out_dir / "synthetic_figure_injection.png"
    figure_path.write_bytes(_make_test_png())

    chapter = Chapter(
        id="clinical-progress",
        title="Clinical Progress and Trial Data Matrix",
        slug="clinical-progress",
        order=1,
        blocks=[
            ChapterBlock(
                type=BlockType.PARAGRAPH,
                content="This chapter validates literature-figure injection from extracted image files.",
            )
        ],
    )

    doc = IRDocument(
        title="Figure Injection Verification",
        subtitle="Synthetic Figure Pipeline Check",
        query="verify figure injection",
        chapters=[chapter],
    )

    injector = ChartInjector()
    enriched_doc = injector.enrich(
        doc,
        evidence_data={"harvested_data": []},
        forensic_data={},
        extracted_figures=[
            {
                "path": str(figure_path),
                "caption": "Synthetic Figure Injection",
                "source": "unit_test",
            }
        ],
    )

    all_image_blocks = []
    for ch in enriched_doc.chapters:
        for block in ch.blocks:
            if block.type == BlockType.IMAGE:
                all_image_blocks.append(block)

    if not all_image_blocks:
        print("[FAIL] No IMAGE block injected into IR document")
        return 1

    if not any((b.metadata or {}).get("css_class") == "literature-figure" for b in all_image_blocks):
        print("[FAIL] Injected IMAGE block is missing literature-figure css_class")
        return 1

    html_renderer = HTMLRenderer()
    html_content = html_renderer.render(enriched_doc, standalone=True)

    if "data:image/" not in html_content:
        print("[FAIL] HTML output does not contain injected data URI image")
        return 1

    if "Synthetic Figure Injection" not in html_content:
        print("[FAIL] HTML output does not contain figure caption")
        return 1

    html_for_pdf = ReportWriterAgent._strip_excessive_inline_images(html_content)
    if "data:image/" not in html_for_pdf:
        print("[FAIL] Inline image was stripped before PDF stage")
        return 1

    pdf_renderer = PDFRenderer()
    html_for_pdf = pdf_renderer._inject_pdf_font_css(html_for_pdf)
    html_for_pdf = pdf_renderer._inject_pdf_enhanced_css(html_for_pdf)
    try:
        html_for_pdf = pdf_renderer.chart_preprocessor.preprocess(html_for_pdf)
    except Exception:
        pass
    html_for_pdf = pdf_renderer.layout_optimizer.optimize(html_for_pdf)

    pdf_bytes = pdf_renderer._html_to_pdf_bytes(html_for_pdf)
    pdf_path = out_dir / "figure_injection_verification.pdf"
    pdf_path.write_bytes(pdf_bytes)

    image_count = _count_pdf_images(pdf_bytes)
    if image_count < 1:
        print("[FAIL] PDF contains no embedded images after injection")
        print(f"[INFO] Output PDF: {pdf_path}")
        return 1

    print("[PASS] Figure generation + HTML injection + PDF embedding verified")
    print(f"[INFO] Output PNG: {figure_path}")
    print(f"[INFO] Output PDF: {pdf_path}")
    print(f"[INFO] Embedded image count in PDF: {image_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
