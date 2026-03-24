#!/usr/bin/env python3
"""
Binance Bot Web Dashboard
"""

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import psutil
import pytz
import requests
from flask import Flask, Response, jsonify, request, send_file
from flask_cors import CORS

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from config import (  # noqa: E402
    FUNDING,
    INDICATORS,
    PRIMARY_TIMEFRAME,
    CONFIRM_TIMEFRAME,
    PROXY_ENABLED,
    PROXY_URL,
    SYMBOLS,
)
from strategy import Strategy  # noqa: E402


app = Flask(__name__)
CORS(app)

BEIJING_TZ = pytz.timezone("Asia/Shanghai")
BOT_DIR = os.path.dirname(os.path.abspath(__file__))
STATUS_FILE = os.path.join(BOT_DIR, ".bot_status")
DB_FILE = os.path.join(BOT_DIR, "trades.db")
LOG_FILE = os.path.join(BOT_DIR, "bot.log")
BOT_SCRIPT = os.path.join(BOT_DIR, "bot.py")
PID_FILE = os.path.join(BOT_DIR, "bot.pid")
IP_CACHE_FILE = os.path.join(BOT_DIR, ".ip_cache")
BINANCE_FAPI_BASE = "https://fapi.binance.com"
TRACKED_SYMBOLS = SYMBOLS

last_bark_ranking_time = 0
BARK_RANKING_INTERVAL = 3600


def to_beijing_time(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return dt
    if dt.tzinfo is None:
        dt = pytz.UTC.localize(dt)
    return dt.astimezone(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")


class BotManager:
    @staticmethod
    def _find_processes():
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                cmdline = " ".join(proc.info["cmdline"] or [])
                if "bot.py" in cmdline and "--real" in cmdline:
                    yield proc
            except Exception:
                continue

    @staticmethod
    def is_running():
        for proc in BotManager._find_processes():
            with open(PID_FILE, "w", encoding="utf-8") as handle:
                handle.write(str(proc.pid))
            return True
        return False

    @staticmethod
    def get_running_pid():
        for proc in BotManager._find_processes():
            return str(proc.pid)
        return None

    @staticmethod
    def _kill_all_bots():
        for proc in BotManager._find_processes():
            try:
                proc.terminate()
            except Exception:
                continue
        time.sleep(1)
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)

    @staticmethod
    def start():
        if BotManager.is_running():
            return {"success": False, "message": "机器人已经在运行中"}

        BotManager._kill_all_bots()

        try:
            import shutil

            python_exe = shutil.which("python") or shutil.which("pythonw") or "python.exe"
            with open(LOG_FILE, "w", encoding="utf-8") as handle:
                handle.write("")
            with open(LOG_FILE, "a", encoding="utf-8") as log_handle:
                process = subprocess.Popen(
                    [python_exe, BOT_SCRIPT, "--real"],
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    cwd=BOT_DIR,
                    creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
                )
            with open(PID_FILE, "w", encoding="utf-8") as handle:
                handle.write(str(process.pid))
            time.sleep(3)
            if BotManager.is_running():
                return {"success": True, "message": f"机器人已启动 (PID: {process.pid})"}
            return {"success": False, "message": "进程启动后异常退出，请检查日志"}
        except Exception as exc:
            return {"success": False, "message": f"启动失败: {exc}"}

    @staticmethod
    def stop():
        try:
            pid = BotManager.get_running_pid()
            if pid:
                psutil.Process(int(pid)).terminate()
                time.sleep(2)
                if BotManager.is_running():
                    psutil.Process(int(pid)).kill()
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)
            time.sleep(1)
            if not BotManager.is_running():
                return {"success": True, "message": "机器人已停止"}
            return {"success": False, "message": "停止失败，请手动结束进程"}
        except Exception as exc:
            return {"success": False, "message": f"停止失败: {exc}"}

    @staticmethod
    def restart():
        BotManager.stop()
        time.sleep(2)
        return BotManager.start()


