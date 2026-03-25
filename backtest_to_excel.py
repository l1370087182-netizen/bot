#!/usr/bin/env python3
"""离线回测并导出中文 Excel。"""

from __future__ import annotations

import argparse
import math
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import requests

# 避免 config.py 在回测时校验真实密钥
os.environ.setdefault("BINANCE_API_KEY", "backtest")
os.environ.setdefault("BINANCE_API_SECRET", "backtest")

from config import (  # noqa: E402
    BACKTEST,
    BREAKEVEN,
    EXIT_STRATEGY,
    FUNDING,
    INDICATORS,
    ENTRY_RULES,
    SIGNAL_QUALITY,
    LEVERAGE,
    MAX_ACTIVE_SYMBOLS,
    PYRAMIDING,
    PYRAMID_TRIGGER_1,
    PYRAMID_TRIGGER_2,
    PROXY_ENABLED,
    PROXY_URL,
    RISK_PER_TRADE,
    RR_2R_MULTIPLE,
    RR_3R_MULTIPLE,
    SIGNAL_WEIGHTS,
    STOP_LOSS_PCT,
    SYMBOLS,
    MARKET_REGIME,
    SYMBOL_STRUCTURE_FILTER,
    get_signal_quality_for_symbol,
)
from strategy import Strategy  # noqa: E402

CSV_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trade_count",
    "taker_buy_base",
    "taker_buy_quote",
    "ignore",
]


@dataclass
class Position:
    trade_id: int
    symbol: str
    side: str
    entry_time: pd.Timestamp
    entry_price: float
    entry_funding: float
    init_qty: float
    qty: float
    entry_balance: float
    executed_exits: List[float] = field(default_factory=list)
    additions: int = 0
    breakeven_on: bool = False
    realized_pnl: float = 0.0
    fee_paid: float = 0.0
    partial_count: int = 0
    max_r: float = -999.0
    min_r: float = 999.0


