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
import time      
import random
import re

BAN_CACHE_FILE = '.binance_ban_cache.json'

# 可选模块（不存在就跳过）
RiskManager = None
trade_recorder = None

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
        self.cached_balance: float = 0.0
        self.account_sync_interval = 30
        self.account_retry_after = 0.0
        
        # 策略（完全兼容原strategy）
        self.strategy = Strategy(SYMBOLS)
        self.risk_manager = RiskManager() if RiskManager else None
        
        self.exchange: Optional[ccxtpro.binanceusdm] = None
        
        logger.info("=" * 60)
        logger.info("[INIT] Binance Bot v12.0 - WebSocket Realtime（最终修复版）")
        logger.info(f"[INIT] Dry Run: {dry_run}, Testnet: {testnet}")
        logger.info("=" * 60)
    
    async def init_exchange(self):
        """最终加强版：10次重试 + 代理支持 + 随机延迟"""
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
        config = {
            'apiKey': BINANCE_API_KEY,
            'secret': BINANCE_API_SECRET,
            'enableRateLimit': True,
            'options': {'defaultType': 'future', 'adjustForTimeDifference': True}
        }
        
        # === 代理支持 ===
        if PROXY_ENABLED and PROXY_URL:
            config['httpsProxy'] = PROXY_URL
            config['wssProxy'] = PROXY_URL
            logger.info(f"[PROXY] 已启用代理: {PROXY_URL}")
        
        if self.testnet:
            config['sandbox'] = True
        
        self.exchange = ccxtpro.binanceusdm(config)
        if self.testnet:
            self.exchange.set_sandbox_mode(True)

        ban_wait = self._get_cached_ban_wait()
        if ban_wait > 0:
            logger.warning(f"[RATE-LIMIT] 检测到历史封禁窗口，延迟 {ban_wait:.0f}s 后再尝试连接 Binance API")
            await asyncio.sleep(ban_wait)
        
        # 10次重试
        for attempt in range(10):
            try:
                logger.info(f"[INIT] 第 {attempt+1}/10 次尝试连接 Binance API...")
                await self.exchange.load_markets()
                self._clear_ban_cache()
                logger.info("✅ 交易所连接成功！")
                return
            except Exception as e:
                self._cache_ban_from_error(e)
                wait = max((2 ** attempt) + random.uniform(0.5, 2.0), self._parse_retry_after(e, default_wait=10.0))
                logger.warning(f"❌ 第 {attempt+1} 次失败: {str(e)[:80]}... {wait:.1f}秒后重试")
                await asyncio.sleep(wait)
        
        await self.close()
        raise Exception("❌ 10次全部失败，请检查代理地址或换手机热点")
        
    async def close(self):
        """关闭交易所连接"""
        if self.exchange:
            await self.exchange.close()
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
    
    async def watch_klines(self):
        """监听K线数据 - 10币种 * 2时间框架"""
        timeframes = ['15m', '1h']
        
        for symbol in SYMBOLS:
            for tf in timeframes:
                key = self._get_cache_key(symbol, tf)
                self.kline_cache[key] = []
                self.kline_closed[key] = False
        
        logger.info(f"[WS] 开始监听 {len(SYMBOLS)} 个币种的 15m 和 1h K线")
        
        while self.running:
            try:
                for symbol in SYMBOLS:
                    for tf in timeframes:
                        try:
                            ohlcv = await self.exchange.watch_ohlcv(symbol, tf)
                            if ohlcv and len(ohlcv) > 0:
                                key = self._get_cache_key(symbol, tf)
                                last_candle = ohlcv[-1]
                                is_closed = len(ohlcv) > 1
                                self.kline_cache[key] = ohlcv
                                
                                if is_closed and not self.kline_closed.get(key, False):
                                    self.kline_closed[key] = True
                                    logger.info(f"[WS-{tf}] {symbol} 新K线已关闭 @ {last_candle[4]}")
                                    if tf == '15m':
                                        await self._on_15m_closed(symbol)
                                elif not is_closed:
                                    self.kline_closed[key] = False
                        except Exception as e:
                            logger.error(f"[WS-KLINE] {symbol} {tf} 错误: {e}")
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"[WS-KLINE] 监听错误: {e}")
                await asyncio.sleep(5)
    
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
            price = ticker['last']
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
                self.positions[symbol] = {
                    'symbol': symbol,
                    'side': position_side,
                    'size': quantity,
                    'entry_price': price,
                    'mark_price': price,
                    'unrealized_pnl': 0.0,
                    'leverage': LEVERAGE,
                    'breakeven_triggered': False
                }
            else:
                await self.exchange.create_market_order(
                    symbol=symbol,
                    side=self._order_side_from_position(position_side),
                    amount=quantity
                )

            self.signal_cooldowns[symbol] = time.time()
            if trade_recorder:
                trade_recorder.record_entry(symbol, side, price, quantity, LEVERAGE, signal)
        except Exception as e:
            logger.error(f"[OPEN] {symbol} ????: {e}")

    async def _close_position(self, symbol: str, exit_data: dict):
        try:
            position = self.positions.get(symbol)
            if not position:
                return
            logger.info(f"[CLOSE] {symbol} 平仓")
            if not self.dry_run:
                await self.exchange.create_market_order(
                    symbol=symbol,
                    side='sell' if position['side'] == 'LONG' else 'buy',
                    amount=position['size']
                )
            ticker = await self.exchange.fetch_ticker(symbol)
            exit_price = ticker['last']
            del self.positions[symbol]
            self.position_additions.pop(symbol, None)
            self.breakeven_prices.pop(symbol, None)
            self.executed_exits.pop(symbol, None)
            if trade_recorder:
                trade_recorder.record_exit(symbol, exit_price, exit_data.get('reason', 'unknown'))
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
                position['size'] -= close_qty
            else:
                await self.exchange.create_market_order(
                    symbol=symbol,
                    side='sell' if position['side'] == 'LONG' else 'buy',
                    amount=close_qty
                )
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
            price = ticker['last']
            quantity = self._format_quantity(symbol, size)
            logger.info(f"[PYRAMID] {symbol} 加仓 @ {price:.4f}, 数量: {quantity}")
            if self.dry_run:
                position['size'] += quantity
                self.position_additions[symbol] = self.position_additions.get(symbol, 0) + 1
            else:
                await self.exchange.create_market_order(
                    symbol=symbol,
                    side='buy' if position['side'] == 'LONG' else 'sell',
                    amount=quantity
                )
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
        logger.info("[WS] 开始监听余额和持仓")
        balance_task = None
        position_task = None
        while self.running:
            try:
                now = time.time()
                if now < self.account_retry_after:
                    await asyncio.sleep(min(5, self.account_retry_after - now))
                    continue

                if balance_task is None or balance_task.done():
                    balance_task = asyncio.create_task(self.exchange.watch_balance({'type': 'future'}))
                if position_task is None or position_task.done():
                    position_task = asyncio.create_task(self.exchange.watch_positions(None, None, None, {'type': 'future'}))

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
                await asyncio.sleep(min(wait_seconds, 30))

    async def update_funding_rates(self):
        """更新资金费率"""
        while self.running:
            try:
                for symbol in SYMBOLS:
                    try:
                        funding = await self.exchange.fetch_funding_rate(symbol)
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
        tasks = [
            asyncio.create_task(self.watch_klines()),
            asyncio.create_task(self.watch_balance_and_positions()),
            asyncio.create_task(self.update_funding_rates()),
        ]
        logger.info("[START] WebSocket机器人启动完成")
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("[STOP] 收到停止信号")
        finally:
            self.running = False
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
