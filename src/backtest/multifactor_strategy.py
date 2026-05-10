from __future__ import annotations

import math
from typing import Any

import pandas as pd

from src.backtest.signals import align_events_to_trading_dates, generate_signals

FACTOR_COLUMNS = [
    "event_factor",
    "momentum_factor",
    "volume_shock",
    "volatility_penalty",
    "liquidity_factor",
    "regime_factor",
]
DEFAULT_MOCK_SIGNAL_THRESHOLD = 0.15
DEFAULT_REAL_MULTIFACTOR_CONFIG = {
    "weights": {
        "trend": 0.45,
        "momentum": 0.35,
        "liquidity": 0.15,
        "volatility": -0.15,
        "event": 0.25,
    },
    "windows": {
        "fast": 12,
        "slow": 36,
        "momentum": 20,
        "volatility": 20,
        "volume": 20,
    },
    "thresholds": {
        "long": 0.18,
        "short": -0.18,
    },
}
REAL_MULTIFACTOR_WEIGHT_KEYS = frozenset(DEFAULT_REAL_MULTIFACTOR_CONFIG["weights"])
REAL_MULTIFACTOR_WINDOW_KEYS = frozenset(DEFAULT_REAL_MULTIFACTOR_CONFIG["windows"])
REAL_MULTIFACTOR_THRESHOLD_KEYS = frozenset(
    DEFAULT_REAL_MULTIFACTOR_CONFIG["thresholds"]
)


class StrategyConfigError(ValueError):
    pass


def generate_mock_multifactor_signals(
    price_window: pd.DataFrame,
    factors: pd.DataFrame,
    threshold: float = DEFAULT_MOCK_SIGNAL_THRESHOLD,
) -> pd.DataFrame:
    threshold = _validate_threshold(threshold)
    signals = price_window[["date"]].copy()
    signals["date"] = _normalize_dates(signals["date"])
    signals = signals.merge(
        _factor_scores(factors),
        on="date",
        how="left",
        validate="many_to_one",
    )
    signals["mock_score"] = signals["mock_score"].fillna(0.0)
    active = signals["mock_score"] > threshold
    signals["signal"] = active.astype(int)
    signals["signal_strength"] = signals["mock_score"].where(active, 0.0).clip(
        lower=0.0,
        upper=1.0,
    )
    return signals[["date", "signal", "signal_strength"]]


