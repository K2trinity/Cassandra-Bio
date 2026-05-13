import { useEffect, useRef, useCallback, useMemo, useState } from 'react';
import * as d3 from 'd3';
import { OHLCRow, BiotechEvent, HoverData, RangeSelection, AnomalySignal, SignalMarker, TradeMarker, ChartDisplayMode } from './types';

interface PlacedEvent extends BiotechEvent {
  px: number; // canvas x
  py: number; // canvas y
  radius: number;
  color: string;
  alpha: number;
  confidenceScore?: number;
  impactScore?: number;
  sourceTier?: string;
  backtestEligible?: boolean;
  reportDerived?: boolean;
}

interface Props {
  ohlcData: OHLCRow[];
  events?: BiotechEvent[] | null;
  displayMode?: ChartDisplayMode;
  onEventClick?: (event: BiotechEvent) => void;
  onAnomalyDetected?: (signal: AnomalySignal) => void;
  onHover?: (date: string | null, ohlc?: HoverData) => void;
  onRangeSelect?: (range: RangeSelection | null) => void;
  highlightedEventId?: string;
  equityCurve?: Array<{ date: string; equity: number }>;
  signals?: SignalMarker[];
  trades?: TradeMarker[];
}

type KlineTimeframe = 'day' | 'week' | 'month';

const KLINE_TIMEFRAME_OPTIONS: Array<{ id: KlineTimeframe; label: string }> = [
  { id: 'day', label: 'Day' },
  { id: 'week', label: 'Week' },
  { id: 'month', label: 'Month' },
];

// Event category/type -> color mapping
const EVENT_CATEGORY_COLOR: Record<string, string> = {
  clinical: '#00e5ff',
  regulatory: '#00e676',
  corporate: '#a78bfa',
  news: '#38bdf8',
  macro: '#f59e0b',
  report: '#f472b6',
};

const EVENT_TYPE_COLOR: Record<string, string> = {
  fda_decision: '#00e676',
  clinical_readout: '#00e5ff',
  partnership: '#667eea',
  financing: '#ffd700',
  patent: '#ff9800',
  competitor: '#ff5252',
  geopolitical: '#a78bfa',
  trade_policy: '#38bdf8',
  sanctions: '#fb7185',
  regulatory_change: '#f59e0b',
  macro_economic: '#94a3b8',
};

const EVENT_TYPE_COLOR_DEFAULT = '#64748b';

interface SourceTierStyle {
  color: string;
  lineWidth: number;
  dash?: number[];
}

function normalizeUnitScore(value: number, useMagnitude = false): number {
  const raw = useMagnitude ? Math.abs(value) : value;
  const normalized = raw > 1 && raw <= 100 ? raw / 100 : raw;
  return Math.max(0, Math.min(1, normalized));
}

function getNumberValue(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function parseChartDate(value: string): Date | null {
  const parts = value.split('-').map((part) => Number(part));
  if (parts.length !== 3 || parts.some((part) => !Number.isInteger(part))) {
    return null;
  }
  const [year, month, day] = parts;
  return new Date(Date.UTC(year, month - 1, day));
}

function formatChartDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function timeframeBucketDate(dateStr: string, timeframe: KlineTimeframe): string | null {
  if (timeframe === 'day') {
    return dateStr;
  }

  const date = parseChartDate(dateStr);
  if (!date) {
    return null;
  }

  if (timeframe === 'month') {
    return formatChartDate(new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), 1)));
  }

  const day = date.getUTCDay();
  const mondayOffset = day === 0 ? -6 : 1 - day;
  const weekStart = new Date(date);
  weekStart.setUTCDate(date.getUTCDate() + mondayOffset);
  return formatChartDate(weekStart);
}

function aggregateOhlcForTimeframe(rows: OHLCRow[], timeframe: KlineTimeframe): OHLCRow[] {
  if (timeframe === 'day') {
    return rows.slice();
  }

  const sorted = rows
    .slice()
    .sort((a, b) => (parseChartDate(a.date)?.getTime() || 0) - (parseChartDate(b.date)?.getTime() || 0));
  const buckets = new Map<string, OHLCRow>();

  for (const row of sorted) {
    const bucketDate = timeframeBucketDate(row.date, timeframe);
    if (!bucketDate) {
      continue;
    }

    const open = Number(row.open);
    const high = Number(row.high);
    const low = Number(row.low);
    const close = Number(row.close);
    const volume = Number(row.volume);
    const existing = buckets.get(bucketDate);

    if (!existing) {
      buckets.set(bucketDate, {
        date: bucketDate,
        open,
        high,
        low,
        close,
        volume: Number.isFinite(volume) ? volume : 0,
      });
      continue;
    }

    existing.high = Math.max(existing.high, high);
    existing.low = Math.min(existing.low, low);
    existing.close = close;
    existing.volume += Number.isFinite(volume) ? volume : 0;
  }

  return Array.from(buckets.values());
}

