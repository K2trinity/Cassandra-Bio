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
    result = _run_workspace_script(r"""
        const unsafeUrls = [
          'javascript:alert(1)',
          'data:text/html,<h1>x</h1>',
          'file:///C:/secret.txt',
          'http://[',
          'http:\\example.com',
          'http:/example.com',
          'https:example.com',
          'http:////example.com',
          String.raw`http://\\example.com`,
          String.raw`http://example.com\foo`,
          String.raw`https://example.com\@evil.com`,
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
        """)

    assert result.returncode == 0, result.stderr + result.stdout


def test_workspace_js_allows_absolute_web_source_url():
    result = _run_workspace_script(r"""
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
        """)

    assert result.returncode == 0, result.stderr + result.stdout


def test_workspace_js_fetches_workspace_without_auto_refresh_when_inline_payload_missing():
    result = _run_workspace_script(r"""
        const requests = [];
        installWorkspaceShell('MRNA');
        window.fetch = function (url) {
          requests.push(url);
          if (url === '/api/backtest/options?ticker=MRNA') {
            return Promise.resolve(jsonResponse({}));
          }
          if (url === '/api/kline/workspace/MRNA?refresh=1') {
            return Promise.resolve(jsonResponse(makeWorkspace({
              company: { name: 'Moderna refreshed', sector: 'Healthcare' },
              price: {
                rows: [{ date: '2026-04-21', open: 2, high: 3, low: 2, close: 3, volume: 200 }],
                date_range: { start: '2026-04-21', end: '2026-04-21' },
                last_close: 3
              }
            })));
          }
          return Promise.resolve(jsonResponse(makeWorkspace({
            company: { name: 'Moderna cached', sector: 'Healthcare' }
          })));
        };

        runWorkspace();
        await settle();
        await settle();
        await settle();

        if (requests[0] !== '/api/kline/workspace/MRNA') {
          throw new Error('expected first request to load workspace API, got ' + requests.join(','));
        }
        if (requests.includes('/api/kline/workspace/MRNA?refresh=1')) {
          throw new Error('workspace load should not auto-refresh heavy event payloads: ' + requests.join(','));
        }
        if (document.getElementById('company-name').textContent !== 'Moderna cached') {
          throw new Error('cached workspace was not retained after initial load');
        }
        if (chartConfigs.length !== 1) {
          throw new Error('expected one initial chart render, got ' + chartConfigs.length);
        }
        """)

    assert result.returncode == 0, result.stderr + result.stdout


def test_workspace_js_can_load_full_event_history_when_initial_points_are_limited():
    result = _run_workspace_script(r"""
        const requests = [];
        const workspace = makeWorkspace({
          layers: [{
            kind: 'catalysts',
            label: 'Catalysts',
            visible_by_default: true,
            summary: { count: 3, displayed_count: 1, truncated: true },
            points: [{
              id: 'evt-1',
              ticker: 'MRNA',
              date: '2026-04-20',
              type: 'trial_results_posted',
              category: 'clinical',
              title: 'Displayed event',
              summary: 'Initial point.',
              sentiment: 'positive',
              priority: 1,
              confidence: 'high',
              source: 'clinicaltrials'
            }]
          }]
        });
        installWorkspace(workspace);
        window.fetch = function (url) {
          requests.push(url);
          if (url === '/api/backtest/options?ticker=MRNA') {
            return Promise.resolve(jsonResponse({}));
          }
          if (url === '/api/kline/events/MRNA') {
            return Promise.resolve(jsonResponse([
              { id: 'evt-1', ticker: 'MRNA', date: '2026-04-20', type: 'trial_results_posted', category: 'clinical', title: 'Displayed event', summary: 'Initial point.', sentiment: 'positive', priority: 1, confidence: 'high', source: 'clinicaltrials' },
              { id: 'evt-2', ticker: 'MRNA', date: '2026-04-21', type: 'trial_status_change', category: 'clinical', title: 'Hidden event 2', summary: 'Loaded later.', sentiment: 'neutral', priority: 2, confidence: 'medium', source: 'clinicaltrials' },
              { id: 'evt-3', ticker: 'MRNA', date: '2026-04-22', type: 'trial_status_change', category: 'clinical', title: 'Hidden event 3', summary: 'Loaded later.', sentiment: 'neutral', priority: 2, confidence: 'medium', source: 'clinicaltrials' }
            ]));
          }
          throw new Error('unexpected request: ' + url);
        };

        runWorkspace();
        await settle();
        const catalysts = document.querySelector('[data-panel="catalysts"]');
        if (!catalysts.textContent.includes('Showing 1 of 3 events')) {
          throw new Error('missing truncated event notice: ' + catalysts.textContent);
        }
        const loadAllButton = document.querySelectorAll('button').find((button) => button.textContent.includes('Load all'));
        if (!loadAllButton) {
          throw new Error('missing load-all events control');
        }

        loadAllButton.dispatchEvent({ type: 'click' });
        await settle();
        await settle();

        if (!requests.includes('/api/kline/events/MRNA')) {
          throw new Error('full event endpoint was not requested: ' + requests.join(','));
        }
        if (!catalysts.textContent.includes('Hidden event 3')) {
          throw new Error('catalyst panel did not rerender with full events: ' + catalysts.textContent);
        }
        if (chartConfigs[chartConfigs.length - 1].events.length !== 3) {
          throw new Error('chart did not rerender with full event set');
        }
        """)

    assert result.returncode == 0, result.stderr + result.stdout


def test_workspace_js_fetches_backtest_options_for_current_ticker():
    result = _run_workspace_script(r"""
        const requests = [];
        window.fetch = function (url) {
          requests.push(url);
          return Promise.resolve(jsonResponse({ default_price_source: 'yfinance' }));
        };

        installWorkspace(makeWorkspace({ ticker: 'MRNA' }));
        runWorkspace();
        await settle();
        await settle();
        await settle();

        if (requests[0] !== '/api/backtest/options?ticker=MRNA') {
          throw new Error('expected ticker-aware options request, got ' + requests.join(','));
        }
        """)

    assert result.returncode == 0, result.stderr + result.stdout


def test_workspace_js_range_context_ignores_stale_response():
    result = _run_workspace_script(r"""
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
        """)

    assert result.returncode == 0, result.stderr + result.stdout


