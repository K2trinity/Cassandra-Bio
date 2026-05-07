(function () {
  "use strict";

  var rangeContextRequestId = 0;
  var EVENT_LAYER_KINDS = ["catalysts", "news", "macro"];

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

    var cleanup = window.PokieChart.render(container, {
      ohlcData: (workspace.price && workspace.price.rows) || [],
      events: activeEvents(workspace, state),
      highlightedEventId: state.selectedEventId,
      equityCurve: state.showBacktest ? state.equityCurve : [],
      signals: state.showBacktest ? state.signals : [],
      trades: state.showBacktest ? state.trades : [],
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
      var card = makeElement("button", {
        type: "button",
        className: "event-card is-" + safeToken(event.category || event.type)
      });
      card.dataset.eventId = event.id;
      card.classList.toggle("is-selected", event.id === state.selectedEventId);

      card.appendChild(makeElement("strong", {
        className: "event-title",
        text: event.title || event.catalyst || event.type || "Catalyst"
      }));
      card.appendChild(makeElement("span", {
        className: "event-meta",
        text: [event.date, event.source, event.confidence].filter(Boolean).join(" · ")
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

  function renderBacktestDiagnostics(node, body) {
    var strategyMetrics = publicStrategyDiagnostics(body && body.strategy);
    if (Object.keys(strategyMetrics).length) {
      var strategySection = makeElement("section", { className: "backtest-diagnostics" });
      strategySection.appendChild(makeElement("h3", { className: "panel-heading", text: "strategy" }));
      appendMetrics(strategySection, strategyMetrics);
      node.appendChild(strategySection);
    }

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

  function renderPortfolioDiagnostics(node, body) {
    var metrics = publicMetrics(body && body.portfolio_metrics);
    if (Object.keys(metrics).length) {
      var summary = makeElement("section", { className: "portfolio-summary" });
      summary.appendChild(makeElement("h3", { className: "panel-heading", text: "Portfolio" }));
      var grid = makeElement("dl", { className: "portfolio-metrics" });
      ["strategy_return", "best_ticker", "worst_ticker", "total_trades", "avg_active_signal_days", "avg_exposure_days"].forEach(function (key) {
        appendPortfolioCard(grid, key, metrics[key]);
      });
      summary.appendChild(grid);
      node.appendChild(summary);
    }

    var constituents = (body && body.constituents) || [];
    if (constituents.length) {
      var leaderboard = makeElement("section", { className: "portfolio-leaderboard" });
      leaderboard.appendChild(makeElement("h3", { className: "panel-heading", text: "Constituents" }));
      constituents.forEach(function (constituent) {
        var row = makeElement("div", { className: "portfolio-row" });
        row.appendChild(makeElement("strong", { text: publicValue(constituent.ticker) || "-" }));
        var details = makeElement("dl", { className: "portfolio-row-metrics" });
        ["strategy_return", "active_signal_days", "trade_count"].forEach(function (key) {
          appendDefinition(details, key, publicValue(constituent[key]));
        });
        if (constituent.exposure_summary) {
          appendDefinition(details, "exposure_days", publicValue(constituent.exposure_summary.exposure_days));
        }
        row.appendChild(details);
        leaderboard.appendChild(row);
      });
      node.appendChild(leaderboard);
    }

    var focus = body && body.focus_ticker;
    if (focus && focus.factor_attribution) {
      var section = makeElement("section", { className: "backtest-diagnostics" });
      section.appendChild(makeElement("h3", { className: "panel-heading", text: "focus_factor_attribution" }));
      appendMetrics(section, publicFactorAttribution(focus.factor_attribution));
      node.appendChild(section);
    }
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
    addInput(form, "Stop Loss Fraction", "stop_loss_pct", "number", "-0.08", "0.001");
    addInput(form, "Max Position Fraction", "max_position_pct", "number", "0.2", "0.001");
    addInput(form, "Slippage Fraction", "slippage_pct", "number", "0.001", "0.0001");
    addInput(form, "Hold Days", "holding_period_days", "number", "5", "1");
    form.appendChild(makeElement("button", { type: "submit", text: "Run Backtest" }));
    var universeButton = makeElement("button", {
      type: "button",
      className: "backtest-universe-button",
      text: "Run Universe"
    });
    var demoUniverseButton = makeElement("button", {
      type: "button",
      className: "backtest-universe-button",
      text: "Run Demo Universe"
    });
    form.appendChild(universeButton);
    form.appendChild(demoUniverseButton);
    panel.appendChild(form);

    var status = makeElement("div", { className: "backtest-status", text: "No run yet." });
    status.id = "backtest-status";
    var results = makeElement("div", { className: "backtest-results" });
    results.id = "backtest-results";
    panel.appendChild(status);
    panel.appendChild(results);

    var savedSummary = (backtestLayer(workspace).summary || {});
    if (savedSummary.run_id || savedSummary.metrics || savedSummary.event_filter || savedSummary.signal_summary || savedSummary.exposure_summary || savedSummary.risk_parameters || savedSummary.baseline || savedSummary.factor_attribution || savedSummary.event_attribution) {
      status.textContent = "Run " + (savedSummary.run_id || "complete") + " complete.";
      renderMetrics(results, savedSummary.metrics || {});
      renderBacktestDiagnostics(results, savedSummary);
    }

    function requestPayload() {
      return {
        ticker: workspace.ticker,
        start_date: form.elements.start_date.value,
        end_date: form.elements.end_date.value,
        stop_loss_pct: Number(form.elements.stop_loss_pct.value),
        max_position_pct: Number(form.elements.max_position_pct.value),
        slippage_pct: Number(form.elements.slippage_pct.value),
        holding_period_days: Number(form.elements.holding_period_days.value)
      };
    }

    function runBacktest(endpoint, options) {
      options = options || {};
      state.backtestRequestId = (state.backtestRequestId || 0) + 1;
      var requestId = state.backtestRequestId;
      status.textContent = options.runningText || "Running backtest.";
      results.replaceChildren();
      clearBacktestOverlays(workspace, state);

      fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestPayload())
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

    demoUniverseButton.addEventListener("click", function (event) {
      event.preventDefault();
      runBacktest("/api/backtest/portfolio/demo/run", {
        portfolio: true,
        runningText: "Running demo universe backtest."
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

  function init() {
    var workspace = readWorkspace();
    if (!workspace) {
      return;
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

    var form = byId("ticker-form");
    if (form) {
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        openTicker(form.elements.symbol.value);
      });
    }

    document.querySelectorAll("[data-tab]").forEach(function (tab) {
      tab.addEventListener("click", function () {
        activatePanel(tab.dataset.tab);
      });
    });

    window.addEventListener("beforeunload", function () {
      if (typeof state.chartCleanup === "function") {
        state.chartCleanup();
      }
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
