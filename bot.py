#!/usr/bin/env python3
"""
Binance Bot - 智能交易监控系统 v3
增强功能：实时监控、紧急平仓、趋势反转检测
"""
import ccxt
import time
import logging
import os
import sys
import json
from datetime import datetime

# ========== 时间偏移修复 ==========
FORCED_OFFSET_MS = 10000
_ccxt_milliseconds = ccxt.Exchange.milliseconds

@staticmethod
def patched_milliseconds():
    return _ccxt_milliseconds() - FORCED_OFFSET_MS

ccxt.Exchange.milliseconds = patched_milliseconds
print(f"🔧 CCXT milliseconds patch applied: -{FORCED_OFFSET_MS}ms")
# ========== 修复结束 ==========

from config import *
from strategy import Strategy
from risk_manager import RiskManager

# Logging setup
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/home/administrator/.openclaw/workspace/binance_bot/bot.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

class BinanceBot:
    def __init__(self, dry_run=True):
        self.dry_run = dry_run
        self.consecutive_errors = 0
        self.max_consecutive_errors = 10
        
        # 实时监控配置
        # 持仓追踪
        self.position_tracking = {}  # 记录持仓信息
        
        # 初始化交易所
        self.exchange = ccxt.binanceusdm({
            'apiKey': BINANCE_API_KEY,
            'secret': BINANCE_API_SECRET,
            'options': {
                'adjustForTimeDifference': False,
                'recvWindow': 60000,
                'defaultMarketType': 'future',
            },
            'enableRateLimit': True,
        })
        
        # 设置杠杆
        self._set_leverage()
        
        # 初始化策略和风控
        self.strategy = Strategy(SYMBOLS)
        self.risk = RiskManager(MAX_DAILY_LOSS_PCT, STOP_LOSS_PCT, TAKE_PROFIT_PCT)
        
        logging.info(f"✅ Bot initialized (Dry Run: {self.dry_run}, Leverage: {LEVERAGE}x)")
        logging.info(f"🧠 Intelligence Level: AI Sentiment & Trend Detection Enabled")

    def _set_leverage(self):
        """为所有交易对设置杠杆"""
        major_symbols = ['ETH/USDT:USDT', 'BNB/USDT:USDT', 'SOL/USDT:USDT', 'XRP/USDT:USDT', 'DOGE/USDT:USDT']
        for symbol in major_symbols:
            try:
                if not self.dry_run:
                    self.exchange.set_leverage(LEVERAGE, symbol)
                    logging.info(f"✅ Leverage set to {LEVERAGE}x for {symbol}")
                else:
                    logging.info(f"[DRY RUN] Would set leverage to {LEVERAGE}x for {symbol}")
            except Exception as e:
                logging.warning(f"⚠️ Could not set leverage for {symbol}: {e}")

    def get_balance(self):
        """获取账户余额"""
        try:
            balance_data = self.exchange.fetch_balance({'type': 'future'})
            usdt_balance = balance_data['total'].get('USDT', 0)
            return float(usdt_balance)
        except Exception as e:
            logging.error(f"❌ Error fetching balance: {e}")
            raise e

    def get_open_positions(self):
        """检查当前是否有未平仓仓位 - 使用标准接口"""
        try:
            positions = self.exchange.fetch_positions()
            active_symbols = []
            for p in positions:
                contracts = float(p.get('contracts', 0) or 0)
                if contracts != 0:
                    active_symbols.append(p['symbol'])
            return active_symbols
        except Exception as e:
            logging.error(f"❌ Error fetching positions: {e}")
            return []

    def get_position_details(self, symbol):
        """获取仓位详情 - 深度适配币安双向持仓模式"""
        try:
            # 使用 fetch_positions，并显式包含所有模式
            positions = self.exchange.fetch_positions([symbol])
            
            for p in positions:
                contracts = float(p.get('contracts', 0) or 0)
                
                # 在币安双向持仓模式下，同一个 symbol 会有两个 entries
                # 一个是 LONG，一个是 SHORT。我们只返回有持仓的那一个。
                if contracts != 0:
                    entry_price = float(p.get('entryPrice', 0) or 0)
                    unrealized_pnl = float(p.get('unrealizedPnl', 0) or 0)
                    leverage = float(p.get('leverage', 10))
                    
                    # 识别持仓方向
                    # 优先看 'side' (LONG/SHORT)，如果没有则看 contracts 正负
                    pos_side = p.get('side', '').upper()
                    if pos_side not in ['LONG', 'SHORT']:
                        pos_side = 'LONG' if contracts > 0 else 'SHORT'
                    
                    # 准确计算 ROI
                    notional = abs(contracts) * entry_price
                    initial_margin = notional / leverage if leverage > 0 else notional
                    pnl_pct = (unrealized_pnl / initial_margin) * 100 if initial_margin > 0 else 0
                    
                    logging.info(f"📍 Detected Position: {symbol} {pos_side} {abs(contracts)} @ {entry_price}")
                    
                    # 安全获取 markPrice
                    mark_price_raw = p.get('markPrice')
                    mark_price = float(mark_price_raw) if mark_price_raw is not None else 0.0
                    
                    return {
                        'side': pos_side,
                        'size': abs(contracts),
                        'entry_price': entry_price,
                        'unrealized_pnl': unrealized_pnl,
                        'leverage': leverage,
                        'mark_price': mark_price,
                        'pnl_pct': pnl_pct
                    }
            return None
        except Exception as e:
            logging.error(f"❌ Error in get_position_details: {e}")
            return None

    def close_position(self, symbol, reason="Manual"):
        """彻底解决 Hedged 模式平仓失败问题"""
        try:
            details = self.get_position_details(symbol)
            if not details:
                logging.warning(f"⚠️ No position to close for {symbol}")
                return None
            
            # 确定平仓买卖方向
            side = 'sell' if details['side'] == 'LONG' else 'buy'
            amount = details['size']
            pos_side = details['side']
            
            logging.info(f"🚨 CLOSING POSITION: {symbol} {pos_side} {amount} - Reason: {reason}")
            
            if self.dry_run:
                logging.info(f"[DRY RUN] Would close {symbol} {pos_side} position")
                return {"id": "dry_run_close"}
            
            # 1. 尝试使用 closePosition=True 平仓（币安专属参数）
            try:
                order = self.exchange.create_market_order(
                    symbol, side, amount, 
                    params={'positionSide': pos_side, 'closePosition': True}
                )
                logging.info(f"✅ Market Close Successful: {order['id']}")
            except Exception as e:
                logging.warning(f"⚠️ Close with closePosition failed, trying reduceOnly: {e}")
                # 2. 尝试使用 reduceOnly 平仓
                order = self.exchange.create_market_order(
                    symbol, side, amount, 
                    params={'positionSide': pos_side, 'reduceOnly': True}
                )
                logging.info(f"✅ Reduce Order Successful: {order['id']}")
            
            # 发送通知
            self._notify(f"🚨 平仓成功: {symbol}", f"原因: {reason}\n盈亏: {details['unrealized_pnl']:+.2f} USDT", "warning")
            
            # 清除追踪记录
            if symbol in self.position_tracking:
                del self.position_tracking[symbol]
            
            return order
            
        except Exception as e:
            logging.error(f"❌ Error closing position: {e}")
            return None

    def _notify(self, title, content, msg_type="info"):
        """创建通知"""
        notify_file = f"/home/administrator/.openclaw/workspace/binance_bot/.notify_{int(time.time())}"
        with open(notify_file, "w") as f:
            f.write(f"TITLE:{title}\nCONTENT:{content}\nTYPE:{msg_type}\nTIME:{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    def monitor_positions(self):
        """实时监控持仓，基于情绪和走势执行平仓 - 支持动态止盈止损"""
        open_positions = self.get_open_positions()
        
        for symbol in open_positions:
            details = self.get_position_details(symbol)
            if not details:
                continue
            
            pnl_pct = details['pnl_pct']
            
            # 初始化或更新追踪记录
            if symbol not in self.position_tracking:
                self.position_tracking[symbol] = {
                    'max_profit': pnl_pct, 
                    'cycles': 0,
                    'entry_price': details['entry_price'],
                    'side': details['side']
                }
            
            self.position_tracking[symbol]['cycles'] += 1
            if pnl_pct > self.position_tracking[symbol]['max_profit']:
                self.position_tracking[symbol]['max_profit'] = pnl_pct
                logging.info(f"📈 {symbol} 新高盈利: {pnl_pct:+.2f}%")
            
            # 获取最大盈利百分比（用于移动止盈）
            max_profit_pct = self.position_tracking[symbol]['max_profit']
            
            # 1. 策略级智能平仓判断（走势与情绪 + 动态止盈止损）
            exit_reason = self.strategy.calculate_exit_signals(
                self.exchange, symbol, details['side'], details['entry_price'], max_profit_pct
            )
            
            if exit_reason:
                logging.info(f"🧠 SMART EXIT: {symbol} triggered by {exit_reason}")
                self.close_position(symbol, f"Smart Strategy: {exit_reason}")
                continue

            # 2. 极端风险控制（硬止损）
            # 即使策略没说话，如果亏损超过预设极端阈值，也要跑路
            if pnl_pct <= -10.0: # 极端止损 10%
                logging.critical(f"🚨 EXTREME STOP: {symbol} PnL {pnl_pct:.2f}% exceeded safety limit")
                self.close_position(symbol, f"Extreme safety stop: {pnl_pct:.2f}% loss")
                continue
            
            # 输出监控日志
            logging.info(f"📊 {symbol} 监控中 | 盈亏: {pnl_pct:+.2f}% | 最高: {max_profit_pct:+.2f}% | 持仓周期: {self.position_tracking[symbol]['cycles']}")

    def check_trend_reversal(self, symbol, current_side):
        """检查趋势是否反转"""
        try:
            # 获取更短时间周期的数据检查趋势
            ohlcv = self.exchange.fetch_ohlcv(symbol, '5m', limit=20)
            if len(ohlcv) < 10:
                return False
            
            # 计算最近的价格变化
            recent_closes = [c[4] for c in ohlcv[-10:]]
            price_change = ((recent_closes[-1] - recent_closes[0]) / recent_closes[0]) * 100
            
            # 如果是多单，检查是否大幅下跌
            if current_side == 'LONG' and price_change < -1.5:
                logging.warning(f"📉 TREND REVERSAL detected for {symbol}: {price_change:.2f}% drop in 50min")
                return True
            
            # 如果是空单，检查是否大幅上涨
            if current_side == 'SHORT' and price_change > 1.5:
                logging.warning(f"📈 TREND REVERSAL detected for {symbol}: {price_change:.2f}% rise in 50min")
                return True
            
            return False
            
        except Exception as e:
            logging.error(f"❌ Error checking trend: {e}")
            return False

    def execute_trade(self, symbol, side, amount):
        """执行开仓 - 强化多空一致性与杠杆控制"""
        try:
            # 1. 强制设置杠杆 (10x)
            if not self.dry_run:
                try:
                    from config import LEVERAGE
                    self.exchange.set_leverage(LEVERAGE, symbol)
                    logging.info(f"⚙️ Force-set Leverage to {LEVERAGE}x for {symbol}")
                except:
                    pass

            ticker = self.exchange.fetch_ticker(symbol)
            price = ticker['ask'] if side == 'buy' else ticker['bid']
            if price is None: price = ticker['last']
            
            amount = float(self.exchange.amount_to_precision(symbol, amount))
            notional = amount * price
            
            # 2. 检查最小名义价值 (20 USDT)
            if notional < 20.0:
                amount = max(amount, 20.5 / price) # 略高于 20 以防波动
                amount = float(self.exchange.amount_to_precision(symbol, amount))
                notional = amount * price

            logging.info(f"🎯 ENTRY ORDER: {side.upper()} {amount} {symbol} @ ~{price} (Value: {notional:.2f} USDT)")

            if self.dry_run:
                logging.info(f"[DRY RUN] Would {side} {symbol} at {price}")
                return {"id": "dry_run_id"}

            # 确定方向
            pos_side = 'LONG' if side == 'buy' else 'SHORT'
            
            # 3. 建立仓位
            order = self.exchange.create_market_order(symbol, side, amount, params={'positionSide': pos_side})
            logging.info(f"✅ Market Order Executed: {order['id']}")
            
            # 4. 设置止损 (ReduceOnly)
            sl_price = self.risk.calculate_stop_loss_price(side, price)
            sl_side = 'sell' if side == 'buy' else 'buy'
            sl_price = self.exchange.price_to_precision(symbol, sl_price)
            
            try:
                self.exchange.create_order(
                    symbol, 'STOP_MARKET', sl_side, amount, None,
                    {'stopPrice': sl_price, 'positionSide': pos_side, 'reduceOnly': True}
                )
                logging.info(f"🛡️ Stop Loss set at {sl_price}")
            except Exception as e:
                logging.error(f"⚠️ Failed to set Stop Loss: {e}")

            # 5. 设置止盈 (ReduceOnly)
            tp_price = self.risk.calculate_take_profit_price(side, price)
            tp_price = self.exchange.price_to_precision(symbol, tp_price)
            try:
                self.exchange.create_order(
                    symbol, 'TAKE_PROFIT_MARKET', sl_side, amount, None,
                    {'stopPrice': tp_price, 'positionSide': pos_side, 'reduceOnly': True}
                )
                logging.info(f"🎯 Take Profit set at {tp_price}")
            except Exception as e:
                logging.error(f"⚠️ Failed to set Take Profit: {e}")
            
            # 初始化持仓追踪记录
            self.position_tracking[symbol] = {
                'max_profit': 0,
                'entry_time': time.time(),
                'cycles': 0,
                'entry_price': price
            }
            
            self._notify(f"✅ 开仓成功: {symbol}", f"方向: {pos_side}\n数量: {amount}\n价格: {price}", "success")
            
            return order
        except Exception as e:
            logging.error(f"❌ Trade Execution Error: {e}")
            return None

    def run(self):
        """主运行循环"""
        logging.info("🤖 Smart Trading Bot started. Monitoring market with real-time protection...")
        cycle_count = 0
        
        while True:
            try:
                cycle_count += 1
                logging.info(f"\n{'='*60}")
                logging.info(f"📈 Cycle {cycle_count} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                logging.info(f"{'='*60}")
                
                # 1. 实时监控持仓（每周期都检查）
                open_positions = self.get_open_positions()
                if open_positions:
                    logging.info(f"🔍 Monitoring {len(open_positions)} position(s)...")
                    self.monitor_positions()
                
                # 2. 获取账户余额
                current_balance = self.get_balance()
                logging.info(f"💰 Account Balance: {current_balance:.2f} USDT")
                
                # 3. 检查是否需要开新仓
                max_positions = 2
                open_positions = self.get_open_positions()  # 重新获取（可能已平仓）
                
                if open_positions:
                    logging.info(f"📦 Active Positions: {open_positions} (Max: {max_positions})")
                    for pos in open_positions:
                        details = self.get_position_details(pos)
                        if details:
                            pnl_emoji = "🟢" if details['unrealized_pnl'] >= 0 else "🔴"
                            logging.info(f"   {pos}: {details['side']} {details['size']} @ {details['entry_price']:.2f} | PnL: {pnl_emoji} {details['unrealized_pnl']:.2f} USDT ({details['pnl_pct']:+.2f}%)")
                    
                    if len(open_positions) >= max_positions:
                        logging.info(f"⏸️ Max positions ({max_positions}) reached. Monitoring only.")
                    else:
                        logging.info(f"📊 Positions: {len(open_positions)}/{max_positions}. Scanning for entries...")
                        self._scan_for_entries(open_positions, max_positions, current_balance)
                else:
                    logging.info("🔍 No active positions. Scanning for signals...")
                    self._scan_for_entries([], max_positions, current_balance)
                
                self.consecutive_errors = 0
                
                logging.info(f"⏳ Cycle {cycle_count} complete. Sleeping {LOOP_INTERVAL}s...")
                time.sleep(LOOP_INTERVAL)
                
            except Exception as e:
                self.consecutive_errors += 1
                logging.error(f"❌ Main Loop Error (Attempt {self.consecutive_errors}/{self.max_consecutive_errors}): {e}")
                
                if self.consecutive_errors >= self.max_consecutive_errors:
                    logging.critical("🛑 Too many consecutive errors. Stopping bot.")
                    self._notify("🛑 交易机器人停止", f"连续错误次数过多，机器人已停止。\n错误: {str(e)}", "error")
                    break
                
                time.sleep(10)

    def _scan_for_entries(self, open_positions, max_positions, balance):
        """扫描入场信号 - 使用账户余额50%开仓"""
        signals = self.strategy.calculate_signals(self.exchange)
        
        if signals:
            logging.info(f"🚨 SIGNAL DETECTED: {signals}")
            for symbol, side in signals.items():
                if symbol == 'meta':
                    continue
                
                # 检查是否已经在该币种上有仓位
                if symbol in open_positions:
                    logging.info(f"⏭️ Already holding {symbol}, skipping...")
                    continue
                
                # 检查趋势是否反转
                current_side = 'LONG' if side == 'buy' else 'SHORT'
                if self.check_trend_reversal(symbol, current_side):
                    logging.warning(f"⚠️ Trend reversal detected for {symbol}, skipping entry")
                    continue
                
                ticker = self.exchange.fetch_ticker(symbol)
                price = ticker['last']
                
                # 计算仓位：使用余额的95%，但最低不少于14 USDT（兼容小资金账户）
                position_value = max(balance * 0.95, 14.0)
                
                # 检查余额是否足够开仓（最低14 USDT）
                if balance < 14:
                    logging.warning(f"⚠️ Balance too low: {balance:.2f} USDT, need at least 14 USDT")
                    continue
                
                amount = position_value / price
                
                # 检查最小数量限制
                min_amount = self.exchange.markets[symbol]['limits']['amount']['min']
                if amount < min_amount:
                    amount = min_amount
                
                amount = float(self.exchange.amount_to_precision(symbol, amount))
                actual_value = amount * price
                
                # 判断多空方向
                direction = "做多" if side == 'buy' else "做空"
                logging.info(f"🎯 Entry: {symbol} {direction} | Amount: {amount} | Value: ~{actual_value:.2f} USDT (50% of {balance:.2f})")
                self.execute_trade(symbol, side, amount)
                
                # 开仓后刷新仓位列表
                open_positions = self.get_open_positions()
                if len(open_positions) >= max_positions:
                    logging.info(f"✅ Reached max positions ({max_positions}), stopping entries for this cycle.")
                    break
        else:
            logging.info("📭 No signal detected.")

if __name__ == "__main__":
    dry_run_flag = '--real' not in sys.argv
    bot = BinanceBot(dry_run=dry_run_flag)
    bot.run()