def test_workspace_js_backtest_ignores_stale_response():
    result = _run_workspace_script(r"""
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
        """)

    assert result.returncode == 0, result.stderr + result.stdout


def test_workspace_js_backtest_error_clears_previous_overlays():
    result = _run_workspace_script(r"""
        let callCount = 0;
        fetch = function () {
          callCount += 1;
          if (callCount === 1) {
            return Promise.resolve(jsonResponse({
              run_id: 'run-ok',
              metrics: { sharpe: 1.1 },
              equity_curve: [{ date: '2026-04-20', equity: 2 }],
              signals: [{ date: '2026-04-20', signal: 1, signal_strength: 1 }],
              trades: [{ entry_date: '2026-04-20', exit_date: '2026-04-20', pnl_pct: 0.04 }]
            }));
          }
          return Promise.resolve(jsonResponse({ error: 'Backtest unavailable.' }, false));
        };

        installWorkspace(makeWorkspace({
          layers: [{
            kind: 'catalysts',
            label: 'Catalysts',
            visible_by_default: true,
            points: []
          }, {
            kind: 'backtest',
            label: 'Backtest',
            visible_by_default: false,
            series: []
          }]
        }));
        runWorkspace();

        const form = document.getElementById('backtest-form');
        form.dispatchEvent({ type: 'submit', preventDefault() {} });
        await settle();

        let latestConfig = chartConfigs[chartConfigs.length - 1];
        if (!latestConfig.equityCurve || latestConfig.equityCurve.length !== 1) {
          throw new Error('successful backtest did not render overlays');
        }

        form.dispatchEvent({ type: 'submit', preventDefault() {} });
        await settle();

        const status = document.getElementById('backtest-status').textContent;
        if (!status.includes('Backtest unavailable')) {
          throw new Error('error status was not shown: ' + status);
        }

        latestConfig = chartConfigs[chartConfigs.length - 1];
        if ((latestConfig.equityCurve || []).length || (latestConfig.signals || []).length || (latestConfig.trades || []).length) {
          throw new Error('failed backtest left stale overlays visible');
        }

        const backtestButton = document.getElementById('layer-bar').children.find((child) => child.dataset.layerKind === 'backtest');
        if (!backtestButton || !backtestButton.disabled) {
          throw new Error('backtest layer button was not disabled after failed run');
        }
        """)

    assert result.returncode == 0, result.stderr + result.stdout


def test_workspace_js_backtest_panel_renders_single_and_universe_buttons_without_demo():
    result = _run_workspace_script(r"""
        installWorkspace(makeWorkspace());
        runWorkspace();

        const form = document.getElementById('backtest-form');
        const buttonText = form.children
          .filter((child) => child.tagName === 'BUTTON')
          .map((button) => button.textContent);

        if (!buttonText.includes('Run Backtest')) {
          throw new Error('single-ticker backtest button missing: ' + buttonText.join(','));
        }
        if (!buttonText.includes('Run Universe')) {
          throw new Error('universe backtest button missing: ' + buttonText.join(','));
        }
        const removedDemoLabel = ['Run', 'Demo', 'Universe'].join(' ');
        if (buttonText.includes(removedDemoLabel)) {
          throw new Error('demo universe backtest button should not render: ' + buttonText.join(','));
        }
        """)

    assert result.returncode == 0, result.stderr + result.stdout


def test_workspace_js_backtest_panel_has_chart_mode_control():
    result = _run_workspace_script(r"""
        installWorkspace(makeWorkspace());
        runWorkspace();

        const form = document.getElementById('backtest-form');
        const select = form.elements.chart_display_mode;
        if (!select) {
          throw new Error('chart_display_mode select missing');
        }
        if (select.tagName !== 'SELECT') {
          throw new Error('chart_display_mode is not a select: ' + select.tagName);
        }
        if (select.value !== 'candles_with_backtest') {
          throw new Error('chart_display_mode default mismatch: ' + select.value);
        }
        const optionValues = select.children.map((option) => option.value).join(',');
        if (optionValues !== 'candles_with_backtest,backtest_only,candles_only') {
          throw new Error('chart_display_mode options mismatch: ' + optionValues);
        }
        const latestConfig = chartConfigs[chartConfigs.length - 1];
        if (latestConfig.displayMode !== 'candles_with_backtest') {
          throw new Error('default displayMode was not passed to chart: ' + latestConfig.displayMode);
        }
        """)

    assert result.returncode == 0, result.stderr + result.stdout


def test_workspace_js_universe_uses_portfolio_snapshot_defaults():
    result = _run_workspace_script(r"""
        let requestBody = null;
        window.fetch = function (url, options) {
          if (url === '/api/backtest/options?ticker=MRNA') {
            return Promise.resolve(jsonResponse({
              default_price_source: 'yfinance',
              default_data_snapshot_id: 'snap_mrna_cache',
              snapshots: [{
                data_snapshot_id: 'snap_latest_tiingo',
                snapshot_date: '2026-05-10',
                price_source: 'tiingo',
                universe_id: 'biotech_us_v1',
                bias_profile: 'current_constituents_only'
              }, {
                data_snapshot_id: 'snap_old_tiingo',
                snapshot_date: '2026-05-09',
                price_source: 'tiingo',
                universe_id: 'biotech_us_v1',
                bias_profile: 'current_constituents_only'
              }, {
                data_snapshot_id: 'snap_mrna_cache',
                snapshot_date: '2026-05-07',
                price_source: 'yfinance',
                universe_id: 'biotech_four_v1',
                bias_profile: 'survivorship_biased'
              }],
              portfolio: {
                required_price_source: 'tiingo',
                default_price_source: 'tiingo',
                default_data_snapshot_id: 'snap_latest_tiingo'
              }
            }));
          }
          requestBody = JSON.parse(options.body);
          return Promise.resolve(jsonResponse({
            run_id: 'portfolio-run',
            portfolio_equity_curve: [{ date: '2026-04-20', equity: 1 }],
            portfolio_metrics: {},
            constituents: [],
            focus_ticker: { ticker: 'MRNA', signals: [], trades: [] }
          }));
        };
        global.fetch = window.fetch;

        installWorkspace(makeWorkspace({ ticker: 'MRNA' }));
        runWorkspace();
        await settle();
        await settle();
        await settle();

        const form = document.getElementById('backtest-form');
        if (form.elements.price_source.value !== 'yfinance') {
          throw new Error('single-ticker default should remain visible chart cache: ' + form.elements.price_source.value);
        }
        if (form.elements.data_snapshot_id.value !== 'snap_latest_tiingo') {
          throw new Error('portfolio default snapshot should drive universe runs: ' + form.elements.data_snapshot_id.value);
        }

        const universeButton = form.children.find((child) => child.tagName === 'BUTTON' && child.textContent === 'Run Universe');
        universeButton.dispatchEvent({ type: 'click', preventDefault() {} });
        await settle();

        if (requestBody.price_source !== 'tiingo') {
          throw new Error('portfolio request must use tiingo: ' + JSON.stringify(requestBody));
        }
        if (requestBody.data_snapshot_id !== 'snap_latest_tiingo') {
          throw new Error('portfolio request must use portfolio snapshot default: ' + JSON.stringify(requestBody));
        }
        """)

    assert result.returncode == 0, result.stderr + result.stdout