class BacktestEngine:
    def __init__(
        self,
        data_dir: Path,
        output_dir: Path,
        start: Optional[str],
        end: Optional[str],
        symbols: Optional[List[str]],
        initial_balance: float,
    ):
        self.data_dir = Path(data_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.start = pd.Timestamp(start) if start else None
        self.end = pd.Timestamp(end) if end else None
        self.symbols = symbols or [s.replace("/USDT:USDT", "USDT") for s in SYMBOLS]
        self.initial_balance = float(initial_balance)

        self.strategy = Strategy()
        self.fee_rate = float(BACKTEST.get("fee_rate", 0.0005))
        self.slippage = float(BACKTEST.get("slippage", 0.001))
        self.funding_cache_dir = Path(__file__).resolve().parent / ".funding_cache"
        self.funding_cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        if PROXY_ENABLED and PROXY_URL:
            self.session.proxies.update({"http": PROXY_URL, "https": PROXY_URL})

        self.frames: Dict[str, Dict[str, object]] = {}
        self.timeline: Optional[pd.Index] = None
        self.market_confirm_df: Optional[pd.DataFrame] = None

        self.trade_id = 0
        self.events: List[dict] = []
        self.trades: List[dict] = []
        self.curve: List[dict] = []
        self.load_notes: List[dict] = []

    def run(self) -> Path:
        self._load_data()
        result = self._backtest()
        return self._export_excel(result)

    def _load_csv_set(self, symbol: str, tf: str) -> Optional[pd.DataFrame]:
        folder = self.data_dir / symbol / tf
        if not folder.exists():
            return None
        files = sorted(folder.glob("*.csv"))
        if not files:
            return None

        parts = [pd.read_csv(f, header=None, names=CSV_COLUMNS) for f in files]
        df = pd.concat(parts, ignore_index=True)
        df["open_time"] = pd.to_numeric(df["open_time"], errors="coerce")
        df["close_time"] = pd.to_numeric(df["close_time"], errors="coerce")
        df = df.dropna(subset=["open_time", "close_time"])\
               .drop_duplicates(subset=["open_time"])\
               .sort_values("open_time")

        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")
        for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["open", "high", "low", "close", "volume"])

        if self.start is not None:
            df = df[df["open_time"] >= self.start]
        if self.end is not None:
            df = df[df["open_time"] <= self.end]
        if df.empty:
            return None

        return df.set_index("open_time")

    def _funding_cache_path(self, symbol: str) -> Path:
        return self.funding_cache_dir / f"{symbol}_funding.csv"

    def _read_cached_funding(self, symbol: str) -> pd.DataFrame:
        cache_path = self._funding_cache_path(symbol)
        if not cache_path.exists():
            return pd.DataFrame(columns=["fundingTime", "fundingRate", "markPrice"])
        df = pd.read_csv(cache_path)
        if df.empty:
            return pd.DataFrame(columns=["fundingTime", "fundingRate", "markPrice"])
        df["fundingTime"] = pd.to_datetime(pd.to_numeric(df["fundingTime"], errors="coerce"), unit="ms")
        df["fundingRate"] = pd.to_numeric(df["fundingRate"], errors="coerce")
        df["markPrice"] = pd.to_numeric(df.get("markPrice", 0), errors="coerce")
        return df.dropna(subset=["fundingTime", "fundingRate"]).sort_values("fundingTime").drop_duplicates("fundingTime")

    def _download_funding_history(self, symbol: str, start_ts: pd.Timestamp, end_ts: pd.Timestamp) -> pd.DataFrame:
        url = "https://fapi.binance.com/fapi/v1/fundingRate"
        start_ms = int(start_ts.timestamp() * 1000)
        end_ms = int(end_ts.timestamp() * 1000)
        cursor = start_ms
        rows: List[dict] = []

        while cursor <= end_ms:
            response = self.session.get(
                url,
                params={"symbol": symbol, "startTime": cursor, "endTime": end_ms, "limit": 1000},
                timeout=20,
            )
            response.raise_for_status()
            batch = response.json()
            if not batch:
                break
            rows.extend(batch)
            last_time = int(batch[-1]["fundingTime"])
            if last_time >= end_ms or len(batch) < 1000:
                break
            cursor = last_time + 1
            time.sleep(0.15)

        df = pd.DataFrame(rows)
        if df.empty:
            return pd.DataFrame(columns=["fundingTime", "fundingRate", "markPrice"])
        df["fundingTime"] = pd.to_datetime(pd.to_numeric(df["fundingTime"], errors="coerce"), unit="ms")
        df["fundingRate"] = pd.to_numeric(df["fundingRate"], errors="coerce")
        df["markPrice"] = pd.to_numeric(df.get("markPrice", 0), errors="coerce")
        df = df.dropna(subset=["fundingTime", "fundingRate"]).sort_values("fundingTime").drop_duplicates("fundingTime")
        raw_save = df.copy()
        raw_save["fundingTime"] = (raw_save["fundingTime"].astype("int64") // 10**6).astype("int64")
        raw_save.to_csv(self._funding_cache_path(symbol), index=False)
        return df

    def _load_funding_history(self, symbol: str, start_ts: pd.Timestamp, end_ts: pd.Timestamp) -> pd.DataFrame:
        cached = self._read_cached_funding(symbol)
        need_fetch = cached.empty
        if not cached.empty:
            cached_min = cached["fundingTime"].min()
            cached_max = cached["fundingTime"].max()
            if cached_min > start_ts or cached_max < end_ts:
                need_fetch = True
        if need_fetch:
            try:
                downloaded = self._download_funding_history(symbol, start_ts, end_ts)
            except requests.RequestException as exc:
                print(f"[Funding] {symbol} 下载失败，回退到本地缓存: {exc}")
                downloaded = pd.DataFrame(columns=["fundingTime", "fundingRate", "markPrice"])
            if not downloaded.empty:
                cached = downloaded
        return cached[(cached["fundingTime"] >= start_ts) & (cached["fundingTime"] <= end_ts)].reset_index(drop=True)

    @staticmethod
    def _funding_at(funding_df: pd.DataFrame, ts: pd.Timestamp) -> float:
        if funding_df is None or funding_df.empty:
            return 0.0
        idx = funding_df["fundingTime"].searchsorted(ts, side="right") - 1
        if idx < 0:
            return 0.0
        return float(funding_df.iloc[idx]["fundingRate"])

    def _load_data(self):
        timeline: Optional[pd.Index] = None

        for symbol in self.symbols:
            d15 = self._load_csv_set(symbol, "15m")
            d1h = self._load_csv_set(symbol, "1h")
            if d15 is None or d1h is None:
                self.load_notes.append({"币种": symbol, "状态": "跳过", "原因": "缺少15m或1h数据"})
                continue
            funding = self._load_funding_history(symbol, d15.index.min(), d15.index.max())

            f15 = self.strategy.calculate_indicators(d15[["open", "high", "low", "close", "volume"]].copy())
            f1h = self.strategy.calculate_indicators(d1h[["open", "high", "low", "close", "volume"]].copy())

            # CVD 强度（用于信号打分）
            hl = (f15["high"] - f15["low"]).replace(0, np.nan)
            delta = f15["volume"] * (((f15["close"] - f15["low"]) / hl).fillna(0.5) - 0.5) * 2
            cvd = delta.cumsum()
            f15["cvd_strength"] = np.minimum(
                100.0,
                ((cvd - cvd.shift(20)).abs() / f15["volume"].rolling(20).mean().replace(0, np.nan)).fillna(0.0) * 50.0,
            )
            f15["atr_avg_100"] = f15["atr"].rolling(100).mean()

            f15 = f15.dropna(subset=["ema200", "stoch_k", "stoch_d", "atr", "adx", "plus_di", "minus_di", "atr_avg_100"])
            f1h = f1h.dropna(subset=["ema200", "stoch_k", "stoch_d", "atr", "adx", "plus_di", "minus_di"])
            if len(f15) < 250 or len(f1h) < 150:
                self.load_notes.append({"币种": symbol, "状态": "跳过", "原因": "有效K线不足"})
                continue

            signal_frame = self._build_signal_frame(symbol, f15, f1h, funding)
            loc_map = {ts: i for i, ts in enumerate(f15.index)}
            self.frames[symbol] = {"15m": f15, "1h": f1h, "funding": funding, "signal_frame": signal_frame, "loc_map": loc_map}
            self.load_notes.append(
                {
                    "币种": symbol,
                    "状态": "载入成功",
                    "15m条数": len(f15),
                    "1h条数": len(f1h),
                    "Funding条数": len(funding),
                    "开始": f15.index.min(),
                    "结束": f15.index.max(),
                }
            )
            timeline = f15.index if timeline is None else timeline.union(f15.index)

        if not self.frames or timeline is None or len(timeline) == 0:
            raise RuntimeError("没有可回测的数据")

        self.timeline = timeline.sort_values()
        leader_symbol = MARKET_REGIME.get("leader_symbol")
        if leader_symbol and leader_symbol in self.frames:
            self.market_confirm_df = self.frames[leader_symbol]["1h"]

    def _build_signal_frame(self, symbol: str, f15: pd.DataFrame, f1h: pd.DataFrame, funding: pd.DataFrame) -> pd.DataFrame:
        confirm_idx = f1h.index.searchsorted(f15.index, side="right") - 1
        valid_confirm = confirm_idx >= 0
        conf = f1h.iloc[np.clip(confirm_idx, 0, len(f1h) - 1)].copy()
        conf.index = f15.index

        if funding is not None and not funding.empty:
            funding_idx = funding["fundingTime"].searchsorted(f15.index, side="right") - 1
            funding_vals = np.where(
                funding_idx >= 0,
                funding.iloc[np.clip(funding_idx, 0, len(funding) - 1)]["fundingRate"].to_numpy(),
                np.nan,
            )
            funding_series = pd.Series(funding_vals, index=f15.index, dtype="float64").fillna(0.0)
        else:
            funding_series = pd.Series(0.0, index=f15.index, dtype="float64")

        market_short_ok = pd.Series(True, index=f15.index, dtype="bool")
        if MARKET_REGIME.get("enabled", False) and MARKET_REGIME.get("short_requires_bearish_regime", True):
            market_confirm = self.market_confirm_df if self.market_confirm_df is not None else f1h
            if market_confirm is not None and not market_confirm.empty:
                market_idx = market_confirm.index.searchsorted(f15.index, side="right") - 1
                valid_market = market_idx >= 0
                market = market_confirm.iloc[np.clip(market_idx, 0, len(market_confirm) - 1)].copy()
                market.index = f15.index
                market_short_ok = (
                    valid_market
                    & (market["adx"] >= MARKET_REGIME.get("adx_threshold", 20))
                    & (market["close"] < market["ema200"])
                    & (market["minus_di"] > market["plus_di"])
                )

        structure_ok = pd.Series(True, index=f15.index, dtype="bool")
        long_structure_ok = pd.Series(True, index=f15.index, dtype="bool")
        short_structure_ok = pd.Series(True, index=f15.index, dtype="bool")
        structure_quote_volume = pd.Series(0.0, index=f15.index, dtype="float64")
        structure_body_efficiency = pd.Series(0.0, index=f15.index, dtype="float64")
        structure_di_dominance = pd.Series(0.0, index=f15.index, dtype="float64")
        structure_ema_gap = pd.Series(0.0, index=f15.index, dtype="float64")
        structure_atr_pct = pd.Series(0.0, index=f15.index, dtype="float64")
        structure_trend_efficiency = pd.Series(0.0, index=f15.index, dtype="float64")
        if SYMBOL_STRUCTURE_FILTER.get("enabled", False):
            quote_volume = conf["close"] * conf["volume"]
            candle_range = (conf["high"] - conf["low"]).replace(0, np.nan)
            body_efficiency = ((conf["close"] - conf["open"]).abs() / candle_range).clip(0, 1)
            di_dominance = (
                (conf["plus_di"] - conf["minus_di"]).abs()
                / (conf["plus_di"] + conf["minus_di"]).replace(0, np.nan)
            ).clip(lower=0)
            ema_gap = (
                (conf["close"] - conf["ema200"]).abs()
                / conf["ema200"].replace(0, np.nan)
            ).clip(lower=0)
            atr_pct = (conf["atr"] / conf["close"]).clip(lower=0)
            trend_lookback = SYMBOL_STRUCTURE_FILTER.get("trend_lookback", 12)
            trend_efficiency = (
                conf["close"].diff(trend_lookback).abs()
                / conf["close"].diff().abs().rolling(trend_lookback).sum().replace(0, np.nan)
            ).clip(lower=0, upper=1)

            structure_quote_volume = quote_volume.rolling(
                SYMBOL_STRUCTURE_FILTER.get("volume_window", 24)
            ).median()
            structure_body_efficiency = body_efficiency.rolling(
                SYMBOL_STRUCTURE_FILTER.get("quality_window", 10)
            ).median()
            structure_di_dominance = di_dominance.rolling(
                SYMBOL_STRUCTURE_FILTER.get("quality_window", 10)
            ).median()
            structure_ema_gap = ema_gap.rolling(
                SYMBOL_STRUCTURE_FILTER.get("quality_window", 10)
            ).median()
            structure_atr_pct = atr_pct.rolling(
                SYMBOL_STRUCTURE_FILTER.get("quality_window", 10)
            ).median()
            structure_trend_efficiency = trend_efficiency

            structure_ok = (
                valid_confirm
                & (structure_quote_volume >= SYMBOL_STRUCTURE_FILTER.get("min_quote_volume", 0.0))
                & (structure_body_efficiency >= SYMBOL_STRUCTURE_FILTER.get("min_body_efficiency", 0.0))
                & (structure_di_dominance >= SYMBOL_STRUCTURE_FILTER.get("min_di_dominance", 0.0))
                & (structure_ema_gap >= SYMBOL_STRUCTURE_FILTER.get("min_ema_gap_pct", 0.0))
                & (structure_atr_pct >= SYMBOL_STRUCTURE_FILTER.get("min_atr_pct", 0.0))
                & (structure_trend_efficiency >= SYMBOL_STRUCTURE_FILTER.get("min_trend_efficiency", 0.0))
            )
            long_structure_ok = structure_ok if SYMBOL_STRUCTURE_FILTER.get("apply_to_long", True) else pd.Series(True, index=f15.index, dtype="bool")
            short_structure_ok = structure_ok if SYMBOL_STRUCTURE_FILTER.get("apply_to_short", False) else pd.Series(True, index=f15.index, dtype="bool")

        closed_atr = f15["atr"].shift(1)
        closed_atr_avg = closed_atr.rolling(100).mean()
        vol_ok = (closed_atr > closed_atr_avg * 0.3) & (closed_atr < closed_atr_avg * 4)
        adx_ok = f15["adx"] > INDICATORS["adx"]["threshold"]

        recent_oversold = f15["stoch_k"].shift(1).rolling(ENTRY_RULES["stoch_lookback"]).min() < INDICATORS["stoch_rsi"]["oversold"]
        recent_overbought = f15["stoch_k"].shift(1).rolling(ENTRY_RULES["stoch_lookback"]).max() > INDICATORS["stoch_rsi"]["overbought"]
        long_ema_ok = f15["close"].shift(1) > f15["ema200"].shift(1) * (1 - ENTRY_RULES["ema_buffer_pct"])
        short_ema_ok = f15["close"].shift(1) < f15["ema200"].shift(1) * (1 + ENTRY_RULES["ema_buffer_pct"])
        prev_stoch = f15["stoch_k"].shift(2)
        prev_close = f15["close"].shift(2)
        last_stoch = f15["stoch_k"].shift(1)
        last_close = f15["close"].shift(1)
        last_open = f15["open"].shift(1)
        current_close = f15["close"]
        current_high = f15["high"]
        current_low = f15["low"]
        last_midpoint = (f15["high"].shift(1) + f15["low"].shift(1)) / 2
        confirm_buffer = ENTRY_RULES.get("price_confirm_buffer_pct", 0.0)
        confirm_use_close = ENTRY_RULES.get("price_confirm_use_close", True)
        long_trigger = (
            (last_stoch <= ENTRY_RULES["long_trigger_k_max"])
            & (last_stoch > prev_stoch)
            & (last_close > prev_close)
        )
        recent_rally_high = f15["high"].shift(1).rolling(ENTRY_RULES.get("short_rally_lookback", 4)).max()
        recent_rally_to_ema = recent_rally_high >= f15["ema200"].shift(1) * (1 - ENTRY_RULES["ema_buffer_pct"])
        bearish_rejection = (last_close < last_open) & (last_close < prev_close) & (last_close <= last_midpoint)
        short_stoch_weak = (last_stoch >= ENTRY_RULES["short_trigger_k_min"]) & (last_stoch < prev_stoch)
        short_trigger = recent_rally_to_ema & bearish_rejection & short_stoch_weak
        if ENTRY_RULES.get("price_confirm_enabled", False):
            long_confirm_source = current_close if confirm_use_close else current_high
            short_confirm_source = current_close if confirm_use_close else current_low
            long_price_confirm = long_confirm_source >= f15["high"].shift(1) * (1 + confirm_buffer)
            short_price_confirm = short_confirm_source <= f15["low"].shift(1) * (1 - confirm_buffer)
        else:
            long_price_confirm = pd.Series(True, index=f15.index, dtype="bool")
            short_price_confirm = pd.Series(True, index=f15.index, dtype="bool")

        confirm_trend_up = conf["plus_di"] > conf["minus_di"]
        confirm_price_above_ema = conf["close"] > conf["ema200"]
        confirm_price_below_ema = conf["close"] < conf["ema200"]
        confirm_long_adx_ok = conf["adx"] >= ENTRY_RULES.get("confirm_long_adx_threshold", 20)
        confirm_short_adx_ok = conf["adx"] >= ENTRY_RULES.get("confirm_short_adx_threshold", 25)
        soft_ratio = ENTRY_RULES["soft_confirm_di_ratio"]
        primary_recover_long = (f15["stoch_k"].shift(1) >= f15["stoch_d"].shift(1)) | (f15["plus_di"].shift(1) >= f15["minus_di"].shift(1) * soft_ratio)
        primary_recover_short = (f15["stoch_k"].shift(1) <= f15["stoch_d"].shift(1)) | (f15["minus_di"].shift(1) >= f15["plus_di"].shift(1) * soft_ratio)
        long_confirm = confirm_long_adx_ok & confirm_trend_up & primary_recover_long
        short_confirm = confirm_short_adx_ok & (~confirm_trend_up) & primary_recover_short
        if ENTRY_RULES.get("require_confirm_ema_alignment", True):
            long_confirm = long_confirm & confirm_price_above_ema
            short_confirm = short_confirm & confirm_price_below_ema

        adx_score = np.minimum(f15["adx"], 50) * 2
        shifted_stoch = f15["stoch_k"].shift(1)
        long_stoch_score = np.clip((50 - shifted_stoch) * 2, 0, 100)
        short_stoch_score = np.clip((shifted_stoch - 50) * 2, 0, 100)
        cvd_score = f15.get("cvd_strength", pd.Series(50.0, index=f15.index)).shift(1).fillna(50.0)
        if FUNDING["enabled"]:
            long_funding_score = np.where(funding_series < -FUNDING["threshold"], 100, 30)
            short_funding_score = np.where(funding_series > FUNDING["threshold"], 100, 30)
        else:
            long_funding_score = np.full(len(f15), 50.0)
            short_funding_score = np.full(len(f15), 50.0)

        long_score = adx_score * SIGNAL_WEIGHTS["adx"] + long_stoch_score * SIGNAL_WEIGHTS["stoch_rsi"] + cvd_score * SIGNAL_WEIGHTS["cvd"] + long_funding_score * SIGNAL_WEIGHTS["funding"]
        short_score = adx_score * SIGNAL_WEIGHTS["adx"] + short_stoch_score * SIGNAL_WEIGHTS["stoch_rsi"] + cvd_score * SIGNAL_WEIGHTS["cvd"] + short_funding_score * SIGNAL_WEIGHTS["funding"]
        quality = get_signal_quality_for_symbol(symbol)
        long_enabled = quality.get("enable_long", True)
        short_enabled = quality.get("enable_short", True)
        long_min_score = quality.get("long_min_score", quality["min_score"])
        short_min_score = quality.get("short_min_score", quality["min_score"])
        long_full_score = quality.get("long_full_risk_score", quality["full_risk_score"])
        short_full_score = quality.get("short_full_risk_score", quality["full_risk_score"])
        long_reduced_risk = quality.get("long_reduced_risk_multiplier", quality["reduced_risk_multiplier"])
        short_reduced_risk = quality.get("short_reduced_risk_multiplier", quality["reduced_risk_multiplier"])

        base_valid = valid_confirm & f15["close"].shift(1).notna() & f15["close"].shift(2).notna()
        long_ready = base_valid & long_enabled & vol_ok & adx_ok & recent_oversold & long_ema_ok & long_structure_ok & long_trigger & long_price_confirm & long_confirm & (long_score >= long_min_score)
        short_ready = base_valid & short_enabled & market_short_ok & vol_ok & adx_ok & recent_overbought & short_ema_ok & short_structure_ok & short_trigger & short_price_confirm & short_confirm & (short_score >= short_min_score)

        long_risk = np.where(long_score >= long_full_score, 1.0, np.where(long_score >= long_min_score, long_reduced_risk, 0.0))
        short_risk = np.where(short_score >= short_full_score, 1.0, np.where(short_score >= short_min_score, short_reduced_risk, 0.0))

        return pd.DataFrame(
            {
                "funding_rate": funding_series,
                "vol_ok": vol_ok.fillna(False),
                "adx_ok": adx_ok.fillna(False),
                "recent_oversold": recent_oversold.fillna(False),
                "recent_overbought": recent_overbought.fillna(False),
                "long_ema_ok": long_ema_ok.fillna(False),
                "short_ema_ok": short_ema_ok.fillna(False),
                "structure_ok": structure_ok.fillna(False),
                "long_structure_ok": long_structure_ok.fillna(False),
                "short_structure_ok": short_structure_ok.fillna(False),
                "structure_quote_volume": structure_quote_volume.fillna(0.0),
                "structure_body_efficiency": structure_body_efficiency.fillna(0.0),
                "structure_di_dominance": structure_di_dominance.fillna(0.0),
                "structure_ema_gap": structure_ema_gap.fillna(0.0),
                "structure_atr_pct": structure_atr_pct.fillna(0.0),
                "structure_trend_efficiency": structure_trend_efficiency.fillna(0.0),
                "long_trigger": long_trigger.fillna(False),
                "short_trigger": short_trigger.fillna(False),
                "long_price_confirm": long_price_confirm.fillna(False),
                "short_price_confirm": short_price_confirm.fillna(False),
                "recent_rally_to_ema": recent_rally_to_ema.fillna(False),
                "bearish_rejection": bearish_rejection.fillna(False),
                "short_stoch_weak": short_stoch_weak.fillna(False),
                "market_short_ok": market_short_ok.fillna(False),
                "long_confirm": long_confirm.fillna(False),
                "short_confirm": short_confirm.fillna(False),
                "entry_price_ref": current_close.ffill().fillna(0.0),
                "long_score": pd.Series(long_score, index=f15.index).fillna(0.0),
                "short_score": pd.Series(short_score, index=f15.index).fillna(0.0),
                "long_ready": long_ready.fillna(False),
                "short_ready": short_ready.fillna(False),
                "long_risk_multiplier": pd.Series(long_risk, index=f15.index).fillna(0.0),
                "short_risk_multiplier": pd.Series(short_risk, index=f15.index).fillna(0.0),
            },
            index=f15.index,
        )

    def _build_signal_diagnostics(self) -> pd.DataFrame:
        rows: List[dict] = []

        for symbol, payload in self.frames.items():
            sf: pd.DataFrame = payload["signal_frame"]
            rows.append(
                {
                    "币种": symbol,
                    "15mK线数": int(len(sf)),
                    "多头_波动率": int(sf["vol_ok"].sum()),
                    "多头_ADX": int((sf["vol_ok"] & sf["adx_ok"]).sum()),
                    "多头_近期超卖": int((sf["vol_ok"] & sf["adx_ok"] & sf["recent_oversold"]).sum()),
                    "多头_EMA之上": int((sf["vol_ok"] & sf["adx_ok"] & sf["recent_oversold"] & sf["long_ema_ok"]).sum()),
                    "多头_结构过滤": int((sf["vol_ok"] & sf["adx_ok"] & sf["recent_oversold"] & sf["long_ema_ok"] & sf["long_structure_ok"]).sum()),
                    "多头_回撤反弹": int((sf["vol_ok"] & sf["adx_ok"] & sf["recent_oversold"] & sf["long_ema_ok"] & sf["long_structure_ok"] & sf["long_trigger"]).sum()),
                    "多头_价格确认": int((sf["vol_ok"] & sf["adx_ok"] & sf["recent_oversold"] & sf["long_ema_ok"] & sf["long_structure_ok"] & sf["long_trigger"] & sf["long_price_confirm"]).sum()),
                    "多头_多周期确认": int((sf["vol_ok"] & sf["adx_ok"] & sf["recent_oversold"] & sf["long_ema_ok"] & sf["long_structure_ok"] & sf["long_trigger"] & sf["long_price_confirm"] & sf["long_confirm"]).sum()),
                    "多头_最终触发": int(sf["long_ready"].sum()),
                    "空头_波动率": int(sf["vol_ok"].sum()),
                    "空头_ADX": int((sf["vol_ok"] & sf["adx_ok"]).sum()),
                    "空头_近期超买": int((sf["vol_ok"] & sf["adx_ok"] & sf["recent_overbought"]).sum()),
                    "空头_EMA之下": int((sf["vol_ok"] & sf["adx_ok"] & sf["recent_overbought"] & sf["short_ema_ok"]).sum()),
                    "空头_结构过滤": int((sf["vol_ok"] & sf["adx_ok"] & sf["recent_overbought"] & sf["short_ema_ok"] & sf["short_structure_ok"]).sum()),
                    "空头_市场偏空": int((sf["vol_ok"] & sf["adx_ok"] & sf["recent_overbought"] & sf["short_ema_ok"] & sf["short_structure_ok"] & sf["market_short_ok"]).sum()),
                    "空头_反弹到压力": int((sf["vol_ok"] & sf["adx_ok"] & sf["recent_overbought"] & sf["short_ema_ok"] & sf["short_structure_ok"] & sf["market_short_ok"] & sf["recent_rally_to_ema"]).sum()),
                    "空头_反弹失败": int((sf["vol_ok"] & sf["adx_ok"] & sf["recent_overbought"] & sf["short_ema_ok"] & sf["short_structure_ok"] & sf["market_short_ok"] & sf["recent_rally_to_ema"] & sf["bearish_rejection"] & sf["short_stoch_weak"]).sum()),
                    "空头_价格确认": int((sf["vol_ok"] & sf["adx_ok"] & sf["recent_overbought"] & sf["short_ema_ok"] & sf["short_structure_ok"] & sf["market_short_ok"] & sf["short_trigger"] & sf["short_price_confirm"]).sum()),
                    "空头_多周期确认": int((sf["vol_ok"] & sf["adx_ok"] & sf["recent_overbought"] & sf["short_ema_ok"] & sf["short_structure_ok"] & sf["market_short_ok"] & sf["short_trigger"] & sf["short_price_confirm"] & sf["short_confirm"]).sum()),
                    "空头_最终触发": int(sf["short_ready"].sum()),
                }
            )

        diag_df = pd.DataFrame(rows)
        if diag_df.empty:
            return diag_df

        total_row = {"币种": "合计"}
        for col in diag_df.columns:
            if col == "币种":
                continue
            total_row[col] = int(diag_df[col].sum())
        return pd.concat([diag_df, pd.DataFrame([total_row])], ignore_index=True)

    def _entry_signal(self, symbol: str, loc: int, payload: Dict[str, object]) -> Optional[dict]:
        signal_frame: pd.DataFrame = payload["signal_frame"]
        if loc >= len(signal_frame):
            return None

        row = signal_frame.iloc[loc]
        if not row["long_ready"] and not row["short_ready"]:
            return None

        f15: pd.DataFrame = payload["15m"]
        signal_bar = f15.iloc[loc]
        side = "LONG"
        score = float(row["long_score"])
        risk_multiplier = float(row["long_risk_multiplier"])
        if row["short_ready"] and ((not row["long_ready"]) or float(row["short_score"]) > score):
            side = "SHORT"
            score = float(row["short_score"])
            risk_multiplier = float(row["short_risk_multiplier"])

        return {
            "symbol": symbol,
            "time": f15.index[loc],
            "side": side,
            "score": score,
            "price": float(row.get("entry_price_ref", signal_bar["close"])),
            "funding_rate": float(row["funding_rate"]),
            "risk_multiplier": risk_multiplier,
        }

    def _apply_slippage(self, price: float, side: str, is_entry: bool) -> float:
        if is_entry:
            return price * (1 + self.slippage) if side == "LONG" else price * (1 - self.slippage)
        return price * (1 - self.slippage) if side == "LONG" else price * (1 + self.slippage)

    @staticmethod
    def _pnl(side: str, entry: float, exit_: float, qty: float) -> float:
        return (exit_ - entry) * qty if side == "LONG" else (entry - exit_) * qty

    def _open(self, ts: pd.Timestamp, sig: dict, balance: float, positions: Dict[str, Position]) -> float:
        self.trade_id += 1
        fill = self._apply_slippage(sig["price"], sig["side"], True)
        risk_multiplier = float(sig.get("risk_multiplier", 1.0) or 1.0)
        notional = balance * RISK_PER_TRADE * risk_multiplier * LEVERAGE
        qty = notional / fill if fill > 0 else 0.0
        if qty <= 0:
            return balance
        fee = notional * self.fee_rate
        balance -= fee

        pos = Position(
            trade_id=self.trade_id,
            symbol=sig["symbol"],
            side=sig["side"],
            entry_time=ts,
            entry_price=fill,
            entry_funding=float(sig.get("funding_rate", 0.0)),
            init_qty=qty,
            qty=qty,
            entry_balance=balance + fee,
            realized_pnl=-fee,
            fee_paid=fee,
        )
        positions[sig["symbol"]] = pos
        self.events.append(
            {
                "时间": ts,
                "交易ID": pos.trade_id,
                "币种": pos.symbol,
                "方向": pos.side,
                "事件": "开仓",
                "价格": round(fill, 6),
                "数量": round(qty, 8),
                "R倍数": np.nan,
                "原因": f"信号分数 {sig['score']:.2f} | 风险倍率 {sig.get('risk_multiplier', 1.0):.2f} | Funding {sig.get('funding_rate', 0.0):.6%}",
                "已实现盈亏": round(-fee, 6),
                "手续费": round(fee, 6),
                "余额": round(balance, 6),
            }
        )
        return balance

    def _manage_position(self, ts: pd.Timestamp, pos: Position, row: pd.Series, df_slice: pd.DataFrame, balance: float) -> float:
        price = float(row["close"])
        atr = float(row["atr"])
        r_multiple, price_change = self.strategy.calculate_r_multiple(pos.entry_price, price, pos.side, STOP_LOSS_PCT)
        pos.max_r = max(pos.max_r, r_multiple)
        pos.min_r = min(pos.min_r, r_multiple)

        # 1. 亏损保护：ATR 止损 / 保本止损
        if price_change < 0:
            stop = self.strategy.calculate_atr_stop_loss(pos.entry_price, atr, pos.side)
            if (pos.side == "LONG" and price <= stop) or (pos.side == "SHORT" and price >= stop):
                return self._close(ts, pos, price, balance, f"ATR止损 {stop:.4f}", r_multiple)

            if pos.breakeven_on and BREAKEVEN["enabled"]:
                be = pos.entry_price * (1 + BREAKEVEN["buffer_pct"]) if pos.side == "LONG" else pos.entry_price * (1 - BREAKEVEN["buffer_pct"])
                if (pos.side == "LONG" and price <= be) or (pos.side == "SHORT" and price >= be):
                    return self._close(ts, pos, price, balance, f"保本止损 {be:.4f}", r_multiple)

        # 2. 设置保本
        if BREAKEVEN["enabled"] and (not pos.breakeven_on) and r_multiple >= BREAKEVEN["trigger_r"]:
            pos.breakeven_on = True
            self.events.append(
                {
                    "时间": ts,
                    "交易ID": pos.trade_id,
                    "币种": pos.symbol,
                    "方向": pos.side,
                    "事件": "设置保本",
                    "价格": round(price, 6),
                    "数量": round(pos.qty, 8),
                    "R倍数": round(r_multiple, 4),
                    "原因": f"达到 {BREAKEVEN['trigger_r']}R",
                    "已实现盈亏": round(pos.realized_pnl, 6),
                    "手续费": 0.0,
                    "余额": round(balance, 6),
                }
            )

        # 3. 加仓
        if PYRAMIDING["enabled"] and pos.additions < PYRAMIDING["max_levels"]:
            levels = [
                {"r": PYRAMID_TRIGGER_1, "pct": PYRAMIDING["levels"][0]["size_pct"]},
                {"r": PYRAMID_TRIGGER_2, "pct": PYRAMIDING["levels"][1]["size_pct"]},
            ]
            for i, lv in enumerate(levels):
                if pos.additions <= i and r_multiple >= lv["r"]:
                    add_qty = pos.qty * lv["pct"]
                    if add_qty > 0:
                        add_fill = self._apply_slippage(price, pos.side, True)
                        add_notional = add_qty * add_fill
                        fee = add_notional * self.fee_rate
                        weighted = pos.entry_price * pos.qty + add_fill * add_qty
                        pos.qty += add_qty
                        pos.entry_price = weighted / pos.qty
                        pos.additions += 1
                        pos.fee_paid += fee
                        balance -= fee
                        self.events.append(
                            {
                                "时间": ts,
                                "交易ID": pos.trade_id,
                                "币种": pos.symbol,
                                "方向": pos.side,
                                "事件": "加仓",
                                "价格": round(add_fill, 6),
                                "数量": round(add_qty, 8),
                                "R倍数": round(r_multiple, 4),
                                "原因": f"触发 {lv['r']}R",
                                "已实现盈亏": round(pos.realized_pnl, 6),
                                "手续费": round(fee, 6),
                                "余额": round(balance, 6),
                            }
                        )
                    break

        # 4. 分批止盈
        exit_levels = [
            {"r": RR_2R_MULTIPLE, "pct": EXIT_STRATEGY["r_levels"][0]["exit_pct"]},
            {"r": RR_3R_MULTIPLE, "pct": EXIT_STRATEGY["r_levels"][1]["exit_pct"]},
        ]
        for lv in exit_levels:
            if r_multiple >= lv["r"] and lv["r"] not in pos.executed_exits:
                out_qty = pos.qty * lv["pct"]
                if out_qty > 0:
                    out_fill = self._apply_slippage(price, pos.side, False)
                    gross = self._pnl(pos.side, pos.entry_price, out_fill, out_qty)
                    fee = out_fill * out_qty * self.fee_rate
                    net = gross - fee
                    pos.qty -= out_qty
                    pos.realized_pnl += net
                    pos.fee_paid += fee
                    pos.partial_count += 1
                    pos.executed_exits.append(lv["r"])
                    balance += net
                    self.events.append(
                        {
                            "时间": ts,
                            "交易ID": pos.trade_id,
                            "币种": pos.symbol,
                            "方向": pos.side,
                            "事件": "部分止盈",
                            "价格": round(out_fill, 6),
                            "数量": round(out_qty, 8),
                            "R倍数": round(r_multiple, 4),
                            "原因": f"触发 {lv['r']}R",
                            "已实现盈亏": round(net, 6),
                            "手续费": round(fee, 6),
                            "余额": round(balance, 6),
                        }
                    )
                    if pos.qty <= 1e-10:
                        return self._finalize_trade(ts, pos, out_fill, balance, f"{lv['r']}R后仓位归零", r_multiple)
                break

        # 5. 追踪止损
        if EXIT_STRATEGY["trailing_stop"]["enabled"] and len(pos.executed_exits) >= len(EXIT_STRATEGY["r_levels"]):
            stop_price = self.strategy.calculate_atr_trailing_stop(
                df_slice.tail(100), pos.side, EXIT_STRATEGY["trailing_stop"]["atr_multiplier"]
            )["stop_price"]
            if (pos.side == "LONG" and price <= stop_price) or (pos.side == "SHORT" and price >= stop_price):
                return self._close(ts, pos, price, balance, f"ATR追踪止损 {stop_price:.4f}", r_multiple)

        return balance

    def _close(self, ts: pd.Timestamp, pos: Position, price: float, balance: float, reason: str, r_multiple: float) -> float:
        fill = self._apply_slippage(price, pos.side, False)
        qty = pos.qty
        gross = self._pnl(pos.side, pos.entry_price, fill, qty)
        fee = fill * qty * self.fee_rate
        net = gross - fee
        pos.realized_pnl += net
        pos.fee_paid += fee
        pos.qty = 0.0
        balance += net

        self.events.append(
            {
                "时间": ts,
                "交易ID": pos.trade_id,
                "币种": pos.symbol,
                "方向": pos.side,
                "事件": "平仓",
                "价格": round(fill, 6),
                "数量": round(qty, 8),
                "R倍数": round(r_multiple, 4) if not pd.isna(r_multiple) else np.nan,
                "原因": reason,
                "已实现盈亏": round(net, 6),
                "手续费": round(fee, 6),
                "余额": round(balance, 6),
            }
        )
        return self._finalize_trade(ts, pos, fill, balance, reason, r_multiple)

    def _finalize_trade(self, ts: pd.Timestamp, pos: Position, exit_price: float, balance: float, reason: str, r_multiple: float) -> float:
        hold_hours = (ts - pos.entry_time).total_seconds() / 3600 if ts >= pos.entry_time else 0
        ret = 0 if pos.entry_balance == 0 else pos.realized_pnl / pos.entry_balance
        self.trades.append(
            {
                "交易ID": pos.trade_id,
                "币种": pos.symbol,
                "方向": pos.side,
                "开仓时间": pos.entry_time,
                "平仓时间": ts,
                "开仓价": round(pos.entry_price, 6),
                "平仓价": round(exit_price, 6),
                "入场Funding": pos.entry_funding,
                "初始数量": round(pos.init_qty, 8),
                "累计加仓次数": pos.additions,
                "分批止盈次数": pos.partial_count,
                "持仓小时": round(hold_hours, 4),
                "净收益": round(pos.realized_pnl, 6),
                "手续费": round(pos.fee_paid, 6),
                "净收益率": round(ret, 6),
                "最大R": round(pos.max_r, 4),
                "最小R": round(pos.min_r, 4),
                "平仓原因": reason,
                "是否保本": "是" if pos.breakeven_on else "否",
                "结果": "盈利" if pos.realized_pnl > 0 else "亏损",
                "平仓后余额": round(balance, 6),
            }
        )
        return balance

    def _unrealized(self, positions: Dict[str, Position], last_prices: Dict[str, float]) -> float:
        val = 0.0
        for symbol, p in positions.items():
            mark = last_prices.get(symbol)
            if mark is None:
                continue
            val += self._pnl(p.side, p.entry_price, mark, p.qty)
        return val

    def _backtest(self) -> dict:
        assert self.timeline is not None

        balance = self.initial_balance
        peak = balance
        max_dd = 0.0
        positions: Dict[str, Position] = {}
        last_prices: Dict[str, float] = {}
        last_signal_at: Dict[str, pd.Timestamp] = {}
        day_mark = None
        cooldown_delta = pd.Timedelta(minutes=ENTRY_RULES["signal_cooldown_minutes"])

        for i, ts in enumerate(self.timeline, start=1):
            if i % 5000 == 0:
                print(f"[Backtest] {i}/{len(self.timeline)} ({i/len(self.timeline):.1%})")

            for symbol, payload in self.frames.items():
                loc = payload["loc_map"].get(ts)
                if loc is not None:
                    last_prices[symbol] = float(payload["15m"].iloc[loc]["close"])

            for symbol in list(positions.keys()):
                payload = self.frames[symbol]
                loc = payload["loc_map"].get(ts)
                if loc is None or loc < 220:
                    continue
                row = payload["15m"].iloc[loc]
                balance = self._manage_position(ts, positions[symbol], row, payload["15m"].iloc[: loc + 1], balance)
                if positions[symbol].qty <= 1e-10:
                    positions.pop(symbol, None)

            slots = max(0, MAX_ACTIVE_SYMBOLS - len(positions))
            if slots > 0:
                cands = []
                for symbol, payload in self.frames.items():
                    if symbol in positions:
                        continue
                    last_entry_ts = last_signal_at.get(symbol)
                    if last_entry_ts is not None and ts - last_entry_ts < cooldown_delta:
                        continue
                    loc = payload["loc_map"].get(ts)
                    if loc is None or loc < 220:
                        continue
                    sig = self._entry_signal(symbol, loc, payload)
                    if sig is not None:
                        cands.append(sig)
                cands.sort(key=lambda x: x["score"], reverse=True)
                for sig in cands[:slots]:
                    balance = self._open(ts, sig, balance, positions)
                    last_signal_at[sig["symbol"]] = ts

            equity = balance + self._unrealized(positions, last_prices)
            peak = max(peak, equity)
            dd = 0 if peak == 0 else (peak - equity) / peak
            max_dd = max(max_dd, dd)

            if day_mark != ts.date():
                day_mark = ts.date()
                self.curve.append(
                    {
                        "日期": pd.Timestamp(ts.date()),
                        "余额": round(balance, 4),
                        "权益": round(equity, 4),
                        "回撤比例": round(dd, 6),
                        "持仓数": len(positions),
                    }
                )

        end_ts = self.timeline[-1]
        for symbol in list(positions.keys()):
            mark = last_prices.get(symbol, positions[symbol].entry_price)
            balance = self._close(end_ts, positions[symbol], mark, balance, "回测结束强制平仓", np.nan)
            positions.pop(symbol, None)

        trades_df = pd.DataFrame(self.trades)
        events_df = pd.DataFrame(self.events)
        curve_df = pd.DataFrame(self.curve)

        wins = int((trades_df["净收益"] > 0).sum()) if not trades_df.empty else 0
        losses = int((trades_df["净收益"] <= 0).sum()) if not trades_df.empty else 0
        win_rate = 0.0 if trades_df.empty else wins / len(trades_df)

        gp = float(trades_df.loc[trades_df["净收益"] > 0, "净收益"].sum()) if not trades_df.empty else 0.0
        gl = float(trades_df.loc[trades_df["净收益"] < 0, "净收益"].sum()) if not trades_df.empty else 0.0
        pf = (abs(gp / gl) if gl != 0 else (math.inf if gp > 0 else None))

        symbol_summary = pd.DataFrame()
        if not trades_df.empty:
            symbol_summary = (
                trades_df.groupby("币种")
                .agg(
                    交易笔数=("交易ID", "count"),
                    净收益=("净收益", "sum"),
                    手续费=("手续费", "sum"),
                    平均净收益=("净收益", "mean"),
                    平均持仓小时=("持仓小时", "mean"),
                    最大单笔盈利=("净收益", "max"),
                    最大单笔亏损=("净收益", "min"),
                    胜率=("结果", lambda x: (x == "盈利").mean()),
                )
                .reset_index()
                .sort_values("净收益", ascending=False)
            )

        month_summary = pd.DataFrame()
        year_summary = pd.DataFrame()
        if not trades_df.empty:
            tmp = trades_df.copy()
            tmp["月"] = pd.to_datetime(tmp["平仓时间"]).dt.to_period("M").astype(str)
            tmp["年"] = pd.to_datetime(tmp["平仓时间"]).dt.year.astype(str)
            month_summary = (
                tmp.groupby("月")
                .agg(交易笔数=("交易ID", "count"), 净收益=("净收益", "sum"), 手续费=("手续费", "sum"), 胜率=("结果", lambda x: (x == "盈利").mean()))
                .reset_index()
                .sort_values("月")
            )
            year_summary = (
                tmp.groupby("年")
                .agg(交易笔数=("交易ID", "count"), 净收益=("净收益", "sum"), 手续费=("手续费", "sum"), 胜率=("结果", lambda x: (x == "盈利").mean()))
                .reset_index()
                .sort_values("年")
            )

        signal_diag = self._build_signal_diagnostics()

        return {
            "初始资金": self.initial_balance,
            "最终资金": round(balance, 4),
            "净收益": round(balance - self.initial_balance, 4),
            "收益率": round((balance - self.initial_balance) / self.initial_balance if self.initial_balance else 0.0, 6),
            "最大回撤": round(max_dd, 6),
            "交易笔数": len(trades_df),
            "盈利笔数": wins,
            "亏损笔数": losses,
            "胜率": round(win_rate, 6),
            "盈亏比": (round(pf, 6) if pf is not None and not math.isinf(pf) else pf),
            "平均持仓小时": (round(float(trades_df["持仓小时"].mean()), 4) if not trades_df.empty else 0.0),
            "手续费合计": (round(float(trades_df["手续费"].sum()), 4) if not trades_df.empty else 0.0),
            "数据开始": min(v["15m"].index.min() for v in self.frames.values()),
            "数据结束": max(v["15m"].index.max() for v in self.frames.values()),
            "参与币种数量": len(self.frames),
            "交易明细": trades_df,
            "事件明细": events_df,
            "资金曲线": curve_df,
            "品种汇总": symbol_summary,
            "月度汇总": month_summary,
            "年度汇总": year_summary,
            "数据载入说明": pd.DataFrame(self.load_notes),
            "信号诊断": signal_diag,
            "参数说明": pd.DataFrame(
                [
                    {"参数": "数据目录", "取值": str(self.data_dir)},
                    {"参数": "输出目录", "取值": str(self.output_dir)},
                    {"参数": "回测开始", "取值": str(self.start) if self.start else "全部"},
                    {"参数": "回测结束", "取值": str(self.end) if self.end else "全部"},
                    {"参数": "初始资金", "取值": self.initial_balance},
                    {"参数": "杠杆", "取值": LEVERAGE},
                    {"参数": "风险比例", "取值": RISK_PER_TRADE},
                    {"参数": "手续费率", "取值": self.fee_rate},
                    {"参数": "滑点", "取值": self.slippage},
                    {"参数": "最大持仓数", "取值": MAX_ACTIVE_SYMBOLS},
                    {"参数": "Funding阈值", "取值": FUNDING.get("threshold", 0.0)},
                    {"参数": "信号最低分", "取值": SIGNAL_QUALITY.get("min_score", 0.0)},
                    {"参数": "满风险分数", "取值": SIGNAL_QUALITY.get("full_risk_score", 0.0)},
                    {"参数": "低分风险倍率", "取值": SIGNAL_QUALITY.get("reduced_risk_multiplier", 0.0)},
                    {"参数": "启用做多", "取值": SIGNAL_QUALITY.get("enable_long", True)},
                    {"参数": "启用做空", "取值": SIGNAL_QUALITY.get("enable_short", True)},
                    {"参数": "做多最低分", "取值": SIGNAL_QUALITY.get("long_min_score", SIGNAL_QUALITY.get("min_score", 0.0))},
                    {"参数": "做多满风险分", "取值": SIGNAL_QUALITY.get("long_full_risk_score", SIGNAL_QUALITY.get("full_risk_score", 0.0))},
                    {"参数": "做多低分风险倍率", "取值": SIGNAL_QUALITY.get("long_reduced_risk_multiplier", SIGNAL_QUALITY.get("reduced_risk_multiplier", 0.0))},
                    {"参数": "做空最低分", "取值": SIGNAL_QUALITY.get("short_min_score", SIGNAL_QUALITY.get("min_score", 0.0))},
                    {"参数": "做空满风险分", "取值": SIGNAL_QUALITY.get("short_full_risk_score", SIGNAL_QUALITY.get("full_risk_score", 0.0))},
                    {"参数": "做空低分风险倍率", "取值": SIGNAL_QUALITY.get("short_reduced_risk_multiplier", SIGNAL_QUALITY.get("reduced_risk_multiplier", 0.0))},
                    {"参数": "市场环境过滤", "取值": MARKET_REGIME.get("enabled", False)},
                    {"参数": "市场主导币", "取值": MARKET_REGIME.get("leader_symbol", "")},
                    {"参数": "空头需市场偏空", "取值": MARKET_REGIME.get("short_requires_bearish_regime", True)},
                    {"参数": "市场ADX门槛", "取值": MARKET_REGIME.get("adx_threshold", 0)},
                    {"参数": "结构过滤启用", "取值": SYMBOL_STRUCTURE_FILTER.get("enabled", False)},
                    {"参数": "结构过滤作用于做多", "取值": SYMBOL_STRUCTURE_FILTER.get("apply_to_long", True)},
                    {"参数": "结构过滤作用于做空", "取值": SYMBOL_STRUCTURE_FILTER.get("apply_to_short", False)},
                    {"参数": "价格确认启用", "取值": ENTRY_RULES.get("price_confirm_enabled", False)},
                    {"参数": "价格确认用收盘", "取值": ENTRY_RULES.get("price_confirm_use_close", True)},
                    {"参数": "价格确认缓冲", "取值": ENTRY_RULES.get("price_confirm_buffer_pct", 0.0)},
                    {"参数": "结构过滤成交额窗口", "取值": SYMBOL_STRUCTURE_FILTER.get("volume_window", 0)},
                    {"参数": "结构过滤质量窗口", "取值": SYMBOL_STRUCTURE_FILTER.get("quality_window", 0)},
                    {"参数": "结构过滤趋势窗口", "取值": SYMBOL_STRUCTURE_FILTER.get("trend_lookback", 0)},
                    {"参数": "结构过滤最小成交额", "取值": SYMBOL_STRUCTURE_FILTER.get("min_quote_volume", 0)},
                    {"参数": "结构过滤最小实体效率", "取值": SYMBOL_STRUCTURE_FILTER.get("min_body_efficiency", 0)},
                    {"参数": "结构过滤最小DI主导度", "取值": SYMBOL_STRUCTURE_FILTER.get("min_di_dominance", 0)},
                    {"参数": "结构过滤最小EMA偏离", "取值": SYMBOL_STRUCTURE_FILTER.get("min_ema_gap_pct", 0)},
                    {"参数": "结构过滤最小ATR占比", "取值": SYMBOL_STRUCTURE_FILTER.get("min_atr_pct", 0)},
                    {"参数": "结构过滤最小趋势效率", "取值": SYMBOL_STRUCTURE_FILTER.get("min_trend_efficiency", 0)},
                    {"参数": "多头触发K上限", "取值": ENTRY_RULES.get("long_trigger_k_max", 0)},
                    {"参数": "空头触发K下限", "取值": ENTRY_RULES.get("short_trigger_k_min", 0)},
                    {"参数": "空头反弹观察根数", "取值": ENTRY_RULES.get("short_rally_lookback", 0)},
                    {"参数": "同币种冷却分钟", "取值": ENTRY_RULES.get("signal_cooldown_minutes", 0)},
                    {"参数": "导出时间", "取值": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
                    {"参数": "说明", "取值": "已接入 Binance 历史 funding rate 并用于评分；多头使用回撤反弹，空头使用反弹到压力位后的失败结构；新增 1h 结构过滤优先压制多头噪音时段，空头继续由独立结构与 BTC 市场环境过滤控制；新增价格确认，要求确认K线有效突破前一根高/低点后才触发入场；保本触发延后至1.5R。"},
                ]
            ),
        }

    def _export_excel(self, result: dict) -> Path:
        out_name = f"量化回测结果_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        out_path = self.output_dir / out_name

        summary_df = pd.DataFrame(
            [
                {"指标": "初始资金", "数值": result["初始资金"]},
                {"指标": "最终资金", "数值": result["最终资金"]},
                {"指标": "净收益", "数值": result["净收益"]},
                {"指标": "收益率", "数值": result["收益率"]},
                {"指标": "最大回撤", "数值": result["最大回撤"]},
                {"指标": "交易笔数", "数值": result["交易笔数"]},
                {"指标": "盈利笔数", "数值": result["盈利笔数"]},
                {"指标": "亏损笔数", "数值": result["亏损笔数"]},
                {"指标": "胜率", "数值": result["胜率"]},
                {"指标": "盈亏比", "数值": result["盈亏比"]},
                {"指标": "平均持仓小时", "数值": result["平均持仓小时"]},
                {"指标": "手续费合计", "数值": result["手续费合计"]},
                {"指标": "数据开始", "数值": result["数据开始"]},
                {"指标": "数据结束", "数值": result["数据结束"]},
                {"指标": "参与币种数量", "数值": result["参与币种数量"]},
            ]
        )

        with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
            summary_df.to_excel(writer, sheet_name="回测汇总", index=False)
            result["参数说明"].to_excel(writer, sheet_name="参数说明", index=False)
            result["数据载入说明"].to_excel(writer, sheet_name="数据载入说明", index=False)
            result["品种汇总"].to_excel(writer, sheet_name="品种汇总", index=False)
            result["年度汇总"].to_excel(writer, sheet_name="年度汇总", index=False)
            result["月度汇总"].to_excel(writer, sheet_name="月度汇总", index=False)
            result["信号诊断"].to_excel(writer, sheet_name="信号诊断", index=False)
            result["交易明细"].to_excel(writer, sheet_name="交易明细", index=False)
            result["事件明细"].to_excel(writer, sheet_name="事件明细", index=False)
            result["资金曲线"].to_excel(writer, sheet_name="资金曲线", index=False)

            for ws in writer.book.worksheets:
                ws.freeze_panes = "A2"
                for col_cells in ws.columns:
                    width = max(len(str(c.value)) if c.value is not None else 0 for c in col_cells[:200])
                    ws.column_dimensions[col_cells[0].column_letter].width = min(max(width + 2, 10), 30)

        return out_path


def parse_args():
    p = argparse.ArgumentParser(description="离线回测并导出中文 Excel")
    p.add_argument("--data-dir", default=r"D:\huice", help="数据目录")
    p.add_argument("--output-dir", default=r"E:\\", help="Excel 输出目录")
    p.add_argument("--start", default=None, help="开始日期，例如 2024-01-01")
    p.add_argument("--end", default=None, help="结束日期，例如 2024-12-31")
    p.add_argument("--symbols", default=None, help="币种列表，如 BTCUSDT,ETHUSDT")
    p.add_argument("--initial-balance", type=float, default=1000.0, help="初始资金")
    return p.parse_args()


def main():
    args = parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] if args.symbols else None
    engine = BacktestEngine(
        data_dir=Path(args.data_dir),
        output_dir=Path(args.output_dir),
        start=args.start,
        end=args.end,
        symbols=symbols,
        initial_balance=args.initial_balance,
    )
    out = engine.run()
    print(f"Backtest completed, Excel exported: {out}")


if __name__ == "__main__":
    main()