function buildTimeframeDateMap(rows: OHLCRow[], timeframe: KlineTimeframe): Map<string, string> {
  const dateMap = new Map<string, string>();
  for (const row of rows) {
    const bucketDate = timeframeBucketDate(row.date, timeframe);
    if (bucketDate) {
      dateMap.set(row.date, bucketDate);
    }
  }
  return dateMap;
}

function mapOverlayDateToTimeframe<T>(
  date: string,
  dateToOhlc: Map<string, T>,
  timeframeDateByDate: Map<string, string>,
  timeframe: KlineTimeframe,
): string | undefined {
  const mappedDate = timeframeDateByDate.get(date) ?? timeframeBucketDate(date, timeframe);
  if (mappedDate && dateToOhlc.has(mappedDate)) {
    return mappedDate;
  }
  return undefined;
}

function aggregateEquityCurveForTimeframe<T>(
  points: Array<{ date: string; equity: number }>,
  dateToOhlc: Map<string, T>,
  timeframeDateByDate: Map<string, string>,
  timeframe: KlineTimeframe,
): Array<{ date: string; equity: number }> {
  const byBucket = new Map<string, { date: string; equity: number; sourceIndex: number }>();

  points.forEach((point, sourceIndex) => {
    if (!Number.isFinite(point.equity)) {
      return;
    }
    const mappedDate = mapOverlayDateToTimeframe(
      point.date,
      dateToOhlc,
      timeframeDateByDate,
      timeframe,
    );
    if (!mappedDate) {
      return;
    }
    byBucket.set(mappedDate, {
      date: mappedDate,
      equity: point.equity,
      sourceIndex,
    });
  });

  return Array.from(byBucket.values())
    .sort((a, b) => a.sourceIndex - b.sourceIndex)
    .map(({ date, equity }) => ({ date, equity }));
}

function formatEquityReturnTick(equity: number, baseEquity: number): string {
  if (!Number.isFinite(equity) || !Number.isFinite(baseEquity) || baseEquity === 0) {
    return '+0.0%';
  }
  const returnPct = (equity / baseEquity - 1) * 100;
  const sign = returnPct >= 0 ? '+' : '';
  return `${sign}${returnPct.toFixed(1)}%`;
}

function equityReturnDomain(equities: number[], baseEquity: number): [number, number] {
  const returns = equities
    .filter((equity) => Number.isFinite(equity) && Number.isFinite(baseEquity) && baseEquity !== 0)
    .map((equity) => equity / baseEquity - 1);

  if (returns.length === 0) {
    return [-0.005, 0.005];
  }

  const minReturn = Math.min(...returns);
  const maxReturn = Math.max(...returns);
  if (minReturn === maxReturn) {
    const flatPadding = Math.max(Math.abs(minReturn) * 0.12, 0.005);
    return [minReturn - flatPadding, maxReturn + flatPadding];
  }

  const padding = Math.max((maxReturn - minReturn) * 0.12, 0.002);
  return [minReturn - padding, maxReturn + padding];
}

function getEventColor(event: BiotechEvent): string {
  if (event.category && EVENT_CATEGORY_COLOR[event.category]) {
    return EVENT_CATEGORY_COLOR[event.category];
  }
  return EVENT_TYPE_COLOR[event.type] || EVENT_TYPE_COLOR_DEFAULT;
}

function getEventRadius(priority: number, priceImpact?: number, impactScore?: number): number {
  let r = 2;
  if (priority === 1) r += 1.2;
  else if (priority === 2) r += 0.6;
  if (impactScore !== undefined) {
    r += normalizeUnitScore(impactScore, true) * 2.2;
  } else if (priceImpact !== undefined) {
    r += Math.min(Math.abs(priceImpact) * 15, 1.5);
  }
  return Math.min(r, 5.5);
}

function getEventAlpha(priority: number, confidenceScore?: number): number {
  if (typeof confidenceScore === 'number') {
    return Math.max(0.25, normalizeUnitScore(confidenceScore));
  }
  return priority === 1 ? 0.8 : priority === 2 ? 0.6 : 0.4;
}

function getEventConfidenceScore(event: BiotechEvent): number | undefined {
  return getNumberValue(event.confidence_score) ?? getNumberValue(event.metadata?.confidence_score);
}

function getEventImpactScore(event: BiotechEvent): number | undefined {
  return getNumberValue(event.impact_score) ?? getNumberValue(event.metadata?.impact_score);
}