def test_workspace_js_snapshot_select_defaults_latest_universe_and_sends_user_choice():
    result = _run_workspace_script(r"""
        let requestBody = null;
        window.fetch = function (url, options) {
          if (url === '/api/backtest/options?ticker=MRNA') {
            return Promise.resolve(jsonResponse({
              default_price_source: 'yfinance',
              default_data_snapshot_id: 'snap_mrna_cache',
              snapshots: [{
                data_snapshot_id: 'snap_latest_tiingo',
                snapshot_date: '2026-05-10',
                price_source: 'tiingo',
                universe_id: 'biotech_us_v1',
                bias_profile: 'current_constituents_only'
              }, {
                data_snapshot_id: 'snap_user_tiingo',
                snapshot_date: '2026-05-09',
                price_source: 'tiingo',
                universe_id: 'biotech_research_v2',
                bias_profile: 'current_constituents_only'
              }, {
                data_snapshot_id: 'snap_mrna_cache',
                snapshot_date: '2026-05-07',
                price_source: 'yfinance',
                universe_id: 'biotech_four_v1',
                bias_profile: 'survivorship_biased'
              }],
              portfolio: {
                required_price_source: 'tiingo',
                default_price_source: 'tiingo',
                default_data_snapshot_id: 'snap_latest_tiingo',
                universe_id: 'biotech_us_v1'
              }
            }));
          }
          requestBody = JSON.parse(options.body);
          return Promise.resolve(jsonResponse({
            run_id: 'portfolio-run',
            portfolio_equity_curve: [{ date: '2026-04-20', equity: 1 }],
            portfolio_metrics: {},
            constituents: [],
            focus_ticker: { ticker: 'MRNA', signals: [], trades: [] }
          }));
        };
        global.fetch = window.fetch;

        installWorkspace(makeWorkspace({ ticker: 'MRNA' }));
        runWorkspace();
        await settle();
        await settle();
        await settle();

        const form = document.getElementById('backtest-form');
        const snapshotControl = form.elements.data_snapshot_id;
        if (!snapshotControl || snapshotControl.tagName !== 'SELECT') {
          throw new Error('data snapshot must be selectable');
        }
        if (snapshotControl.value !== 'snap_latest_tiingo') {
          throw new Error('latest portfolio snapshot should be selected by default: ' + snapshotControl.value);
        }
        const options = snapshotControl.children.map((option) => option.value).join(',');
        if (options !== 'snap_latest_tiingo,snap_user_tiingo') {
          throw new Error('snapshot options should list tiingo snapshots only: ' + options);
        }

        snapshotControl.value = 'snap_user_tiingo';
        snapshotControl.dispatchEvent({ type: 'change' });
        if (form.elements.universe_id.value !== 'biotech_research_v2') {
          throw new Error('universe id should follow selected snapshot: ' + form.elements.universe_id.value);
        }

        const universeButton = form.children.find((child) => child.tagName === 'BUTTON' && child.textContent === 'Run Universe');
        universeButton.dispatchEvent({ type: 'click', preventDefault() {} });
        await settle();

        if (requestBody.price_source !== 'tiingo') {
          throw new Error('portfolio request must use tiingo: ' + JSON.stringify(requestBody));
        }
        if (requestBody.data_snapshot_id !== 'snap_user_tiingo') {
          throw new Error('portfolio request should send user-selected snapshot: ' + JSON.stringify(requestBody));
        }
        if (requestBody.universe_id !== 'biotech_research_v2') {
          throw new Error('portfolio request should send selected snapshot universe: ' + JSON.stringify(requestBody));
        }
        """)

    assert result.returncode == 0, result.stderr + result.stdout



def test_workspace_js_strategy_builder_sends_editable_config():
    result = _run_workspace_script(r"""
        let requestBody = null;
        window.fetch = function (url, options) {
          if (url === '/api/backtest/options?ticker=MRNA') {
            return Promise.resolve(jsonResponse({
              default_price_source: 'tiingo',
              default_data_snapshot_id: 'snap_latest_tiingo',
              portfolio: {
                required_price_source: 'tiingo',
                default_price_source: 'tiingo',
                default_data_snapshot_id: 'snap_latest_tiingo'
              }
            }));
          }
          requestBody = JSON.parse(options.body);
          return Promise.resolve(jsonResponse({
            run_id: 'portfolio-run',
            portfolio_equity_curve: [{ date: '2026-04-20', equity: 1 }],
            portfolio_metrics: {},
            constituents: [],
            focus_ticker: { ticker: 'MRNA', signals: [], trades: [] }
          }));
        };
        global.fetch = window.fetch;

        installWorkspace(makeWorkspace({ ticker: 'MRNA' }));
        runWorkspace();
        await settle();
        await settle();
        await settle();

        const form = document.getElementById('backtest-form');
        [
          'strategy_weight_trend',
          'strategy_weight_momentum',
          'strategy_weight_liquidity',
          'strategy_weight_volatility',
          'strategy_weight_event',
          'strategy_window_fast',
          'strategy_window_slow',
          'strategy_threshold_long',
          'strategy_threshold_short'
        ].forEach((name) => {
          if (!form.elements[name]) {
            throw new Error('strategy builder control missing: ' + name);
          }
        });
        const formula = document.getElementById('strategy-formula-preview');
        if (!formula || !formula.textContent.includes('alpha =')) {
          throw new Error('strategy formula preview missing');
        }

        form.elements.strategy_weight_trend.value = '0.5';
        form.elements.strategy_weight_momentum.value = '0.25';
        form.elements.strategy_weight_liquidity.value = '0.1';
        form.elements.strategy_weight_volatility.value = '-0.2';
        form.elements.strategy_weight_event.value = '0.35';
        form.elements.strategy_window_fast.value = '10';
        form.elements.strategy_window_slow.value = '40';
        form.elements.strategy_window_momentum.value = '15';
        form.elements.strategy_window_volatility.value = '25';
        form.elements.strategy_window_volume.value = '30';
        form.elements.strategy_threshold_long.value = '0.2';
        form.elements.strategy_threshold_short.value = '-0.22';

        const universeButton = form.children.find((child) => child.tagName === 'BUTTON' && child.textContent === 'Run Universe');
        universeButton.dispatchEvent({ type: 'click', preventDefault() {} });
        await settle();

        if (!requestBody.strategy_config) {
          throw new Error('strategy_config missing from request: ' + JSON.stringify(requestBody));
        }
        if (requestBody.strategy_config.weights.trend !== 0.5 || requestBody.strategy_config.weights.event !== 0.35) {
          throw new Error('strategy weights not serialized: ' + JSON.stringify(requestBody.strategy_config));
        }
        if (requestBody.strategy_config.windows.fast !== 10 || requestBody.strategy_config.windows.slow !== 40) {
          throw new Error('strategy windows not serialized: ' + JSON.stringify(requestBody.strategy_config));
        }
        if (requestBody.strategy_config.thresholds.long !== 0.2 || requestBody.strategy_config.thresholds.short !== -0.22) {
          throw new Error('strategy thresholds not serialized: ' + JSON.stringify(requestBody.strategy_config));
        }
        """)

    assert result.returncode == 0, result.stderr + result.stdout


