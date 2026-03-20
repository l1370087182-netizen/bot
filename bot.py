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
# 动态获取时间偏移
import requests

try:
    resp = requests.get('https://api.binance.com/api/v3/time', timeout=5)
    server_time = resp.json()['serverTime']
    local_time = int(time.time() * 1000)
    FORCED_OFFSET_MS = local_time - server_time + 1000  # 加1000ms缓冲
except:
    FORCED_OFFSET_MS = 3000  # 默认值

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
                'adjustForTimeDifference': True,
                'recvWindow': 10000,
                'defaultMarketType': 'future',
            },
            'enableRateLimit': True,
        })
        
        # 初始化策略和风控
        self.strategy = Strategy(SYMBOLS)
        self.risk = RiskManager(MAX_DAILY_LOSS_PCT, STOP_LOSS_PCT, TAKE_PROFIT_PCT)
        
        logging.info(f"✅ Bot initialized (Dry Run: {self.dry_run})")
        logging.info(f"🧠 Dynamic Leverage: Enabled (3x-10x based on margin ratio)")
        logging.info(f"🧠 Intelligence Level: AI Sentiment & Trend Detection Enabled")

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
                    try:
                        entry_price = float(p.get('entryPrice') if p.get('entryPrice') is not None else 0.0)
                        unrealized_pnl = float(p.get('unrealizedPnl') if p.get('unrealizedPnl') is not None else 0.0)
                        leverage = float(p.get('leverage') if p.get('leverage') is not None else 10.0)
                    except (ValueError, TypeError):
                        entry_price = 0.0
                        unrealized_pnl = 0.0
                        leverage = 10.0
                    
                    # 识别持仓方向
                    pos_side = str(p.get('side', '')).upper()
                    if pos_side not in ['LONG', 'SHORT']:
                        pos_side = 'LONG' if contracts > 0 else 'SHORT'
                    
                    # 准确计算 ROI
                    notional = abs(contracts) * entry_price
                    initial_margin = notional / leverage if leverage > 0 else notional
                    pnl_pct = (unrealized_pnl / initial_margin) * 100 if initial_margin > 0 else 0
                    
                    logging.info(f"📍 Detected Position: {symbol} {pos_side} {abs(contracts)} @ {entry_price}")
                    
                    # 安全获取 markPrice
                    mark_price_raw = p.get('markPrice')
                    try:
                        mark_price = float(mark_price_raw) if mark_price_raw is not None else entry_price
                    except (ValueError, TypeError):
                        mark_price = entry_price
                    
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
            
            # 1. 尝试平仓 - 双向持仓模式下只使用 positionSide
            try:
                order = self.exchange.create_market_order(
                    symbol, side, amount, 
                    params={'positionSide': pos_side}
                )
                logging.info(f"✅ Market Close Successful: {order['id']}")
            except Exception as e:
                logging.warning(f"⚠️ Close failed: {e}")
                return None
            
            # 发送通知
            self._notify(f"🚨 平仓成功: {symbol}", f"原因: {reason}\n盈亏: {details['unrealized_pnl']:+.2f} USDT", "warning")
            
            # 清除追踪记录 - 确保该币种可以重新开仓
            if symbol in self.position_tracking:
                logging.info(f"🗑️ Clearing position tracking for {symbol}")
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

    def _update_status_file(self, open_positions, balance):
        """更新实时状态文件（供 Web 面板读取）"""
        try:
            status = {
                'timestamp': time.time(),
                'balance': balance,
                'position_count': len(open_positions),
                'positions': []
            }
            
            for symbol in open_positions:
                details = self.get_position_details(symbol)
                if details:
                    tracking = self.position_tracking.get(symbol, {})
                    status['positions'].append({
                        'symbol': symbol,
                        'side': details['side'],
                        'size': details['size'],
                        'entry_price': details['entry_price'],
                        'mark_price': details['mark_price'],
                        'unrealized_pnl': details['unrealized_pnl'],
                        'pnl_pct': details['pnl_pct'],
                        'max_profit': tracking.get('max_profit', 0),
                        'cycles': tracking.get('cycles', 0)
                    })
            
            status_file = "/home/administrator/.openclaw/workspace/binance_bot/.bot_status"
            with open(status_file, 'w') as f:
                json.dump(status, f)
        except Exception as e:
            logging.debug(f"Failed to update status file: {e}")

    def monitor_positions(self):
        """实时监控持仓，基于 ATR 移动止损和情绪执行平仓"""
        open_positions = self.get_open_positions()
        
        for symbol in open_positions:
            details = self.get_position_details(symbol)
            if not details:
                continue
            
            pnl_pct = details['pnl_pct']
            current_price = details['mark_price']
            
            # 初始化或更新追踪记录
            if symbol not in self.position_tracking:
                self.position_tracking[symbol] = {
                    'max_profit': pnl_pct,
                    'cycles': 0,
                    'entry_price': details['entry_price'],
                    'side': details['side'],
                    'highest_price': current_price if details['side'] == 'LONG' else 0,
                    'lowest_price': current_price if details['side'] == 'SHORT' else float('inf'),
                    'atr_stop_price': None
                }
            
            self.position_tracking[symbol]['cycles'] += 1
            if pnl_pct > self.position_tracking[symbol]['max_profit']:
                self.position_tracking[symbol]['max_profit'] = pnl_pct
                logging.info(f"📈 {symbol} 新高盈利: {pnl_pct:+.2f}%")
            
            # 获取最大盈利百分比（用于移动止盈）
            max_profit_pct = self.position_tracking[symbol]['max_profit']
            
            # 1. 策略级智能平仓判断（ATR移动止损 + 走势与情绪）
            exit_reason = self.strategy.calculate_exit_signals(
                self.exchange, symbol, details['side'], details['entry_price'], 
                max_profit_pct, self.position_tracking[symbol]
            )
            
            if exit_reason:
                logging.info(f"🧠 SMART EXIT: {symbol} triggered by {exit_reason}")
                self.close_position(symbol, f"Smart Strategy: {exit_reason}")
                continue

            # 2. 紧急硬止损 (10%) - 最后防线，仅在极端情况下触发
            if pnl_pct <= -10.0:
                logging.critical(f"🚨 EMERGENCY STOP: {symbol} PnL {pnl_pct:.2f}% exceeded hard limit")
                self.close_position(symbol, f"Emergency Stop: {pnl_pct:.2f}%")
                continue
            
            # 输出监控日志（包含ATR止损线信息）
            atr_stop = self.position_tracking[symbol].get('atr_stop_price', 'N/A')
            if atr_stop != 'N/A':
                atr_stop_str = f"ATR止损:{atr_stop:.2f}"
            else:
                atr_stop_str = "ATR止损:计算中"
            logging.info(f"📊 {symbol} 监控中 | 盈亏:{pnl_pct:+.2f}% | 最高:{max_profit_pct:+.2f}% | {atr_stop_str} | 周期:{self.position_tracking[symbol]['cycles']}")

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

    def execute_trade(self, symbol, side, amount, leverage=None):
        """执行开仓 - 支持动态杠杆"""
        try:
            # 使用传入的杠杆或默认杠杆
            from config import LEVERAGE as DEFAULT_LEVERAGE
            use_leverage = leverage if leverage else DEFAULT_LEVERAGE
            
            # 1. 设置杠杆
            if not self.dry_run:
                try:
                    self.exchange.set_leverage(use_leverage, symbol)
                    logging.info(f"⚙️ Set Leverage to {use_leverage}x for {symbol}")
                except Exception as e:
                    logging.warning(f"⚠️ Could not set leverage for {symbol}: {e}")

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

            logging.info(f"🎯 ENTRY ORDER: {side.upper()} {amount} {symbol} @ ~{price:.4f} (Value: {notional:.2f} USDT, {use_leverage}x)")

            if self.dry_run:
                logging.info(f"[DRY RUN] Would {side} {symbol} at {price} with {use_leverage}x leverage")
                return {"id": "dry_run_id"}

            # 确定方向
            pos_side = 'LONG' if side == 'buy' else 'SHORT'
            
            # 3. 建立仓位
            order = self.exchange.create_market_order(symbol, side, amount, params={'positionSide': pos_side})
            logging.info(f"✅ Market Order Executed: {order['id']}")
            
            # 纯动态监控平仓 - 不设置固定止损止盈订单
            # 所有平仓逻辑由 monitor_positions() 动态处理
            
            # 初始化持仓追踪记录（包含ATR移动止损所需数据）
            self.position_tracking[symbol] = {
                'max_profit': 0,
                'entry_time': time.time(),
                'cycles': 0,
                'entry_price': price,
                'side': pos_side,
                'highest_price': price if pos_side == 'LONG' else 0,
                'lowest_price': price if pos_side == 'SHORT' else float('inf'),
                'atr_stop_price': None,  # 将在第一个监控周期计算
                'leverage': use_leverage  # 记录使用的杠杆
            }
            
            self._notify(f"✅ 开仓成功: {symbol}", f"方向: {pos_side}\n数量: {amount}\n价格: {price}\n杠杆: {use_leverage}x", "success")
            
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
                
                # 1. 获取账户余额
                current_balance = self.get_balance()
                logging.info(f"💰 Account Balance: {current_balance:.2f} USDT")
                
                # 2. 实时监控持仓（每周期都检查）
                open_positions = self.get_open_positions()
                if open_positions:
                    logging.info(f"🔍 Monitoring {len(open_positions)} position(s)...")
                    self.monitor_positions()
                    
                # 更新实时状态文件（供 Web 面板读取）
                self._update_status_file(open_positions, current_balance)
                
                # 2. 检查是否需要开新仓
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

    def calculate_dynamic_leverage(self, balance, current_price, min_notional=20.0):
        """
        计算动态杠杆倍数 - 基于保证金比率
        
        策略:
        1. 目标使用余额的 50% 作为保证金
        2. 根据当前价格计算所需杠杆，使名义价值 >= min_notional
        3. 杠杆范围: 3x - 10x
        
        Returns:
            dict: {'leverage': int, 'margin': float, 'notional': float}
        """
        from config import DYNAMIC_LEVERAGE
        
        if not DYNAMIC_LEVERAGE['enabled']:
            # 使用固定杠杆
            margin = balance * POSITION_SIZE_PCT
            leverage = LEVERAGE
            notional = margin * leverage
            return {'leverage': leverage, 'margin': margin, 'notional': notional}
        
        max_lev = DYNAMIC_LEVERAGE['max_leverage']
        min_lev = DYNAMIC_LEVERAGE['min_leverage']
        target_margin_ratio = DYNAMIC_LEVERAGE['target_margin_ratio']
        min_margin = DYNAMIC_LEVERAGE['min_margin_amount']
        
        # 目标保证金金额 (余额的 50%)
        target_margin = balance * target_margin_ratio
        
        # 确保不低于最小保证金
        margin = max(target_margin, min_margin)
        
        # 计算达到最小名义价值所需的杠杆
        required_leverage = min_notional / margin if margin > 0 else max_lev
        
        # 限制杠杆范围
        leverage = int(max(min_lev, min(max_lev, required_leverage)))
        
        # 重新计算名义价值
        notional = margin * leverage
        
        # 如果名义价值仍不足，调整保证金
        if notional < min_notional:
            margin = min_notional / leverage
            notional = margin * leverage
        
        return {
            'leverage': leverage,
            'margin': margin,
            'notional': notional
        }

    def _scan_for_entries(self, open_positions, max_positions, balance):
        """扫描入场信号 - 使用动态杠杆和保证金比率"""
        signals = self.strategy.calculate_signals(self.exchange)
        
        if signals:
            logging.info(f"🚨 SIGNAL DETECTED: {signals}")
            for symbol, side in signals.items():
                if symbol == 'meta':
                    continue
                
                # ========== 单币种仓位限制检查 ==========
                # 检查是否已经在该币种上有仓位（包括做多或做空）
                if symbol in open_positions:
                    logging.info(f"⏭️ Already holding {symbol}, cannot open new position until current one is closed.")
                    continue
                
                # 检查该币种是否正在追踪中（有未完成的仓位记录）
                # 这确保即使API暂时查询不到仓位，也不会重复开仓
                if symbol in self.position_tracking:
                    logging.info(f"⏭️ {symbol} position tracking active, waiting for close confirmation.")
                    continue
                
                # 检查趋势是否反转
                current_side = 'LONG' if side == 'buy' else 'SHORT'
                if self.check_trend_reversal(symbol, current_side):
                    logging.warning(f"⚠️ Trend reversal detected for {symbol}, skipping entry")
                    continue
                
                ticker = self.exchange.fetch_ticker(symbol)
                price = ticker['last']
                
                # ========== 动态杠杆计算 ==========
                position_config = self.calculate_dynamic_leverage(balance, price, MIN_ORDER_VALUE_USDT)
                leverage = position_config['leverage']
                margin = position_config['margin']
                notional = position_config['notional']
                
                # 检查是否满足最小名义价值
                if notional < MIN_ORDER_VALUE_USDT:
                    logging.warning(f"⚠️ Account too small: {balance:.2f} USDT, cannot meet min notional {MIN_ORDER_VALUE_USDT} USDT")
                    continue
                
                # 检查保证金是否足够
                if margin > balance * 0.95:  # 留 5% 缓冲
                    logging.warning(f"⚠️ Insufficient margin: need {margin:.2f} USDT, have {balance:.2f} USDT")
                    continue
                
                logging.info(f"💰 Dynamic Leverage: {leverage}x | Margin: {margin:.2f} USDT | Notional: {notional:.2f} USDT (Balance: {balance:.2f} USDT)")
                
                amount = notional / price
                
                # 检查最小数量限制
                min_amount = self.exchange.markets[symbol]['limits']['amount']['min']
                if amount < min_amount:
                    amount = min_amount
                
                amount = float(self.exchange.amount_to_precision(symbol, amount))
                actual_notional = amount * price
                
                # 判断多空方向
                direction = "做多" if side == 'buy' else "做空"
                logging.info(f"🎯 Entry: {symbol} {direction} {amount} @ ~{price:.4f} | Value: ~{actual_notional:.2f} USDT ({leverage}x leverage)")
                
                # 执行交易（传入动态杠杆）
                self.execute_trade(symbol, side, amount, leverage)
                
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