function getEventBacktestEligible(event: BiotechEvent): boolean | undefined {
  if (typeof event.backtest_eligible === 'boolean') return event.backtest_eligible;
  if (typeof event.metadata?.backtest_eligible === 'boolean') return event.metadata.backtest_eligible;
  return undefined;
}

function isReportDerivedEvent(event: BiotechEvent): boolean {
  return event.metadata?.derived_from_report === true || event.metadata?.report_bridge === true;
}

function getEventSourceTier(event: BiotechEvent): string | undefined {
  if (typeof event.source_tier === 'string' && event.source_tier.trim()) {
    return event.source_tier.trim();
  }
  if (typeof event.metadata?.source_tier === 'string' && event.metadata.source_tier.trim()) {
    return event.metadata.source_tier.trim();
  }
  return undefined;
}

function normalizeSourceTier(sourceTier?: string): 'primary' | 'secondary' | 'tertiary' | undefined {
  if (!sourceTier) return undefined;
  const normalized = sourceTier.toLowerCase().replace(/[\s_-]+/g, '');
  if (['1', 'tier1', 'primary', 'official', 'exchange', 'regulatory'].includes(normalized)) {
    return 'primary';
  }
  if (['3', 'tier3', 'tertiary', 'derived', 'model', 'inferred'].includes(normalized)) {
    return 'tertiary';
  }
  return 'secondary';
}

function getSourceTierStyle(sourceTier?: string): SourceTierStyle | null {
  const tier = normalizeSourceTier(sourceTier);
  if (tier === 'primary') return { color: '#f8fafc', lineWidth: 1.7 };
  if (tier === 'secondary') return { color: '#cbd5e1', lineWidth: 1.2, dash: [3, 2] };
  if (tier === 'tertiary') return { color: '#64748b', lineWidth: 1, dash: [1.5, 2.5] };
  return null;
}

function formatSourceTier(sourceTier?: string): string {
  if (!sourceTier) return '-';
  return sourceTier.replace(/[_-]+/g, ' ');
}

function formatScore(score?: number, useMagnitude = false): string {
  return score === undefined ? '-' : normalizeUnitScore(score, useMagnitude).toFixed(2);
}