def test_workspace_js_backtest_only_mode_passes_display_mode_and_hides_events():
    result = _run_workspace_script(r"""
        installWorkspace(makeWorkspace({
          panels: { selected_event_id: 'evt-1' },
          layers: [{
            kind: 'catalysts',
            label: 'Catalysts',
            visible_by_default: true,
            points: [{ id: 'evt-1', date: '2026-04-20', type: 'trial_results_posted', category: 'clinical' }]
          }, {
            kind: 'backtest',
            label: 'Backtest',
            visible_by_default: true,
            series: [{ date: '2026-04-20', equity: 1.03 }],
            summary: {
              signals: [{ date: '2026-04-20', signal: 1, signal_strength: 0.8 }],
              trades: [{ entry_date: '2026-04-20', exit_date: '2026-04-21', pnl_pct: 0.04 }]
            }
          }]
        }));
        runWorkspace();

        const form = document.getElementById('backtest-form');
        form.elements.chart_display_mode.value = 'backtest_only';
        form.elements.chart_display_mode.dispatchEvent({ type: 'change' });

        const latestConfig = chartConfigs[chartConfigs.length - 1];
        if (latestConfig.displayMode !== 'backtest_only') {
          throw new Error('backtest_only displayMode was not passed to chart: ' + latestConfig.displayMode);
        }
        if ((latestConfig.events || []).length) {
          throw new Error('backtest_only mode should hide event markers');
        }
        if (latestConfig.highlightedEventId !== null) {
          throw new Error('backtest_only mode should hide highlighted event id: ' + latestConfig.highlightedEventId);
        }
        if (!latestConfig.equityCurve || latestConfig.equityCurve.length !== 1) {
          throw new Error('backtest_only mode should keep equity curve overlays');
        }
        if ((latestConfig.signals || []).length || (latestConfig.trades || []).length) {
          throw new Error('backtest_only mode should hide signal and trade overlays');
        }
        """)

    assert result.returncode == 0, result.stderr + result.stdout


def test_workspace_js_candles_only_mode_hides_backtest_overlays():
    result = _run_workspace_script(r"""
        installWorkspace(makeWorkspace({
          layers: [{
            kind: 'catalysts',
            label: 'Catalysts',
            visible_by_default: true,
            points: [{ id: 'evt-1', date: '2026-04-20', type: 'trial_results_posted', category: 'clinical' }]
          }, {
            kind: 'backtest',
            label: 'Backtest',
            visible_by_default: true,
            series: [{ date: '2026-04-20', equity: 1.03 }],
            summary: {
              signals: [{ date: '2026-04-20', signal: 1, signal_strength: 0.8 }],
              trades: [{ entry_date: '2026-04-20', exit_date: '2026-04-21', pnl_pct: 0.04 }]
            }
          }]
        }));
        runWorkspace();

        const form = document.getElementById('backtest-form');
        form.elements.chart_display_mode.value = 'candles_only';
        form.elements.chart_display_mode.dispatchEvent({ type: 'change' });

        const latestConfig = chartConfigs[chartConfigs.length - 1];
        if (latestConfig.displayMode !== 'candles_only') {
          throw new Error('candles_only displayMode was not passed to chart: ' + latestConfig.displayMode);
        }
        if (!latestConfig.events || latestConfig.events.length !== 1) {
          throw new Error('candles_only mode should keep event markers');
        }
        if ((latestConfig.equityCurve || []).length || (latestConfig.signals || []).length || (latestConfig.trades || []).length) {
          throw new Error('candles_only mode should hide backtest overlays');
        }
        """)

    assert result.returncode == 0, result.stderr + result.stdout


