"""Backend technical indicator calculations for every stock."""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

from TRADELE.services.data_fetcher import candles_to_dataframe


class IndicatorCalculator:
    """Compute technical indicators from OHLCV candle data."""

    EMA_PERIODS = (5, 9, 20, 50, 100, 200)
    SMA_PERIODS = (20, 50, 200)

    def compute(self, symbol: str, candles: list[dict]) -> Optional[dict[str, Any]]:
        if len(candles) < 20:
            return None

        df = candles_to_dataframe(candles)
        df = self._enrich(df)
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else last

        close = float(last["close"])
        snapshot: dict[str, Any] = {
            "symbol": symbol,
            "close": close,
            "open": float(last.get("open", close)),
            "high": float(last["high"]),
            "low": float(last["low"]),
            "volume": float(last.get("volume", 0)),
            "change_pct": self._pct_change(close, float(prev["close"])),
            "gap_pct": self._pct_change(close, float(prev["close"])),
        }

        for p in self.EMA_PERIODS:
            col = f"ema_{p}"
            if col in df.columns:
                snapshot[col] = self._f(df[col].iloc[-1])
                snapshot[f"prev_{col}"] = self._f(df[col].iloc[-2])

        for p in self.SMA_PERIODS:
            col = f"sma_{p}"
            if col in df.columns:
                snapshot[col] = self._f(df[col].iloc[-1])

        for key in (
            "rsi", "macd", "macd_signal", "macd_hist", "adx", "atr",
            "bb_upper", "bb_middle", "bb_lower", "supertrend", "obv", "cmf", "cci",
            "stoch_rsi", "vwap", "high_20d", "low_20d", "high_52w", "low_52w",
            "volume_ratio", "is_nr7", "dist_ema_20_pct", "dist_ema_50_pct", "dist_ema_200_pct",
        ):
            if key in df.columns:
                snapshot[key] = self._serialize(df[key].iloc[-1])

        return snapshot

    def _enrich(self, df: pd.DataFrame) -> pd.DataFrame:
        c, h, l, v = df["close"], df["high"], df["low"], df["volume"]

        for p in self.EMA_PERIODS:
            df[f"ema_{p}"] = c.ewm(span=p, adjust=False).mean()
        for p in self.SMA_PERIODS:
            df[f"sma_{p}"] = c.rolling(p, min_periods=1).mean()

        df["rsi"] = self._rsi(c)
        macd_line, signal, hist = self._macd(c)
        df["macd"], df["macd_signal"], df["macd_hist"] = macd_line, signal, hist
        df["adx"] = self._adx(h, l, c)
        df["atr"] = self._atr(h, l, c)
        bb_u, bb_m, bb_l = self._bollinger(c)
        df["bb_upper"], df["bb_middle"], df["bb_lower"] = bb_u, bb_m, bb_l
        df["supertrend"] = self._supertrend(h, l, c, df["atr"])
        df["obv"] = self._obv(c, v)
        df["cmf"] = self._cmf(h, l, c, v)
        df["cci"] = self._cci(h, l, c)
        df["stoch_rsi"] = self._stoch_rsi(c)
        df["vwap"] = self._vwap(h, l, c, v)

        df["high_20d"] = h.rolling(20, min_periods=1).max()
        df["low_20d"] = l.rolling(20, min_periods=1).min()
        df["high_52w"] = h.rolling(min(252, len(df)), min_periods=1).max()
        df["low_52w"] = l.rolling(min(252, len(df)), min_periods=1).min()

        vol_avg = v.rolling(20, min_periods=1).mean()
        df["volume_ratio"] = v / vol_avg.replace(0, np.nan)

        daily_range = h - l
        df["is_nr7"] = daily_range == daily_range.rolling(7, min_periods=7).min()

        for p in (20, 50, 200):
            ema_col = f"ema_{p}"
            if ema_col in df.columns:
                df[f"dist_ema_{p}_pct"] = (c - df[ema_col]) / df[ema_col].replace(0, np.nan) * 100

        return df

    @staticmethod
    def _f(val: Any) -> Optional[float]:
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return None
        if isinstance(val, (bool, np.bool_)):
            return bool(val)
        return round(float(val), 4)

    @staticmethod
    def _serialize(val: Any) -> Any:
        if isinstance(val, (bool, np.bool_)):
            return bool(val)
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return None
        return round(float(val), 4)

    @staticmethod
    def _pct_change(current: float, previous: float) -> float:
        if not previous:
            return 0.0
        return round((current - previous) / previous * 100, 2)

    @staticmethod
    def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, 1e-10)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
        ema_fast = series.ewm(span=fast, adjust=False).mean()
        ema_slow = series.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        return macd_line, signal_line, macd_line - signal_line

    @staticmethod
    def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        return tr.ewm(alpha=1 / period, adjust=False).mean()

    @staticmethod
    def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
        atr = IndicatorCalculator._atr(high, low, close, period)
        plus_di = 100 * (plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr.replace(0, 1e-10))
        minus_di = 100 * (minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr.replace(0, 1e-10))
        dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-10) * 100
        return dx.ewm(alpha=1 / period, adjust=False).mean()

    @staticmethod
    def _bollinger(series: pd.Series, period: int = 20, std_dev: float = 2.0):
        mid = series.rolling(period, min_periods=1).mean()
        std = series.rolling(period, min_periods=1).std()
        return mid + std_dev * std, mid, mid - std_dev * std

    @staticmethod
    def _supertrend(high: pd.Series, low: pd.Series, close: pd.Series, atr: pd.Series, mult: float = 3.0) -> pd.Series:
        hl2 = (high + low) / 2
        upper = hl2 + mult * atr
        lower = hl2 - mult * atr
        st = pd.Series(index=close.index, dtype=float)
        direction = pd.Series(1, index=close.index)
        for i in range(1, len(close)):
            if close.iloc[i] > upper.iloc[i - 1]:
                direction.iloc[i] = 1
            elif close.iloc[i] < lower.iloc[i - 1]:
                direction.iloc[i] = -1
            else:
                direction.iloc[i] = direction.iloc[i - 1]
            st.iloc[i] = lower.iloc[i] if direction.iloc[i] == 1 else upper.iloc[i]
        return st

    @staticmethod
    def _obv(close: pd.Series, volume: pd.Series) -> pd.Series:
        direction = np.sign(close.diff()).fillna(0)
        return (direction * volume).cumsum()

    @staticmethod
    def _cmf(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, period: int = 20) -> pd.Series:
        mfm = ((close - low) - (high - close)) / (high - low).replace(0, 1e-10)
        mfv = mfm * volume
        return mfv.rolling(period, min_periods=1).sum() / volume.rolling(period, min_periods=1).sum().replace(0, 1e-10)

    @staticmethod
    def _cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> pd.Series:
        tp = (high + low + close) / 3
        sma = tp.rolling(period, min_periods=1).mean()
        mad = tp.rolling(period, min_periods=1).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
        return (tp - sma) / (0.015 * mad.replace(0, 1e-10))

    @staticmethod
    def _stoch_rsi(series: pd.Series, period: int = 14) -> pd.Series:
        rsi = IndicatorCalculator._rsi(series, period)
        min_rsi = rsi.rolling(period, min_periods=1).min()
        max_rsi = rsi.rolling(period, min_periods=1).max()
        return (rsi - min_rsi) / (max_rsi - min_rsi).replace(0, 1e-10) * 100

    @staticmethod
    def _vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
        tp = (high + low + close) / 3
        cum_vol = volume.cumsum()
        return (tp * volume).cumsum() / cum_vol.replace(0, 1e-10)


def compute_indicators(symbol: str, candles: list[dict]) -> Optional[dict[str, Any]]:
    return IndicatorCalculator().compute(symbol, candles)
