// src/kline/chart/types.ts

export interface OHLCRow {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface BiotechEvent {
  id: string;
  date: string;
  type: 'fda_decision' | 'clinical_readout' | 'partnership' | 'financing' | 'patent' | 'competitor' | 'geopolitical' | 'trade_policy' | 'sanctions' | 'regulatory_change' | 'macro_economic';
  priority: 1 | 2 | 3;
  ticker: string;
  disease_area: string;
  catalyst: string;
  sentiment: 'positive' | 'negative' | 'neutral';
  price_impact?: number;
  source?: 'openfda' | 'clinicaltrials' | 'gdelt' | 'cassandra_report' | 'manual';
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

export interface ChartConfig {
  ohlcData: OHLCRow[];
  events: BiotechEvent[];
  onEventClick?: (event: BiotechEvent) => void;
  onAnomalyDetected?: (signal: AnomalySignal) => void;
  onHover?: (date: string | null, ohlc?: HoverData) => void;
  onRangeSelect?: (range: RangeSelection | null) => void;
  highlightedEventId?: string;
  equityCurve?: EquityPoint[];
  signals?: SignalMarker[];
  trades?: TradeMarker[];
}