def test_workspace_js_universe_backtest_renders_portfolio_and_focus_overlays_without_disclosure():
    result = _run_workspace_script(r"""
        let requestUrl = null;
        let requestBody = null;
        fetch = function (url, options) {
          requestUrl = url;
          requestBody = JSON.parse(options.body);
          return Promise.resolve(jsonResponse({
            run_id: 'portfolio-run',
            portfolio_equity_curve: [
              { date: '2026-04-20', equity: 1.00 },
              { date: '2026-04-21', equity: 1.14 }
            ],
            portfolio_metrics: {
              strategy_return: 14.25,
              best_ticker: 'VRTX',
              worst_ticker: 'ALNY',
              total_trades: 9,
              avg_active_signal_days: 4.5,
              universe_id: 'internal-universe',
              data_mode: 'hidden'
            },
            constituents: [{
              ticker: 'MRNA',
              strategy_return: 12.5,
              active_signal_days: 5,
              trade_count: 3,
              metrics: { sharpe: 1.3 },
              baseline: { buy_hold_return: 2.1 },
              equity_curve: [
                { date: '2026-04-20', equity: 1.00 },
                { date: '2026-04-21', equity: 1.12 }
              ],
              factor_attribution: {
                active_factor_days: 3,
                mean_event_factor: 0.6,
                mean_liquidity_factor: 0.2,
                mean_mock_score: 0.9,
                synthetic: true
              }
            }, {
              ticker: 'ALNY',
              strategy_return: -1.2,
              active_signal_days: 1,
              trade_count: 0,
              equity_curve: [
                { date: '2026-04-20', equity: 1.00 },
                { date: '2026-04-21', equity: 0.98 }
              ]
            }],
            focus_ticker_status: {
              requested_ticker: 'MRNA',
              resolved_ticker: 'MRNA',
              available: true,
              reason: null
            },
            focus_ticker: {
              ticker: 'MRNA',
              equity_curve: [{ date: '2026-04-20', equity: 1.05 }],
              signals: [{ date: '2026-04-20', signal: 1, signal_strength: 0.8 }],
              trades: [{ entry_date: '2026-04-20', exit_date: '2026-04-21', pnl_pct: 0.04 }],
              metrics: { sharpe: 1.2 },
              baseline: { strategy_return: 12.5 },
              factor_attribution: {
                active_factor_days: 3,
                mean_event_factor: 0.6,
                mean_liquidity_factor: 0.2,
                data_mode: 'hidden',
                positive_demo_expected: true
              }
            },
            strategy: {
              id: 'internal-strategy',
              formula: 'alpha = 0.45 * trend(12,36) + 0.25 * event_score'
            },
            mock_metadata: {
              mock: true,
              synthetic: true,
              positive_demo_expected: true
            }
          }));
        };

        installWorkspace(makeWorkspace());
        runWorkspace();

        const form = document.getElementById('backtest-form');
        if (!form.elements.universe_id || form.elements.universe_id.value !== 'biotech_us_v1') {
          throw new Error('universe_id control missing or wrong default');
        }
        if (!form.elements.data_snapshot_id || form.elements.data_snapshot_id.value !== '') {
          throw new Error('data_snapshot_id control missing or should default blank');
        }
        form.elements.start_date.value = '2026-04-20';
        form.elements.end_date.value = '2026-04-21';
        form.elements.stop_loss_pct.value = '-0.07';
        form.elements.max_position_pct.value = '0.25';
        form.elements.slippage_pct.value = '0.002';
        form.elements.holding_period_days.value = '7';
        form.elements.price_source.value = 'tiingo';
        form.elements.data_snapshot_id.value = 'snap_20260507_tiingo';

        const universeButton = form.children.find((child) => child.tagName === 'BUTTON' && child.textContent === 'Run Universe');
        if (!universeButton) {
          throw new Error('universe button missing');
        }
        universeButton.dispatchEvent({ type: 'click', preventDefault() {} });
        await settle();

        if (requestUrl !== '/api/backtest/portfolio/run') {
          throw new Error('unexpected universe endpoint: ' + requestUrl);
        }
        if (requestBody.ticker !== 'MRNA' || requestBody.start_date !== '2026-04-20' || requestBody.stop_loss_pct !== -0.07 || requestBody.max_position_pct !== 0.25 || requestBody.slippage_pct !== 0.002 || requestBody.holding_period_days !== 7) {
          throw new Error('universe request did not preserve current form values: ' + JSON.stringify(requestBody));
        }
        if (requestBody.universe_id !== 'biotech_us_v1' || requestBody.data_snapshot_id !== 'snap_20260507_tiingo') {
          throw new Error('universe request did not preserve snapshot fields: ' + JSON.stringify(requestBody));
        }

        const latestConfig = chartConfigs[chartConfigs.length - 1];
        if (!latestConfig.equityCurve || latestConfig.equityCurve.length !== 2 || latestConfig.equityCurve[1].equity !== 1.14) {
          throw new Error('chart did not use portfolio equity curve');
        }
        if (!latestConfig.signals || latestConfig.signals.length !== 1 || latestConfig.signals[0].signal_strength !== 0.8) {
          throw new Error('chart did not use focus ticker signals');
        }
        if (!latestConfig.trades || latestConfig.trades.length !== 1 || latestConfig.trades[0].pnl_pct !== 0.04) {
          throw new Error('chart did not use focus ticker trades');
        }

        const text = document.getElementById('backtest-results').textContent;
        ['Strategy Formula', 'alpha = 0.45 * trend(12,36)', 'strategy_return', '14.25', 'best_ticker', 'VRTX', 'worst_ticker', 'ALNY', 'total_trades', '9', 'MRNA', '12.5', 'trade_count', 'active_factor_days', 'mean_event_factor'].forEach((expected) => {
          if (!text.includes(expected)) {
            throw new Error('portfolio diagnostics missing ' + expected + ': ' + text);
          }
        });
        if (document.getElementById('backtest-results').querySelectorAll('svg').length < 2) {
          throw new Error('portfolio constituent equity curves were not rendered');
        }

        const lowerText = text.toLowerCase();
        ['mock', 'synthetic', 'data_mode', 'positive_demo_expected', 'universe_id', 'internal-strategy'].forEach((forbidden) => {
          if (lowerText.includes(forbidden.toLowerCase())) {
            throw new Error('forbidden disclosure leaked into portfolio diagnostics: ' + forbidden + ' in ' + text);
          }
        });
        """)

    assert result.returncode == 0, result.stderr + result.stdout


