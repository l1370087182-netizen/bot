#!/usr/bin/env python3
"""
Binance Bot v12.0 - WebSocket实时版（最终修复版）
修复: 缩进错误、函数重复、PARTIAL_EXIT、Breakeven、strategy兼容
总行数: 1487行
"""

import asyncio
import ccxt.pro as ccxtpro
import logging
import os
import sys
import json
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Optional, List

from config import *
from strategy import Strategy
from runtime_tracking import RunTracker, write_status_file
import time      
import random
import re

BAN_CACHE_FILE = '.binance_ban_cache.json'

# 可选模块（不存在就跳过）
RiskManager = None

# 设置日志
logger = logging.getLogger()
logger.setLevel(logging.INFO)
while logger.handlers:
    logger.removeHandler(logger.handlers[0])
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler = logging.FileHandler('bot.log', mode='a', encoding='utf-8')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)
logger.propagate = False


class WebSocketBot:
    """WebSocket实时交易机器人 - v12.0 最终版"""
    
    def __init__(self, dry_run=True, testnet=False):
        self.dry_run = dry_run
        self.testnet = testnet
        self.mode = 'testnet' if testnet else ('paper' if dry_run else 'real')
        self.mode_label = 'Binance Testnet' if testnet else ('本地模拟盘' if dry_run else '实盘')
        self.running = False
        
        # K线缓存 + 持仓跟踪
        self.kline_cache: Dict[str, List] = {}
        self.kline_closed: Dict[str, bool] = {}
        self.positions: Dict[str, dict] = {}
        self.position_additions: Dict[str, int] = {}
        self.breakeven_prices: Dict[str, float] = {}
        self.executed_exits: Dict[str, List] = {}
        self.funding_rates: Dict[str, float] = {}
        self.signal_cooldowns: Dict[str, float] = {}
        self.cached_balance: float = float(PAPER_TRADING['starting_balance']) if dry_run else 0.0
        self.account_sync_interval = 30
        self.account_retry_after = 0.0
        self.paper_start_balance = float(PAPER_TRADING['starting_balance'])
        self.paper_realized_pnl = 0.0
        self.paper_fees_paid = 0.0
        self.paper_funding_paid = 0.0
        self.status_interval = int(PAPER_TRADING['status_interval_seconds'])
        self.snapshot_interval = int(PAPER_TRADING['equity_snapshot_interval_seconds'])
        self.taker_fee_rate = float(PAPER_TRADING['taker_fee_rate'])
        self.paper_slippage_pct = float(PAPER_TRADING['slippage_pct'])
        self.funding_period_seconds = float(PAPER_TRADING['funding_period_seconds'])
        self.last_status_write = 0.0
        self.last_equity_snapshot = 0.0
        
        # 策略（完全兼容原strategy）
        self.strategy = Strategy(SYMBOLS)
        self.risk_manager = RiskManager() if RiskManager else None
        self.run_tracker = RunTracker(self.mode, self.cached_balance if self.dry_run else 0.0)
        
        self.exchange: Optional[ccxtpro.binanceusdm] = None
        self.exchange_market: Optional[ccxtpro.binanceusdm] = None
        self.exchange_account: Optional[ccxtpro.binanceusdm] = None
        self.kline_tasks: List[asyncio.Task] = []
        self.kline_task_map: Dict[str, asyncio.Task] = {}
        self.kline_group_count = 2 if self.testnet else 4
        
        logger.info("=" * 60)
        logger.info("[INIT] Binance Bot v12.0 - WebSocket Realtime（最终修复版）")
        logger.info(f"[INIT] Dry Run: {dry_run}, Testnet: {testnet}")
        logger.info(f"[INIT] Mode: {self.mode_label}")
        logger.info("=" * 60)
    
    def _build_exchange_config(self):
        config = {
            'apiKey': BINANCE_TESTNET_API_KEY if self.testnet else BINANCE_API_KEY,
            'secret': BINANCE_TESTNET_API_SECRET if self.testnet else BINANCE_API_SECRET,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future',
                'adjustForTimeDifference': True,
                'fetchCurrencies': False,
                'enableDemoTrading': self.testnet,
            }
        }

        if PROXY_ENABLED and PROXY_URL:
            config['httpsProxy'] = PROXY_URL
            config['wssProxy'] = PROXY_URL
        return config

    def _apply_demo_urls(self, exchange):
        if self.testnet:
            demo_api = dict(exchange.urls.get('demo', {}))
            merged_api = dict(exchange.urls.get('api', {}))
            merged_api.update(demo_api)
            if 'ws' in demo_api:
                merged_api['ws'] = demo_api['ws']
            exchange.urls['api'] = merged_api
        return exchange

    def _create_exchange(self):
        exchange = ccxtpro.binanceusdm(self._build_exchange_config())
        return self._apply_demo_urls(exchange)

    async def _close_exchange(self, exchange):
        if exchange:
            try:
                await exchange.close()
            except Exception:
                pass

    async def init_exchange(self):
        """初始化连接层：拆分行情与账户 exchange，并保留原有策略逻辑。"""
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        if PROXY_ENABLED and PROXY_URL:
            logger.info(f"[PROXY] 已启用代理: {PROXY_URL}")

        if self.testnet:
            logger.info("[INIT] Using Binance demo futures endpoints")

        ban_wait = self._get_cached_ban_wait()
        if ban_wait > 0:
            logger.warning(f"[RATE-LIMIT] 检测到历史封禁窗口，延迟 {ban_wait:.0f}s 后再尝试连接 Binance API")
            await asyncio.sleep(ban_wait)
        
        # 10次重试
        for attempt in range(10):
            try:
                logger.info(f"[INIT] 第 {attempt+1}/10 次尝试连接 Binance API...")
                await self._close_exchange(self.exchange_market)
                await self._close_exchange(self.exchange_account)
                self.exchange_market = self._create_exchange()
                self.exchange_account = self._create_exchange()
                await self.exchange_market.load_markets()
                await self.exchange_account.load_markets()
                self.exchange = self.exchange_account
                self._clear_ban_cache()
                logger.info("✅ 交易所连接成功！")
                return
            except Exception as e:
                self._cache_ban_from_error(e)
                await self._close_exchange(self.exchange_market)
                await self._close_exchange(self.exchange_account)
                self.exchange_market = None
                self.exchange_account = None
                self.exchange = None
                wait = max((2 ** attempt) + random.uniform(0.5, 2.0), self._parse_retry_after(e, default_wait=10.0))
                logger.warning(f"❌ 第 {attempt+1} 次失败: {str(e)[:80]}... {wait:.1f}秒后重试")
                await asyncio.sleep(wait)
        
        await self.close()
        raise Exception("❌ 10次全部失败，请检查代理地址或换手机热点")
        
    async def close(self):
        """关闭交易所连接"""
        for task in list(self.kline_tasks):
            if task and not task.done():
                task.cancel()
        if self.kline_tasks:
            await asyncio.gather(*self.kline_tasks, return_exceptions=True)
        self.kline_tasks = []
        self.kline_task_map = {}
        await self._close_exchange(self.exchange_market)
        if self.exchange_account is not self.exchange_market:
            await self._close_exchange(self.exchange_account)
        self.exchange_market = None
        self.exchange_account = None
        self.exchange = None
        logger.info("[EXIT] 交易所连接已关闭")
    
    def _get_cache_key(self, symbol: str, timeframe: str) -> str:
        return f"{symbol}_{timeframe}"
    
    def _ohlcv_to_df(self, ohlcv: list) -> pd.DataFrame:
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        for column in ['open', 'high', 'low', 'close', 'volume']:
            df[column] = pd.to_numeric(df[column], errors='coerce')
        df.set_index('timestamp', inplace=True)
        return df

    def _get_indicator_frames(self, symbol: str):
        key_15m = self._get_cache_key(symbol, '15m')
        key_1h = self._get_cache_key(symbol, '1h')
        ohlcv_15m = self.kline_cache.get(key_15m, [])
        ohlcv_1h = self.kline_cache.get(key_1h, [])
        if len(ohlcv_15m) < 210 or len(ohlcv_1h) < 120:
            return None, None
        df_15m = self.strategy.calculate_indicators(self._ohlcv_to_df(ohlcv_15m))
        df_1h = self.strategy.calculate_indicators(self._ohlcv_to_df(ohlcv_1h))
        return df_15m, df_1h

    @staticmethod
    def _calculate_cvd_strength(df: pd.DataFrame) -> float:
        try:
            cvd_df = df.copy()
            cvd_df['delta'] = cvd_df.apply(
                lambda row: row['volume'] * ((row['close'] - row['low']) / (row['high'] - row['low']) - 0.5) * 2
                if row['high'] != row['low'] else 0,
                axis=1,
            )
            cvd_df['cvd'] = cvd_df['delta'].cumsum()
            cvd_delta = abs(cvd_df['cvd'].iloc[-1] - cvd_df['cvd'].iloc[-20])
            avg_volume = cvd_df['volume'].rolling(20).mean().iloc[-1]
            cvd_ratio = cvd_delta / avg_volume if avg_volume and avg_volume > 0 else 0
            return float(min(100, cvd_ratio * 50))
        except Exception:
            return 50.0
    @staticmethod
    def _failed_checks(checks):
        return [label for label, ok in checks if not ok]


    async def _build_signal_from_cache(self, symbol: str):
        df_15m, df_1h = self._get_indicator_frames(symbol)
        if df_15m is None or df_1h is None:
            return None

        market_confirm_df = None
        leader_symbol = MARKET_REGIME.get('leader_symbol')
        if leader_symbol:
            if leader_symbol == symbol:
                market_confirm_df = df_1h
            else:
                _, market_confirm_df = self._get_indicator_frames(leader_symbol)

        funding_rate = self.funding_rates.get(symbol, 0.0)
        cvd_strength = self._calculate_cvd_strength(df_15m)
        signal_state = self.strategy.evaluate_signal_setup(
            df_15m, df_1h, funding_rate, cvd_strength, market_confirm_df=market_confirm_df, symbol=symbol
        )
        if not signal_state:
            return None

        curr = signal_state['curr']
        last_closed = signal_state['last_closed']
        logger.info(
            f"[SCAN] {symbol} | Price:${last_closed['close']:.2f} | EMA200:${last_closed['ema200']:.2f} | "
            f"ADX:{curr['adx']:.1f} | Stoch:{last_closed['stoch_k']:.1f} | Funding:{funding_rate:.4%}"
        )

        if signal_state['signal']:
            return signal_state['signal']

        logger.info(f"[SIGNAL] {symbol} long blocked: {' | '.join(self._failed_checks(signal_state['long_checks']))}")
        logger.info(f"[SIGNAL] {symbol} short blocked: {' | '.join(self._failed_checks(signal_state['short_checks']))}")
        return None

    def _sync_position_cache(self, positions: List[dict]):
        active_symbols = set()
        for pos in positions or []:
            symbol = pos['symbol']
            size = float(pos.get('contracts', 0) or pos.get('contractSize', 0) or 0)
            if size == 0:
                continue
            active_symbols.add(symbol)
            self.positions[symbol] = {
                'symbol': symbol,
                'side': 'LONG' if size > 0 else 'SHORT',
                'size': abs(size),
                'entry_price': float(pos.get('entryPrice', 0) or 0),
                'mark_price': float(pos.get('markPrice', 0) or pos.get('lastPrice', 0) or 0),
                'unrealized_pnl': float(pos.get('unrealizedPnl', 0) or 0),
                'leverage': int(float(pos.get('leverage', LEVERAGE) or LEVERAGE)),
                'breakeven_triggered': symbol in self.breakeven_prices
            }
        for symbol in list(self.positions.keys()):
            if symbol not in active_symbols and symbol in SYMBOLS:
                del self.positions[symbol]

    def _normalize_position_side(self, side: str) -> str:
        side_value = (side or '').lower()
        if side_value in ('buy', 'long'):
            return 'LONG'
        if side_value in ('sell', 'short'):
            return 'SHORT'
        raise ValueError(f"Unsupported side: {side}")

    def _order_side_from_position(self, position_side: str) -> str:
        return 'buy' if self._normalize_position_side(position_side) == 'LONG' else 'sell'

    @staticmethod
    def _signed_price_return(entry_price: float, mark_price: float, side: str) -> float:
        if not entry_price:
            return 0.0
        direction = 1 if side == 'LONG' else -1
        return ((mark_price - entry_price) / entry_price) * direction

    def _apply_execution_price(self, price: float, position_side: str, *, is_entry: bool) -> float:
        slip = self.paper_slippage_pct if self.dry_run else 0.0
        if slip <= 0:
            return price
        side = self._normalize_position_side(position_side)
        if side == 'LONG':
            return price * (1 + slip) if is_entry else price * (1 - slip)
        return price * (1 - slip) if is_entry else price * (1 + slip)

    def _current_equity(self) -> float:
        if not self.dry_run:
            return self.cached_balance
        unrealized = sum(float(pos.get('unrealized_pnl', 0) or 0) for pos in self.positions.values())
        return float(self.cached_balance + unrealized)

    @staticmethod
    def _duration_hours_from_iso(iso_value: str | None) -> float:
        if not iso_value:
            return 0.0
        try:
            return max(0.0, (time.time() - datetime.fromisoformat(iso_value).timestamp()) / 3600.0)
        except Exception:
            return 0.0

    def _build_status_payload(self) -> dict:
        positions = []
        for symbol, pos in self.positions.items():
            mark_price = float(pos.get('mark_price', pos.get('entry_price', 0)) or 0)
            entry_price = float(pos.get('entry_price', 0) or 0)
            signed_return = self._signed_price_return(entry_price, mark_price, pos.get('side', 'LONG'))
            positions.append(
                {
                    'symbol': symbol,
                    'side': pos.get('side'),
                    'size': float(pos.get('size', 0) or 0),
                    'entry_price': entry_price,
                    'mark_price': mark_price,
                    'unrealized_pnl': float(pos.get('unrealized_pnl', 0) or 0),
                    'price_change_pct': signed_return,
                    'leverage': int(pos.get('leverage', LEVERAGE) or LEVERAGE),
                    'breakeven_triggered': bool(pos.get('breakeven_triggered', False)),
                    'opened_at': pos.get('opened_at'),
                }
            )
        return {
            'status': 'running' if self.running else 'stopped',
            'mode': self.mode,
            'mode_label': self.mode_label,
            'dry_run': self.dry_run,
            'testnet': self.testnet,
            'timestamp': time.time(),
            'updated_at': datetime.now().isoformat(timespec='seconds'),
            'balance': round(float(self.cached_balance), 4),
            'equity': round(float(self._current_equity()), 4),
            'starting_balance': round(float(self.paper_start_balance if self.dry_run else self.cached_balance), 4),
            'realized_pnl': round(float(self.cached_balance - self.paper_start_balance), 4) if self.dry_run else 0.0,
            'unrealized_pnl': round(float(sum(pos.get('unrealized_pnl', 0) or 0 for pos in self.positions.values())), 4),
            'fees_paid': round(float(self.paper_fees_paid), 4),
            'funding_paid': round(float(self.paper_funding_paid), 4),
            'position_count': len(positions),
            'positions': positions,
            'database_path': str(self.run_tracker.db_path),
            'data_file_path': str(self.run_tracker.data_path),
            'run_id': self.run_tracker.run_id,
        }

    def _write_runtime_state(self, *, force_snapshot: bool = False) -> None:
        payload = self._build_status_payload()
        write_status_file(payload)
        now = time.time()
        append_curve = force_snapshot or (now - self.last_equity_snapshot >= self.snapshot_interval)
        self.run_tracker.update_snapshot(payload, append_curve=append_curve)
        self.last_status_write = now
        if append_curve:
            self.last_equity_snapshot = now

    async def _status_loop(self):
        while self.running:
            try:
                self._write_runtime_state()
            except Exception as exc:
                logger.error(f"[STATUS] runtime state write failed: {exc}")
            await asyncio.sleep(self.status_interval)

    def _update_paper_position_mark(self, symbol: str, mark_price: float) -> None:
        if not self.dry_run or symbol not in self.positions:
            return
        position = self.positions[symbol]
        now = time.time()
        last_funding_ts = float(position.get('last_funding_ts', now) or now)
        elapsed = max(0.0, now - last_funding_ts)
        if elapsed > 0:
            funding_rate = float(self.funding_rates.get(symbol, 0.0) or 0.0)
            notional = float(position.get('size', 0) or 0) * mark_price
            funding_cashflow = notional * funding_rate * (elapsed / self.funding_period_seconds)
            funding_pnl = -funding_cashflow if position.get('side') == 'LONG' else funding_cashflow
            if funding_pnl:
                self.cached_balance += funding_pnl
                self.paper_funding_paid += funding_pnl
                position['funding_paid'] = float(position.get('funding_paid', 0.0) or 0.0) + funding_pnl
            position['last_funding_ts'] = now

        entry_price = float(position.get('entry_price', 0) or 0)
        direction = 1 if position.get('side') == 'LONG' else -1
        unrealized = (mark_price - entry_price) * float(position.get('size', 0) or 0) * direction
        position['mark_price'] = mark_price
        position['unrealized_pnl'] = float(unrealized)
        position['price_change_pct'] = self._signed_price_return(entry_price, mark_price, position.get('side', 'LONG'))
    
    def _build_kline_groups(self, timeframes):
        streams = [(symbol, tf) for tf in timeframes for symbol in SYMBOLS]
        group_count = max(1, min(self.kline_group_count, len(streams)))
        groups = [[] for _ in range(group_count)]
        for index, stream in enumerate(streams):
            groups[index % group_count].append(stream)
        return [group for group in groups if group]

    async def _watch_kline_group(self, group_index: int, streams: List[tuple]):
        stream_backoffs = {self._get_cache_key(symbol, tf): 1.0 for symbol, tf in streams}
        await asyncio.sleep(group_index * 0.6)
        while self.running:
            if not self.exchange_market:
                await asyncio.sleep(1)
                continue

            for symbol, tf in streams:
                if not self.running:
                    break
                key = self._get_cache_key(symbol, tf)
                try:
                    ohlcv = await self.exchange_market.watch_ohlcv(symbol, tf)
                    if ohlcv and len(ohlcv) > 0:
                        last_candle = ohlcv[-1]
                        is_closed = len(ohlcv) > 1
                        self.kline_cache[key] = ohlcv
                        self._update_paper_position_mark(symbol, float(last_candle[4]))

                        if is_closed and not self.kline_closed.get(key, False):
                            self.kline_closed[key] = True
                            logger.info(f"[WS-{tf}] {symbol} 新K线已关闭 @ {last_candle[4]}")
                            if tf == '15m':
                                await self._on_15m_closed(symbol)
                        elif not is_closed:
                            self.kline_closed[key] = False
                    stream_backoffs[key] = 1.0
                    await asyncio.sleep(0.05)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"[WS-KLINE] {symbol} {tf} 错误: {e}")
                    wait = min(stream_backoffs[key], 20.0)
                    stream_backoffs[key] = min(stream_backoffs[key] * 1.8, 20.0)
                    await asyncio.sleep(wait + random.uniform(0.1, 0.4))

    async def watch_klines(self):
        """监听K线数据：少量分组 task，降低 Testnet 对高并发订阅的拒绝概率。"""
        timeframes = ['15m', '1h']

        for symbol in SYMBOLS:
            for tf in timeframes:
                key = self._get_cache_key(symbol, tf)
                self.kline_cache[key] = []
                self.kline_closed[key] = False

        logger.info(f"[WS] 开始监听 {len(SYMBOLS)} 个币种的 15m 和 1h K线")

        self.kline_tasks = []
        self.kline_task_map = {}
        groups = self._build_kline_groups(timeframes)
        logger.info(f"[WS] K线流分组数: {len(groups)}")
        for group_index, streams in enumerate(groups):
            task_key = f"group_{group_index}"
            task = asyncio.create_task(self._watch_kline_group(group_index, streams))
            self.kline_tasks.append(task)
            self.kline_task_map[task_key] = task

        try:
            await asyncio.gather(*self.kline_tasks)
        finally:
            self.kline_tasks = []
            self.kline_task_map = {}
    
    async def _on_15m_closed(self, symbol: str):
        """15m K????????"""
        try:
            if symbol in self.positions:
                key_15m = self._get_cache_key(symbol, '15m')
                ohlcv_15m = self.kline_cache.get(key_15m, [])
                if len(ohlcv_15m) >= 50:
                    df_15m = self._ohlcv_to_df(ohlcv_15m)
                    await self._check_position_management(symbol, df_15m)

            signal_data = await self._build_signal_from_cache(symbol)
            if signal_data:
                side = signal_data.get('side')
                logger.info(f"[SIGNAL] {symbol} trigger {side} | score:{signal_data.get('score', 0):.1f} | risk:{signal_data.get('risk_multiplier', 1.0):.2f}")
                if await self._can_open_position(symbol, side):
                    await self._open_position(symbol, side, signal_data)

        except Exception as e:
            logger.error(f"[STRATEGY] {symbol} signal build failed: {e}")

    async def _check_position_management(self, symbol: str, df: pd.DataFrame):
        """检查持仓管理 - 修复PARTIAL_EXIT和Breakeven Bug"""
        if symbol not in self.positions:
            return
        
        position = self.positions[symbol]
        
        try:
            result = await self.strategy.check_exit_and_pyramiding(
                exchange=self.exchange,
                symbol=symbol,
                current_side=position['side'],
                entry_price=position['entry_price'],
                position_size=position['size'],
                balance=await self._get_balance(),
                executed_exits=self.executed_exits.get(symbol, []),
                current_additions=self.position_additions.get(symbol, 0),
                breakeven_triggered=position.get('breakeven_triggered', False),
                df=df
            )
            
            if not result:
                return
            
            action = result.get('action')
            
            if action == 'CLOSE_ALL':
                logger.info(f"[EXIT] {symbol} 触发平仓: {result.get('reason')}")
                await self._close_position(symbol, result)
                
            elif action == 'PARTIAL_EXIT':
                exit_pct = result.get('exit_pct', 0)
                logger.info(f"[PARTIAL] {symbol} 触发部分平仓 {exit_pct*100}%: {result.get('reason')}")
                await self._partial_close_position(symbol, exit_pct, result)
                if symbol not in self.executed_exits:
                    self.executed_exits[symbol] = []
                self.executed_exits[symbol].append(result.get('r_multiple_level'))
                
            elif action == 'SET_BREAKEVEN':
                buffer_pct = result.get('buffer_pct', 0.005)
                breakeven_price = position['entry_price'] * (1 + buffer_pct) if position['side'] == 'LONG' else position['entry_price'] * (1 - buffer_pct)
                self.breakeven_prices[symbol] = breakeven_price
                position['breakeven_triggered'] = True
                position['breakeven_price'] = breakeven_price
                logger.info(f"[BREAKEVEN] {symbol} 设置保本止损 @ {breakeven_price:.4f}")
                
            elif action == 'PYRAMID':
                if symbol in self.executed_exits and len(self.executed_exits[symbol]) > 0:
                    logger.info(f"[PYRAMID] {symbol} 已部分平仓，跳过加仓")
                    return
                level = result.get('level', 1)
                size = result.get('size', 0)
                logger.info(f"[PYRAMID] {symbol} 触发金字塔加仓 第{level}层")
                await self._pyramiding_add(symbol, size, result)
                
        except Exception as e:
            logger.error(f"[POSITION] {symbol} 持仓管理失败: {e}")
    
    async def _get_balance(self) -> float:
        try:
            if self.dry_run:
                return self._current_equity()
            if self.cached_balance > 0:
                return self.cached_balance
            balance = await self.exchange.fetch_balance()
            self.cached_balance = float(balance.get('USDT', {}).get('free', 0))
            return self.cached_balance
        except:
            return 1000.0

    @staticmethod
    def _parse_retry_after(error: Exception, default_wait: float = 60.0) -> float:
        message = str(error)
        now_ms = int(time.time() * 1000)
        banned_match = re.search(r"banned until (\d{13})", message)
        if banned_match:
            retry_at_ms = int(banned_match.group(1))
            return max(default_wait, (retry_at_ms - now_ms) / 1000 + 2)
        if "429" in message or "418" in message or '"code":-1003' in message or "Too many requests" in message:
            return max(default_wait, 120.0)
        return default_wait

    @staticmethod
    def _ban_cache_path() -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), BAN_CACHE_FILE)

    def _get_cached_ban_wait(self) -> float:
        try:
            path = self._ban_cache_path()
            if not os.path.exists(path):
                return 0.0
            with open(path, 'r', encoding='utf-8') as handle:
                data = json.load(handle)
            retry_at_ms = int(data.get('retry_at_ms', 0) or 0)
            now_ms = int(time.time() * 1000)
            if retry_at_ms <= now_ms:
                self._clear_ban_cache()
                return 0.0
            return (retry_at_ms - now_ms) / 1000 + 2
        except Exception:
            return 0.0

    def _cache_ban_from_error(self, error: Exception):
        try:
            message = str(error)
            retry_at_ms = None
            banned_match = re.search(r"banned until (\d{13})", message)
            if banned_match:
                retry_at_ms = int(banned_match.group(1))
            elif "429" in message or "418" in message or '"code":-1003' in message or "Too many requests" in message:
                retry_at_ms = int((time.time() + 120) * 1000)
            if retry_at_ms:
                with open(self._ban_cache_path(), 'w', encoding='utf-8') as handle:
                    json.dump({"retry_at_ms": retry_at_ms, "updated_at": int(time.time())}, handle)
        except Exception:
            pass

    def _clear_ban_cache(self):
        try:
            path = self._ban_cache_path()
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
    
    async def _can_open_position(self, symbol: str, side: str) -> bool:
        target_side = self._normalize_position_side(side)
        now = time.time()
        if symbol in self.signal_cooldowns:
            cooldown_seconds = ENTRY_RULES['signal_cooldown_minutes'] * 60
            if now - self.signal_cooldowns[symbol] < cooldown_seconds:
                return False
        active_count = len([p for p in self.positions.values() if p['size'] > 0])
        if active_count >= MAX_ACTIVE_SYMBOLS and symbol not in self.positions:
            return False
        if symbol in self.positions:
            pos = self.positions[symbol]
            if target_side != pos['side']:
                return False
        return True
    
    async def _open_position(self, symbol: str, side: str, signal: dict):
        try:
            position_side = self._normalize_position_side(side)
            ticker = await self.exchange.fetch_ticker(symbol)
            price = float(ticker['last'])
            balance = await self._get_balance()
            risk_multiplier = float(signal.get('risk_multiplier', 1.0) or 1.0)
            risk_amount = balance * RISK_PER_TRADE * risk_multiplier
            position_value = risk_amount * LEVERAGE
            quantity = position_value / price
            quantity = self._format_quantity(symbol, quantity)
            if quantity <= 0:
                logger.info(f"[OPEN] {symbol} skipped because formatted quantity is zero")
                return

            logger.info(f"[OPEN] {symbol} {side.upper()} @ {price:.4f}, qty: {quantity}, risk_mult: {risk_multiplier:.2f}")

            if self.dry_run:
                execution_price = self._apply_execution_price(price, position_side, is_entry=True)
                fee = execution_price * quantity * self.taker_fee_rate
                self.cached_balance -= fee
                self.paper_fees_paid += fee
                opened_at = datetime.now().isoformat(timespec='seconds')
                self.positions[symbol] = {
                    'symbol': symbol,
                    'side': position_side,
                    'size': quantity,
                    'entry_price': execution_price,
                    'mark_price': price,
                    'unrealized_pnl': 0.0,
                    'leverage': LEVERAGE,
                    'breakeven_triggered': False,
                    'opened_at': opened_at,
                    'funding_paid': 0.0,
                    'entry_fee_paid': fee,
                    'last_funding_ts': time.time(),
                    'risk_multiplier': risk_multiplier,
                }
                self.run_tracker.append_event(
                    'entry',
                    {
                        'symbol': symbol,
                        'side': position_side,
                        'price': execution_price,
                        'mark_price': price,
                        'size': quantity,
                        'fee': fee,
                        'risk_multiplier': risk_multiplier,
                    },
                )
            else:
                await self.exchange.create_market_order(
                    symbol=symbol,
                    side=self._order_side_from_position(position_side),
                    amount=quantity
                )

            self.signal_cooldowns[symbol] = time.time()
            self._write_runtime_state(force_snapshot=True)
        except Exception as e:
            logger.error(f"[OPEN] {symbol} open failed: {e}")

    async def _close_position(self, symbol: str, exit_data: dict):
        try:
            position = self.positions.get(symbol)
            if not position:
                return
            logger.info(f"[CLOSE] {symbol} 平仓")
            ticker = await self.exchange.fetch_ticker(symbol)
            exit_price = float(ticker['last'])
            if not self.dry_run:
                await self.exchange.create_market_order(
                    symbol=symbol,
                    side='sell' if position['side'] == 'LONG' else 'buy',
                    amount=position['size']
                )
            else:
                execution_price = self._apply_execution_price(exit_price, position['side'], is_entry=False)
                close_qty = float(position['size'])
                direction = 1 if position['side'] == 'LONG' else -1
                gross_pnl = (execution_price - float(position['entry_price'])) * close_qty * direction
                fee = execution_price * close_qty * self.taker_fee_rate
                funding_component = float(position.get('funding_paid', 0.0) or 0.0)
                self.cached_balance += gross_pnl - fee
                self.paper_realized_pnl += gross_pnl - fee + funding_component
                self.paper_fees_paid += fee
                margin_used = max((float(position['entry_price']) * close_qty) / LEVERAGE, 1e-9)
                pnl_pct = ((gross_pnl - fee + funding_component) / margin_used) * 100
                self.run_tracker.record_trade(
                    symbol=symbol,
                    side=position['side'],
                    entry_price=float(position['entry_price']),
                    exit_price=execution_price,
                    size=close_qty,
                    leverage=LEVERAGE,
                    pnl=float(gross_pnl - fee + funding_component),
                    pnl_pct=float(pnl_pct),
                    entry_time=position.get('opened_at', datetime.now().isoformat(timespec='seconds')),
                    exit_time=datetime.now().isoformat(timespec='seconds'),
                    duration_hours=self._duration_hours_from_iso(position.get('opened_at')),
                    exit_reason=exit_data.get('reason', 'unknown'),
                    extra={
                        'fee': fee,
                        'funding_pnl': funding_component,
                        'mark_price': exit_price,
                    },
                )
                self.run_tracker.append_event(
                    'close',
                    {
                        'symbol': symbol,
                        'side': position['side'],
                        'exit_price': execution_price,
                        'mark_price': exit_price,
                        'size': close_qty,
                        'reason': exit_data.get('reason', 'unknown'),
                    },
                )
            del self.positions[symbol]
            self.position_additions.pop(symbol, None)
            self.breakeven_prices.pop(symbol, None)
            self.executed_exits.pop(symbol, None)
            self._write_runtime_state(force_snapshot=True)
        except Exception as e:
            logger.error(f"[CLOSE] {symbol} 平仓失败: {e}")
    
    async def _partial_close_position(self, symbol: str, pct: float, exit_data: dict):
        try:
            position = self.positions.get(symbol)
            if not position:
                return
            close_qty = position['size'] * pct
            close_qty = self._format_quantity(symbol, close_qty)
            logger.info(f"[PARTIAL] {symbol} 部分平仓 {pct*100}%")
            if self.dry_run:
                ticker = await self.exchange.fetch_ticker(symbol)
                exit_price = float(ticker['last'])
                execution_price = self._apply_execution_price(exit_price, position['side'], is_entry=False)
                current_size = float(position['size'])
                if current_size <= 0:
                    return
                close_ratio = close_qty / current_size
                direction = 1 if position['side'] == 'LONG' else -1
                gross_pnl = (execution_price - float(position['entry_price'])) * close_qty * direction
                fee = execution_price * close_qty * self.taker_fee_rate
                funding_component = float(position.get('funding_paid', 0.0) or 0.0) * close_ratio
                self.cached_balance += gross_pnl - fee
                self.paper_realized_pnl += gross_pnl - fee + funding_component
                self.paper_fees_paid += fee
                position['funding_paid'] = float(position.get('funding_paid', 0.0) or 0.0) - funding_component
                position['size'] -= close_qty
                margin_used = max((float(position['entry_price']) * close_qty) / LEVERAGE, 1e-9)
                pnl_pct = ((gross_pnl - fee + funding_component) / margin_used) * 100
                self.run_tracker.record_trade(
                    symbol=symbol,
                    side=position['side'],
                    entry_price=float(position['entry_price']),
                    exit_price=execution_price,
                    size=close_qty,
                    leverage=LEVERAGE,
                    pnl=float(gross_pnl - fee + funding_component),
                    pnl_pct=float(pnl_pct),
                    entry_time=position.get('opened_at', datetime.now().isoformat(timespec='seconds')),
                    exit_time=datetime.now().isoformat(timespec='seconds'),
                    duration_hours=self._duration_hours_from_iso(position.get('opened_at')),
                    exit_reason=exit_data.get('reason', 'partial_exit'),
                    extra={
                        'fee': fee,
                        'funding_pnl': funding_component,
                        'partial_close': True,
                        'mark_price': exit_price,
                    },
                )
                self.run_tracker.append_event(
                    'partial_close',
                    {
                        'symbol': symbol,
                        'side': position['side'],
                        'exit_price': execution_price,
                        'mark_price': exit_price,
                        'size': close_qty,
                        'remaining_size': position['size'],
                        'reason': exit_data.get('reason', 'partial_exit'),
                    },
                )
                if position['size'] <= 0:
                    del self.positions[symbol]
                    self.position_additions.pop(symbol, None)
                    self.breakeven_prices.pop(symbol, None)
                    self.executed_exits.pop(symbol, None)
            else:
                await self.exchange.create_market_order(
                    symbol=symbol,
                    side='sell' if position['side'] == 'LONG' else 'buy',
                    amount=close_qty
                )
            self._write_runtime_state(force_snapshot=True)
        except Exception as e:
            logger.error(f"[PARTIAL] {symbol} 部分平仓失败: {e}")
    
    async def _pyramiding_add(self, symbol: str, size: float, add_data: dict):
        try:
            position = self.positions.get(symbol)
            if not position:
                return
            if symbol in self.executed_exits and len(self.executed_exits[symbol]) > 0:
                logger.info(f"[PYRAMID] {symbol} 已部分平仓，跳过加仓")
                return
            ticker = await self.exchange.fetch_ticker(symbol)
            price = float(ticker['last'])
            quantity = self._format_quantity(symbol, size)
            logger.info(f"[PYRAMID] {symbol} 加仓 @ {price:.4f}, 数量: {quantity}")
            if self.dry_run:
                execution_price = self._apply_execution_price(price, position['side'], is_entry=True)
                fee = execution_price * quantity * self.taker_fee_rate
                old_size = float(position['size'])
                new_size = old_size + quantity
                if new_size <= 0:
                    return
                position['entry_price'] = ((float(position['entry_price']) * old_size) + (execution_price * quantity)) / new_size
                position['size'] = new_size
                position['mark_price'] = price
                self.cached_balance -= fee
                self.paper_fees_paid += fee
                self.position_additions[symbol] = self.position_additions.get(symbol, 0) + 1
                self.run_tracker.append_event(
                    'pyramid',
                    {
                        'symbol': symbol,
                        'side': position['side'],
                        'price': execution_price,
                        'mark_price': price,
                        'size': quantity,
                        'fee': fee,
                        'level': add_data.get('level'),
                    },
                )
            else:
                await self.exchange.create_market_order(
                    symbol=symbol,
                    side='buy' if position['side'] == 'LONG' else 'sell',
                    amount=quantity
                )
            self._write_runtime_state(force_snapshot=True)
        except Exception as e:
            logger.error(f"[PYRAMID] {symbol} 加仓失败: {e}")
    
    def _format_quantity(self, symbol: str, quantity: float) -> float:
        try:
            market = self.exchange.market(symbol)
            step_size = market['limits']['amount']['min']
            if step_size:
                precision = len(str(step_size).split('.')[-1].rstrip('0'))
                return round(quantity - (quantity % step_size), precision)
        except:
            pass
        return round(quantity, 3)
    
    async def watch_balance_and_positions(self):
        """通过用户数据流实时同步余额和持仓。"""
        if self.testnet:
            logger.info("[WS] Testnet 账户流改用 REST 低频同步")
            await self.poll_balance_and_positions()
            return

        logger.info("[WS] 开始监听余额和持仓")
        balance_task = None
        position_task = None
        while self.running:
            try:
                now = time.time()
                if now < self.account_retry_after:
                    await asyncio.sleep(min(5, self.account_retry_after - now))
                    continue

                if not self.exchange_account:
                    await asyncio.sleep(1)
                    continue

                if balance_task is None or balance_task.done():
                    balance_task = asyncio.create_task(self.exchange_account.watch_balance({'type': 'future'}))
                if position_task is None or position_task.done():
                    position_task = asyncio.create_task(self.exchange_account.watch_positions(None, None, None, {'type': 'future'}))

                done, _ = await asyncio.wait({balance_task, position_task}, return_when=asyncio.FIRST_COMPLETED)

                if balance_task in done:
                    balance = balance_task.result()
                    usdt = balance.get('USDT', {}) if isinstance(balance, dict) else {}
                    self.cached_balance = float(usdt.get('free', 0) or usdt.get('total', 0) or self.cached_balance)
                    balance_task = None

                if position_task in done:
                    positions = position_task.result()
                    self._sync_position_cache(positions)
                    position_task = None

            except Exception as e:
                self._cache_ban_from_error(e)
                for task in (balance_task, position_task):
                    if not task:
                        continue
                    if task.done():
                        try:
                            task.exception()
                        except Exception:
                            pass
                    else:
                        task.cancel()
                balance_task = None
                position_task = None
                logger.error(f"[WS-POSITION] 持仓监听错误: {e}")
                wait_seconds = self._parse_retry_after(e)
                self.account_retry_after = time.time() + wait_seconds
                logger.warning(f"[WS-POSITION] 触发限频保护，暂停账户同步 {wait_seconds:.0f}s")
                await asyncio.sleep(min(wait_seconds, 60))

    async def poll_balance_and_positions(self):
        """Testnet 账户同步降级为低频 REST，绕开不稳定的账户 WebSocket。"""
        while self.running:
            try:
                now = time.time()
                if now < self.account_retry_after:
                    await asyncio.sleep(min(5, self.account_retry_after - now))
                    continue

                if not self.exchange_account:
                    await asyncio.sleep(1)
                    continue

                balance = await self.exchange_account.fetch_balance({'type': 'future'})
                usdt = balance.get('USDT', {}) if isinstance(balance, dict) else {}
                self.cached_balance = float(usdt.get('free', 0) or usdt.get('total', 0) or self.cached_balance)

                try:
                    positions = await self.exchange_account.fetch_positions(None, None, None, {'type': 'future'})
                except Exception:
                    positions = []
                self._sync_position_cache(positions)
                await asyncio.sleep(self.account_sync_interval)
            except Exception as e:
                self._cache_ban_from_error(e)
                logger.error(f"[ACCOUNT-POLL] 账户同步失败: {e}")
                wait_seconds = self._parse_retry_after(e, default_wait=float(self.account_sync_interval))
                self.account_retry_after = time.time() + wait_seconds
                await asyncio.sleep(min(wait_seconds, 60))

    async def update_funding_rates(self):
        """更新资金费率"""
        while self.running:
            try:
                for symbol in SYMBOLS:
                    try:
                        if not self.exchange_market:
                            continue
                        funding = await self.exchange_market.fetch_funding_rate(symbol)
                        self.funding_rates[symbol] = float(funding.get('fundingRate', 0))
                    except:
                        pass
                await asyncio.sleep(600)
            except Exception as e:
                self._cache_ban_from_error(e)
                logger.error(f"[FUNDING] 更新失败: {e}")
                await asyncio.sleep(60)
    
    async def run(self):
        """主运行循环"""
        self.running = True
        await self.init_exchange()
        if not self.dry_run:
            try:
                await self._get_balance()
            except Exception:
                pass
        self._write_runtime_state(force_snapshot=True)
        tasks = [
            asyncio.create_task(self.watch_klines()),
            asyncio.create_task(self.update_funding_rates()),
            asyncio.create_task(self._status_loop()),
        ]
        if not self.dry_run:
            tasks.append(asyncio.create_task(self.watch_balance_and_positions()))
        logger.info("[START] WebSocket机器人启动完成")
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("[STOP] 收到停止信号")
        finally:
            self.running = False
            try:
                self.run_tracker.finalize(self._build_status_payload())
                write_status_file({**self._build_status_payload(), 'status': 'stopped'})
            except Exception as exc:
                logger.error(f"[STATUS] finalize failed: {exc}")
            await self.close()


async def main():
    import argparse
    parser = argparse.ArgumentParser(description='Binance Bot v12.0')
    parser.add_argument('--testnet', action='store_true')
    parser.add_argument('--real', action='store_true')
    args = parser.parse_args()
    
    bot = WebSocketBot(dry_run=not args.real, testnet=args.testnet)
    try:
        await bot.run()
    except KeyboardInterrupt:
        logger.info("[EXIT] 用户中断")
        await bot.close()


if __name__ == '__main__':
    asyncio.run(main())
