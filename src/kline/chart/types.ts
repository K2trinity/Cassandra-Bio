// src/kline/chart/types.ts

export interface OHLCRow {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface BiotechEventMetadata extends Record<string, unknown> {
  backtest_eligible?: boolean;
  confidence_score?: number;
  impact_score?: number;
  source_tier?: string;
}

export interface BiotechEvent {
  id: string;
  ticker: string;
  date: string;
  type: string;
  category?: 'clinical' | 'regulatory' | 'corporate' | 'news' | 'macro' | 'report';
  title?: string;
  summary?: string;
  priority: 1 | 2 | 3 | 4 | 5;
  disease_area?: string;
  catalyst?: string;
  sentiment: 'positive' | 'negative' | 'neutral' | 'unknown';
  confidence?: 'high' | 'medium' | 'low';
  price_impact?: number;
  impact_score?: number;
  confidence_score?: number;
  backtest_eligible?: boolean;
  source?: string;
  source_tier?: string;
  source_entity?: string;
  source_ids?: string[];
  source_url?: string;
  metadata?: BiotechEventMetadata;
}

export interface HoverData {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  change: number;
}

export interface RangeSelection {
  startDate: string;
  endDate: string;
  priceChange?: number;
  popupX?: number;
  popupY?: number;
}

export interface AnomalySignal {
  ticker: string;
  date: string;
  type: 'volume_spike' | 'gap' | 'particle_cluster';
  magnitude: number;
}

export interface EquityPoint {
  date: string;
  equity: number;
}

export interface SignalMarker {
  date: string;
  signal: -1 | 0 | 1;
  signal_strength: number;
  source_event_ids?: string[];
}

export interface TradeMarker {
  entry_date: string;
  exit_date: string;
  direction: 'long' | 'short';
  size: number;
  entry_price: number;
  exit_price: number;
  pnl_pct: number;
}

export type ChartDisplayMode = 'candles_with_backtest' | 'backtest_only' | 'candles_only';

export interface ChartConfig {
  ohlcData: OHLCRow[];
  events: BiotechEvent[];
  displayMode?: ChartDisplayMode;
  onEventClick?: (event: BiotechEvent) => void;
  onAnomalyDetected?: (signal: AnomalySignal) => void;
  onHover?: (date: string | null, ohlc?: HoverData) => void;
  onRangeSelect?: (range: RangeSelection | null) => void;
  highlightedEventId?: string;
  equityCurve?: EquityPoint[];
  signals?: SignalMarker[];
  trades?: TradeMarker[];
}
