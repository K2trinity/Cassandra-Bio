(function () {
  "use strict";

  var rangeContextRequestId = 0;
  var refreshRequestId = 0;
  var activeState = null;
  var EVENT_LAYER_KINDS = ["catalysts", "news", "macro"];
  var CHART_DISPLAY_MODES = [
    ["candles_with_backtest", "Candles + Backtest"],
    ["backtest_only", "Backtest Only"],
    ["candles_only", "Candles Only"]
  ];
  var BACKTEST_STRATEGY_OPTIONS = [
    ["multifactor_score", "Multifactor Score"],
    ["event_baseline", "Event Baseline"]
  ];
  var BACKTEST_PRICE_SOURCE_OPTIONS = [
    ["yfinance", "Visible Chart Cache"],
    ["tiingo", "Research Snapshot"]
  ];
  var DEFAULT_STRATEGY_CONFIG = {
    weights: {
      trend: 0.45,
      momentum: 0.35,
      liquidity: 0.15,
      volatility: -0.15,
      event: 0.25
    },
    windows: {
      fast: 12,
      slow: 36,
      momentum: 20,
      volatility: 20,
      volume: 20
    },
    thresholds: {
      long: 0.18,
      short: -0.18
    }
  };

  function byId(id) {
    return document.getElementById(id);
  }

  function readWorkspace() {
    var node = byId("kline-workspace-data");
    if (!node) {
      return null;
    }
    try {
      return JSON.parse(node.textContent || "{}");
    } catch (error) {
      return null;
    }
  }

  function readWorkspaceTicker() {
    var root = byId("kline-workspace");
    var ticker = root && root.dataset && root.dataset.ticker;
    return ticker ? String(ticker).trim().toUpperCase() : null;
  }

  function browserFetch() {
    if (window.fetch && typeof window.fetch === "function") {
      return window.fetch.bind(window);
    }
    if (typeof fetch === "function") {
      return fetch;
    }
    return null;
  }

  function workspaceApiUrl(ticker, refresh) {
    var url = "/api/kline/workspace/" + encodeURIComponent(ticker);
    return refresh ? url + "?refresh=1" : url;
  }

  function fetchWorkspace(ticker, options) {
    options = options || {};
    var request = browserFetch();
    if (!request) {
      return Promise.reject(new Error("workspace fetch unavailable"));
    }
    return request(workspaceApiUrl(ticker, options.refresh)).then(function (response) {
      return response.json().then(function (body) {
        return { ok: response.ok, body: body };
      });
    }).then(function (result) {
      if (!result.ok) {
        throw new Error((result.body && result.body.error) || "Workspace unavailable.");
      }
      return result.body;
    });
  }

  function catalystLayer(workspace) {
    return (workspace.layers || []).find(function (layer) {
      return layer.kind === "catalysts";
    }) || { points: [] };
  }

  function isEventLayerKind(kind) {
    return EVENT_LAYER_KINDS.indexOf(kind) !== -1;
  }

  function eventLayers(workspace) {
    return (workspace.layers || []).filter(function (layer) {
      return isEventLayerKind(layer.kind);
    });
  }

  function allEvents(workspace) {
    var events = [];
    eventLayers(workspace).forEach(function (layer) {
      events = events.concat(layer.points || []);
    });
    return events;
  }

  function activeEvents(workspace, state) {
    var events = [];
    eventLayers(workspace).forEach(function (layer) {
      if (state.visibleEventLayers && state.visibleEventLayers[layer.kind]) {
        events = events.concat(layer.points || []);
      }
    });
    return events;
  }

  function backtestLayer(workspace) {
    return (workspace.layers || []).find(function (layer) {
      return layer.kind === "backtest";
    }) || { series: [], summary: {} };
  }

  function layerVisibleByDefault(workspace, kind) {
    var layer = (workspace.layers || []).find(function (item) {
      return item.kind === kind;
    });
    return !layer || layer.visible_by_default !== false;
  }

  function hasBacktestOverlays(state) {
    return Boolean(
      (state.equityCurve && state.equityCurve.length) ||
      (state.signals && state.signals.length) ||
      (state.trades && state.trades.length)
    );
  }

  function safeToken(value) {
    return String(value || "unknown").toLowerCase().replace(/[^a-z0-9_-]/g, "-");
  }

  function setText(node, value) {
    if (node) {
      node.textContent = value == null || value === "" ? "-" : String(value);
    }
  }

  function makeElement(tag, options) {
    var node = document.createElement(tag);
    options = options || {};
    if (options.className) {
      node.className = options.className;
    }
    if (options.text !== undefined) {
      node.textContent = options.text;
    }
    if (options.type) {
      node.type = options.type;
    }
    return node;
  }

  function renderLoading(ticker) {
    setText(byId("company-name"), ticker || "K-line");
    setText(byId("last-close"), "-");
    setText(byId("coverage-range"), "-");
    setText(byId("hover-readout"), "-");

    var strip = byId("source-strip");
    if (strip) {
      strip.replaceChildren(makeElement("span", {
        className: "source-chip is-loading",
        text: "workspace: loading"
      }));
    }

    var chart = byId("kline-container");
    if (chart) {
      chart.textContent = "Loading workspace.";
    }

    document.querySelectorAll("[data-panel]").forEach(function (panel) {
      panel.replaceChildren(makeElement("p", {
        className: "empty-state",
        text: "Loading workspace."
      }));
    });
  }

  function renderLoadError(message) {
    var strip = byId("source-strip");
    if (strip) {
      strip.replaceChildren(makeElement("span", {
        className: "source-chip is-error",
        text: "workspace: error"
      }));
    }

    var chart = byId("kline-container");
    if (chart) {
      chart.textContent = message || "Workspace unavailable.";
    }

    var statusPanel = document.querySelector('[data-panel="status"]');
    if (statusPanel) {
      statusPanel.replaceChildren(makeElement("p", {
        className: "empty-state",
        text: message || "Workspace unavailable."
      }));
    }
  }

  function formatMoney(value) {
    return Number.isFinite(Number(value)) ? "$" + Number(value).toFixed(2) : "-";
  }

  function formatPercent(value) {
    return Number.isFinite(Number(value)) ? Number(value).toFixed(2) + "%" : "-";
  }

  function safeExternalUrl(value) {
    if (!value) {
      return null;
    }
    var trimmed = String(value).trim();
    if (trimmed.indexOf("\\") !== -1) {
      return null;
    }
    if (!/^https?:\/\/[^/?#\s]+(?:[/?#]|$)/i.test(trimmed)) {
      return null;
    }
    try {
      var parsed = new URL(trimmed);
      if (parsed.protocol === "http:" || parsed.protocol === "https:") {
        return parsed.href;
      }
    } catch (error) {
      return null;
    }
    return null;
  }

  function activatePanel(name) {
    document.querySelectorAll("[data-tab]").forEach(function (tab) {
      var active = tab.dataset.tab === name;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", active ? "true" : "false");
    });
    document.querySelectorAll("[data-panel]").forEach(function (panel) {
      panel.classList.toggle("is-active", panel.dataset.panel === name);
    });
  }

  function renderChart(workspace, state) {
    var container = byId("kline-container");
    if (typeof state.chartCleanup === "function") {
      state.chartCleanup();
      state.chartCleanup = null;
    }
    if (container) {
      container.replaceChildren();
    }
    if (!container || !window.PokieChart || typeof window.PokieChart.render !== "function") {
      return null;
    }

    var chartMode = state.chartDisplayMode || "candles_with_backtest";
    var showBacktestOverlay = state.showBacktest && chartMode !== "candles_only";
    var showSignalOverlays = showBacktestOverlay && chartMode === "candles_with_backtest";
    var showEventMarkers = chartMode !== "backtest_only";

    var cleanup = window.PokieChart.render(container, {
      ohlcData: (workspace.price && workspace.price.rows) || [],
      displayMode: chartMode,
      events: showEventMarkers ? activeEvents(workspace, state) : [],
      highlightedEventId: showEventMarkers ? state.selectedEventId : null,
      equityCurve: showBacktestOverlay ? state.equityCurve : [],
      signals: showSignalOverlays ? state.signals : [],
      trades: showSignalOverlays ? state.trades : [],
      onEventClick: function (event) {
        state.selectedEventId = event && event.id;
        renderCatalysts(workspace, state);
        renderDetails(workspace, state);
        activatePanel("details");
        renderChart(workspace, state);
      },
      onHover: function (date, ohlc) {
        var node = byId("hover-readout");
        if (!node) {
          return;
        }
        node.textContent = ohlc ? date + " " + formatMoney(ohlc.close) : "-";
      },
      onRangeSelect: function (range) {
        if (range) {
          loadRangeContext(workspace.ticker, range.startDate, range.endDate);
        }
      }
    });

    state.chartCleanup = typeof cleanup === "function" ? cleanup : null;
    return state.chartCleanup;
  }

  function renderHeader(workspace) {
    setText(byId("company-name"), workspace.company && workspace.company.name);
    setText(byId("last-close"), formatMoney(workspace.price && workspace.price.last_close));
    var range = (workspace.price && workspace.price.date_range) || {};
    setText(byId("coverage-range"), range.start && range.end ? range.start + " to " + range.end : "-");
    setText(byId("hover-readout"), "-");

    var strip = byId("source-strip");
    if (!strip) {
      return;
    }
    strip.replaceChildren();
    (workspace.data_status || []).forEach(function (status) {
      var item = makeElement("span", {
        className: "source-chip is-" + safeToken(status.status),
        text: status.source + ": " + status.status + " (" + status.item_count + ")"
      });
      strip.appendChild(item);
    });
    appendRefreshControl(strip, workspace.ticker);
  }

  function appendRefreshControl(strip, ticker) {
    var button = makeElement("button", {
      type: "button",
      className: "source-refresh-button",
      text: "Refresh"
    });
    button.addEventListener("click", function () {
      refreshWorkspace(ticker);
    });
    strip.appendChild(button);
  }

  function renderRefreshStatus(status, text) {
    var strip = byId("source-strip");
    if (!strip) {
      return;
    }
    var chip = byId("workspace-refresh-status");
    if (!chip) {
      chip = makeElement("span", { className: "source-chip" });
      chip.id = "workspace-refresh-status";
      strip.appendChild(chip);
    }
    chip.className = "source-chip is-" + safeToken(status);
    chip.textContent = text;
  }

  function renderLayerBar(workspace, state) {
    var bar = byId("layer-bar");
    if (!bar) {
      return;
    }
    bar.replaceChildren();

    var renderedLayerKinds = {};
    (workspace.layers || []).forEach(function (layer) {
      var button = makeElement("button", { type: "button", text: layer.label || layer.kind });
      button.dataset.layerKind = layer.kind;
      renderedLayerKinds[layer.kind] = true;
      var isEventLayer = isEventLayerKind(layer.kind);
      var isBacktest = layer.kind === "backtest";
      var isActive = isEventLayer
        ? state.visibleEventLayers && state.visibleEventLayers[layer.kind]
        : isBacktest
          ? state.showBacktest && hasBacktestOverlays(state)
          : layer.visible_by_default !== false;
      button.classList.toggle("is-active", isActive);
      if (isEventLayer) {
        button.addEventListener("click", function () {
          state.visibleEventLayers[layer.kind] = !state.visibleEventLayers[layer.kind];
          renderLayerBar(workspace, state);
          renderChart(workspace, state);
        });
      } else if (isBacktest) {
        button.disabled = !hasBacktestOverlays(state);
        button.addEventListener("click", function () {
          if (!hasBacktestOverlays(state)) {
            return;
          }
          state.showBacktest = !state.showBacktest;
          renderLayerBar(workspace, state);
          renderChart(workspace, state);
        });
      } else {
        button.disabled = true;
      }
      bar.appendChild(button);
    });

    (workspace.capabilities || []).forEach(function (capability) {
      if (renderedLayerKinds[capability.id]) {
        return;
      }
      var button = makeElement("button", { type: "button", text: capability.label });
      button.disabled = !capability.enabled;
      button.dataset.capability = capability.id;
      button.dataset.phase = String(capability.phase || "");
      button.title = capability.enabled ? capability.label : "Phase " + capability.phase + " capability placeholder";
      bar.appendChild(button);
    });
  }

  function renderCatalysts(workspace, state) {
    var panel = document.querySelector('[data-panel="catalysts"]');
    if (!panel) {
      return;
    }
    var events = catalystLayer(workspace).points || [];
    panel.replaceChildren();

    if (!events.length) {
      panel.appendChild(makeElement("p", { className: "empty-state", text: "No catalysts for this ticker." }));
      return;
    }

    events.forEach(function (event) {
      var reportDerived = isReportDerivedEvent(event);
      var card = makeElement("button", {
        type: "button",
        className: "event-card is-" + safeToken(event.category || event.type) + (reportDerived ? " is-report" : "")
      });
      card.dataset.eventId = event.id;
      card.classList.toggle("is-selected", event.id === state.selectedEventId);

      if (reportDerived) {
        card.appendChild(makeElement("span", {
          className: "event-origin-badge",
          text: "Report"
        }));
      }
      card.appendChild(makeElement("strong", {
        className: "event-title",
        text: event.title || event.catalyst || event.type || "Catalyst"
      }));
      card.appendChild(makeElement("span", {
        className: "event-meta",
        text: [event.date, eventSourceLabel(event), event.confidence].filter(Boolean).join(" · ")
      }));
      if (event.summary) {
        card.appendChild(makeElement("p", { className: "event-summary", text: event.summary }));
      }

      card.addEventListener("click", function () {
        state.selectedEventId = event.id;
        renderCatalysts(workspace, state);
        renderDetails(workspace, state);
        renderChart(workspace, state);
        activatePanel("details");
      });
      panel.appendChild(card);
    });
  }

  function appendDefinition(list, term, value) {
    list.appendChild(makeElement("dt", { text: term }));
    list.appendChild(makeElement("dd", { text: value == null || value === "" ? "-" : String(value) }));
  }

  function isReportDerivedEvent(event) {
    return Boolean(event && event.metadata && (
      event.metadata.derived_from_report === true || event.metadata.report_bridge === true
    ));
  }

  function eventSourceLabel(event) {
    var source = event && event.source ? String(event.source) : "";
    if (!isReportDerivedEvent(event)) {
      return source;
    }
    return source ? source + " · from report" : "from report";
  }

  function eventMetadataValue(event, key) {
    if (event && event[key] != null) {
      return event[key];
    }
    if (event && event.metadata && event.metadata[key] != null) {
      return event.metadata[key];
    }
    return null;
  }

  function renderDetails(workspace, state) {
    var panel = document.querySelector('[data-panel="details"]');
    if (!panel) {
      return;
    }
    var events = allEvents(workspace);
    var selected = events.find(function (event) {
      return event.id === state.selectedEventId;
    });
    panel.replaceChildren();

    if (!selected) {
      panel.appendChild(makeElement("p", {
        className: "empty-state",
        text: "Select a catalyst to inspect source metadata."
      }));
      return;
    }

    panel.appendChild(makeElement("h3", {
      className: "details-title",
      text: selected.title || selected.catalyst || selected.type || "Catalyst"
    }));
    if (selected.summary) {
      panel.appendChild(makeElement("p", { className: "event-summary", text: selected.summary }));
    }

    var list = makeElement("dl", { className: "details-list" });
    appendDefinition(list, "Date", selected.date);
    appendDefinition(list, "Category", selected.category || selected.type);
    appendDefinition(list, "Source", selected.source);
    if (isReportDerivedEvent(selected)) {
      appendDefinition(list, "Origin", "Report");
      appendDefinition(list, "Report company", eventMetadataValue(selected, "report_company_name"));
      appendDefinition(list, "Report path", eventMetadataValue(selected, "report_path"));
    }
    appendDefinition(list, "Source entity", selected.source_entity);
    appendDefinition(list, "Identifiers", (selected.source_ids || []).join(", "));
    appendDefinition(list, "Confidence", selected.confidence || "medium");
    appendDefinition(list, "Source tier", eventMetadataValue(selected, "source_tier"));
    appendDefinition(list, "Confidence score", eventMetadataValue(selected, "confidence_score"));
    appendDefinition(list, "Backtest eligible", eventMetadataValue(selected, "backtest_eligible"));
    appendDefinition(list, "Sentiment", selected.sentiment || "unknown");
    appendDefinition(list, "Impact score", eventMetadataValue(selected, "impact_score"));
    panel.appendChild(list);

    var sourceUrl = safeExternalUrl(selected.source_url);
    if (sourceUrl) {
      var link = makeElement("a", { className: "source-link", text: "Open source" });
      link.href = sourceUrl;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      panel.appendChild(link);
    }
  }

  function renderStatus(workspace) {
    var panel = document.querySelector('[data-panel="status"]');
    if (!panel) {
      return;
    }
    panel.replaceChildren();
    panel.appendChild(makeElement("h3", { className: "panel-heading", text: "Data status" }));

    (workspace.data_status || []).forEach(function (status) {
      var row = makeElement("div", {
        className: "status-row is-" + safeToken(status.status),
        text: status.source + " · " + status.status + " · " + status.item_count
      });
      if (status.message) {
        row.title = status.message;
      }
      panel.appendChild(row);
    });

    (workspace.warnings || []).forEach(function (warning) {
      panel.appendChild(makeElement("div", {
        className: "warning-row",
        text: warning.message
      }));
    });
  }

  function addInput(form, labelText, name, type, value, step) {
    var label = makeElement("label", { text: labelText });
    var input = makeElement("input");
    input.name = name;
    input.type = type;
    if (value !== undefined) {
      input.value = value;
    }
    if (step) {
      input.step = step;
    }
    if (type === "date") {
      input.required = true;
    }
    label.appendChild(input);
    form.appendChild(label);
    return input;
  }

  function addSelect(form, labelText, name, options, value) {
    var label = makeElement("label", { text: labelText });
    var select = makeElement("select");
    select.name = name;
    (options || []).forEach(function (optionConfig) {
      var optionValue = Array.isArray(optionConfig) ? optionConfig[0] : optionConfig.value;
      var optionLabel = Array.isArray(optionConfig) ? optionConfig[1] : optionConfig.label;
      var option = makeElement("option", { text: optionLabel || optionValue });
      option.value = optionValue;
      select.appendChild(option);
    });
    select.value = value;
    label.appendChild(select);
    form.appendChild(label);
    return select;
  }

  function replaceSelectOptions(select, options, value) {
    if (!select || !Array.isArray(options) || !options.length) {
      return;
    }
    select.replaceChildren();
    options.forEach(function (optionConfig) {
      var optionValue = Array.isArray(optionConfig) ? optionConfig[0] : optionConfig.id || optionConfig.value;
      var optionLabel = Array.isArray(optionConfig) ? optionConfig[1] : optionConfig.label || optionValue;
      var option = makeElement("option", { text: optionLabel || optionValue });
      option.value = optionValue;
      select.appendChild(option);
    });
    var children = Array.prototype.slice.call(select.children || []);
    if (value && children.some(function (option) { return option.value === value; })) {
      select.value = value;
    } else if (children.length) {
      select.value = children[0].value;
    }
  }

  function snapshotOptionLabel(snapshot) {
    var parts = [
      snapshot.data_snapshot_id,
      snapshot.price_source,
      snapshot.universe_id,
      snapshot.snapshot_date
    ].filter(Boolean);
    return parts.join(" | ");
  }

  function snapshotSelectOptions(snapshots) {
    return (Array.isArray(snapshots) ? snapshots : [])
      .filter(function (snapshot) {
        return snapshot &&
          snapshot.data_snapshot_id &&
          String(snapshot.price_source || "").trim() === "tiingo";
      })
      .map(function (snapshot) {
        return {
          id: String(snapshot.data_snapshot_id || ""),
          label: snapshotOptionLabel(snapshot)
        };
      });
  }

  function renderMetrics(node, metrics) {
    node.replaceChildren();
    appendMetrics(node, metrics);
  }

  function appendMetrics(node, metrics) {
    var keys = Object.keys(metrics || {});
    if (!keys.length) {
      return;
    }
    var list = makeElement("dl", { className: "metrics-list" });
    keys.forEach(function (key) {
      appendDefinition(list, key, metrics[key]);
    });
    node.appendChild(list);
  }

  function isDisclosureKey(key) {
    var normalized = String(key || "").toLowerCase();
    return normalized.indexOf("mock") !== -1 ||
      normalized === "data_mode" ||
      normalized === "positive_demo_expected" ||
      normalized === "synthetic" ||
      normalized === "universe_id" ||
      normalized === "strategy" ||
      normalized === "strategy_id";
  }

  function isDisclosureValue(value) {
    if (typeof value !== "string") {
      return false;
    }
    return value.toLowerCase().indexOf("mock") !== -1;
  }

  function publicValue(value) {
    return isDisclosureValue(value) ? "-" : value;
  }

  function publicMetrics(metrics) {
    var filtered = {};
    Object.keys(metrics || {}).forEach(function (key) {
      if (isDisclosureKey(key) || isDisclosureValue(metrics[key])) {
        return;
      }
      filtered[key] = metrics[key];
    });
    return filtered;
  }

  function publicStrategyDiagnostics(strategy) {
    if (!strategy) {
      return {};
    }
    return publicMetrics({
      price_basis: strategy.price_basis,
      holding_period_days: strategy.holding_period_days
    });
  }

  function renderStrategyFormula(node, strategy, sectionClassName) {
    var formula = strategy && typeof strategy.formula === "string" ? strategy.formula.trim() : "";
    if (!formula || isDisclosureValue(formula)) {
      return;
    }
    var section = makeElement("section", { className: sectionClassName || "backtest-diagnostics" });
    section.appendChild(makeElement("h3", { className: "panel-heading", text: "Strategy Formula" }));
    section.appendChild(makeElement("code", { className: "strategy-formula", text: formula }));
    node.appendChild(section);
  }

  function renderBacktestDiagnostics(node, body) {
    var strategyMetrics = publicStrategyDiagnostics(body && body.strategy);
    if (Object.keys(strategyMetrics).length) {
      var strategySection = makeElement("section", { className: "backtest-diagnostics" });
      strategySection.appendChild(makeElement("h3", { className: "panel-heading", text: "strategy" }));
      appendMetrics(strategySection, strategyMetrics);
      node.appendChild(strategySection);
    }
    renderStrategyFormula(node, body && body.strategy);

    ["event_filter", "signal_summary", "exposure_summary", "risk_parameters", "baseline", "factor_attribution"].forEach(function (key) {
      if (!body || !body[key]) {
        return;
      }
      var section = makeElement("section", { className: "backtest-diagnostics" });
      section.appendChild(makeElement("h3", { className: "panel-heading", text: key }));
      appendMetrics(section, key === "factor_attribution" ? publicFactorAttribution(body[key]) : publicMetrics(body[key]));
      node.appendChild(section);
    });
    renderEventAttribution(node, body && body.event_attribution);
  }

  function publicFactorAttribution(metrics) {
    var filtered = {};
    Object.keys(metrics || {}).forEach(function (key) {
      if (isDisclosureKey(key) || isDisclosureValue(metrics[key])) {
        return;
      }
      filtered[key] = metrics[key];
    });
    return filtered;
  }

  function appendPortfolioCard(grid, label, value) {
    var card = makeElement("div", { className: "portfolio-metric" });
    card.appendChild(makeElement("dt", { text: label }));
    card.appendChild(makeElement("dd", { text: value == null || value === "" ? "-" : String(value) }));
    grid.appendChild(card);
  }

  function appendPortfolioRowMetric(grid, label, value) {
    var card = makeElement("div", { className: "portfolio-row-metric" });
    card.appendChild(makeElement("dt", { text: label }));
    card.appendChild(makeElement("dd", { text: value == null || value === "" ? "-" : String(value) }));
    grid.appendChild(card);
  }

  function makeEquitySparkline(curve) {
    var points = Array.isArray(curve) ? curve.filter(function (point) {
      return point && Number.isFinite(Number(point.equity));
    }) : [];
    if (points.length < 2) {
      return null;
    }
    var equities = points.map(function (point) { return Number(point.equity); });
    var min = Math.min.apply(Math, equities);
    var max = Math.max.apply(Math, equities);
    var span = max - min || 1;
    var width = 120;
    var height = 34;
    var linePoints = equities.map(function (equity, index) {
      var x = points.length === 1 ? width : (index / (points.length - 1)) * width;
      var y = height - ((equity - min) / span) * height;
      return x.toFixed(2) + "," + y.toFixed(2);
    }).join(" ");
    var svg = makeElement("svg", { className: "portfolio-sparkline" });
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "constituent equity curve");
    var polyline = makeElement("polyline");
    polyline.setAttribute("points", linePoints);
    polyline.setAttribute("fill", "none");
    polyline.setAttribute("stroke", "currentColor");
    polyline.setAttribute("stroke-width", "2");
    svg.appendChild(polyline);
    return svg;
  }

  function renderPortfolioDiagnostics(node, body) {
    node.replaceChildren();
    var layout = makeElement("div", { className: "portfolio-results" });
    var overview = makeElement("div", { className: "portfolio-overview" });
    var detailGrid = makeElement("div", { className: "portfolio-results-grid" });

    renderStrategyFormula(overview, body && body.strategy, "portfolio-strategy");

    var metrics = publicMetrics(body && body.portfolio_metrics);
    if (Object.keys(metrics).length) {
      var summary = makeElement("section", { className: "portfolio-summary" });
      summary.appendChild(makeElement("h3", { className: "panel-heading", text: "Portfolio" }));
      var grid = makeElement("dl", { className: "portfolio-metrics" });
      ["strategy_return", "best_ticker", "worst_ticker", "total_trades", "avg_active_signal_days", "avg_exposure_days"].forEach(function (key) {
        appendPortfolioCard(grid, key, metrics[key]);
      });
      summary.appendChild(grid);
      overview.appendChild(summary);
    }
    if (overview.children.length) {
      layout.appendChild(overview);
    }

    var constituents = (body && body.constituents) || [];
    if (constituents.length) {
      var leaderboard = makeElement("section", { className: "portfolio-leaderboard" });
      leaderboard.appendChild(makeElement("h3", { className: "panel-heading", text: "Constituents" }));
      constituents.forEach(function (constituent) {
        var row = makeElement("div", { className: "portfolio-row" });
        var symbol = makeElement("div", { className: "portfolio-row-symbol" });
        symbol.appendChild(makeElement("strong", { text: publicValue(constituent.ticker) || "-" }));
        row.appendChild(symbol);
        var chartCell = makeElement("div", { className: "portfolio-row-chart" });
        var sparkline = makeEquitySparkline(constituent.equity_curve);
        if (sparkline) {
          chartCell.appendChild(sparkline);
        } else {
          chartCell.appendChild(makeElement("span", { className: "portfolio-sparkline-empty", text: "-" }));
        }
        row.appendChild(chartCell);
        var details = makeElement("dl", { className: "portfolio-row-metrics" });
        ["strategy_return", "active_signal_days", "trade_count"].forEach(function (key) {
          appendPortfolioRowMetric(details, key, publicValue(constituent[key]));
        });
        appendPortfolioRowMetric(
          details,
          "exposure_days",
          publicValue(constituent.exposure_summary && constituent.exposure_summary.exposure_days)
        );
        row.appendChild(details);
        leaderboard.appendChild(row);
      });
      detailGrid.appendChild(leaderboard);
    }

    var focusStatus = body && body.focus_ticker_status;
    var focus = body && body.focus_ticker;
    var focusAttribution = publicFactorAttribution(focus && focus.factor_attribution);
    var shouldRenderFocus = (focusStatus && focusStatus.available === false) || Object.keys(focusAttribution).length;
    if (shouldRenderFocus) {
      var focusPanel = makeElement("section", { className: "portfolio-focus" });
      focusPanel.appendChild(makeElement("h3", { className: "panel-heading", text: "Focus Ticker" }));
      if (focus && focus.ticker) {
        var focusTicker = makeElement("dl", { className: "portfolio-focus-ticker" });
        appendPortfolioRowMetric(focusTicker, "ticker", publicValue(focus.ticker) || "-");
        focusPanel.appendChild(focusTicker);
      }
      if (focusStatus && focusStatus.available === false) {
        focusPanel.appendChild(makeElement("div", {
          className: "warning-row",
          text: "Focus ticker " + (focusStatus.requested_ticker || "-") + " is unavailable in this snapshot; showing " + (focusStatus.resolved_ticker || "-") + "."
        }));
      }
      if (Object.keys(focusAttribution).length) {
        var attribution = makeElement("div", { className: "portfolio-focus-attribution" });
        attribution.appendChild(makeElement("h4", { className: "panel-subheading", text: "factor_attribution" }));
        var attributionMetrics = makeElement("dl", { className: "portfolio-focus-metrics" });
        Object.keys(focusAttribution).forEach(function (key) {
          appendPortfolioRowMetric(attributionMetrics, key, focusAttribution[key]);
        });
        attribution.appendChild(attributionMetrics);
        focusPanel.appendChild(attribution);
      }
      detailGrid.appendChild(focusPanel);
    }
    if (detailGrid.children.length) {
      layout.appendChild(detailGrid);
    }
    node.appendChild(layout);
  }

  function clearBacktestOverlays(workspace, state) {
    state.equityCurve = [];
    state.signals = [];
    state.trades = [];
    state.showBacktest = false;
    renderLayerBar(workspace, state);
    renderChart(workspace, state);
  }

  function renderEventAttribution(node, attribution) {
    if (!attribution) {
      return;
    }
    var section = makeElement("section", { className: "backtest-diagnostics" });
    section.appendChild(makeElement("h3", { className: "panel-heading", text: "event_attribution" }));
    [
      ["by_source", "source"],
      ["by_category", "category"],
      ["by_type", "type"]
    ].forEach(function (config) {
      var groupKey = config[0];
      var labelKey = config[1];
      var rows = attribution[groupKey] || [];
      if (!rows.length) {
        return;
      }
      section.appendChild(makeElement("h4", { className: "panel-subheading", text: groupKey }));
      var list = makeElement("dl", { className: "metrics-list" });
      rows.forEach(function (row) {
        appendDefinition(list, row[labelKey] || "unknown", row.count);
      });
      section.appendChild(list);
    });
    node.appendChild(section);
  }

  function cloneStrategyConfig() {
    return JSON.parse(JSON.stringify(DEFAULT_STRATEGY_CONFIG));
  }

  function numericFormValue(form, name, fallback) {
    var element = form.elements[name];
    var value = element ? Number(element.value) : fallback;
    return Number.isFinite(value) ? value : fallback;
  }

  function integerFormValue(form, name, fallback) {
    var value = Math.round(numericFormValue(form, name, fallback));
    return Number.isFinite(value) ? value : fallback;
  }

  function readStrategyConfig(form) {
    var config = cloneStrategyConfig();
    config.weights.trend = numericFormValue(form, "strategy_weight_trend", config.weights.trend);
    config.weights.momentum = numericFormValue(form, "strategy_weight_momentum", config.weights.momentum);
    config.weights.liquidity = numericFormValue(form, "strategy_weight_liquidity", config.weights.liquidity);
    config.weights.volatility = numericFormValue(form, "strategy_weight_volatility", config.weights.volatility);
    config.weights.event = numericFormValue(form, "strategy_weight_event", config.weights.event);
    config.windows.fast = integerFormValue(form, "strategy_window_fast", config.windows.fast);
    config.windows.slow = integerFormValue(form, "strategy_window_slow", config.windows.slow);
    config.windows.momentum = integerFormValue(form, "strategy_window_momentum", config.windows.momentum);
    config.windows.volatility = integerFormValue(form, "strategy_window_volatility", config.windows.volatility);
    config.windows.volume = integerFormValue(form, "strategy_window_volume", config.windows.volume);
    config.thresholds.long = numericFormValue(form, "strategy_threshold_long", config.thresholds.long);
    config.thresholds.short = numericFormValue(form, "strategy_threshold_short", config.thresholds.short);
    return config;
  }

  function strategyFormulaText(config) {
    return "alpha = " +
      config.weights.trend + " * trend(" + config.windows.fast + "," + config.windows.slow + ") + " +
      config.weights.momentum + " * momentum(" + config.windows.momentum + ") + " +
      config.weights.liquidity + " * liquidity(" + config.windows.volume + ") + " +
      config.weights.volatility + " * volatility(" + config.windows.volatility + ") + " +
      config.weights.event + " * event_score; long alpha > " +
      config.thresholds.long + "; short alpha < " + config.thresholds.short;
  }

  function addStrategyBuilder(form) {
    var section = makeElement("section", { className: "strategy-builder" });
    section.appendChild(makeElement("h3", { className: "panel-heading", text: "Strategy Builder" }));
    var formula = makeElement("code", {
      className: "strategy-formula",
      text: strategyFormulaText(cloneStrategyConfig())
    });
    formula.id = "strategy-formula-preview";
    section.appendChild(formula);

    addInput(section, "Trend Weight", "strategy_weight_trend", "number", String(DEFAULT_STRATEGY_CONFIG.weights.trend), "0.01");
    addInput(section, "Momentum Weight", "strategy_weight_momentum", "number", String(DEFAULT_STRATEGY_CONFIG.weights.momentum), "0.01");
    addInput(section, "Liquidity Weight", "strategy_weight_liquidity", "number", String(DEFAULT_STRATEGY_CONFIG.weights.liquidity), "0.01");
    addInput(section, "Volatility Weight", "strategy_weight_volatility", "number", String(DEFAULT_STRATEGY_CONFIG.weights.volatility), "0.01");
    addInput(section, "Event Weight", "strategy_weight_event", "number", String(DEFAULT_STRATEGY_CONFIG.weights.event), "0.01");
    addInput(section, "Fast Window", "strategy_window_fast", "number", String(DEFAULT_STRATEGY_CONFIG.windows.fast), "1");
    addInput(section, "Slow Window", "strategy_window_slow", "number", String(DEFAULT_STRATEGY_CONFIG.windows.slow), "1");
    addInput(section, "Momentum Window", "strategy_window_momentum", "number", String(DEFAULT_STRATEGY_CONFIG.windows.momentum), "1");
    addInput(section, "Volatility Window", "strategy_window_volatility", "number", String(DEFAULT_STRATEGY_CONFIG.windows.volatility), "1");
    addInput(section, "Volume Window", "strategy_window_volume", "number", String(DEFAULT_STRATEGY_CONFIG.windows.volume), "1");
    addInput(section, "Long Threshold", "strategy_threshold_long", "number", String(DEFAULT_STRATEGY_CONFIG.thresholds.long), "0.01");
    addInput(section, "Short Threshold", "strategy_threshold_short", "number", String(DEFAULT_STRATEGY_CONFIG.thresholds.short), "0.01");

    section.addEventListener("change", function () {
      formula.textContent = strategyFormulaText(readStrategyConfig(form));
    });
    form.appendChild(section);
  }

  function renderBacktest(workspace, state) {
    var panel = document.querySelector('[data-panel="backtest"]');
    if (!panel) {
      return;
    }
    panel.replaceChildren();
    panel.appendChild(makeElement("h3", { className: "panel-heading", text: "Backtest" }));

    var form = makeElement("form", { className: "backtest-form" });
    form.id = "backtest-form";
    var range = (workspace.price && workspace.price.date_range) || {};
    addInput(form, "Start", "start_date", "date", range.start || "");
    addInput(form, "End", "end_date", "date", range.end || "");
    var strategySelect = addSelect(
      form,
      "Strategy",
      "strategy_id",
      BACKTEST_STRATEGY_OPTIONS,
      "multifactor_score"
    );
    var priceSourceSelect = addSelect(
      form,
      "Price Source",
      "price_source",
      BACKTEST_PRICE_SOURCE_OPTIONS,
      "yfinance"
    );
    var dataSnapshotSelect = addSelect(form, "Data Snapshot", "data_snapshot_id", [], "");
    addInput(form, "Stop Loss Fraction", "stop_loss_pct", "number", "-0.08", "0.001");
    addInput(form, "Max Position Fraction", "max_position_pct", "number", "0.2", "0.001");
    addInput(form, "Slippage Fraction", "slippage_pct", "number", "0.001", "0.0001");
    addInput(form, "Hold Days", "holding_period_days", "number", "5", "1");
    var universeInput = addInput(form, "Universe ID", "universe_id", "text", "biotech_us_v1");
    var chartModeSelect = addSelect(
      form,
      "Chart Display Mode",
      "chart_display_mode",
      CHART_DISPLAY_MODES,
      state.chartDisplayMode || "candles_with_backtest"
    );
    addStrategyBuilder(form);
    form.appendChild(makeElement("button", { type: "submit", text: "Run Backtest" }));
    var universeButton = makeElement("button", {
      type: "button",
      className: "backtest-universe-button",
      text: "Run Universe"
    });
    form.appendChild(universeButton);
    panel.appendChild(form);

    var status = makeElement("div", { className: "backtest-status", text: "No run yet." });
    status.id = "backtest-status";
    var results = makeElement("div", { className: "backtest-results" });
    results.id = "backtest-results";
    panel.appendChild(status);
    panel.appendChild(results);
    var portfolioDefaults = {
      required_price_source: "tiingo",
      default_price_source: "tiingo",
      default_data_snapshot_id: "",
      universe_id: "biotech_us_v1"
    };
    var recentSnapshots = [];
    var universeTouched = false;

    function syncSnapshotControl() {
      dataSnapshotSelect.disabled = false;
    }

    function selectedSnapshot() {
      var snapshotId = String(dataSnapshotSelect.value || "").trim();
      for (var index = 0; index < recentSnapshots.length; index += 1) {
        if (String(recentSnapshots[index].data_snapshot_id || "") === snapshotId) {
          return recentSnapshots[index];
        }
      }
      return null;
    }

    function syncUniverseFromSelectedSnapshot(force) {
      var snapshot = selectedSnapshot();
      if (!snapshot || !snapshot.universe_id) {
        return;
      }
      if (force || !universeTouched) {
        universeInput.value = String(snapshot.universe_id || "");
      }
    }

    function applyBacktestOptions(options) {
      options = options || {};
      recentSnapshots = Array.isArray(options.snapshots) ? options.snapshots : [];
      replaceSelectOptions(
        strategySelect,
        options.strategies || BACKTEST_STRATEGY_OPTIONS,
        options.default_strategy_id || strategySelect.value || "multifactor_score"
      );
      replaceSelectOptions(
        priceSourceSelect,
        options.price_sources || BACKTEST_PRICE_SOURCE_OPTIONS,
        options.default_price_source || priceSourceSelect.value || "tiingo"
      );
      if (options.portfolio) {
        portfolioDefaults = {
          required_price_source: options.portfolio.required_price_source || "tiingo",
          default_price_source: options.portfolio.default_price_source || "tiingo",
          default_data_snapshot_id: options.portfolio.default_data_snapshot_id || "",
          universe_id: options.portfolio.universe_id || "biotech_us_v1"
        };
      }
      replaceSelectOptions(
        dataSnapshotSelect,
        snapshotSelectOptions(recentSnapshots),
        portfolioDefaults.default_data_snapshot_id || options.default_data_snapshot_id || dataSnapshotSelect.value
      );
      syncUniverseFromSelectedSnapshot(false);
      syncSnapshotControl();
    }

    function loadBacktestOptions() {
      var optionsFetch = window.fetch;
      if (typeof optionsFetch !== "function") {
        syncSnapshotControl();
        return;
      }
      var optionsUrl = "/api/backtest/options";
      var ticker = String(workspace.ticker || "").trim().toUpperCase();
      if (ticker) {
        optionsUrl += "?ticker=" + encodeURIComponent(ticker);
      }
      Promise.resolve().then(function () {
        return optionsFetch.call(window, optionsUrl);
      }).then(function (response) {
        return response.json().then(function (body) {
          return { ok: response.ok, body: body };
        });
      }).then(function (result) {
        if (result.ok) {
          applyBacktestOptions(result.body);
        }
      }).catch(function () {
        syncSnapshotControl();
      });
    }

    var savedSummary = (backtestLayer(workspace).summary || {});
    if (savedSummary.run_id || savedSummary.metrics || savedSummary.event_filter || savedSummary.signal_summary || savedSummary.exposure_summary || savedSummary.risk_parameters || savedSummary.baseline || savedSummary.factor_attribution || savedSummary.event_attribution) {
      status.textContent = "Run " + (savedSummary.run_id || "complete") + " complete.";
      renderMetrics(results, savedSummary.metrics || {});
      renderBacktestDiagnostics(results, savedSummary);
    }

    chartModeSelect.addEventListener("change", function () {
      state.chartDisplayMode = chartModeSelect.value || "candles_with_backtest";
      renderChart(workspace, state);
    });
    priceSourceSelect.addEventListener("change", syncSnapshotControl);
    dataSnapshotSelect.addEventListener("change", function () {
      var snapshot = selectedSnapshot();
      if (snapshot && snapshot.price_source) {
        priceSourceSelect.value = String(snapshot.price_source || priceSourceSelect.value);
      }
      syncUniverseFromSelectedSnapshot(true);
      syncSnapshotControl();
    });
    universeInput.addEventListener("input", function () {
      universeTouched = true;
    });
    universeInput.addEventListener("change", function () {
      universeTouched = true;
    });
    syncSnapshotControl();
    loadBacktestOptions();

    function requestPayload(options) {
      options = options || {};
      var priceSource = String(form.elements.price_source.value || "tiingo").trim();
      var selectedDataSnapshotId = String(form.elements.data_snapshot_id.value || "").trim();
      if (options.portfolio) {
        var requiredSource = String(portfolioDefaults.required_price_source || portfolioDefaults.default_price_source || "tiingo").trim();
        if (priceSource !== requiredSource) {
          priceSource = requiredSource;
        }
        if (!selectedDataSnapshotId) {
          selectedDataSnapshotId = String(portfolioDefaults.default_data_snapshot_id || "").trim();
        }
      }
      var payload = {
        ticker: workspace.ticker,
        start_date: form.elements.start_date.value,
        end_date: form.elements.end_date.value,
        strategy_id: String(form.elements.strategy_id.value || "multifactor_score").trim(),
        data_mode: "real",
        backtest_mode: "exploratory",
        price_source: priceSource,
        stop_loss_pct: Number(form.elements.stop_loss_pct.value),
        max_position_pct: Number(form.elements.max_position_pct.value),
        slippage_pct: Number(form.elements.slippage_pct.value),
        holding_period_days: Number(form.elements.holding_period_days.value),
        strategy_config: readStrategyConfig(form)
      };
      var universeId = String(form.elements.universe_id.value || "").trim();
      if (universeId) {
        payload.universe_id = universeId;
      }
      if (priceSource === "tiingo" && selectedDataSnapshotId) {
        payload.data_snapshot_id = selectedDataSnapshotId;
      }
      return payload;
    }

    function runBacktest(endpoint, options) {
      options = options || {};
      state.backtestRequestId = (state.backtestRequestId || 0) + 1;
      var requestId = state.backtestRequestId;
      var payload = requestPayload(options);
      var strategyConfig = payload.strategy_config || {};
      var strategyWindows = strategyConfig.windows || {};
      var strategyThresholds = strategyConfig.thresholds || {};
      if (strategyWindows.fast >= strategyWindows.slow) {
        status.textContent = "Fast window must be less than slow window.";
        return;
      }
      if (strategyThresholds.short >= strategyThresholds.long) {
        status.textContent = "Short threshold must be less than long threshold.";
        return;
      }
      if (payload.price_source === "tiingo" && !payload.data_snapshot_id) {
        status.textContent = "Select a data snapshot.";
        return;
      }
      status.textContent = options.runningText || "Running backtest.";
      results.replaceChildren();
      clearBacktestOverlays(workspace, state);

      fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }).then(function (response) {
        return response.json().then(function (body) {
          return { ok: response.ok, body: body };
        });
      }).then(function (result) {
        if (requestId !== state.backtestRequestId) {
          return;
        }
        var body = result.body || {};
        if (!result.ok) {
          status.textContent = body.error || "Backtest failed.";
          clearBacktestOverlays(workspace, state);
          return;
        }
        if (options.portfolio) {
          state.equityCurve = body.portfolio_equity_curve || [];
          state.signals = (body.focus_ticker && body.focus_ticker.signals) || [];
          state.trades = (body.focus_ticker && body.focus_ticker.trades) || [];
        } else {
          state.equityCurve = body.equity_curve || [];
          state.signals = body.signals || [];
          state.trades = body.trades || [];
        }
        state.showBacktest = true;
        status.textContent = "Run " + (body.run_id || "complete") + " complete.";
        if (options.portfolio) {
          renderPortfolioDiagnostics(results, body);
        } else {
          renderMetrics(results, body.metrics || {});
          renderBacktestDiagnostics(results, body);
        }
        renderLayerBar(workspace, state);
        renderChart(workspace, state);
      }).catch(function () {
        if (requestId !== state.backtestRequestId) {
          return;
        }
        status.textContent = "Backtest failed.";
        clearBacktestOverlays(workspace, state);
      });
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      runBacktest("/api/backtest/run", { runningText: "Running backtest." });
    });

    universeButton.addEventListener("click", function (event) {
      event.preventDefault();
      runBacktest("/api/backtest/portfolio/run", {
        portfolio: true,
        runningText: "Running universe backtest."
      });
    });

  }

  function loadRangeContext(ticker, startDate, endDate) {
    var node = byId("range-context");
    if (!node) {
      return;
    }
    node.hidden = false;
    node.textContent = "Loading range context.";
    var requestId = ++rangeContextRequestId;

    var url = "/api/kline/range-context/" + encodeURIComponent(ticker) +
      "?start=" + encodeURIComponent(startDate) +
      "&end=" + encodeURIComponent(endDate);
    fetch(url).then(function (response) {
      return response.json().then(function (body) {
        return { ok: response.ok, body: body };
      });
    }).then(function (result) {
      if (requestId !== rangeContextRequestId) {
        return;
      }
      var body = result.body || {};
      if (!result.ok) {
        node.textContent = body.error || "Range context unavailable.";
        return;
      }
      node.replaceChildren();
      node.appendChild(makeElement("strong", { text: startDate + " to " + endDate }));
      node.appendChild(document.createTextNode(
        ": " + body.catalyst_count + " catalysts, price change " + formatPercent(body.price_change_pct)
      ));
    }).catch(function () {
      if (requestId !== rangeContextRequestId) {
        return;
      }
      node.textContent = "Range context unavailable.";
    });
  }

  function openTicker(symbol) {
    var clean = String(symbol || "").trim().toUpperCase();
    if (clean) {
      window.location.href = "/kline/" + encodeURIComponent(clean);
    }
  }

  function bindTickerForm() {
    var form = byId("ticker-form");
    if (!form) {
      return;
    }
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      openTicker(form.elements.symbol.value);
    });
  }

  function bindTabs() {
    document.querySelectorAll("[data-tab]").forEach(function (tab) {
      tab.addEventListener("click", function () {
        activatePanel(tab.dataset.tab);
      });
    });
  }

  function renderWorkspace(workspace) {
    if (activeState && typeof activeState.chartCleanup === "function") {
      activeState.chartCleanup();
      activeState.chartCleanup = null;
    }

    var savedBacktest = backtestLayer(workspace);
    var savedBacktestSummary = savedBacktest.summary || {};

    var state = {
      selectedEventId: (workspace.panels && workspace.panels.selected_event_id) || null,
      visibleEventLayers: eventLayers(workspace).reduce(function (visibility, layer) {
        visibility[layer.kind] = layer.visible_by_default !== false;
        return visibility;
      }, {}),
      showBacktest: layerVisibleByDefault(workspace, "backtest"),
      equityCurve: savedBacktest.series || [],
      signals: savedBacktestSummary.signals || [],
      trades: savedBacktestSummary.trades || [],
      chartDisplayMode: "candles_with_backtest",
      backtestRequestId: 0,
      chartCleanup: null
    };

    renderHeader(workspace);
    renderLayerBar(workspace, state);
    renderCatalysts(workspace, state);
    renderDetails(workspace, state);
    renderBacktest(workspace, state);
    renderStatus(workspace);
    renderChart(workspace, state);

    activeState = state;
  }

  function refreshWorkspace(ticker) {
    if (!ticker) {
      return Promise.resolve();
    }
    var requestId = ++refreshRequestId;
    renderRefreshStatus("refreshing", "workspace: refreshing");
    return fetchWorkspace(ticker, { refresh: true }).then(function (loadedWorkspace) {
      if (requestId !== refreshRequestId) {
        return;
      }
      renderWorkspace(loadedWorkspace);
      renderRefreshStatus("ready", "workspace: refreshed");
    }).catch(function () {
      if (requestId !== refreshRequestId) {
        return;
      }
      renderRefreshStatus("error", "workspace: refresh failed");
    });
  }

  function init() {
    bindTickerForm();
    bindTabs();
    window.addEventListener("beforeunload", function () {
      if (activeState && typeof activeState.chartCleanup === "function") {
        activeState.chartCleanup();
      }
    });

    var workspace = readWorkspace();
    if (workspace) {
      renderWorkspace(workspace);
      return;
    }

    var ticker = readWorkspaceTicker();
    if (!ticker) {
      return;
    }

    renderLoading(ticker);
    fetchWorkspace(ticker).then(function (loadedWorkspace) {
      renderWorkspace(loadedWorkspace);
      refreshWorkspace(loadedWorkspace.ticker || ticker);
    }).catch(function (error) {
      renderLoadError(error && error.message);
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
