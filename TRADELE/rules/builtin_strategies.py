"""Built-in scanner strategies — seeded into scanner_rules.json on first run."""
from __future__ import annotations

from TRADELE.rules.conditions import Condition, Operator
from TRADELE.rules.registry_types import ScannerStrategy


def get_builtin_strategies() -> list[ScannerStrategy]:
    return _swing_strategies() + _intraday_strategies() + _positional_strategies()


def _swing_strategies() -> list[ScannerStrategy]:
    return [
        ScannerStrategy(
            id="ema_golden_cross",
            name="Golden Cross",
            style="swing",
            description="EMA20 crossed above EMA50 with volume confirmation",
            conditions=[
                Condition(
                    id="ema_cross",
                    label="EMA20 crossed EMA50",
                    field="ema_20",
                    operator=Operator.CROSS_ABOVE,
                    ref_field="ema_50",
                    weight=2.0,
                    reason_template="EMA20 crossed above EMA50",
                ),
                Condition(
                    id="vol_spike",
                    label="Volume > 1.5x avg",
                    field="volume_ratio",
                    operator=Operator.GTE,
                    value=1.5,
                    weight=1.0,
                    reason_template="Volume {value:.1f}x 20-day average",
                ),
                Condition(
                    id="rsi_momentum",
                    label="RSI 50-70",
                    field="rsi",
                    operator=Operator.BETWEEN,
                    value=(50, 70),
                    weight=1.0,
                    reason_template="RSI {value:.0f} (momentum zone)",
                ),
            ],
        ),
        ScannerStrategy(
            id="high_volume_breakout",
            name="High Volume Breakout",
            style="swing",
            description="Price breaks 20-day high with 2x volume",
            conditions=[
                Condition(
                    id="breakout",
                    label="Above 20D high",
                    field="close",
                    operator=Operator.GT,
                    ref_field="high_20d",
                    weight=2.0,
                    reason_template="Breakout above 20D high ({ref:.2f})",
                ),
                Condition(
                    id="vol_2x",
                    label="Volume 2x",
                    field="volume_ratio",
                    operator=Operator.GTE,
                    value=2.0,
                    weight=1.5,
                    reason_template="Volume {value:.1f}x average",
                ),
                Condition(
                    id="macd_bull",
                    label="MACD bullish",
                    field="macd_hist",
                    operator=Operator.GT,
                    value=0,
                    weight=1.0,
                    reason_template="MACD histogram positive",
                ),
            ],
        ),
        ScannerStrategy(
            id="nr7",
            name="NR7",
            style="swing",
            description="Narrowest range in 7 days — volatility contraction",
            conditions=[
                Condition(
                    id="nr7",
                    label="NR7",
                    field="is_nr7",
                    operator=Operator.EQ,
                    value=True,
                    weight=2.0,
                    reason_template="NR7 — narrowest range in 7 days",
                ),
                Condition(
                    id="near_high",
                    label="Near 20D high",
                    field="close",
                    operator=Operator.WITHIN_PCT,
                    ref_field="high_20d",
                    value=3.0,
                    weight=1.0,
                    reason_template="Within {pct}% of 20D high",
                ),
            ],
        ),
    ]


