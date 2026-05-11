from __future__ import annotations

from pathlib import Path


def test_requirements_include_matplotlib_for_pdf_chart_svg_rendering():
    requirements = Path("requirements.txt").read_text(encoding="utf-8").lower()

    assert "matplotlib" in requirements
