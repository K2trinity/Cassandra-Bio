"""
图表渲染端到端测试
======================
覆盖范围：
1. IRValidator  — chart 块结构校验（合法 / 缺字段 / 类型错误）
2. IRValidator  — _fix_block 修复 chart / graph / visualization 别名
3. HTMLRenderer — _render_chart 输出含 canvas / Chart.js 脚本
4. HTMLRenderer — _render_wordcloud 输出 canvas
5. IRDocument   — 多图表完整 HTML 文档渲染（写入 tests/output/chart_test.html 供人工验查）
"""

import sys
import os
import json
import re
import unittest
from pathlib import Path

# ── 路径 ──────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.report_engine.ir.schema import (
    IRDocument, Chapter, ChapterBlock, BlockType,
)
from src.report_engine.ir.validator import IRValidator
from src.report_engine.renderers.html_renderer import HTMLRenderer, _render_chart, _render_wordcloud


# ─────────────────────────────────────────────────────────────────────────────
# 辅助数据
# ─────────────────────────────────────────────────────────────────────────────
VALID_CHART_CONTENT = {
    "type": "bar",
    "title": "不良事件发生率（按严重等级）",
    "caption": "数据来源: NCT03456789",
    "labels": ["Grade 1-2", "Grade 3", "Grade 4+"],
    "datasets": [
        {
            "label": "治疗组",
            "data": [45.2, 18.7, 8.3],
            "backgroundColor": ["#4A90E2", "#E85D75", "#FF6B6B"],
        }
    ],
}

VALID_LINE_CONTENT = {
    "type": "line",
    "title": "临床试验入组进度",
    "labels": ["2021-Q1", "2021-Q2", "2021-Q3", "2021-Q4"],
    "datasets": [
        {
            "label": "累计入组",
            "data": [12, 45, 88, 130],
            "backgroundColor": "#4A90E2",
            "borderColor": "#1a73e8",
        }
    ],
}

VALID_PIE_CONTENT = {
    "type": "pie",
    "title": "终止原因分布",
    "labels": ["疗效不足", "安全性问题", "资金问题", "其他"],
    "datasets": [
        {
            "data": [42, 28, 18, 12],
            "backgroundColor": ["#E85D75", "#FF6B6B", "#FFB347", "#4A90E2"],
        }
    ],
}


def _make_chart_block(content: dict) -> ChapterBlock:
    return ChapterBlock(type=BlockType.CHART, content=content)


def _make_wordcloud_block() -> ChapterBlock:
    return ChapterBlock(
        type=BlockType.WORDCLOUD,
        content=[
            {"word": "hepatotoxicity", "weight": 9.5},
            {"word": "nivolumab", "weight": 8.2},
            {"word": "adverse event", "weight": 7.1},
            {"word": "immunotherapy", "weight": 6.8},
            {"word": "grade 3", "weight": 6.0},
        ],
        metadata={"title": "高频风险词云"},
    )


