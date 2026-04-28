from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run_workspace_script(body: str) -> subprocess.CompletedProcess[str]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required to execute workspace.js regressions")

    script = (
        _dom_harness()
        + "\n"
        + textwrap.indent(textwrap.dedent(body), "        ")
        + "\n        })().catch((error) => { console.error(error && error.stack || error); process.exit(1); });\n"
    )
    return subprocess.run(
        [node, "-e", script],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def test_workspace_js_rejects_non_absolute_web_source_urls():
    result = _run_workspace_script(
        r"""
        const unsafeUrls = [
          'javascript:alert(1)',
          'data:text/html,<h1>x</h1>',
          'file:///C:/secret.txt',
          'http://[',
          '/internal',
          'not a url',
          '',
          '   '
        ];

        for (const sourceUrl of unsafeUrls) {
          resetDocument();
          installWorkspace(makeWorkspace({
            panels: { selected_event_id: 'evt-1' },
            layers: [catalystLayerWithSourceUrl(sourceUrl)]
          }));
          runWorkspace();

          const details = document.querySelector('[data-panel="details"]');
          const links = details.children.filter((child) => child.tagName === 'A');
          if (links.length !== 0) {
            throw new Error('unsafe source_url produced a clickable link: ' + sourceUrl + ' -> ' + links[0].href);
          }
        }
        """
    )

    assert result.returncode == 0, result.stderr + result.stdout


def test_workspace_js_allows_absolute_web_source_url():
    result = _run_workspace_script(
        r"""
        const expected = 'https://clinicaltrials.gov/study/NCT00000001';
        installWorkspace(makeWorkspace({
          panels: { selected_event_id: 'evt-1' },
          layers: [catalystLayerWithSourceUrl(expected)]
        }));
        runWorkspace();

        const details = document.querySelector('[data-panel="details"]');
        const links = details.children.filter((child) => child.tagName === 'A');
        if (links.length !== 1) {
          throw new Error('valid absolute source_url did not produce exactly one link');
        }
        if (links[0].href !== expected) {
          throw new Error('valid source_url changed unexpectedly: ' + links[0].href);
        }
        """
    )

    assert result.returncode == 0, result.stderr + result.stdout


def test_workspace_js_range_context_ignores_stale_response():
    result = _run_workspace_script(
        r"""
        const deferred = [];
        fetch = function (url) {
          const request = makeDeferred();
          request.url = url;
          deferred.push(request);
          return request.promise;
        };

        installWorkspace(makeWorkspace());
        runWorkspace();

        chartConfigs[chartConfigs.length - 1].onRangeSelect({
          startDate: '2026-04-01',
          endDate: '2026-04-02'
        });
        chartConfigs[chartConfigs.length - 1].onRangeSelect({
          startDate: '2026-04-03',
          endDate: '2026-04-04'
        });

        deferred[1].resolve(jsonResponse({
          catalyst_count: 2,
          price_change_pct: 4.5
        }));
        await settle();
        deferred[0].resolve(jsonResponse({
          catalyst_count: 99,
          price_change_pct: -12.25
        }));
        await settle();

        const text = document.getElementById('range-context').textContent;
        if (!text.includes('2026-04-03 to 2026-04-04')) {
          throw new Error('latest range was not retained: ' + text);
        }
        if (text.includes('99 catalysts') || text.includes('2026-04-01')) {
          throw new Error('stale range response overwrote latest context: ' + text);
        }
        """
    )

    assert result.returncode == 0, result.stderr + result.stdout


def test_workspace_js_backtest_ignores_stale_response():
    result = _run_workspace_script(
        r"""
        const deferred = [];
        fetch = function (url) {
          const request = makeDeferred();
          request.url = url;
          deferred.push(request);
          return request.promise;
        };

        installWorkspace(makeWorkspace());
        runWorkspace();

        const form = document.getElementById('backtest-form');
        form.dispatchEvent({ type: 'submit', preventDefault() {} });
        form.dispatchEvent({ type: 'submit', preventDefault() {} });

        deferred[1].resolve(jsonResponse({
          run_id: 'run-B',
          metrics: { sharpe: 2.2 },
          equity_curve: [{ date: '2026-04-20', equity: 2 }],
          signals: [{ date: '2026-04-20', signal: 1, signal_strength: 1 }],
          trades: []
        }));
        await settle();
        deferred[0].resolve(jsonResponse({
          run_id: 'run-A',
          metrics: { sharpe: -1.5 },
          equity_curve: [{ date: '2026-04-20', equity: 1 }],
          signals: [],
          trades: []
        }));
        await settle();

        const status = document.getElementById('backtest-status').textContent;
        if (!status.includes('run-B')) {
          throw new Error('latest backtest status was not retained: ' + status);
        }
        if (status.includes('run-A')) {
          throw new Error('stale backtest response overwrote latest status: ' + status);
        }
        const latestConfig = chartConfigs[chartConfigs.length - 1];
        if (!latestConfig.equityCurve || latestConfig.equityCurve[0].equity !== 2) {
          throw new Error('stale backtest response overwrote chart overlays');
        }
        """
    )

    assert result.returncode == 0, result.stderr + result.stdout


def _dom_harness() -> str:
    return textwrap.dedent(
        r"""
        const fs = require('fs');
        const vm = require('vm');

        class ClassList {
          constructor() { this.values = new Set(); }
          add(...names) { names.forEach((name) => this.values.add(name)); }
          remove(...names) { names.forEach((name) => this.values.delete(name)); }
          toggle(name, force) {
            const next = force === undefined ? !this.values.has(name) : Boolean(force);
            if (next) this.values.add(name); else this.values.delete(name);
            return next;
          }
          contains(name) { return this.values.has(name); }
          toString() { return Array.from(this.values).join(' '); }
        }

        class Element {
          constructor(tagName, ownerDocument) {
            this.tagName = String(tagName || '').toUpperCase();
            this.ownerDocument = ownerDocument;
            this.children = [];
            this.parentNode = null;
            this.dataset = {};
            this.style = {};
            this.classList = new ClassList();
            this.eventListeners = {};
            this.attributes = {};
            this.hidden = false;
            this.disabled = false;
            this.value = '';
            this.name = '';
            this.type = '';
            this.href = '';
            this.target = '';
            this.rel = '';
            this._textContent = '';
            this._id = '';
          }
          set id(value) {
            this._id = String(value);
            if (this.ownerDocument) this.ownerDocument.byId.set(this._id, this);
          }
          get id() { return this._id; }
          set className(value) {
            this._className = String(value || '');
            this.classList = new ClassList();
            this._className.split(/\s+/).filter(Boolean).forEach((name) => this.classList.add(name));
          }
          get className() { return this._className || this.classList.toString(); }
          set textContent(value) {
            this._textContent = String(value ?? '');
            this.children = [];
          }
          get textContent() {
            return this._textContent + this.children.map((child) => child.textContent).join('');
          }
          setAttribute(name, value) {
            this.attributes[name] = String(value);
            if (name === 'id') this.id = value;
            if (name === 'class') this.className = value;
            if (name.startsWith('data-')) {
              const key = name.slice(5).replace(/-([a-z])/g, (_, char) => char.toUpperCase());
              this.dataset[key] = String(value);
            }
          }
          appendChild(child) {
            child.parentNode = this;
            this.children.push(child);
            return child;
          }
          append(...items) {
            items.forEach((item) => {
              this.appendChild(typeof item === 'string' ? this.ownerDocument.createTextNode(item) : item);
            });
          }
          replaceChildren(...items) {
            this.children = [];
            this._textContent = '';
            this.append(...items);
          }
          addEventListener(type, handler) {
            this.eventListeners[type] = this.eventListeners[type] || [];
            this.eventListeners[type].push(handler);
          }
          dispatchEvent(event) {
            event.currentTarget = this;
            (this.eventListeners[event.type] || []).forEach((handler) => handler(event));
          }
          querySelector(selector) {
            return this.querySelectorAll(selector)[0] || null;
          }
          querySelectorAll(selector) {
            return collect(this).filter((node) => matches(node, selector));
          }
          get elements() {
            const elements = {};
            collect(this).forEach((node) => {
              if (node.name) elements[node.name] = node;
            });
            return elements;
          }
        }

        class TextNode {
          constructor(value) {
            this.tagName = '#TEXT';
            this.children = [];
            this.textContent = String(value ?? '');
          }
        }

        function collect(root) {
          const nodes = [];
          function visit(node) {
            node.children.forEach((child) => {
              nodes.push(child);
              visit(child);
            });
          }
          visit(root);
          return nodes;
        }

        function matches(node, selector) {
          if (selector === '[data-tab]') return node.dataset && node.dataset.tab !== undefined;
          if (selector === '[data-panel]') return node.dataset && node.dataset.panel !== undefined;
          const dataPanel = selector.match(/^\[data-panel="([^"]+)"\]$/);
          if (dataPanel) return node.dataset && node.dataset.panel === dataPanel[1];
          if (selector.startsWith('#')) return node.id === selector.slice(1);
          return node.tagName === selector.toUpperCase();
        }

        class Document {
          constructor() {
            this.byId = new Map();
            this.body = new Element('body', this);
            this.listeners = {};
          }
          createElement(tagName) { return new Element(tagName, this); }
          createTextNode(value) { return new TextNode(value); }
          getElementById(id) { return this.byId.get(id) || null; }
          querySelector(selector) { return this.body.querySelector(selector); }
          querySelectorAll(selector) { return this.body.querySelectorAll(selector); }
          addEventListener(type, handler) {
            this.listeners[type] = this.listeners[type] || [];
            this.listeners[type].push(handler);
          }
          fire(type) {
            (this.listeners[type] || []).forEach((handler) => handler({ type }));
          }
        }

        const document = new Document();
        const window = {
          document,
          location: { href: 'https://example.test/kline/MRNA' },
          addEventListener() {},
        };
        const chartConfigs = [];
        window.PokieChart = {
          render(container, config) {
            chartConfigs.push(config);
            return function cleanup() {};
          }
        };
        global.document = document;
        global.window = window;
        global.fetch = undefined;

        function addNode(id, tagName = 'div') {
          const node = document.createElement(tagName);
          node.id = id;
          document.body.appendChild(node);
          return node;
        }

        function resetDocument() {
          document.byId = new Map();
          document.body = new Element('body', document);
          document.listeners = {};
          chartConfigs.length = 0;
        }

        function installWorkspace(workspace) {
          const script = addNode('kline-workspace-data', 'script');
          script.textContent = JSON.stringify(workspace);
          addNode('source-strip');
          addNode('company-name');
          addNode('last-close');
          addNode('coverage-range');
          addNode('hover-readout');
          addNode('layer-bar');
          addNode('kline-container');
          addNode('range-context');

          const tickerForm = addNode('ticker-form', 'form');
          const symbol = document.createElement('input');
          symbol.name = 'symbol';
          symbol.value = workspace.ticker || 'MRNA';
          tickerForm.appendChild(symbol);

          ['catalysts', 'details', 'backtest', 'status'].forEach((name) => {
            const tab = document.createElement('button');
            tab.dataset.tab = name;
            document.body.appendChild(tab);
            const panel = document.createElement('section');
            panel.dataset.panel = name;
            document.body.appendChild(panel);
          });
        }

        function catalystLayerWithSourceUrl(sourceUrl) {
          return {
            kind: 'catalysts',
            label: 'Catalysts',
            visible_by_default: true,
            points: [{
              id: 'evt-1',
              ticker: 'MRNA',
              date: '2026-04-20',
              type: 'clinical_readout',
              category: 'clinical',
              title: 'Source event',
              summary: 'Source link test.',
              sentiment: 'unknown',
              priority: 1,
              source: 'clinicaltrials',
              source_url: sourceUrl
            }]
          };
        }

        function makeWorkspace(overrides = {}) {
          return Object.assign({
            ticker: 'MRNA',
            company: { name: 'Moderna, Inc.', sector: 'Healthcare' },
            price: {
              rows: [{ date: '2026-04-20', open: 1, high: 2, low: 1, close: 2, volume: 100 }],
              date_range: { start: '2026-04-20', end: '2026-04-21' },
              last_close: 2
            },
            panels: {},
            layers: [{
              kind: 'catalysts',
              label: 'Catalysts',
              visible_by_default: true,
              points: []
            }],
            data_status: [],
            warnings: [],
            capabilities: []
          }, overrides);
        }

        function makeDeferred() {
          let resolve;
          let reject;
          const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
          return { promise, resolve, reject };
        }

        function jsonResponse(body, ok = true) {
          return { ok, json: () => Promise.resolve(body) };
        }

        async function settle() {
          await Promise.resolve();
          await Promise.resolve();
          await Promise.resolve();
        }

        function runWorkspace() {
          const code = fs.readFileSync('static/kline/workspace.js', 'utf8');
          const context = {
            console,
            document,
            window,
            fetch: (...args) => global.fetch(...args),
            URL,
            encodeURIComponent,
          };
          context.globalThis = context;
          vm.runInNewContext(code, context, { filename: 'workspace.js' });
          document.fire('DOMContentLoaded');
        }

        (async () => {
        """
    )