def _intraday_strategies() -> list[ScannerStrategy]:
    return [
        ScannerStrategy(
            id="vwap_bounce",
            name="VWAP Bounce",
            style="intraday",
            description="Price bounced off VWAP with volume",
            conditions=[
                Condition(
                    id="above_vwap",
                    label="Above VWAP",
                    field="close",
                    operator=Operator.GT,
                    ref_field="vwap",
                    weight=1.5,
                    reason_template="Price above VWAP ({ref:.2f})",
                ),
                Condition(
                    id="vol_spike",
                    label="Volume spike",
                    field="volume_ratio",
                    operator=Operator.GTE,
                    value=1.5,
                    weight=1.0,
                    reason_template="Volume {value:.1f}x average",
                ),
                Condition(
                    id="rsi_ok",
                    label="RSI 45-65",
                    field="rsi",
                    operator=Operator.BETWEEN,
                    value=(45, 65),
                    weight=1.0,
                    reason_template="RSI {value:.0f}",
                ),
            ],
        ),
        ScannerStrategy(
            id="gap_up_continuation",
            name="Gap Up Continuation",
            style="intraday",
            description="Gap up with momentum continuation",
            conditions=[
                Condition(
                    id="gap_up",
                    label="Gap up > 1%",
                    field="gap_pct",
                    operator=Operator.GTE,
                    value=1.0,
                    weight=2.0,
                    reason_template="Gap up {value:.1f}%",
                ),
                Condition(
                    id="above_open",
                    label="Above open",
                    field="close",
                    operator=Operator.GT,
                    ref_field="open",
                    weight=1.0,
                    reason_template="Holding above open",
                ),
                Condition(
                    id="vol_confirm",
                    label="Volume confirm",
                    field="volume_ratio",
                    operator=Operator.GTE,
                    value=1.2,
                    weight=1.0,
                    reason_template="Volume {value:.1f}x",
                ),
            ],
        ),
        ScannerStrategy(
            id="volume_spike",
            name="Volume Spike",
            style="intraday",
            description="Unusual volume with price momentum",
            conditions=[
                Condition(
                    id="vol_3x",
                    label="Volume > 3x",
                    field="volume_ratio",
                    operator=Operator.GTE,
                    value=3.0,
                    weight=2.0,
                    reason_template="Volume spike {value:.1f}x",
                ),
                Condition(
                    id="price_up",
                    label="Price up",
                    field="change_pct",
                    operator=Operator.GT,
                    value=0.5,
                    weight=1.0,
                    reason_template="Price up {value:.1f}%",
                ),
            ],
        ),
    ]


def _positional_strategies() -> list[ScannerStrategy]:
    return [
        ScannerStrategy(
            id="near_200_ema",
            name="Near 200 EMA",
            style="positional",
            description="Pullback to 200 EMA in uptrend",
            conditions=[
                Condition(
                    id="uptrend",
                    label="EMA50 > EMA200",
                    field="ema_50",
                    operator=Operator.GT,
                    ref_field="ema_200",
                    weight=1.5,
                    reason_template="Uptrend: EMA50 above EMA200",
                ),
                Condition(
                    id="near_200",
                    label="Within 3% of EMA200",
                    field="close",
                    operator=Operator.WITHIN_PCT,
                    ref_field="ema_200",
                    value=3.0,
                    weight=2.0,
                    reason_template="Within {pct}% of 200 EMA",
                ),
                Condition(
                    id="rsi_ok",
                    label="RSI 40-60",
                    field="rsi",
                    operator=Operator.BETWEEN,
                    value=(40, 60),
                    weight=1.0,
                    reason_template="RSI {value:.0f} (healthy pullback)",
                ),
            ],
        ),
        ScannerStrategy(
            id="52w_high_breakout",
            name="52 Week High Breakout",
            style="positional",
            description="Breaking out near 52-week high",
            conditions=[
                Condition(
                    id="near_52w",
                    label="Within 2% of 52W high",
                    field="close",
                    operator=Operator.WITHIN_PCT,
                    ref_field="high_52w",
                    value=2.0,
                    weight=2.0,
                    reason_template="Within {pct}% of 52-week high",
                ),
                Condition(
                    id="vol_confirm",
                    label="Volume confirm",
                    field="volume_ratio",
                    operator=Operator.GTE,
                    value=1.5,
                    weight=1.0,
                    reason_template="Volume {value:.1f}x average",
                ),
                Condition(
                    id="macd_bull",
                    label="MACD bullish",
                    field="macd_hist",
                    operator=Operator.GT,
                    value=0,
                    weight=1.0,
                    reason_template="MACD positive",
                ),
            ],
        ),
        ScannerStrategy(
            id="weekly_breakout",
            name="Weekly Breakout",
            style="positional",
            description="Monthly/weekly range breakout with trend",
            conditions=[
                Condition(
                    id="above_ema50",
                    label="Above EMA50",
                    field="close",
                    operator=Operator.GT,
                    ref_field="ema_50",
                    weight=1.0,
                    reason_template="Price above EMA50",
                ),
                Condition(
                    id="break_20w",
                    label="Above 20-week high proxy",
                    field="close",
                    operator=Operator.GT,
                    ref_field="high_20d",
                    weight=2.0,
                    reason_template="Breaking recent range high",
                ),
                Condition(
                    id="adx_trend",
                    label="ADX > 20",
                    field="adx",
                    operator=Operator.GTE,
                    value=20,
                    weight=1.0,
                    reason_template="ADX {value:.0f} (trending)",
                ),
            ],
        ),
    ]