# ─────────────────────────────────────────────────────────────────────────────
# 测试组 1：IRValidator — chart 块结构校验
# ─────────────────────────────────────────────────────────────────────────────
class TestValidatorChartBlock(unittest.TestCase):

    def setUp(self):
        self.validator = IRValidator()

    def _chapter_with_blocks(self, *blocks):
        """构造最小合法 chapter dict 以触发 validate_chapter"""
        return {
            "title": "Test Chapter",
            "blocks": list(blocks),
        }

    # ── 合法 chart ──
    def test_valid_bar_chart_passes(self):
        block = {"type": "chart", "content": VALID_CHART_CONTENT}
        chapter = self._chapter_with_blocks(
            {"type": "paragraph", "content": "Intro paragraph with enough characters here."},
            block,
        )
        valid, errors = self.validator.validate_chapter(chapter)
        chart_errors = [e for e in errors if "chart" in e.lower() or "Chart" in e]
        self.assertEqual(chart_errors, [], f"Unexpected chart errors: {chart_errors}")

    def test_valid_line_chart_passes(self):
        block = {"type": "chart", "content": VALID_LINE_CONTENT}
        chapter = self._chapter_with_blocks(
            {"type": "paragraph", "content": "Intro paragraph with enough characters here."},
            block,
        )
        _, errors = self.validator.validate_chapter(chapter)
        chart_errors = [e for e in errors if "chart" in e.lower()]
        self.assertEqual(chart_errors, [])

    # ── 缺少 type 字段 ──
    def test_chart_missing_type_raises_error(self):
        bad_content = {k: v for k, v in VALID_CHART_CONTENT.items() if k != "type"}
        block = {"type": "chart", "content": bad_content}
        chapter = self._chapter_with_blocks(
            {"type": "paragraph", "content": "Intro paragraph with enough characters here."},
            block,
        )
        _, errors = self.validator.validate_chapter(chapter)
        self.assertTrue(any("type" in e for e in errors), f"Expected type error, got: {errors}")

    # ── 缺少 datasets ──
    def test_chart_missing_datasets_raises_error(self):
        bad_content = {"type": "bar", "title": "X", "labels": ["A", "B"]}
        block = {"type": "chart", "content": bad_content}
        chapter = self._chapter_with_blocks(
            {"type": "paragraph", "content": "Intro paragraph with enough characters here."},
            block,
        )
        _, errors = self.validator.validate_chapter(chapter)
        self.assertTrue(any("datasets" in e for e in errors), f"Expected datasets error, got: {errors}")

    # ── datasets 为空列表 ──
    def test_chart_empty_datasets_raises_error(self):
        bad_content = {"type": "bar", "labels": ["A"], "datasets": []}
        block = {"type": "chart", "content": bad_content}
        chapter = self._chapter_with_blocks(
            {"type": "paragraph", "content": "Intro paragraph with enough characters here."},
            block,
        )
        _, errors = self.validator.validate_chapter(chapter)
        self.assertTrue(any("datasets" in e for e in errors))

    # ── content 为非 dict ──
    def test_chart_content_not_dict_raises_error(self):
        block = {"type": "chart", "content": "this is wrong"}
        chapter = self._chapter_with_blocks(
            {"type": "paragraph", "content": "Intro paragraph with enough characters here."},
            block,
        )
        _, errors = self.validator.validate_chapter(chapter)
        self.assertTrue(any("dict" in e.lower() for e in errors),
                        f"Expected dict error, got: {errors}")

    # ── dataset 缺 data 字段 ──
    def test_chart_dataset_missing_data_raises_error(self):
        bad_content = {
            "type": "bar",
            "labels": ["A"],
            "datasets": [{"label": "X"}],   # 缺 "data"
        }
        block = {"type": "chart", "content": bad_content}
        chapter = self._chapter_with_blocks(
            {"type": "paragraph", "content": "Intro paragraph with enough characters here."},
            block,
        )
        _, errors = self.validator.validate_chapter(chapter)
        self.assertTrue(any("data" in e for e in errors), f"Expected data field error, got: {errors}")


# ─────────────────────────────────────────────────────────────────────────────
# 测试组 2：IRValidator — _fix_block 别名修复
# ─────────────────────────────────────────────────────────────────────────────
class TestValidatorChartFix(unittest.TestCase):

    def setUp(self):
        self.validator = IRValidator()

    def _fix(self, block):
        return self.validator._fix_block(block, 0)

    def test_fix_graph_alias(self):
        result = self._fix({"type": "graph", "content": VALID_CHART_CONTENT})
        self.assertEqual(result["type"], BlockType.CHART.value)

    def test_fix_visualization_alias(self):
        result = self._fix({"type": "visualization", "content": VALID_CHART_CONTENT})
        self.assertEqual(result["type"], BlockType.CHART.value)

    def test_fix_Chart_capitalized(self):
        result = self._fix({"type": "Chart", "content": VALID_CHART_CONTENT})
        self.assertEqual(result["type"], BlockType.CHART.value)

    def test_fix_non_dict_content_wrapped(self):
        """content 为字符串时应被包装成最小合法 chart dict"""
        result = self._fix({"type": "chart", "content": "Some plain text"})
        self.assertIsInstance(result["content"], dict)
        self.assertIn("type", result["content"])
        self.assertIn("datasets", result["content"])


