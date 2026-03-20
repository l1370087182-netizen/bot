#!/usr/bin/env python3
"""
Binance Bot - 智能交易监控系统 v7.0 (机构级因子版)
更新：MTF宏观过滤、ATR加权调仓、MFI资金流验证
"""
import ccxt
import time
import logging
import os
import sys
import json
import pandas as pd
import numpy as np
from datetime import datetime
import requests

# ========== 时间偏移修复 ==========
try:
    resp = requests.get('https://api.binance.com/api/v3/time', timeout=5)
    server_time = resp.json()['serverTime']
    local_time = int(time.time() * 1000)
    FORCED_OFFSET_MS = local_time - server_time + 1000
except:
    FORCED_OFFSET_MS = 3000

_ccxt_milliseconds = ccxt.Exchange.milliseconds
@staticmethod
def patched_milliseconds():
    return _ccxt_milliseconds() - FORCED_OFFSET_MS
ccxt.Exchange.milliseconds = patched_milliseconds
# ========== 修复结束 ==========

from config import *
from strategy import Strategy
from risk_manager import RiskManager

# Logging setup
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

class BinanceBot:
    def __init__(self, dry_run=True):
        self.dry_run = dry_run
        self.consecutive_errors = 0
        self.max_consecutive_errors = 10
        self.cooldowns = {}
        self.position_tracking = self._load_position_tracking()  # 加载持久化数据
        
        self.exchange = ccxt.binanceusdm({
            'apiKey': BINANCE_API_KEY,
            'secret': BINANCE_API_SECRET,
            'options': {'adjustForTimeDifference': True, 'recvWindow': 10000, 'defaultMarketType': 'future'},
            'enableRateLimit': True,
        })
        
        self.strategy = Strategy(SYMBOLS)
        self.risk = RiskManager(MAX_DAILY_LOSS_PCT, STOP_LOSS_PCT, TAKE_PROFIT_PCT)
        
        logging.info(f"✅ Bot v9.0 Initialized (Dry Run: {self.dry_run})")
        logging.info("⚠️ 免责声明: 本系统为实验性量化策略，无回测验证，请谨慎使用")

    def get_balance(self):
        """获取余额，带重试机制"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                balance_data = self.exchange.fetch_balance({'type': 'future'})
                balance = float(balance_data['total'].get('USDT', 0))
                self.consecutive_errors = 0  # 重置错误计数
                return balance
            except Exception as e:
                self.consecutive_errors += 1
                logging.error(f"❌ Balance Error (attempt {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # 指数退避
                else:
                    raise e
    
    def get_open_positions(self):
        """获取持仓，带重试机制"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                positions = self.exchange.fetch_positions()
                self.consecutive_errors = 0
                return [p['symbol'] for p in positions if float(p.get('contracts', 0) or 0) != 0]
            except Exception as e:
                self.consecutive_errors += 1
                logging.error(f"❌ Fetch Positions Error (attempt {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    return []

    def get_position_details(self, symbol):
        try:
            positions = self.exchange.fetch_positions([symbol])
            for p in positions:
                contracts = float(p.get('contracts', 0) or 0)
                if contracts != 0:
                    entry_price = float(p.get('entryPrice') or 0.0)
                    unrealized_pnl = float(p.get('unrealizedPnl') or 0.0)
                    leverage = float(p.get('leverage') or 10.0)
                    pos_side = str(p.get('side', '')).upper()
                    if pos_side not in ['LONG', 'SHORT']:
                        pos_side = 'LONG' if contracts > 0 else 'SHORT'
                    
                    notional = abs(contracts) * entry_price
                    initial_margin = notional / leverage if leverage > 0 else notional
                    pnl_pct = (unrealized_pnl / initial_margin) * 100 if initial_margin > 0 else 0
                    mark_price = float(p.get('markPrice') or entry_price)
                    liquidation_price = float(p.get('liquidationPrice') or 0.0)
                    
                    # 计算强平风险
                    liquidation_risk = self._calculate_liquidation_risk(
                        pos_side, entry_price, liquidation_price, leverage
                    )
                    
                    return {
                        'side': pos_side, 'size': abs(contracts), 'entry_price': entry_price,
                        'unrealized_pnl': unrealized_pnl, 'leverage': leverage,
                        'mark_price': mark_price, 'pnl_pct': pnl_pct,
                        'liquidation_price': liquidation_price,
                        'liquidation_risk': liquidation_risk
                    }
            return None
        except Exception as e:
            logging.error(f"❌ Position Details Error: {e}")
            return None
    
    def _calculate_liquidation_risk(self, side, entry_price, liq_price, leverage):
        """计算强平风险等级"""
        if not liq_price or liq_price == 0:
            return 'UNKNOWN'
        
        if side == 'LONG':
            distance_pct = (entry_price - liq_price) / entry_price * 100
        else:
            distance_pct = (liq_price - entry_price) / entry_price * 100
        
        # 风险等级
        if distance_pct < 10:
            return 'HIGH'  # 高风险
        elif distance_pct < 20:
            return 'MEDIUM'  # 中等风险
        else:
            return 'LOW'  # 低风险

    def _load_position_tracking(self):
        """加载持仓追踪数据（持久化 max_profit）"""
        try:
            tracking_file = "/home/administrator/.openclaw/workspace/binance_bot/.position_tracking"
            if os.path.exists(tracking_file):
                with open(tracking_file, 'r') as f:
                    data = json.load(f)
                    # 转换字符串 key 回 float (时间戳)
                    return {k: v for k, v in data.items()}
            return {}
        except Exception as e:
            logging.error(f"❌ Load tracking error: {e}")
            return {}

    def _save_position_tracking(self):
        """保存持仓追踪数据"""
        try:
            tracking_file = "/home/administrator/.openclaw/workspace/binance_bot/.position_tracking"
            with open(tracking_file, 'w') as f:
                json.dump(self.position_tracking, f)
        except Exception as e:
            logging.error(f"❌ Save tracking error: {e}")

    def execute_trade(self, symbol, side, amount, use_leverage=10):
        try:
            if not self.dry_run:
                self.exchange.set_leverage(int(use_leverage), symbol)
            
            pos_side = 'LONG' if side == 'buy' else 'SHORT'
            if not self.dry_run:
                order = self.exchange.create_market_order(symbol, side, amount, params={'positionSide': pos_side})
            else:
                order = {'id': 'dry_run_trade'}
            
            self.position_tracking[symbol] = {
                'max_profit': 0, 'entry_time': time.time(), 'cycles': 0,
                'entry_price': 0, 'side': pos_side, 'atr_stop_price': None
            }
            self._save_position_tracking()  # 持久化
            
            msg = f"🚀 v7.0 {pos_side} {symbol}\n数量: {amount}\n杠杆: {use_leverage}x"
            self._notify(f"✅ 开仓成功: {symbol}", msg, "success")
            return order
        except Exception as e:
            logging.error(f"❌ Trade Execution Error: {e}")
            return None

    def close_position(self, symbol, reason="Manual"):
        try:
            details = self.get_position_details(symbol)
            if not details: return None
            
            side = 'sell' if details['side'] == 'LONG' else 'buy'
            if not self.dry_run:
                order = self.exchange.create_market_order(symbol, side, details['size'], params={'positionSide': details['side']})
            
            pnl_str = f"{details['unrealized_pnl']:+.2f} USDT ({details['pnl_pct']:+.2f}%)"
            self._notify(f"🚨 平仓成功: {symbol}", f"原因: {reason}\n盈亏: {pnl_str}", "warning")
            
            if details['unrealized_pnl'] < 0:
                self.cooldowns[symbol] = time.time()
            
            if symbol in self.position_tracking: 
                del self.position_tracking[symbol]
                self._save_position_tracking()  # 持久化
            return True
        except Exception as e:
            logging.error(f"❌ Close Error: {e}")
            return None

    def _notify(self, title, content, msg_type="info"):
        try:
            bark_url = f"https://api.day.app/jRTuEZmk2j254haTnwtd7Q/{requests.utils.quote(title)}/{requests.utils.quote(content)}?group=BinanceBot"
            requests.get(bark_url, timeout=10)
        except: pass

    def _update_status_file(self, open_positions, balance):
        try:
            status = {'timestamp': time.time(), 'balance': balance, 'position_count': len(open_positions), 'positions': []}
            for symbol in open_positions:
                d = self.get_position_details(symbol)
                if d:
                    status['positions'].append({
                        'symbol': symbol, 'side': d['side'], 'size': d['size'],
                        'entry_price': d['entry_price'], 'mark_price': d['mark_price'],
                        'unrealized_pnl': d['unrealized_pnl'], 'pnl_pct': d['pnl_pct'],
                        'leverage': d['leverage'], 'liquidation_price': d['liquidation_price']
                    })
            with open("/home/administrator/.openclaw/workspace/binance_bot/.bot_status", 'w') as f:
                json.dump(status, f)
        except: pass

    def calculate_dynamic_leverage(self, balance, current_price, symbol_atr, funding_rate=0):
        """
        动态杠杆计算 - 基于波动率和资金费率
        
        考虑因素:
        1. ATR波动率 - 波动越大杠杆越低
        2. 资金费率 - 正费率(多头付)降低多头杠杆
        3. 账户余额 - 余额越少杠杆越低(保护小账户)
        """
        # 基础杠杆
        base_leverage = 10
        
        # 1. 波动率调节
        if symbol_atr and current_price:
            volatility_ratio = symbol_atr / current_price
            # 波动率 < 0.5%: 10x, 0.5-1%: 7x, 1-2%: 5x, 2-3%: 3x, >3%: 2x
            if volatility_ratio < 0.005:
                vol_adjusted = 10
            elif volatility_ratio < 0.01:
                vol_adjusted = 7
            elif volatility_ratio < 0.02:
                vol_adjusted = 5
            elif volatility_ratio < 0.03:
                vol_adjusted = 3
            else:
                vol_adjusted = 2
        else:
            vol_adjusted = 5
        
        # 2. 资金费率调节 (如果资金费率高，降低杠杆)
        funding_adjusted = vol_adjusted
        if funding_rate > 0.0001:  # 0.01%资金费率
            funding_adjusted = max(3, vol_adjusted - 2)
        elif funding_rate > 0.0005:  # 0.05%资金费率
            funding_adjusted = max(2, vol_adjusted - 3)
        
        # 3. 余额保护 (小账户降低杠杆)
        if balance < 50:
            balance_adjusted = max(3, funding_adjusted - 3)
        elif balance < 100:
            balance_adjusted = max(5, funding_adjusted - 2)
        else:
            balance_adjusted = funding_adjusted
        
        final_leverage = min(base_leverage, balance_adjusted)
        
        # 计算保证金和名义价值
        margin = balance * 0.2  # 20%保证金
        notional = margin * final_leverage
        
        return {
            'leverage': final_leverage,
            'margin': margin,
            'notional': notional,
            'volatility_ratio': volatility_ratio if symbol_atr and current_price else 0
        }

    def _scan_for_entries(self, balance):
        signals = self.strategy.calculate_signals(self.exchange)
        if not signals: return
        
        for symbol, side in signals.items():
            if symbol in self.cooldowns and time.time() - self.cooldowns[symbol] < 3600: continue
            
            curr_pos = self.get_open_positions()
            if len(curr_pos) >= 5 or symbol in curr_pos: continue
            
            try:
                ticker = self.exchange.fetch_ticker(symbol)
                # 简单 ATR 获取
                ohlcv = self.exchange.fetch_ohlcv(symbol, '30m', limit=20)
                df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
                tr = np.max(pd.concat([df['h']-df['l'], np.abs(df['h']-df['c'].shift()), np.abs(df['l']-df['c'].shift())], axis=1), axis=1)
                atr = tr.rolling(14).mean().iloc[-1]
                
                cfg = self.calculate_dynamic_leverage(balance, ticker['last'], atr)
                amount = float(self.exchange.amount_to_precision(symbol, cfg['notional'] / ticker['last']))
                
                if cfg['notional'] >= 10.0:
                    self.execute_trade(symbol, side, amount, cfg['leverage'])
            except: continue

    def monitor_positions(self):
        symbols = self.get_open_positions()
        for s in symbols:
            d = self.get_position_details(s)
            if not d: continue
            
            track = self.position_tracking.get(s, {'max_profit': 0})
            if d['pnl_pct'] > track['max_profit']: 
                track['max_profit'] = d['pnl_pct']
                self.position_tracking[s] = track
                self._save_position_tracking()  # 保存新的 max_profit
            
            exit_reason = self.strategy.calculate_exit_signals(self.exchange, s, d['side'], d['entry_price'], track['max_profit'], track)
            if exit_reason:
                self.close_position(s, exit_reason)

    def run(self):
        logging.info("🚀 v9.0 Dynamic Dual Filter System Running...")
        logging.info("📊 策略: 纯技术指标规则系统 | 无机器学习成分")
        last_scan = 0
        while True:
            try:
                now = time.time()
                balance = self.get_balance()
                pos = self.get_open_positions()
                
                # 检查每日亏损限制
                if not self.risk.check_daily_limit(balance):
                    logging.warning("🛑 Daily loss limit reached. Trading halted.")
                    time.sleep(300)  # 5分钟后重试
                    continue
                
                # 每 2s 监控与同步
                self.monitor_positions()
                self._update_status_file(pos, balance)
                
                # 每 60s 扫描
                if now - last_scan >= 60:
                    logging.info(f"💰 Account Balance: {balance:.2f} USDT")
                    self._scan_for_entries(balance)
                    last_scan = now
                
                time.sleep(2)
            except Exception as e:
                logging.error(f"Main Error: {e}")
                time.sleep(10)

if __name__ == "__main__":
    bot = BinanceBot(dry_run='--real' not in sys.argv)
    bot.run()