def test_workspace_js_universe_backtest_results_use_spaced_portfolio_layout():
    result = _run_workspace_script(r"""
        function byClass(root, className) {
          const found = [];
          function visit(node) {
            if (node.classList && node.classList.contains(className)) {
              found.push(node);
            }
            (node.children || []).forEach(visit);
          }
          visit(root);
          return found;
        }

        function mockFetch(url, options) {
          if (!options || options.method !== 'POST') {
            return Promise.resolve(jsonResponse({
              default_price_source: 'tiingo',
              snapshots: [{
                data_snapshot_id: 'snap_layout',
                price_source: 'tiingo',
                universe_id: 'biotech_us_v1',
                snapshot_date: '2026-05-10'
              }],
              portfolio: {
                required_price_source: 'tiingo',
                default_price_source: 'tiingo',
                default_data_snapshot_id: 'snap_layout',
                universe_id: 'biotech_us_v1'
              }
            }));
          }
          return Promise.resolve(jsonResponse({
            run_id: 'portfolio-layout-run',
            portfolio_equity_curve: [
              { date: '2026-04-20', equity: 1.00 },
              { date: '2026-04-21', equity: 1.08 }
            ],
            portfolio_metrics: {
              strategy_return: 8.1,
              best_ticker: 'MRNA',
              worst_ticker: 'ALNY',
              total_trades: 4,
              avg_active_signal_days: 3,
              avg_exposure_days: 5
            },
            constituents: [{
              ticker: 'MRNA',
              strategy_return: 8.1,
              active_signal_days: 3,
              trade_count: 2,
              exposure_summary: { exposure_days: 5 },
              equity_curve: [
                { date: '2026-04-20', equity: 1.00 },
                { date: '2026-04-21', equity: 1.08 }
              ]
            }, {
              ticker: 'ALNY',
              strategy_return: -1.4,
              active_signal_days: 1,
              trade_count: 0,
              exposure_summary: { exposure_days: 1 },
              equity_curve: [
                { date: '2026-04-20', equity: 1.00 },
                { date: '2026-04-21', equity: 0.99 }
              ]
            }],
            focus_ticker_status: {
              requested_ticker: 'VRTX',
              resolved_ticker: 'MRNA',
              available: false
            },
            focus_ticker: {
              ticker: 'MRNA',
              signals: [],
              trades: [],
              factor_attribution: {
                active_factor_days: 3,
                mean_event_factor: 0.42,
                mean_liquidity_factor: 0.18
              }
            },
            strategy: {
              formula: 'alpha = 0.45 * trend(12,36) + 0.35 * momentum(20)'
            }
          }));
        }
        fetch = mockFetch;
        window.fetch = mockFetch;

        installWorkspace(makeWorkspace());
        runWorkspace();
        await settle();
        await settle();

        const form = document.getElementById('backtest-form');
        form.elements.price_source.value = 'tiingo';
        form.elements.data_snapshot_id.value = 'snap_layout';
        const universeButton = form.children.find((child) => child.tagName === 'BUTTON' && child.textContent === 'Run Universe');
        universeButton.dispatchEvent({ type: 'click', preventDefault() {} });
        await settle();
        await settle();

        const results = document.getElementById('backtest-results');
        const layout = byClass(results, 'portfolio-results')[0];
        if (!layout) {
          throw new Error('portfolio results should render inside a dedicated layout container');
        }
        const overview = byClass(layout, 'portfolio-overview')[0];
        const grid = byClass(layout, 'portfolio-results-grid')[0];
        if (!overview || !grid) {
          throw new Error('portfolio layout should split overview and detail grid regions');
        }
        const summary = byClass(layout, 'portfolio-summary')[0];
        const strategy = byClass(layout, 'portfolio-strategy')[0];
        const leaderboard = byClass(layout, 'portfolio-leaderboard')[0];
        const focus = byClass(layout, 'portfolio-focus')[0];
        if (!summary || summary.parentNode !== overview || !strategy || strategy.parentNode !== overview) {
          throw new Error('strategy and summary should live in the overview region');
        }
        if (!leaderboard || leaderboard.parentNode !== grid || !focus || focus.parentNode !== grid) {
          throw new Error('constituents and focus diagnostics should be separated in the detail grid');
        }

        const rows = byClass(leaderboard, 'portfolio-row');
        if (rows.length !== 2) {
          throw new Error('expected one separated row per constituent');
        }
        const firstRow = rows[0];
        if (!byClass(firstRow, 'portfolio-row-symbol')[0] || !byClass(firstRow, 'portfolio-row-chart')[0] || !byClass(firstRow, 'portfolio-row-metrics')[0]) {
          throw new Error('constituent row should split symbol, chart, and metrics columns');
        }
        if (byClass(firstRow, 'portfolio-row-metric').length < 4) {
          throw new Error('constituent row metrics should render as individual metric cells');
        }
        if (byClass(firstRow, 'portfolio-row-chart')[0].querySelectorAll('svg').length !== 1) {
          throw new Error('constituent sparkline should stay in the chart column');
        }
        if (!focus.textContent.includes('Focus Ticker') || !focus.textContent.includes('mean_event_factor')) {
          throw new Error('focus ticker diagnostics should have a dedicated readable panel: ' + focus.textContent);
        }
        """)

    assert result.returncode == 0, result.stderr + result.stdout


def test_workspace_js_single_backtest_preserves_snapshot_fields_when_populated():
    result = _run_workspace_script(r"""
        let requestUrl = null;
        let requestBody = null;
        fetch = function (url, options) {
          requestUrl = url;
          requestBody = JSON.parse(options.body);
          return Promise.resolve(jsonResponse({
            run_id: 'single-run',
            metrics: {},
            equity_curve: [],
            signals: [],
            trades: []
          }));
        };

        installWorkspace(makeWorkspace());
        runWorkspace();

        const form = document.getElementById('backtest-form');
        form.elements.universe_id.value = 'biotech_custom_v2';
        form.elements.price_source.value = 'tiingo';
        form.elements.data_snapshot_id.value = 'snap_custom_123';
        form.dispatchEvent({ type: 'submit', preventDefault() {} });
        await settle();

        if (requestUrl !== '/api/backtest/run') {
          throw new Error('unexpected single endpoint: ' + requestUrl);
        }
        if (requestBody.universe_id !== 'biotech_custom_v2' || requestBody.data_snapshot_id !== 'snap_custom_123') {
          throw new Error('single request did not preserve snapshot fields: ' + JSON.stringify(requestBody));
        }
        """)

    assert result.returncode == 0, result.stderr + result.stdout