# ─────────────────────────────────────────────────────────────────────────────
# 测试组 3：HTMLRenderer — chart/wordcloud 片段渲染
# ─────────────────────────────────────────────────────────────────────────────
class TestHTMLRendererChartFragment(unittest.TestCase):

    # ── _render_chart ──
    def test_render_chart_produces_canvas(self):
        block = _make_chart_block(VALID_CHART_CONTENT)
        html = _render_chart(block, chart_index=0)
        self.assertIn('<canvas', html)
        self.assertIn('__cassandraCharts', html)
        self.assertIn('report-chart-figure', html)

    def test_render_chart_embeds_correct_type(self):
        block = _make_chart_block(VALID_CHART_CONTENT)
        html = _render_chart(block, chart_index=0)
        config = json.loads(re.search(r'config: (\{.*?\})\}\);', html, re.DOTALL).group(1))
        self.assertEqual(config["type"], "bar")

    def test_render_chart_embeds_labels(self):
        block = _make_chart_block(VALID_CHART_CONTENT)
        html = _render_chart(block, chart_index=0)
        self.assertIn("Grade 1-2", html)
        self.assertIn("Grade 3", html)

    def test_render_chart_shows_title(self):
        block = _make_chart_block(VALID_CHART_CONTENT)
        html = _render_chart(block, chart_index=0)
        self.assertIn("chart-title", html)
        self.assertIn("不良事件发生率", html)

    def test_render_chart_shows_caption(self):
        block = _make_chart_block(VALID_CHART_CONTENT)
        html = _render_chart(block, chart_index=0)
        self.assertIn("chart-caption", html)
        self.assertIn("NCT03456789", html)

    def test_render_chart_bad_content_returns_error(self):
        block = ChapterBlock(type=BlockType.CHART, content="not a dict")
        html = _render_chart(block, chart_index=0)
        self.assertIn("chart-error", html)

    def test_render_pie_chart(self):
        block = _make_chart_block(VALID_PIE_CONTENT)
        html = _render_chart(block, chart_index=1)
        config = json.loads(re.search(r'config: (\{.*?\})\}\);', html, re.DOTALL).group(1))
        self.assertEqual(config["type"], "pie")

    def test_render_multiple_charts_unique_ids(self):
        block0 = _make_chart_block(VALID_CHART_CONTENT)
        block1 = _make_chart_block(VALID_LINE_CONTENT)
        html0 = _render_chart(block0, chart_index=0)
        html1 = _render_chart(block1, chart_index=1)
        id0 = re.search(r'id="(chart-\d+-\w+)"', html0).group(1)
        id1 = re.search(r'id="(chart-\d+-\w+)"', html1).group(1)
        self.assertNotEqual(id0, id1, "每个图表应该有唯一 ID")

    # ── _render_wordcloud ──
    def test_render_wordcloud_produces_canvas(self):
        block = _make_wordcloud_block()
        html = _render_wordcloud(block, wc_index=0)
        self.assertIn('<canvas', html)
        self.assertIn('__cassandraWordclouds', html)
        self.assertIn('report-wordcloud-figure', html)

    def test_render_wordcloud_embeds_words(self):
        block = _make_wordcloud_block()
        html = _render_wordcloud(block, wc_index=0)
        self.assertIn("hepatotoxicity", html)
        self.assertIn("nivolumab", html)


