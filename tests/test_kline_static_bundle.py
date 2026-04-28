from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


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