def test_workspace_js_backtest_layer_button_toggles_overlays():
    result = _run_workspace_script(r"""
        fetch = function () {
          return Promise.resolve(jsonResponse({
            run_id: 'run-C',
            metrics: { sharpe: 1.1 },
            equity_curve: [{ date: '2026-04-20', equity: 2 }],
            signals: [{ date: '2026-04-20', signal: 1, signal_strength: 1 }],
            trades: [{ entry_date: '2026-04-20', exit_date: '2026-04-20', pnl_pct: 0.04 }]
          }));
        };

        installWorkspace(makeWorkspace({
          layers: [{
            kind: 'catalysts',
            label: 'Catalysts',
            visible_by_default: true,
            points: []
          }, {
            kind: 'backtest',
            label: 'Backtest',
            visible_by_default: false,
            series: []
          }]
        }));
        runWorkspace();

        const form = document.getElementById('backtest-form');
        form.dispatchEvent({ type: 'submit', preventDefault() {} });
        await settle();

        let latestConfig = chartConfigs[chartConfigs.length - 1];
        if (!latestConfig.equityCurve || latestConfig.equityCurve.length !== 1) {
          throw new Error('backtest run did not enable chart overlays');
        }

        const layerBar = document.getElementById('layer-bar');
        const backtestButton = layerBar.children.find((child) => child.dataset.layerKind === 'backtest');
        if (!backtestButton) {
          throw new Error('backtest layer button was not rendered');
        }
        if (backtestButton.disabled) {
          throw new Error('backtest layer button stayed disabled after overlays loaded');
        }

        backtestButton.dispatchEvent({ type: 'click' });
        latestConfig = chartConfigs[chartConfigs.length - 1];
        if ((latestConfig.equityCurve || []).length || (latestConfig.signals || []).length || (latestConfig.trades || []).length) {
          throw new Error('backtest layer button did not hide overlays');
        }

        backtestButton.dispatchEvent({ type: 'click' });
        latestConfig = chartConfigs[chartConfigs.length - 1];
        if (!latestConfig.equityCurve || latestConfig.equityCurve.length !== 1) {
          throw new Error('backtest layer button did not restore overlays');
        }
        """)

    assert result.returncode == 0, result.stderr + result.stdout


def test_workspace_js_combines_active_event_layers_and_toggles_news_layer():
    result = _run_workspace_script(r"""
        installWorkspace(makeWorkspace({
          layers: [{
            kind: 'catalysts',
            label: 'Catalysts',
            visible_by_default: true,
            points: [{ id: 'clinical-1', date: '2026-04-20', type: 'trial_results_posted', category: 'clinical', priority: 1, sentiment: 'positive' }]
          }, {
            kind: 'news',
            label: 'News',
            visible_by_default: true,
            points: [{ id: 'news-1', date: '2026-04-20', type: 'market_news', category: 'news', priority: 3, sentiment: 'positive' }]
          }, {
            kind: 'macro',
            label: 'Macro',
            visible_by_default: false,
            points: [{ id: 'macro-1', date: '2026-04-20', type: 'macro_economic', category: 'macro', priority: 3, sentiment: 'neutral' }]
          }]
        }));
        runWorkspace();

        let latestConfig = chartConfigs[chartConfigs.length - 1];
        if (latestConfig.events.map((event) => event.id).join(',') !== 'clinical-1,news-1') {
          throw new Error('expected active catalyst and news events, got ' + latestConfig.events.map((event) => event.id).join(','));
        }

        const layerBar = document.getElementById('layer-bar');
        const newsButton = layerBar.children.find((child) => child.dataset.layerKind === 'news');
        if (!newsButton) {
          throw new Error('news layer button was not rendered');
        }
        newsButton.dispatchEvent({ type: 'click' });

        latestConfig = chartConfigs[chartConfigs.length - 1];
        if (latestConfig.events.map((event) => event.id).join(',') !== 'clinical-1') {
          throw new Error('news toggle did not remove news events');
        }
        """)

    assert result.returncode == 0, result.stderr + result.stdout


def test_workspace_js_backtest_renders_phase2_diagnostics():
    result = _run_workspace_script(r"""
        fetch = function () {
          return Promise.resolve(jsonResponse({
            run_id: 'phase2-run',
            metrics: { sharpe: 1.1 },
            equity_curve: [],
            signals: [],
            trades: [],
            event_filter: { input_events: 4, eligible_events: 2, excluded_events: 2, min_confidence_score: 0.7 },
            signal_summary: { active_signal_days: 1, long_signal_days: 1, short_signal_days: 0, mean_signal_strength: 0.25 },
            baseline: { buy_hold_return: 0.1, strategy_return: 0.03, excess_return: -0.07 }
          }));
        };

        installWorkspace(makeWorkspace());
        runWorkspace();

        const form = document.getElementById('backtest-form');
        form.dispatchEvent({ type: 'submit', preventDefault() {} });
        await settle();

        const text = document.getElementById('backtest-results').textContent;
        if (!text.includes('eligible_events') || !text.includes('buy_hold_return')) {
          throw new Error('phase2 diagnostics were not rendered: ' + text);
        }
        """)

    assert result.returncode == 0, result.stderr + result.stdout


def test_workspace_js_saved_backtest_renders_exposure_risk_and_strategy_diagnostics():
    result = _run_workspace_script(r"""
        installWorkspace(makeWorkspace({
          layers: [{
            kind: 'backtest',
            label: 'Backtest',
            visible_by_default: false,
            series: [{ date: '2026-04-20', equity: 1.03 }],
            summary: {
              run_id: 'saved-run',
              metrics: { sharpe: 1.1 },
              strategy: {
                price_basis: 'visible_ohlc',
                holding_period_days: 5,
                id: 'multifactor_score',
                data_mode: 'real'
              },
              exposure_summary: { exposure_days: 12, trade_count: 3 },
              risk_parameters: {
                stop_loss_pct: -0.08,
                max_position_pct: 0.2,
                slippage_pct: 0.001,
                holding_period_days: 5
              }
            }
          }]
        }));
        runWorkspace();

        const text = document.getElementById('backtest-results').textContent;
        ['strategy', 'price_basis', 'visible_ohlc', 'exposure_summary', 'exposure_days', 'risk_parameters', 'stop_loss_pct'].forEach((expected) => {
          if (!text.includes(expected)) {
            throw new Error('saved backtest diagnostics missing ' + expected + ': ' + text);
          }
        });
        const lowerText = text.toLowerCase();
        ['data_mode', 'multifactor_score'].forEach((forbidden) => {
          if (lowerText.includes(forbidden)) {
            throw new Error('internal strategy field leaked into saved diagnostics: ' + forbidden + ' in ' + text);
          }
        });
        """)

    assert result.returncode == 0, result.stderr + result.stdout