export default function CandlestickChart({
  ohlcData,
  events,
  displayMode,
  onEventClick,
  onAnomalyDetected,
  onHover,
  onRangeSelect,
  highlightedEventId,
  equityCurve,
  signals,
  trades,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const resolvedDisplayMode: ChartDisplayMode = displayMode ?? 'candles_with_backtest';
  const shouldRenderCandles = resolvedDisplayMode !== 'backtest_only';
  const shouldRenderEvents = resolvedDisplayMode !== 'backtest_only';
  const shouldRenderBacktestLine = resolvedDisplayMode !== 'candles_only';
  const shouldRenderTradeAndSignalOverlays = resolvedDisplayMode === 'candles_with_backtest';

  // Refs for interaction state
  const placedRef = useRef<PlacedEvent[]>([]);
  const quadtreeRef = useRef<d3.Quadtree<PlacedEvent> | null>(null);
  const hoveredEventRef = useRef<PlacedEvent | null>(null);
  const marginRef = useRef({ top: 16, right: 40, bottom: 24, left: 48 });
  const [activeTimeframe, setActiveTimeframe] = useState<KlineTimeframe>('day');
  const displayOhlcData = useMemo(
    () => aggregateOhlcForTimeframe(ohlcData || [], activeTimeframe),
    [ohlcData, activeTimeframe],
  );
  const timeframeDateByDate = useMemo(
    () => buildTimeframeDateMap(ohlcData || [], activeTimeframe),
    [ohlcData, activeTimeframe],
  );

  const drawEvents = useCallback((highlight: PlacedEvent | null = null) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const placed = placedRef.current;
    for (const p of placed) {
      const isHover = p === highlight;
      const isHighlighted = highlightedEventId && p.id === highlightedEventId;

      let alpha = p.alpha;
      if (isHover || isHighlighted) alpha = 1;
      ctx.globalAlpha = alpha;

      let radius = p.radius;
      if (isHover || isHighlighted) radius = Math.max(p.radius, 3.5);

      ctx.fillStyle = p.color;

      if (isHover || isHighlighted) {
        ctx.shadowColor = p.color;
        ctx.shadowBlur = 14 * dpr;
      } else {
        ctx.shadowColor = 'transparent';
        ctx.shadowBlur = 0;
      }

      ctx.beginPath();
      ctx.arc(p.px * dpr, p.py * dpr, radius * dpr, 0, Math.PI * 2);
      ctx.fill();

      if (p.reportDerived) {
        ctx.shadowColor = 'transparent';
        ctx.shadowBlur = 0;
        ctx.globalAlpha = isHover || isHighlighted ? 0.95 : Math.max(alpha, 0.55);
        ctx.strokeStyle = 'rgba(248, 250, 252, 0.78)';
        ctx.lineWidth = 1.15 * dpr;
        ctx.setLineDash([2.5 * dpr, 2 * dpr]);
        ctx.beginPath();
        ctx.arc(p.px * dpr, p.py * dpr, (radius + 3.2) * dpr, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
      }

      const sourceTierStyle = getSourceTierStyle(p.sourceTier);
      if (sourceTierStyle) {
        ctx.shadowColor = 'transparent';
        ctx.shadowBlur = 0;
        ctx.globalAlpha = isHover || isHighlighted ? 1 : Math.max(alpha, 0.65);
        ctx.strokeStyle = sourceTierStyle.color;
        ctx.lineWidth = sourceTierStyle.lineWidth * dpr;
        ctx.setLineDash(sourceTierStyle.dash ? sourceTierStyle.dash.map((value) => value * dpr) : []);
        ctx.beginPath();
        ctx.arc(p.px * dpr, p.py * dpr, (radius + 1.8) * dpr, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
      }

      if (isHover || isHighlighted) {
        ctx.shadowColor = p.color;
        ctx.shadowBlur = 10 * dpr;
        ctx.strokeStyle = p.color;
        ctx.lineWidth = 1.5 * dpr;
        ctx.beginPath();
        ctx.arc(p.px * dpr, p.py * dpr, (radius + 3) * dpr, 0, Math.PI * 2);
        ctx.stroke();
      }
    }

    ctx.globalAlpha = 1;
    ctx.shadowColor = 'transparent';
    ctx.shadowBlur = 0;
  }, [highlightedEventId]);

  useEffect(() => {
    if (!displayOhlcData || displayOhlcData.length === 0) return;
    drawChart(displayOhlcData, events || [], timeframeDateByDate, activeTimeframe);
  }, [displayOhlcData, events, highlightedEventId, equityCurve, signals, trades, timeframeDateByDate, activeTimeframe, resolvedDisplayMode]);

  function drawChart(
    rawData: OHLCRow[],
    eventList: BiotechEvent[],
    overlayDateMap: Map<string, string>,
    timeframe: KlineTimeframe,
  ) {
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const container = containerRef.current;
    if (!container) return;

    const fullWidth = container.clientWidth;
    const fullHeight = container.clientHeight || 600;
    const margin = marginRef.current;
    const width = fullWidth - margin.left - margin.right;
    const height = fullHeight - margin.top - margin.bottom;

    svg.attr('width', fullWidth).attr('height', fullHeight);

    const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

    const data = rawData.map((d, i) => ({
      date: new Date(d.date),
      dateStr: d.date,
      open: +d.open,
      high: +d.high,
      low: +d.low,
      close: +d.close,
      volume: +d.volume,
      change: i > 0 ? ((+d.close - +rawData[i - 1].close) / +rawData[i - 1].close) * 100 : 0,
    }));

    const dateToOhlc = new Map<string, typeof data[0]>();
    for (const d of data) {
      dateToOhlc.set(d.dateStr, d);
    }

    const x = d3.scaleTime()
      .domain(d3.extent(data, (d) => d.date) as [Date, Date])
      .range([0, width]);

    const y = d3.scaleLinear()
      .domain([d3.min(data, (d) => d.low)! * 0.92, d3.max(data, (d) => d.high)! * 1.03])
      .range([height, 0]);

    // Grid lines
    g.append('g')
      .attr('class', 'grid-y')
      .call(
        d3.axisLeft(y)
          .ticks(8)
          .tickSize(-width)
          .tickFormat(() => '')
      )
      .selectAll('line')
      .style('stroke', '#1a1e2e')
      .style('stroke-width', 1);
    g.selectAll('.grid-y .domain').remove();

    // X Axis
    g.append('g')
      .attr('transform', `translate(0,${height})`)
      .call(d3.axisBottom(x).ticks(8).tickFormat(d3.timeFormat('%b %y') as any))
      .selectAll('text')
      .style('font-size', '12px')
      .style('fill', '#555');

    // Y Axis
    g.append('g')
      .call(d3.axisLeft(y).ticks(6).tickFormat((d) => `$${Number(d).toFixed(0)}`))
      .selectAll('text')
      .style('font-size', '12px')
      .style('fill', '#555');

    // Right Y-axis and equity curve (only if equityCurve has data)
    const mappedEquityCurve = aggregateEquityCurveForTimeframe(
      equityCurve || [],
      dateToOhlc,
      overlayDateMap,
      timeframe,
    );

    if (shouldRenderBacktestLine && mappedEquityCurve.length > 0) {
      const baseEquity = mappedEquityCurve[0].equity;
      if (Number.isFinite(baseEquity) && baseEquity !== 0) {
        const yEquityReturn = d3.scaleLinear()
          .domain(equityReturnDomain(mappedEquityCurve.map((point) => point.equity), baseEquity))
          .range([height, 0]);

        // Right Y-axis
        g.append('g')
          .attr('transform', `translate(${width},0)`)
          .call(d3.axisRight(yEquityReturn).ticks(6).tickFormat((d) => {
            const returnValue = Number(d);
            return formatEquityReturnTick(baseEquity * (1 + returnValue), baseEquity);
          }))
          .selectAll('text')
          .style('font-size', '12px')
          .style('fill', '#ff9800');

        // Equity curve line
        const equityLine = d3.line<typeof mappedEquityCurve[0]>()
          .x((d) => {
            return x(dateToOhlc.get(d.date)!.date);
          })
          .y((d) => yEquityReturn(d.equity / baseEquity - 1));

        g.append('path')
          .datum(mappedEquityCurve)
          .attr('fill', 'none')
          .attr('stroke', '#ff9800')
          .attr('stroke-width', 2)
          .attr('opacity', 0.6)
          .attr('d', equityLine);
      }
    }

    g.selectAll('.domain').style('stroke', '#1a2030');
    g.selectAll('.tick line').style('stroke', '#1a2030');

    const candleWidth = Math.max(1.5, (width / data.length) * 0.65);

    // Candlesticks
    if (shouldRenderCandles) {
      const candles = g.selectAll('.candle').data(data).enter().append('g').attr('class', 'candle');

      candles.append('line')
        .attr('x1', (d) => x(d.date))
        .attr('x2', (d) => x(d.date))
        .attr('y1', (d) => y(d.high))
        .attr('y2', (d) => y(d.low))
        .attr('stroke', (d) => (d.close >= d.open ? '#00e676' : '#ff5252'))
        .attr('stroke-width', 1);

      candles.append('rect')
        .attr('x', (d) => x(d.date) - candleWidth / 2)
        .attr('y', (d) => y(Math.max(d.open, d.close)))
        .attr('width', candleWidth)
        .attr('height', (d) => Math.max(1, Math.abs(y(d.open) - y(d.close))))
        .attr('fill', (d) => (d.close >= d.open ? '#00e676' : '#ff5252'));
    }

    if (shouldRenderTradeAndSignalOverlays && trades && trades.length > 0) {
      const tradeLayer = g.insert('g', '.candle').attr('class', 'trade-layer');
      trades.forEach((trade) => {
        const entryDate = mapOverlayDateToTimeframe(trade.entry_date, dateToOhlc, overlayDateMap, timeframe);
        const exitDate = mapOverlayDateToTimeframe(trade.exit_date, dateToOhlc, overlayDateMap, timeframe);
        if (!entryDate || !exitDate) return;

        const entry = dateToOhlc.get(entryDate);
        const exit = dateToOhlc.get(exitDate);
        if (!entry || !exit) return;

        const x0 = x(entry.date);
        const x1 = x(exit.date);
        const left = Math.min(x0, x1);
        const widthSpan = Math.max(2, Math.abs(x1 - x0) || candleWidth);
        const color = trade.pnl_pct >= 0 ? '#22c55e' : '#ef4444';

        tradeLayer.append('rect')
          .attr('x', left - candleWidth / 2)
          .attr('y', 0)
          .attr('width', widthSpan + candleWidth)
          .attr('height', height)
          .attr('fill', color)
          .attr('opacity', 0.055);
      });
    }

    if (shouldRenderTradeAndSignalOverlays && signals && signals.length > 0) {
      const signalLayer = g.append('g').attr('class', 'signal-layer');
      signals.forEach((signalItem) => {
        if (signalItem.signal === 0) return;
        const signalDate = mapOverlayDateToTimeframe(signalItem.date, dateToOhlc, overlayDateMap, timeframe);
        if (!signalDate) return;

        const ohlc = dateToOhlc.get(signalDate);
        if (!ohlc) return;

        const cx = x(ohlc.date);
        const isLong = signalItem.signal > 0;
        const cy = isLong ? y(ohlc.low) + 16 : y(ohlc.high) - 16;
        const color = isLong ? '#22c55e' : '#ef4444';
        const points = isLong
          ? `${cx},${cy - 7} ${cx - 6},${cy + 5} ${cx + 6},${cy + 5}`
          : `${cx},${cy + 7} ${cx - 6},${cy - 5} ${cx + 6},${cy - 5}`;
        const opacity = Math.max(0.45, Math.min(1, Number(signalItem.signal_strength) || 0.45));

        signalLayer.append('polygon')
          .attr('points', points)
          .attr('fill', color)
          .attr('stroke', '#0f172a')
          .attr('stroke-width', 1.2)
          .attr('opacity', opacity);
      });
    }

    // Place events overlaid on K-line
    const eventsByDate = new Map<string, BiotechEvent[]>();
    if (shouldRenderEvents) {
      for (const evt of eventList) {
        const eventDate = mapOverlayDateToTimeframe(evt.date, dateToOhlc, overlayDateMap, timeframe);
        if (!eventDate) continue;

        const arr = eventsByDate.get(eventDate) || [];
        arr.push(evt);
        eventsByDate.set(eventDate, arr);
      }
    }

    const placed: PlacedEvent[] = [];
    const eSpacing = Math.max(4.5, Math.min(7, height / 80));

    for (const [dateStr, eArr] of eventsByDate) {
      const ohlc = dateToOhlc.get(dateStr);
      if (!ohlc) continue;

      const cx = x(ohlc.date);

      // Sort: priority 1 first, then by price_impact descending
      eArr.sort((a, b) => {
        if (a.priority !== b.priority) return a.priority - b.priority;
        return Math.abs(b.price_impact || 0) - Math.abs(a.price_impact || 0);
      });

      for (let i = 0; i < eArr.length; i++) {
        const evt = eArr[i];
        const confidenceScore = getEventConfidenceScore(evt);
        const impactScore = getEventImpactScore(evt);
        const sourceTier = getEventSourceTier(evt);
        const backtestEligible = getEventBacktestEligible(evt);
        const reportDerived = isReportDerivedEvent(evt);
        const radius = getEventRadius(evt.priority, evt.price_impact, impactScore);
        const candleLowY = y(ohlc.low);
        const py = margin.top + candleLowY + 6 + i * eSpacing;

        if (py > margin.top + height + 10) break;

        placed.push({
          ...evt,
          px: margin.left + cx,
          py,
          radius,
          color: getEventColor(evt),
          alpha: getEventAlpha(evt.priority, confidenceScore),
          confidenceScore,
          impactScore,
          sourceTier,
          backtestEligible,
          reportDerived,
        });
      }
    }

    placedRef.current = shouldRenderEvents ? placed : [];

    quadtreeRef.current = shouldRenderEvents
      ? d3.quadtree<PlacedEvent>()
        .x((d) => d.px)
        .y((d) => d.py)
        .addAll(placed)
      : null;

    const canvas = canvasRef.current;
    if (canvas) {
      const dpr = window.devicePixelRatio || 1;
      canvas.width = fullWidth * dpr;
      canvas.height = fullHeight * dpr;
      canvas.style.width = `${fullWidth}px`;
      canvas.style.height = `${fullHeight}px`;
      drawEvents();
    }

    // Crosshair elements
    const crossV = g.append('line')
      .style('stroke', '#333')
      .style('stroke-width', 0.5)
      .style('stroke-dasharray', '4,3')
      .style('display', 'none')
      .style('pointer-events', 'none');

    const crossH = g.append('line')
      .style('stroke', '#333')
      .style('stroke-width', 0.5)
      .style('stroke-dasharray', '4,3')
      .style('display', 'none')
      .style('pointer-events', 'none');

    const priceLabel = g.append('g').style('display', 'none');
    priceLabel.append('rect')
      .attr('fill', '#1a1e2e')
      .attr('rx', 3)
      .attr('width', 46)
      .attr('height', 18);
    priceLabel.append('text')
      .attr('fill', '#aaa')
      .attr('font-size', '12px')
      .attr('text-anchor', 'middle')
      .attr('dy', '13px');

    const dateLabel = g.append('g').style('display', 'none');
    dateLabel.append('rect')
      .attr('fill', '#1a1e2e')
      .attr('rx', 3)
      .attr('width', 75)
      .attr('height', 20);
    dateLabel.append('text')
      .attr('fill', '#aaa')
      .attr('font-size', '13px')
      .attr('text-anchor', 'middle')
      .attr('dy', '14px');

    const bisect = d3.bisector<typeof data[0], Date>((d) => d.date).left;

    function snapToData(px: number) {
      const xDate = x.invert(px);
      const idx = bisect(data, xDate, 1);
      const d0 = data[idx - 1];
      const d1 = data[idx];
      if (!d0) return data[0];
      return d1 && xDate.getTime() - d0.date.getTime() > d1.date.getTime() - xDate.getTime() ? d1 : d0;
    }

    function findEvent(mouseX: number, mouseY: number): PlacedEvent | null {
      const qt = quadtreeRef.current;
      if (!qt) return null;
      const searchRadius = 8;
      let closest: PlacedEvent | null = null;
      let closestDist = searchRadius;

      qt.visit((node, x0, y0, x1, y1) => {
        if (!('data' in node)) {
          return x0 > mouseX + searchRadius || x1 < mouseX - searchRadius ||
                 y0 > mouseY + searchRadius || y1 < mouseY - searchRadius;
        }
        let leaf: typeof node | undefined = node;
        while (leaf) {
          const p = leaf.data;
          const dx = p.px - mouseX;
          const dy = p.py - mouseY;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < closestDist) {
            closestDist = dist;
            closest = p;
          }
          leaf = (leaf as any).next;
        }
        return false;
      });

      return closest;
    }

    let brushMoving = false;
    const brush = d3.brushX<unknown>()
      .extent([[0, 0], [width, height + margin.bottom]])
      .on('end', function (event) {
        if (brushMoving) return;
        if (!event.selection) {
          if (event.sourceEvent) {
            const [mx] = d3.pointer(event.sourceEvent, g.node());
            const d = snapToData(mx);
            const [absX, absY] = d3.pointer(event.sourceEvent, container);
            const hit = findEvent(absX, absY);
            if (hit) {
              onEventClick?.(hit);
            }
          }
          return;
        }
        const [x0, x1] = event.selection as [number, number];
        const d0 = snapToData(x0);
        const d1 = snapToData(x1);
        if (d0.dateStr === d1.dateStr) {
          brushMoving = true;
          d3.select(this).call(brush.move, null);
          brushMoving = false;
          return;
        }
        brushMoving = true;
        d3.select(this).call(brush.move, [x(d0.date), x(d1.date)]);
        brushMoving = false;
        const priceChange = ((d1.close - d0.open) / d0.open) * 100;
        const popupX = margin.left + x(d1.date) + 8;
        const popupY = margin.top + Math.min(y(d0.close), y(d1.close)) - 20;
        onRangeSelect?.({ startDate: d0.dateStr, endDate: d1.dateStr, priceChange, popupX, popupY });
      });

    const brushG = g.append('g')
      .attr('class', 'brush')
      .call(brush);

    brushG.selectAll('.selection')
      .attr('fill', '#667eea')
      .attr('fill-opacity', 0.15)
      .attr('stroke', '#667eea')
      .attr('stroke-width', 1);

    brushG.select('.overlay')
      .style('cursor', 'crosshair')
      .on('mousemove.hover', function (event) {
        const [mx, my] = d3.pointer(event);
        const d = snapToData(mx);
        const cx = x(d.date);
        const priceAtY = y.invert(my);

        crossV.attr('x1', cx).attr('x2', cx).attr('y1', 0).attr('y2', height).style('display', null);
        crossH.attr('x1', 0).attr('x2', width).attr('y1', my).attr('y2', my).style('display', null);

        priceLabel.style('display', null)
          .attr('transform', `translate(${-46},${my - 9})`);
        priceLabel.select('text')
          .attr('x', 23)
          .text(`$${priceAtY.toFixed(2)}`);

        dateLabel.style('display', null)
          .attr('transform', `translate(${cx - 37.5},${height})`);
        dateLabel.select('text')
          .attr('x', 37.5)
          .text(d.dateStr);

        onHover?.(d.dateStr, {
          date: d.dateStr,
          open: d.open,
          high: d.high,
          low: d.low,
          close: d.close,
          change: d.change,
        });

        const [absX, absY] = d3.pointer(event, container);
        const hit = findEvent(absX, absY);

        if (hit !== hoveredEventRef.current) {
          hoveredEventRef.current = hit;
          drawEvents(hit);

          const tooltip = tooltipRef.current;
          if (tooltip) {
            if (hit) {
              const tooltipTitle = hit.title || hit.catalyst || hit.summary || hit.type || 'Catalyst';
              const tooltipType = hit.category || hit.type || 'event';
              const impactStr = hit.price_impact !== undefined ? `${(hit.price_impact * 100).toFixed(2)}%` : '-';
              const impactColor = hit.price_impact !== undefined ? (hit.price_impact >= 0 ? '#00e676' : '#ff5252') : '#555';
              const confidenceScore = hit.confidenceScore ?? getEventConfidenceScore(hit);
              const impactScore = hit.impactScore ?? getEventImpactScore(hit);
              const sourceTier = hit.sourceTier || getEventSourceTier(hit);
              const backtestEligible = hit.backtestEligible ?? getEventBacktestEligible(hit);
              const reportDerived = hit.reportDerived ?? isReportDerivedEvent(hit);
              tooltip.replaceChildren();
              const title = document.createElement('div');
              title.className = 'pt-title';
              title.textContent = tooltipTitle;
              const meta = document.createElement('div');
              meta.className = 'pt-meta';
              const type = document.createElement('span');
              type.className = 'pt-sentiment';
              type.style.color = hit.color;
              type.textContent = tooltipType;
              const impact = document.createElement('span');
              impact.className = 'pt-ret';
              impact.style.color = impactColor;
              impact.textContent = `Impact: ${impactStr}`;
              const tier = document.createElement('span');
              tier.className = 'pt-source-tier';
              tier.textContent = `Source tier: ${formatSourceTier(sourceTier)}`;
              const confidence = document.createElement('span');
              confidence.className = 'pt-confidence';
              confidence.textContent = `Confidence: ${formatScore(confidenceScore)}`;
              const score = document.createElement('span');
              score.className = 'pt-impact-score';
              score.textContent = `Impact score: ${formatScore(impactScore, true)}`;
              const backtest = document.createElement('span');
              backtest.className = 'pt-backtest';
              backtest.textContent = `Backtest: ${backtestEligible === true ? 'eligible' : 'visual only'}`;
              if (reportDerived) {
                const origin = document.createElement('span');
                origin.className = 'pt-origin';
                origin.textContent = 'Origin: Report';
                meta.append(type, origin, impact, tier, confidence, score, backtest);
              } else {
                meta.append(type, impact, tier, confidence, score, backtest);
              }
              tooltip.append(title, meta);
              tooltip.style.display = 'block';
              tooltip.style.left = '0px';
              tooltip.style.top = '0px';
              const tipW = tooltip.offsetWidth || 280;
              const tipH = tooltip.offsetHeight || 88;
              const onRight = hit.px < fullWidth / 2;
              const tipX = onRight ? hit.px + 12 : hit.px - tipW - 12;
              const tipY = hit.py - 40;
              const maxX = Math.max(4, fullWidth - tipW - 4);
              const maxY = Math.max(4, fullHeight - tipH - 4);
              tooltip.style.left = `${Math.min(maxX, Math.max(4, tipX))}px`;
              tooltip.style.top = `${Math.min(maxY, Math.max(4, tipY))}px`;
            } else {
              tooltip.style.display = 'none';
            }
          }
        }
      })
      .on('mouseleave.hover', function () {
        crossV.style('display', 'none');
        crossH.style('display', 'none');
        priceLabel.style('display', 'none');
        dateLabel.style('display', 'none');
        onHover?.(null);

        if (hoveredEventRef.current) {
          hoveredEventRef.current = null;
          drawEvents();
        }
        const tooltip = tooltipRef.current;
        if (tooltip) tooltip.style.display = 'none';
      });

    // Anomaly detection
    detectAnomalies(data, shouldRenderEvents ? eventList : []);
  }

  function detectAnomalies(data: any[], eventList: BiotechEvent[]) {
    if (!onAnomalyDetected) return;

    // Volume spike detection: > 2x 5-day average
    for (let i = 4; i < data.length; i++) {
      const avg5 = (data[i - 4].volume + data[i - 3].volume + data[i - 2].volume + data[i - 1].volume + data[i].volume) / 5;
      const spike = data[i].volume / avg5;
      if (spike > 2) {
        onAnomalyDetected({
          ticker: '',
          date: data[i].dateStr,
          type: 'volume_spike',
          magnitude: spike,
        });
      }
    }

    // Gap detection: > 5% price change
    for (let i = 1; i < data.length; i++) {
      const gap = Math.abs((data[i].open - data[i - 1].close) / data[i - 1].close);
      if (gap > 0.05) {
        onAnomalyDetected({
          ticker: '',
          date: data[i].dateStr,
          type: 'gap',
          magnitude: gap,
        });
      }
    }

    // Event cluster detection: >= 3 events on same day
    const eventsByDate = new Map<string, number>();
    for (const evt of eventList) {
      eventsByDate.set(evt.date, (eventsByDate.get(evt.date) || 0) + 1);
    }
    for (const [date, count] of eventsByDate) {
      if (count >= 3) {
        onAnomalyDetected({
          ticker: '',
          date,
          type: 'particle_cluster',
          magnitude: count,
        });
      }
    }
  }

  return (
    <div ref={containerRef} className="chart-container">
      <div className="kline-timeframe-control" role="group" aria-label="K-line timeframe">
        {KLINE_TIMEFRAME_OPTIONS.map((option) => (
          <button
            key={option.id}
            type="button"
            className={`kline-timeframe-button${activeTimeframe === option.id ? ' is-active' : ''}`}
            aria-pressed={activeTimeframe === option.id}
            title={`${option.label} K-line`}
            onClick={() => setActiveTimeframe(option.id)}
          >
            {option.label}
          </button>
        ))}
      </div>
      <svg ref={svgRef}></svg>
      <canvas
        ref={canvasRef}
        className="particle-layer"
      />
      <div ref={tooltipRef} className="particle-tooltip" style={{ display: 'none' }} />
    </div>
  );
}