class LogReader:
    @staticmethod
    def _level_from_line(line):
        upper = line.upper()
        if "ERROR" in upper or "❌" in line:
            return "ERROR"
        if "WARNING" in upper or "⚠" in line:
            return "WARNING"
        if "[OPEN]" in line or "[CLOSE]" in line or "[PARTIAL]" in line or "[PYRAMID]" in line:
            return "TRADE"
        if "[SIGNAL]" in line or "✅" in line:
            return "SIGNAL"
        return "INFO"

    @staticmethod
    def get_recent_logs(lines=120):
        try:
            if not os.path.exists(LOG_FILE):
                return []
            with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as handle:
                recent_logs = handle.readlines()[-lines:]
            parsed = []
            for raw_line in recent_logs:
                line = raw_line.strip()
                if not line:
                    continue
                parsed.append(
                    {
                        "line": line,
                        "level": LogReader._level_from_line(line),
                        "timestamp": line[:19] if len(line) >= 19 else "",
                    }
                )
            return parsed
        except Exception as exc:
            return [{"line": f"读取日志失败: {exc}", "level": "ERROR", "timestamp": ""}]

    @staticmethod
    def search_logs(keyword, lines=50):
        try:
            if not os.path.exists(LOG_FILE):
                return []
            with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as handle:
                matched = [line.strip() for line in handle.readlines() if keyword in line]
            return matched[-lines:]
        except Exception as exc:
            return [f"日志搜索失败: {exc}"]

    @staticmethod
    def get_connection_state():
        try:
            if not os.path.exists(LOG_FILE):
                return {"state": "unknown", "message": "暂无日志"}
            with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as handle:
                recent = [line.strip() for line in handle.readlines()[-80:] if line.strip()]
            for line in reversed(recent):
                if "418 I'm a teapot" in line or "Too many requests" in line or '"code":-1003' in line:
                    return {"state": "limited", "message": "Binance API 限频中"}
                if "交易所连接成功" in line:
                    return {"state": "connected", "message": "Binance API 已连接"}
            return {"state": "unknown", "message": "等待连接状态"}
        except Exception as exc:
            return {"state": "unknown", "message": f"状态读取失败: {exc}"}