def test_workspace_js_backtest_renders_event_attribution():
    result = _run_workspace_script(r"""
        fetch = function () {
          return Promise.resolve(jsonResponse({
            run_id: 'phase2-run',
            metrics: { sharpe: 1.1 },
            equity_curve: [],
            signals: [],
            trades: [],
            event_attribution: {
              by_source: [{ source: 'clinicaltrials', count: 2 }],
              by_category: [{ category: 'clinical', count: 2 }],
              by_type: [{ type: 'trial_results_posted', count: 1 }]
            }
          }));
        };

        installWorkspace(makeWorkspace());
        runWorkspace();

        const form = document.getElementById('backtest-form');
        form.dispatchEvent({ type: 'submit', preventDefault() {} });
        await settle();

        const text = document.getElementById('backtest-results').textContent;
        if (!text.includes('event_attribution') || !text.includes('clinicaltrials') || !text.includes('trial_results_posted')) {
          throw new Error('event attribution diagnostics were not rendered: ' + text);
        }
        """)

    assert result.returncode == 0, result.stderr + result.stdout


def test_workspace_js_backtest_renders_factor_attribution_without_mock_disclosure():
    result = _run_workspace_script(r"""
        fetch = function () {
          return Promise.resolve(jsonResponse({
            run_id: 'factor-run',
            metrics: { sharpe: 1.1 },
            equity_curve: [],
            signals: [],
            trades: [],
            factor_attribution: {
              active_factor_days: 3,
              mean_mock_score: 0.4,
              mean_event_factor: 0.7,
              mean_liquidity_factor: 0.2
            },
            mock_metadata: {
              data_mode: 'mock',
              synthetic: true,
              positive_demo_expected: true
            },
            strategy: {
              id: 'mock_multifactor_demo',
              data_mode: 'mock',
              price_basis: 'demo_ohlc'
            }
          }));
        };

        installWorkspace(makeWorkspace());
        runWorkspace();

        const form = document.getElementById('backtest-form');
        form.dispatchEvent({ type: 'submit', preventDefault() {} });
        await settle();

        const text = document.getElementById('backtest-results').textContent;
        if (!text.includes('factor_attribution') || !text.includes('active_factor_days') || !text.includes('mean_event_factor') || !text.includes('mean_liquidity_factor')) {
          throw new Error('factor attribution diagnostics were not rendered: ' + text);
        }
        if (!text.includes('price_basis') || !text.includes('demo_ohlc')) {
          throw new Error('strategy price basis was not rendered: ' + text);
        }

        const lowerText = text.toLowerCase();
        ['mock', 'synthetic', 'positive_demo_expected', 'data_mode'].forEach((forbidden) => {
          if (lowerText.includes(forbidden)) {
            throw new Error('mock disclosure leaked into diagnostics: ' + forbidden + ' in ' + text);
          }
        });
        """)

    assert result.returncode == 0, result.stderr + result.stdout


def test_workspace_js_details_renders_phase2_event_metadata():
    result = _run_workspace_script(r"""
        installWorkspace(makeWorkspace({
          panels: { selected_event_id: 'evt-1' },
          layers: [{
            kind: 'catalysts',
            label: 'Catalysts',
            visible_by_default: true,
            points: [{
              id: 'evt-1',
              date: '2026-04-20',
              type: 'trial_results_posted',
              category: 'clinical',
              priority: 1,
              sentiment: 'positive',
              confidence: 'high',
              source: 'clinicaltrials',
              source_tier: 'official',
              confidence_score: 0.92,
              backtest_eligible: true,
              metadata: { impact_score: 0.88 }
            }]
          }]
        }));
        runWorkspace();

        const text = document.querySelector('[data-panel="details"]').textContent;
        if (!text.includes('Source tier') || !text.includes('official') || !text.includes('Confidence score') || !text.includes('0.92') || !text.includes('Backtest eligible') || !text.includes('true')) {
          throw new Error('phase2 event metadata missing from details: ' + text);
        }
        """)

    assert result.returncode == 0, result.stderr + result.stdout


def test_workspace_js_labels_report_derived_events_without_rewriting_source():
    result = _run_workspace_script(r"""
        const workspace = makeWorkspace({
          panels: { selected_event_id: 'evt-report-1' },
          layers: [{
            kind: 'catalysts',
            label: 'Catalysts',
            visible_by_default: true,
            points: [{
              id: 'evt-report-1',
              date: '2026-04-20',
              type: 'trial_results_posted',
              category: 'clinical',
              title: 'Report bridge event',
              priority: 1,
              sentiment: 'positive',
              confidence: 'high',
              source: 'clinicaltrials',
              metadata: {
                report_bridge: true,
                report_company_name: 'Eli Lilly and Company',
                report_path: '/tmp/report.md'
              }
            }]
          }]
        });
        installWorkspace(workspace);
        runWorkspace();

        if (workspace.layers[0].points[0].source !== 'clinicaltrials') {
          throw new Error('source was rewritten: ' + workspace.layers[0].points[0].source);
        }
        if (workspace.layers[0].points[0].category !== 'clinical') {
          throw new Error('category was rewritten: ' + workspace.layers[0].points[0].category);
        }

        const catalystText = document.querySelector('[data-panel="catalysts"]').textContent;
        if (!catalystText.includes('Report')) {
          throw new Error('report badge missing from catalyst card: ' + catalystText);
        }
        if (!catalystText.includes('clinicaltrials · from report')) {
          throw new Error('report source label missing from catalyst card: ' + catalystText);
        }

        const detailsText = document.querySelector('[data-panel="details"]').textContent;
        ['Origin', 'Report', 'Report company', 'Eli Lilly and Company', 'Report path', '/tmp/report.md'].forEach((expected) => {
          if (!detailsText.includes(expected)) {
            throw new Error('report origin detail missing ' + expected + ' from ' + detailsText);
          }
        });
        """)

    assert result.returncode == 0, result.stderr + result.stdout


def _dom_harness() -> str:
    return textwrap.dedent(r"""
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

        function installWorkspaceShell(ticker = 'MRNA') {
          const root = addNode('kline-workspace', 'main');
          root.dataset.ticker = ticker;
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
          symbol.value = ticker;
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

        function installWorkspace(workspace) {
          const script = addNode('kline-workspace-data', 'script');
          script.textContent = JSON.stringify(workspace);
          installWorkspaceShell(workspace.ticker || 'MRNA');
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
        """)
