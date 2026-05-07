from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


def test_kline_chart_equity_axis_uses_return_percent_formatter():
    repo_root = Path(__file__).resolve().parents[1]
    source = (repo_root / "src/kline/chart/CandlestickChart.tsx").read_text()
    bundle = (repo_root / "static/vendor/pokie-chart.umd.js").read_text()

    assert "formatEquityReturnTick" in source
    assert "equityReturnDomain" in source
    assert "baseEquity" in source
    assert "+0.0%" in source
    assert "+0.0%" in bundle


def test_kline_chart_invalid_equity_base_does_not_abort_chart_draw():
    repo_root = Path(__file__).resolve().parents[1]
    source = (repo_root / "src/kline/chart/CandlestickChart.tsx").read_text()

    assert "if (Number.isFinite(baseEquity) && baseEquity !== 0)" in source
    assert "baseEquity === 0) return" not in source


def test_kline_chart_exposes_day_week_month_timeframe_controls():
    repo_root = Path(__file__).resolve().parents[1]
    source = (repo_root / "src/kline/chart/CandlestickChart.tsx").read_text()
    bundle = (repo_root / "static/vendor/pokie-chart.umd.js").read_text()
    css = (repo_root / "static/vendor/pokie-chart.css").read_text()

    assert "KLINE_TIMEFRAME_OPTIONS" in source
    assert "aggregateOhlcForTimeframe" in source
    assert "mapOverlayDateToTimeframe" in source
    assert "kline-timeframe-control" in source
    assert "kline-timeframe-control" in bundle
    assert "kline-timeframe-control" in css
    for label in ["Day", "Week", "Month"]:
        assert label in source
        assert label in bundle


def test_static_kline_bundle_registers_without_node_process_global():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required to smoke-test the browser UMD bundle")

    script = textwrap.dedent(
        r"""
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('static/vendor/pokie-chart.umd.js', 'utf8');
        const context = {
          console: { log() {}, info() {}, warn() {}, error() {} },
          setTimeout,
          clearTimeout,
          setInterval,
          clearInterval,
          queueMicrotask,
          requestAnimationFrame(callback) { return setTimeout(callback, 16); },
          cancelAnimationFrame(handle) { clearTimeout(handle); },
          navigator: { userAgent: 'node-vm-browser-smoke' },
          document: {
            createElement() { return { style: {}, setAttribute() {}, appendChild() {} }; },
            createElementNS() { return { style: {}, setAttribute() {}, appendChild() {} }; },
            addEventListener() {},
            removeEventListener() {},
          },
        };
        context.window = context;
        context.self = context;
        context.globalThis = context;
        delete context.process;

        vm.runInNewContext(code, context, { filename: 'pokie-chart.umd.js' });

        if (!context.PokieChart || typeof context.PokieChart.render !== 'function') {
          throw new Error('PokieChart.render was not registered');
        }
        """
    )

    result = subprocess.run(
        [node, "-e", script],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