class WebDashboard:
    def __init__(self):
        self.strategy = Strategy(TRACKED_SYMBOLS)
        self.session = requests.Session()
        self.snapshot_ttl = 1
        self.snapshot_refresh_interval = 1
        self.market_chart_ttl = 1800
        self.snapshot_cache = None
        self.snapshot_cache_time = 0.0
        self.market_chart_cache = None
        self.market_chart_cache_time = 0.0
        self.cache_lock = threading.Lock()
        self.refresh_lock = threading.Lock()
        self.stop_event = threading.Event()

        if PROXY_ENABLED and PROXY_URL:
            self.session.proxies.update({"http": PROXY_URL, "https": PROXY_URL})

        self._refresh_snapshot()
        self.refresh_thread = threading.Thread(target=self._snapshot_refresh_loop, name="dashboard-snapshot", daemon=True)
        self.refresh_thread.start()

    def _request_binance(self, path, params=None):
        response = self.session.get(
            f"{BINANCE_FAPI_BASE}{path}",
            params=params or {},
            timeout=5,
        )
        response.raise_for_status()
        return response.json()

    def _snapshot_refresh_loop(self):
        while not self.stop_event.is_set():
            started = time.time()
            self._refresh_snapshot()
            elapsed = time.time() - started
            self.stop_event.wait(max(0.1, self.snapshot_refresh_interval - elapsed))

    @staticmethod
    def _api_symbol(symbol):
        return symbol.replace("/USDT:USDT", "USDT")

    @staticmethod
    def _display_symbol(symbol):
        return symbol.replace(":USDT", "")

    @staticmethod
    def _ohlcv_to_df(rows):
        df = pd.DataFrame(
            rows,
            columns=[
                "open_time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "close_time",
                "quote_volume",
                "trades",
                "taker_buy_base",
                "taker_buy_quote",
                "ignore",
            ],
        )
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        for column in ["open", "high", "low", "close", "volume"]:
            df[column] = df[column].astype(float)
        return df.set_index("open_time")[["open", "high", "low", "close", "volume"]]

    @staticmethod
    def _resample_ohlcv(df, rule, limit=None):
        resampled = (
            df.resample(rule)
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            .dropna()
        )
        if limit is not None:
            resampled = resampled.tail(limit)
        return resampled

    def _fetch_symbol_klines(self, api_symbol, interval, limit):
        rows = self._request_binance(
            "/fapi/v1/klines",
            {"symbol": api_symbol, "interval": interval, "limit": limit},
        )
        return self._ohlcv_to_df(rows)

    def _fetch_market_context(self):
        tickers = self._request_binance("/fapi/v1/ticker/24hr")
        funding_rows = self._request_binance("/fapi/v1/premiumIndex")
        ticker_map = {row["symbol"]: row for row in tickers}
        funding_map = {row["symbol"]: float(row.get("lastFundingRate", 0) or 0) for row in funding_rows}
        return ticker_map, funding_map

    @staticmethod
    def _calc_cvd_strength(df):
        high_low = (df["high"] - df["low"]).replace(0, np.nan)
        delta = df["volume"] * (((df["close"] - df["low"]) / high_low).fillna(0.5) - 0.5) * 2
        cvd = delta.cumsum()
        cvd_delta = abs(cvd.iloc[-1] - cvd.iloc[-20])
        avg_volume = df["volume"].rolling(20).mean().iloc[-1]
        if avg_volume <= 0 or pd.isna(avg_volume):
            return 50.0
        return float(min(100.0, (cvd_delta / avg_volume) * 50.0))

    @staticmethod
    def _funding_filter_pass(side, funding_rate):
        if side == "buy":
            return not (funding_rate > 0.0005)
        return not (funding_rate < -0.0005)

    def _multitimeframe_confirm(self, df_primary, df_confirm, signal_side):
        last_primary = df_primary.iloc[-1]
        last_confirm = df_confirm.iloc[-1]
        adx_ok = last_confirm["adx"] >= 20
        primary_up = last_primary["plus_di"] > last_primary["minus_di"]
        confirm_up = last_confirm["plus_di"] > last_confirm["minus_di"]
        if signal_side == "buy":
            return adx_ok and primary_up and confirm_up
        return adx_ok and (not primary_up) and (not confirm_up)

    @staticmethod
    def _condition_row(label, ok, good_emoji="✅", bad_emoji="❌"):
        return {"label": label, "ok": bool(ok), "emoji": good_emoji if ok else bad_emoji}

    def _analyze_symbol(self, symbol, ticker_map, funding_map):
        api_symbol = self._api_symbol(symbol)
        display_symbol = self._display_symbol(symbol)
        raw_15m = self._fetch_symbol_klines(api_symbol, PRIMARY_TIMEFRAME, 480)
        df_15m = self.strategy.calculate_indicators(raw_15m.copy())
        df_1h = self.strategy.calculate_indicators(self._resample_ohlcv(raw_15m, "1h", limit=120).copy())

        curr = df_15m.iloc[-1]
        last_closed = df_15m.iloc[-2]
        prev_closed = df_15m.iloc[-3]
        ticker = ticker_map.get(api_symbol, {})
        funding_rate = float(funding_map.get(api_symbol, 0.0))
        vol_ok = self.strategy.check_volatility_filter(df_15m)
        adx_ok = curr["adx"] > INDICATORS["adx"]["threshold"]
        long_stoch_ok = last_closed["stoch_k"] < INDICATORS["stoch_rsi"]["oversold"]
        short_stoch_ok = last_closed["stoch_k"] > INDICATORS["stoch_rsi"]["overbought"]
        long_ema_ok = last_closed["close"] > last_closed["ema200"]
        short_ema_ok = last_closed["close"] < last_closed["ema200"]
        golden_cross = last_closed["stoch_k"] > last_closed["stoch_d"] and prev_closed["stoch_k"] <= prev_closed["stoch_d"]
        dead_cross = last_closed["stoch_k"] < last_closed["stoch_d"] and prev_closed["stoch_k"] >= prev_closed["stoch_d"]
        long_confirm_ok = self._multitimeframe_confirm(df_15m, df_1h, "buy")
        short_confirm_ok = self._multitimeframe_confirm(df_15m, df_1h, "sell")
        long_funding_ok = self._funding_filter_pass("buy", funding_rate)
        short_funding_ok = self._funding_filter_pass("sell", funding_rate)
        cvd_strength = self._calc_cvd_strength(df_15m)

        long_score = round(
            float(self.strategy.calculate_signal_score(curr["adx"], last_closed["stoch_k"], cvd_strength, funding_rate, "buy")),
            2,
        )
        short_score = round(
            float(self.strategy.calculate_signal_score(curr["adx"], last_closed["stoch_k"], cvd_strength, funding_rate, "sell")),
            2,
        )

        long_conditions = [
            self._condition_row("波动率过滤", vol_ok),
            self._condition_row(f"ADX>{INDICATORS['adx']['threshold']}", adx_ok),
            self._condition_row(f"Stoch<{INDICATORS['stoch_rsi']['oversold']}", long_stoch_ok),
            self._condition_row("价格站上EMA200", long_ema_ok),
            self._condition_row("15m金叉", golden_cross),
            self._condition_row("1h趋势确认", long_confirm_ok),
            self._condition_row("Funding不过热", long_funding_ok),
        ]
        short_conditions = [
            self._condition_row("波动率过滤", vol_ok),
            self._condition_row(f"ADX>{INDICATORS['adx']['threshold']}", adx_ok),
            self._condition_row(f"Stoch>{INDICATORS['stoch_rsi']['overbought']}", short_stoch_ok),
            self._condition_row("价格跌破EMA200", short_ema_ok),
            self._condition_row("15m死叉", dead_cross),
            self._condition_row("1h趋势确认", short_confirm_ok),
            self._condition_row("Funding不过冷", short_funding_ok),
        ]

        long_failed = [f"{item['emoji']} {item['label']}" for item in long_conditions if not item["ok"]]
        short_failed = [f"{item['emoji']} {item['label']}" for item in short_conditions if not item["ok"]]
        long_passed = [f"{item['emoji']} {item['label']}" for item in long_conditions if item["ok"]]
        short_passed = [f"{item['emoji']} {item['label']}" for item in short_conditions if item["ok"]]

        return {
            "symbol": display_symbol,
            "exchange_symbol": api_symbol,
            "price": float(ticker.get("lastPrice", last_closed["close"])),
            "change_24h": float(ticker.get("priceChangePercent", 0.0)),
            "volume_24h": float(ticker.get("quoteVolume", 0.0)),
            "adx": round(float(curr["adx"]), 2),
            "stoch": round(float(last_closed["stoch_k"]), 2),
            "ema200": round(float(last_closed["ema200"]), 4),
            "funding": round(funding_rate * 100, 4),
            "cvd_strength": round(cvd_strength, 2),
            "long_score": long_score,
            "short_score": short_score,
            "long_ready": not long_failed,
            "short_ready": not short_failed,
            "long_failed": long_failed,
            "short_failed": short_failed,
            "long_passed": long_passed,
            "short_passed": short_passed,
            "long_fail_count": len(long_failed),
            "short_fail_count": len(short_failed),
            "signal_bias": "LONG" if long_score >= short_score else "SHORT",
            "long_conditions": long_conditions,
            "short_conditions": short_conditions,
        }

    def _fallback_symbol_row(self, symbol, ticker_map, funding_map, error):
        api_symbol = self._api_symbol(symbol)
        display_symbol = self._display_symbol(symbol)
        ticker = ticker_map.get(api_symbol, {})
        funding_rate = float(funding_map.get(api_symbol, 0.0))
        long_conditions = [
            self._condition_row("波动率过滤", False),
            self._condition_row(f"ADX>{INDICATORS['adx']['threshold']}", False),
            self._condition_row(f"Stoch<{INDICATORS['stoch_rsi']['oversold']}", False),
            self._condition_row("价格站上EMA200", False),
            self._condition_row("15m金叉", False),
            self._condition_row("1h趋势确认", False),
            self._condition_row("Funding不过热", False),
        ]
        short_conditions = [
            self._condition_row("波动率过滤", False),
            self._condition_row(f"ADX>{INDICATORS['adx']['threshold']}", False),
            self._condition_row(f"Stoch>{INDICATORS['stoch_rsi']['overbought']}", False),
            self._condition_row("价格跌破EMA200", False),
            self._condition_row("15m死叉", False),
            self._condition_row("1h趋势确认", False),
            self._condition_row("Funding不过冷", False),
        ]
        reason = f"⚠️ 数据刷新失败: {error}"
        return {
            "symbol": display_symbol,
            "exchange_symbol": api_symbol,
            "price": float(ticker.get("lastPrice", 0.0)),
            "change_24h": float(ticker.get("priceChangePercent", 0.0)),
            "volume_24h": float(ticker.get("quoteVolume", 0.0)),
            "adx": 0.0,
            "stoch": 0.0,
            "ema200": 0.0,
            "funding": round(funding_rate * 100, 4),
            "cvd_strength": 0.0,
            "long_score": 0.0,
            "short_score": 0.0,
            "long_ready": False,
            "short_ready": False,
            "long_failed": [reason],
            "short_failed": [reason],
            "long_passed": [],
            "short_passed": [],
            "long_fail_count": len(long_conditions),
            "short_fail_count": len(short_conditions),
            "signal_bias": "LONG",
            "long_conditions": long_conditions,
            "short_conditions": short_conditions,
        }

    def _market_stats_from_tickers(self, ticker_map):
        tracked_changes = []
        for symbol in TRACKED_SYMBOLS:
            row = ticker_map.get(self._api_symbol(symbol))
            if row:
                tracked_changes.append(float(row.get("priceChangePercent", 0.0)))
        up = sum(1 for value in tracked_changes if value > 1)
        down = sum(1 for value in tracked_changes if value < -1)
        neutral = len(tracked_changes) - up - down
        if up > down * 1.2:
            condition = "上涨"
        elif down > up * 1.2:
            condition = "下跌"
        else:
            condition = "震荡"
        return {"up": up, "down": down, "neutral": neutral, "total": len(tracked_changes), "condition": condition}

    def _build_snapshot(self):
        now = time.time()
        ticker_map, funding_map = self._fetch_market_context()

        with self.cache_lock:
            market_stats = self.market_chart_cache
            market_chart_cache_time = self.market_chart_cache_time

        if market_stats is None or now - market_chart_cache_time >= self.market_chart_ttl:
            market_stats = {
                **self._market_stats_from_tickers(ticker_map),
                "updated_at": to_beijing_time(datetime.now()),
            }
            with self.cache_lock:
                self.market_chart_cache = market_stats
                self.market_chart_cache_time = time.time()

        scan_details = []
        with ThreadPoolExecutor(max_workers=max(1, len(TRACKED_SYMBOLS))) as executor:
            futures = {
                executor.submit(self._analyze_symbol, symbol, ticker_map, funding_map): symbol
                for symbol in TRACKED_SYMBOLS
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    scan_details.append(future.result())
                except Exception as exc:
                    scan_details.append(self._fallback_symbol_row(symbol, ticker_map, funding_map, exc))

        scan_details.sort(key=lambda row: max(row["long_score"], row["short_score"]), reverse=True)
        long_rankings = sorted(scan_details, key=lambda row: row["long_score"], reverse=True)
        short_rankings = sorted(scan_details, key=lambda row: row["short_score"], reverse=True)

        payload = {
            "long_rankings": [
                {
                    "symbol": row["symbol"],
                    "score": row["long_score"],
                    "adx": row["adx"],
                    "stoch": row["stoch"],
                    "price": row["price"],
                    "change_24h": row["change_24h"],
                    "funding": row["funding"],
                    "ready": row["long_ready"],
                    "failed_reasons": row["long_failed"],
                }
                for row in long_rankings
            ],
            "short_rankings": [
                {
                    "symbol": row["symbol"],
                    "score": row["short_score"],
                    "adx": row["adx"],
                    "stoch": row["stoch"],
                    "price": row["price"],
                    "change_24h": row["change_24h"],
                    "funding": row["funding"],
                    "ready": row["short_ready"],
                    "failed_reasons": row["short_failed"],
                }
                for row in short_rankings
            ],
            "scan_details": scan_details,
            "market_condition": market_stats["condition"],
            "market_stats": market_stats,
            "ranking_signature": {
                "long": "|".join(f"{row['symbol']}:{row['long_score']:.2f}" for row in long_rankings[:5]),
                "short": "|".join(f"{row['symbol']}:{row['short_score']:.2f}" for row in short_rankings[:5]),
            },
            "scan_signature": "|".join(
                f"{row['symbol']}:{row['long_score']:.2f}:{row['short_score']:.2f}:{row['change_24h']:.2f}:{row['funding']:.4f}"
                for row in scan_details
            ),
            "timestamp": to_beijing_time(datetime.now()),
        }
        return payload

    def _refresh_snapshot(self):
        if not self.refresh_lock.acquire(blocking=False):
            with self.cache_lock:
                return self.snapshot_cache
        try:
            payload = self._build_snapshot()
            with self.cache_lock:
                self.snapshot_cache = payload
                self.snapshot_cache_time = time.time()
            return payload
        except Exception as exc:
            with self.cache_lock:
                if self.snapshot_cache is not None:
                    return self.snapshot_cache
            return {
                "error": str(exc),
                "long_rankings": [],
                "short_rankings": [],
                "scan_details": [],
                "market_condition": "未知",
                "market_stats": {"up": 0, "down": 0, "neutral": 0, "total": 0, "updated_at": None},
                "ranking_signature": {"long": "", "short": ""},
                "scan_signature": "",
                "timestamp": to_beijing_time(datetime.now()),
            }
        finally:
            self.refresh_lock.release()

    def get_symbol_rankings(self, force=False):
        with self.cache_lock:
            snapshot = self.snapshot_cache
            snapshot_cache_time = self.snapshot_cache_time

        if snapshot is None:
            return self._refresh_snapshot()

        if force:
            refreshed = self._refresh_snapshot()
            return refreshed if refreshed is not None else snapshot

        if time.time() - snapshot_cache_time > self.snapshot_ttl * 2:
            self._refresh_snapshot()
            with self.cache_lock:
                return self.snapshot_cache or snapshot

        return snapshot

    def get_signal_prediction(self):
        try:
            rankings = self.get_symbol_rankings()
            scans = rankings.get("scan_details", [])
            ready_long = [row for row in scans if row["long_ready"]]
            ready_short = [row for row in scans if row["short_ready"]]
            closest = min(scans, key=lambda row: min(row["long_fail_count"], row["short_fail_count"])) if scans else None

            if ready_long or ready_short:
                return {
                    "status": "active",
                    "message": "已有接近或达到开仓条件的币种，注意排行榜顶部信号。",
                    "prediction": "随时可能开仓",
                    "confidence": "high",
                    "long_candidates": ready_long[:5],
                    "short_candidates": ready_short[:5],
                    "timestamp": to_beijing_time(datetime.now()),
                }

            if closest:
                miss_side = "做多" if closest["long_fail_count"] <= closest["short_fail_count"] else "做空"
                miss_count = min(closest["long_fail_count"], closest["short_fail_count"])
                return {
                    "status": "waiting",
                    "message": f"{closest['symbol']} 最接近 {miss_side} 开仓，还差 {miss_count} 个条件。",
                    "prediction": "观察中",
                    "confidence": "medium" if miss_count <= 2 else "low",
                    "long_candidates": rankings.get("long_rankings", [])[:5],
                    "short_candidates": rankings.get("short_rankings", [])[:5],
                    "timestamp": to_beijing_time(datetime.now()),
                }

            return {
                "status": "waiting",
                "message": "暂时没有足够接近开仓条件的币种。",
                "prediction": "暂无机会",
                "confidence": "low",
                "long_candidates": [],
                "short_candidates": [],
                "timestamp": to_beijing_time(datetime.now()),
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def get_bot_status(self):
        try:
            if os.path.exists(STATUS_FILE):
                with open(STATUS_FILE, "r", encoding="utf-8") as handle:
                    status = json.load(handle)
                if "timestamp" in status:
                    status["beijing_time"] = to_beijing_time(datetime.fromtimestamp(status["timestamp"]))
                return status
        except Exception:
            pass
        return {"status": "unknown", "balance": 0, "positions": []}

    def get_performance_metrics(self):
        default = {
            "error": None,
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0,
            "net_pnl": 0,
            "today_pnl": 0,
            "today_trades": 0,
            "recent_trades": [],
        }
        try:
            if not os.path.exists(DB_FILE):
                default["error"] = "Database not found"
                return default

            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trades'")
            if not cursor.fetchone():
                conn.close()
                default["error"] = "Trades table not found"
                return default

            seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()
            cursor.execute(
                """
                SELECT COUNT(*),
                       SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END),
                       SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END),
                       SUM(pnl)
                FROM trades
                WHERE exit_time >= ?
                """,
                (seven_days_ago,),
            )
            total, wins, losses, net_pnl = cursor.fetchone()
            total = total or 0
            wins = wins or 0
            losses = losses or 0
            net_pnl = net_pnl or 0

            cursor.execute(
                """
                SELECT SUM(pnl), COUNT(*)
                FROM trades
                WHERE date(exit_time) = date('now', 'localtime')
                """
            )
            today_pnl, today_trades = cursor.fetchone()

            cursor.execute(
                """
                SELECT symbol, side, pnl, pnl_pct, exit_time
                FROM trades
                ORDER BY exit_time DESC
                LIMIT 10
                """
            )
            recent_trades = cursor.fetchall()
            conn.close()

            return {
                "error": None,
                "total_trades": total,
                "winning_trades": wins,
                "losing_trades": losses,
                "win_rate": round((wins / total * 100) if total else 0, 2),
                "net_pnl": round(net_pnl, 2),
                "today_pnl": round(today_pnl or 0, 2),
                "today_trades": today_trades or 0,
                "recent_trades": [
                    {
                        "symbol": row[0],
                        "side": row[1],
                        "pnl": round(row[2] or 0, 2),
                        "pnl_pct": round(row[3] or 0, 2),
                        "time": to_beijing_time(row[4]),
                    }
                    for row in recent_trades
                ],
            }
        except Exception as exc:
            default["error"] = str(exc)
            return default

    def get_position_details(self):
        status = self.get_bot_status()
        positions = status.get("positions", [])
        return [
            {
                "symbol": pos.get("symbol"),
                "side": pos.get("side"),
                "size": pos.get("size"),
                "entry_price": pos.get("entry_price"),
                "mark_price": pos.get("mark_price"),
                "pnl": pos.get("unrealized_pnl"),
                "pnl_pct": pos.get("price_change_pct", 0) * 100,
                "leverage": pos.get("leverage"),
                "liquidation_price": pos.get("liquidation_price"),
            }
            for pos in positions
        ]


dashboard = WebDashboard()


@app.route("/")
def index():
    return send_file("web_dashboard.html")


@app.route("/ranking")
def ranking_page():
    return send_file("web_dashboard.html")


@app.route("/api/status")
def api_status():
    return jsonify(dashboard.get_bot_status())


@app.route("/api/performance")
def api_performance():
    return jsonify(dashboard.get_performance_metrics())


@app.route("/api/positions")
def api_positions():
    return jsonify(dashboard.get_position_details())


@app.route("/api/rankings")
def api_rankings():
    return jsonify(dashboard.get_symbol_rankings())


@app.route("/api/summary")
def api_summary():
    rankings = dashboard.get_symbol_rankings()
    connection_state = LogReader.get_connection_state()
    return jsonify(
        {
            "status": dashboard.get_bot_status(),
            "performance": dashboard.get_performance_metrics(),
            "positions": dashboard.get_position_details(),
            "bot_connection": connection_state,
            "rankings": {
                "long": rankings.get("long_rankings", [])[:5],
                "short": rankings.get("short_rankings", [])[:5],
                "market_stats": rankings.get("market_stats", {}),
                "market_condition": rankings.get("market_condition"),
                "signature": rankings.get("ranking_signature", {}),
            },
            "bot_running": BotManager.is_running(),
            "timestamp": to_beijing_time(datetime.now()),
        }
    )


@app.route("/api/bot/status")
def api_bot_status():
    return jsonify({"running": BotManager.is_running(), "pid": BotManager.get_running_pid()})


@app.route("/api/bot/start", methods=["POST"])
def api_bot_start():
    return jsonify(BotManager.start())


@app.route("/api/bot/stop", methods=["POST"])
def api_bot_stop():
    return jsonify(BotManager.stop())


@app.route("/api/bot/restart", methods=["POST"])
def api_bot_restart():
    return jsonify(BotManager.restart())


@app.route("/api/logs")
def api_logs():
    lines = request.args.get("lines", 120, type=int)
    return jsonify(
        {
            "logs": LogReader.get_recent_logs(lines),
            "scan_details": dashboard.get_symbol_rankings().get("scan_details", []),
            "timestamp": to_beijing_time(datetime.now()),
        }
    )


@app.route("/api/logs/search")
def api_logs_search():
    keyword = request.args.get("keyword", "")
    lines = request.args.get("lines", 50, type=int)
    return jsonify({"logs": LogReader.search_logs(keyword, lines)})


@app.route("/api/prediction")
def api_prediction():
    result = dashboard.get_signal_prediction()
    global last_bark_ranking_time
    current_time = time.time()
    if current_time - last_bark_ranking_time >= BARK_RANKING_INTERVAL:
        try:
            from bark_notifier import bark

            long_candidates = result.get("long_candidates", [])
            short_candidates = result.get("short_candidates", [])
            prediction = result.get("prediction", "未知")
            if long_candidates or short_candidates:
                if bark.notify_ranking(long_candidates, short_candidates, 0, prediction):
                    last_bark_ranking_time = current_time
        except Exception:
            pass
    return jsonify(result)


def load_cached_ip():
    try:
        if os.path.exists(IP_CACHE_FILE):
            with open(IP_CACHE_FILE, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data.get("ip"), data.get("timestamp")
    except Exception:
        pass
    return None, None


def save_cached_ip(ip):
    try:
        with open(IP_CACHE_FILE, "w", encoding="utf-8") as handle:
            json.dump({"ip": ip, "timestamp": datetime.now().isoformat()}, handle)
    except Exception:
        pass


def get_current_ip():
    proxies = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_ENABLED and PROXY_URL else None
    services = [
        "https://api.ipify.org?format=json",
        "https://httpbin.org/ip",
        "https://api.my-ip.io/ip.json",
    ]
    for service in services:
        try:
            response = requests.get(service, timeout=5, proxies=proxies)
            data = response.json()
            if "ip" in data:
                return data["ip"]
            if "origin" in data:
                return data["origin"].split(",")[0].strip()
        except Exception:
            continue
    return "unknown"


def check_binance_connection():
    try:
        proxies = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_ENABLED and PROXY_URL else None
        response = requests.get(f"{BINANCE_FAPI_BASE}/fapi/v1/ping", timeout=5, proxies=proxies)
        return "connected" if response.status_code == 200 else "error"
    except Exception:
        return "disconnected"


last_detected_ip, last_detected_time = load_cached_ip()


@app.route("/api/ip/current")
def api_ip_current():
    return jsonify(
        {
            "current_ip": last_detected_ip,
            "cached_at": last_detected_time,
            "binance_status": "unknown",
            "timestamp": to_beijing_time(datetime.now()),
        }
    )


@app.route("/api/ip/check", methods=["POST"])
def api_ip_check():
    global last_detected_ip, last_detected_time
    current_ip = get_current_ip()
    previous_ip = last_detected_ip
    ip_changed = bool(previous_ip and previous_ip != current_ip)
    last_detected_ip = current_ip
    last_detected_time = to_beijing_time(datetime.now())
    save_cached_ip(current_ip)
    return jsonify(
        {
            "success": True,
            "current_ip": current_ip,
            "previous_ip": previous_ip,
            "ip_changed": ip_changed,
            "binance_status": check_binance_connection(),
            "cached_at": last_detected_time,
            "timestamp": to_beijing_time(datetime.now()),
        }
    )


@app.route("/stream")
def stream():
    def event_stream():
        while True:
            try:
                rankings = dashboard.get_symbol_rankings()
                payload = {
                    "long_rankings": rankings.get("long_rankings", [])[:5],
                    "short_rankings": rankings.get("short_rankings", [])[:5],
                    "scan_details": rankings.get("scan_details", []),
                    "market_condition": rankings.get("market_condition"),
                    "market_stats": rankings.get("market_stats", {}),
                    "ranking_signature": rankings.get("ranking_signature", {}),
                    "scan_signature": rankings.get("scan_signature", ""),
                    "timestamp": rankings.get("timestamp"),
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\\n\\n"
                time.sleep(1)
            except Exception as exc:
                yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\\n\\n"
                time.sleep(2)

    return Response(event_stream(), mimetype="text/event-stream")


if __name__ == "__main__":
    print("Web Dashboard starting...")
    print("Main page: http://localhost:8081/")
    port = int(os.environ.get("PORT", 8081))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False)