# ─────────────────────────────────────────────────────────────────────────────
# 测试组 4：完整 IRDocument → HTML 文档渲染
# ─────────────────────────────────────────────────────────────────────────────
class TestFullDocumentChartRendering(unittest.TestCase):

    def _build_doc(self) -> IRDocument:
        blocks = [
            ChapterBlock(type=BlockType.HEADING, content="安全性分析", level=2,
                         block_id="safety-analysis"),
            ChapterBlock(type=BlockType.PARAGRAPH,
                         content="以下图表展示临床试验中观察到的不良事件分布与趋势。"),
            _make_chart_block(VALID_CHART_CONTENT),
            ChapterBlock(type=BlockType.HEADING, content="入组趋势", level=3,
                         block_id="enrollment-trend"),
            _make_chart_block(VALID_LINE_CONTENT),
            ChapterBlock(type=BlockType.HEADING, content="终止原因", level=3,
                         block_id="termination-reasons"),
            _make_chart_block(VALID_PIE_CONTENT),
            _make_wordcloud_block(),
        ]
        chapter = Chapter(
            id="safety",
            title="安全性与风险分析",
            slug="safety",
            order=1,
            blocks=blocks,
            metadata={"target_words": 500},
        )
        return IRDocument(
            title="Cassandra 图表渲染测试报告",
            subtitle="Nivolumab 肝毒性深度分析",
            query="assess nivolumab hepatotoxicity",
            chapters=[chapter],
            metadata={
                "generated_at": "2026-03-04T22:00:00",
                "risk_score": "8.2/10",
            },
        )

    def test_full_document_renders_without_error(self):
        doc = self._build_doc()
        renderer = HTMLRenderer()
        result = renderer.render(doc)
        self.assertIsInstance(result, str)
        self.assertIn("<!DOCTYPE html>", result)

    def test_full_document_contains_chart_js_cdn(self):
        doc = self._build_doc()
        html = HTMLRenderer().render(doc)
        self.assertIn("chart.js", html.lower())

    def test_full_document_contains_three_charts(self):
        doc = self._build_doc()
        html = HTMLRenderer().render(doc)
        chart_pushes = re.findall(r'__cassandraCharts\.push', html)
        self.assertEqual(len(chart_pushes), 3, f"Expected 3 charts, got {len(chart_pushes)}")

    def test_full_document_contains_wordcloud(self):
        doc = self._build_doc()
        html = HTMLRenderer().render(doc)
        self.assertIn("__cassandraWordclouds", html)

    def test_full_document_contains_toc(self):
        doc = self._build_doc()
        html = HTMLRenderer().render(doc)
        self.assertIn("toc-container", html)

    def test_full_document_saved_for_visual_inspection(self):
        """将渲染结果写入 tests/output/chart_test.html 供浏览器人工检查"""
        doc = self._build_doc()
        html = HTMLRenderer().render(doc)
        out_dir = Path(__file__).parent / "output"
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / "chart_test.html"
        out_path.write_text(html, encoding="utf-8")
        self.assertTrue(out_path.exists())
        print(f"\n  📄 可视化报告已写入: {out_path}")

    def test_chart_init_script_present(self):
        doc = self._build_doc()
        html = HTMLRenderer().render(doc)
        self.assertIn("initCharts", html)
        self.assertIn("initWordclouds", html)


# ─────────────────────────────────────────────────────────────────────────────
# 测试组 5：ChapterBlock.from_dict 反序列化
# ─────────────────────────────────────────────────────────────────────────────
class TestChartBlockDeserialization(unittest.TestCase):

    def test_from_dict_chart_type(self):
        data = {"type": "chart", "content": VALID_CHART_CONTENT}
        block = ChapterBlock.from_dict(data)
        self.assertEqual(block.type, BlockType.CHART)
        self.assertEqual(block.content["type"], "bar")
        self.assertEqual(len(block.content["datasets"]), 1)

    def test_from_dict_chart_preserves_datasets(self):
        data = {"type": "chart", "content": VALID_LINE_CONTENT}
        block = ChapterBlock.from_dict(data)
        self.assertEqual(block.content["labels"][0], "2021-Q1")
        self.assertEqual(block.content["datasets"][0]["data"][3], 130)


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [
        TestValidatorChartBlock,
        TestValidatorChartFix,
        TestHTMLRendererChartFragment,
        TestFullDocumentChartRendering,
        TestChartBlockDeserialization,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
