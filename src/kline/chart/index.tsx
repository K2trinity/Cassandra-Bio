// src/kline/chart/index.tsx
import { createRoot } from 'react-dom/client';
import CandlestickChart from './CandlestickChart';
import type { ChartConfig } from './types';

export { default as CandlestickChart } from './CandlestickChart';
export type { OHLCRow, BiotechEvent, HoverData, RangeSelection, AnomalySignal, EquityPoint, SignalMarker, TradeMarker, ChartDisplayMode, ChartConfig } from './types';

function render(container: HTMLElement, config: ChartConfig): () => void {
  const root = createRoot(container);
  root.render(
    <CandlestickChart
      ohlcData={config.ohlcData}
      events={config.events}
      displayMode={config.displayMode}
      onEventClick={config.onEventClick}
      onAnomalyDetected={config.onAnomalyDetected}
      onHover={config.onHover}
      onRangeSelect={config.onRangeSelect}
      highlightedEventId={config.highlightedEventId}
      equityCurve={config.equityCurve}
      signals={config.signals}
      trades={config.trades}
    />
  );
  return () => root.unmount();
}

if (typeof window !== 'undefined') {
  (window as any).PokieChart = { render };
}