def generate_real_multifactor_signals(
    price_window: pd.DataFrame,
    events_df: pd.DataFrame,
    report_confidence: float = 1.0,
    strategy_config: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Generate non-hindsight signals from visible OHLC history and optional events.

    All price-derived features are shifted one trading day, so a signal emitted
    for date T only uses data available before T. The strategy executor then
    enters on T+1, preserving the no-lookahead boundary.
    """
    if price_window.empty or "date" not in price_window.columns:
        return pd.DataFrame(columns=["date", "signal", "signal_strength"])

    config = normalize_real_multifactor_strategy_config(strategy_config)
    weights = config["weights"]
    windows = config["windows"]
    thresholds = config["thresholds"]

    required_columns = {"date", "close"}
    if not required_columns.issubset(price_window.columns):
        return pd.DataFrame(columns=["date", "signal", "signal_strength"])

    rows = price_window.copy()
    rows["date"] = _normalize_dates(rows["date"])
    rows["close"] = _coerce_numeric_series(rows["close"])
    if "volume" not in rows.columns:
        rows["volume"] = 0.0
    rows["volume"] = _coerce_numeric_series(rows["volume"])
    rows = rows.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    if rows.empty:
        return pd.DataFrame(columns=["date", "signal", "signal_strength"])

    close = rows["close"].clip(lower=0.01)
    returns = close.pct_change()
    fast_ma = close.rolling(
        windows["fast"],
        min_periods=max(2, windows["fast"] // 2),
    ).mean()
    slow_ma = close.rolling(
        windows["slow"],
        min_periods=max(3, windows["slow"] // 3),
    ).mean()
    trend = ((fast_ma / slow_ma) - 1).clip(-0.08, 0.08) / 0.08
    momentum = close.pct_change(windows["momentum"]).clip(-0.25, 0.25) / 0.25
    volatility = (
        returns.rolling(
            windows["volatility"],
            min_periods=max(3, windows["volatility"] // 2),
        )
        .std()
        .fillna(0.0)
    )
    volatility_penalty = (volatility / 0.08).clip(0.0, 1.0)
    volume_ratio = (
        rows["volume"]
        / rows["volume"]
        .rolling(windows["volume"], min_periods=max(3, windows["volume"] // 4))
        .mean()
        .clip(lower=1.0)
    ).replace([math.inf, -math.inf], 1.0).fillna(1.0)
    liquidity = (volume_ratio - 1.0).clip(-0.5, 0.5) / 0.5

    price_score = (
        weights["trend"] * trend.fillna(0.0)
        + weights["momentum"] * momentum.fillna(0.0)
        + weights["liquidity"] * liquidity.fillna(0.0)
        + weights["volatility"] * volatility_penalty.fillna(0.0)
    ).shift(1).fillna(0.0)

    event_component = _event_component(rows, events_df, report_confidence)
    score = (price_score + weights["event"] * event_component).clip(-1.0, 1.0)

    signals = rows[["date"]].copy()
    signals["signal"] = 0
    signals.loc[score > thresholds["long"], "signal"] = 1
    signals.loc[score < thresholds["short"], "signal"] = -1
    signals["signal_strength"] = score.abs().where(signals["signal"] != 0, 0.0).clip(
        lower=0.0,
        upper=1.0,
    )
    return signals[["date", "signal", "signal_strength"]]


def summarize_factor_attribution(
    factors: pd.DataFrame,
    threshold: float = DEFAULT_MOCK_SIGNAL_THRESHOLD,
) -> dict[str, Any]:
    threshold = _validate_threshold(threshold)
    try:
        rows = _normalized_factor_rows(factors)
    except (AttributeError, KeyError, TypeError, ValueError):
        return _empty_factor_attribution()
    if rows.empty:
        return _empty_factor_attribution()

    active = rows[rows["mock_score"] > threshold]
    if active.empty:
        return _empty_factor_attribution()

    summary = {
        "active_factor_days": int(len(active)),
        "mean_mock_score": _round_float(active["mock_score"].mean()),
    }
    for column in FACTOR_COLUMNS:
        summary[f"mean_{column}"] = _round_float(active[column].mean())
    return summary


def _event_component(
    price_window: pd.DataFrame,
    events_df: pd.DataFrame,
    report_confidence: float,
) -> pd.Series:
    component = pd.Series(0.0, index=price_window.index)
    if events_df.empty:
        return component

    try:
        aligned_events = align_events_to_trading_dates(events_df, price_window)
        event_signals = generate_signals(
            price_window,
            aligned_events,
            report_confidence=report_confidence,
        )
    except (KeyError, TypeError, ValueError):
        return component
    if event_signals.empty:
        return component

    event_rows = event_signals[["date", "signal", "signal_strength"]].copy()
    event_rows["date"] = _normalize_dates(event_rows["date"])
    merged = price_window[["date"]].merge(event_rows, on="date", how="left")
    event_direction = merged["signal"].fillna(0.0) * merged["signal_strength"].fillna(0.0)
    return event_direction.shift(1).fillna(0.0)


def normalize_real_multifactor_strategy_config(
    value: dict[str, Any] | None,
) -> dict[str, dict[str, float | int]]:
    config: dict[str, dict[str, float | int]] = {
        section: dict(values)
        for section, values in DEFAULT_REAL_MULTIFACTOR_CONFIG.items()
    }
    if value is None:
        return config
    if not isinstance(value, dict):
        raise StrategyConfigError("strategy_config must be an object")

    unknown_sections = sorted(set(value) - {"weights", "windows", "thresholds"})
    if unknown_sections:
        raise StrategyConfigError(
            "strategy_config contains unsupported sections: "
            + ", ".join(unknown_sections)
        )

    _merge_float_section(
        config["weights"],
        value.get("weights"),
        section_name="weights",
        allowed_keys=REAL_MULTIFACTOR_WEIGHT_KEYS,
        min_value=-5.0,
        max_value=5.0,
    )
    _merge_int_section(
        config["windows"],
        value.get("windows"),
        section_name="windows",
        allowed_keys=REAL_MULTIFACTOR_WINDOW_KEYS,
        min_value=2,
        max_value=504,
    )
    _merge_float_section(
        config["thresholds"],
        value.get("thresholds"),
        section_name="thresholds",
        allowed_keys=REAL_MULTIFACTOR_THRESHOLD_KEYS,
        min_value=-1.0,
        max_value=1.0,
    )

    if int(config["windows"]["fast"]) >= int(config["windows"]["slow"]):
        raise StrategyConfigError(
            "strategy_config.windows.fast must be less than strategy_config.windows.slow"
        )
    if float(config["thresholds"]["short"]) >= float(config["thresholds"]["long"]):
        raise StrategyConfigError(
            "strategy_config.thresholds.short must be less than strategy_config.thresholds.long"
        )
    if float(config["thresholds"]["long"]) <= 0:
        raise StrategyConfigError("strategy_config.thresholds.long must be positive")
    if float(config["thresholds"]["short"]) >= 0:
        raise StrategyConfigError("strategy_config.thresholds.short must be negative")

    return config


def real_multifactor_formula(config: dict[str, Any] | None = None) -> str:
    resolved = normalize_real_multifactor_strategy_config(config)
    weights = resolved["weights"]
    windows = resolved["windows"]
    thresholds = resolved["thresholds"]
    return (
        "alpha = "
        f"{weights['trend']} * trend({windows['fast']},{windows['slow']}) + "
        f"{weights['momentum']} * momentum({windows['momentum']}) + "
        f"{weights['liquidity']} * liquidity({windows['volume']}) + "
        f"{weights['volatility']} * volatility({windows['volatility']}) + "
        f"{weights['event']} * event_score; "
        f"long alpha > {thresholds['long']}; "
        f"short alpha < {thresholds['short']}"
    )


def _merge_float_section(
    target: dict[str, float | int],
    raw: object,
    *,
    section_name: str,
    allowed_keys: frozenset[str],
    min_value: float,
    max_value: float,
) -> None:
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise StrategyConfigError(f"strategy_config.{section_name} must be an object")
    unknown = sorted(set(raw) - allowed_keys)
    if unknown:
        raise StrategyConfigError(
            f"strategy_config.{section_name} contains unsupported keys: "
            + ", ".join(unknown)
        )
    for key, value in raw.items():
        number = _finite_number(
            value,
            f"strategy_config.{section_name}.{key}",
            min_value=min_value,
            max_value=max_value,
        )
        target[key] = number


def _merge_int_section(
    target: dict[str, float | int],
    raw: object,
    *,
    section_name: str,
    allowed_keys: frozenset[str],
    min_value: int,
    max_value: int,
) -> None:
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise StrategyConfigError(f"strategy_config.{section_name} must be an object")
    unknown = sorted(set(raw) - allowed_keys)
    if unknown:
        raise StrategyConfigError(
            f"strategy_config.{section_name} contains unsupported keys: "
            + ", ".join(unknown)
        )
    for key, value in raw.items():
        number = _finite_number(
            value,
            f"strategy_config.{section_name}.{key}",
            min_value=float(min_value),
            max_value=float(max_value),
        )
        if not float(number).is_integer():
            raise StrategyConfigError(
                f"strategy_config.{section_name}.{key} must be an integer"
            )
        target[key] = int(number)


def _finite_number(
    value: object,
    label: str,
    *,
    min_value: float,
    max_value: float,
) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise StrategyConfigError(f"{label} must be numeric") from exc
    if not math.isfinite(number):
        raise StrategyConfigError(f"{label} must be finite")
    if not (min_value <= number <= max_value):
        raise StrategyConfigError(
            f"{label} must be between {min_value:g} and {max_value:g}"
        )
    return number


def _factor_scores(factors: pd.DataFrame) -> pd.DataFrame:
    return _normalized_factor_rows(factors)[["date", "mock_score"]]


def _normalized_factor_rows(factors: pd.DataFrame) -> pd.DataFrame:
    if not factors.columns.is_unique:
        raise ValueError("factors must have unique columns")
    if factors.empty:
        return _empty_normalized_factor_rows()
    if "date" not in factors.columns:
        return _empty_normalized_factor_rows()

    rows = factors.copy()
    rows["date"] = _normalize_dates(rows["date"])
    for column in ["mock_score", *FACTOR_COLUMNS]:
        if column not in rows.columns:
            rows[column] = 0.0
        rows[column] = _coerce_numeric_series(rows[column])

    rows = rows.dropna(subset=["date"])
    if rows.empty:
        return _empty_normalized_factor_rows()

    rows = rows[["date", "mock_score", *FACTOR_COLUMNS]].reset_index(drop=True)
    rows["_source_order"] = range(len(rows))
    rows = rows.sort_values(
        ["date", "mock_score", "_source_order"],
        ascending=[True, False, True],
        kind="mergesort",
    )
    rows = rows.drop_duplicates(subset=["date"], keep="first")
    return rows.drop(columns=["_source_order"]).reset_index(drop=True)


def _normalize_dates(values: pd.Series) -> pd.Series:
    dates = values.apply(_normalize_date_value)
    return pd.to_datetime(dates, errors="coerce").astype("datetime64[ns]")


def _normalize_date_value(value: object) -> pd.Timestamp:
    try:
        date = pd.Timestamp(value)
    except (TypeError, ValueError):
        return pd.NaT
    if pd.isna(date):
        return pd.NaT
    if date.tzinfo is not None:
        date = date.tz_localize(None)
    return date.normalize()


def _coerce_numeric_series(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    return numeric.replace([math.inf, -math.inf], 0.0).fillna(0.0).astype(float)


def _empty_normalized_factor_rows() -> pd.DataFrame:
    rows = {
        "date": pd.Series(dtype="datetime64[ns]"),
        "mock_score": pd.Series(dtype="float64"),
    }
    for column in FACTOR_COLUMNS:
        rows[column] = pd.Series(dtype="float64")
    return pd.DataFrame(rows)


def _validate_threshold(threshold: float) -> float:
    try:
        number = float(threshold)
    except (TypeError, ValueError) as exc:
        raise ValueError("threshold must be non-negative") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError("threshold must be non-negative")
    return number


def _empty_factor_attribution() -> dict[str, Any]:
    summary: dict[str, Any] = {
        "active_factor_days": 0,
        "mean_mock_score": 0.0,
    }
    for column in FACTOR_COLUMNS:
        summary[f"mean_{column}"] = 0.0
    return summary


def _round_float(value: object) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return round(number, 6)
