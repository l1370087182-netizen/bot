#!/usr/bin/env python3
"""
Binance Bot - 智能交易监控系统 v10.0 (机构级因子版)
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
from performance_tracker import PerformanceTracker
from telegram_notifier import telegram

# 导入智能执行模块
try:
    from src.execution.execution_intelligence import ExecutionStrategy, TWAPExecutor
    EXECUTION_INTEL_AVAILABLE = True
except ImportError as e:
    EXECUTION_INTEL_AVAILABLE = False
    logging.warning(f"智能执行模块未可用: {e}")

# ========== v10.0 新架构模块 ==========
import sys
sys.path.insert(0, 'src')

try:
    from risk.position_sizer import PositionSizer
    from risk.pyramiding import PyramidingManager
    from risk.exit_manager import ExitManager
    from risk.account_guardian import AccountGuardian
    from risk.coin_grouper import CoinGrouper
    from strategies.signal_scorer import SignalQualityScorer
    from utils.database import DatabaseManager
    V10_AVAILABLE = True
except ImportError as e:
    V10_AVAILABLE = False
    print(f"v10.0 modules not available: {e}")
# ========== v10.0 模块结束 ==========

from risk_manager import RiskManager

# Logging setup - 强制单文件处理器实时刷新
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# 彻底清除所有现有处理器，防止重复输出
while logger.handlers:
    logger.removeHandler(logger.handlers[0])

# 文件处理器
file_handler = logging.FileHandler('bot.log', mode='a', encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

# 立即刷新
def flush_emit(record):
    logging.FileHandler.emit(file_handler, record)
    file_handler.stream.flush()

file_handler.emit = flush_emit
logger.addHandler(file_handler)

# 注意：不再添加StreamHandler，因为nohup会将stdout也重定向到日志文件，导致重复
# 如果需要查看实时输出，请使用 tail -f bot.log

class BinanceBot:
    def __init__(self, dry_run=True):
        self.dry_run = dry_run
        self.consecutive_errors = 0
        self.max_consecutive_errors = 10
        self.cooldowns = {}
        self.position_tracking = self._load_position_tracking()  # 加载持久化数据
        
        # Windows E盘报告路径
        self.windows_report_path = "/mnt/e/TradingReports"
        self._init_windows_report_path()
        
        self.exchange = ccxt.binanceusdm({
            'apiKey': BINANCE_API_KEY,
            'secret': BINANCE_API_SECRET,
            'options': {'adjustForTimeDifference': True, 'recvWindow': 10000, 'defaultMarketType': 'future'},
            'enableRateLimit': True,
        })
        
        self.strategy = Strategy(SYMBOLS)
        self.risk = RiskManager(MAX_DAILY_LOSS_PCT, STOP_LOSS_PCT, TAKE_PROFIT_PCT)
        
        # 初始化智能执行器
        if EXECUTION_INTEL_AVAILABLE:
            self.execution_strategy = ExecutionStrategy(self.exchange, max_slippage_pct=0.15)
            self.twap_executor = TWAPExecutor(self.exchange, num_slices=2, interval_seconds=3)
            logging.info("🧠 智能执行算法已启用 (Maker优先 + TWAP拆单)")
        else:
            self.execution_strategy = None
            self.twap_executor = None
        # ========== v10.0 新架构初始化 ==========
        if V10_AVAILABLE:
            self.position_sizer = PositionSizer(risk_per_trade=0.02)
            self.pyramiding = PyramidingManager()
            self.exit_manager = ExitManager()
            self.guardian = AccountGuardian(
                daily_loss_limit=0.05,
                drawdown_limit_1=0.07,
                drawdown_limit_2=0.10
            )
            self.coin_grouper = CoinGrouper()
            self.signal_scorer = SignalQualityScorer()
            self.db = DatabaseManager('trades.db')
            self.v10_mode = True
            logging.info("🚀 v10.0 Mode: Three-layer protection + Amplifier")
        else:
            self.v10_mode = False
            self.position_sizer = None
        # ========== v10.0 初始化结束 ==========

        
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
                open_pos = [p['symbol'] for p in positions if float(p.get('contracts', 0) or 0) != 0]
                if open_pos:
                    logging.info(f"📊 当前持仓: {open_pos}")
                return open_pos
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

    def _init_windows_report_path(self):
        """初始化Windows E盘报告目录"""
        try:
            # 创建Windows E盘报告目录
            windows_path = "/mnt/e/TradingReports"
            if os.path.exists("/mnt/e"):
                os.makedirs(windows_path, exist_ok=True)
                # 创建子目录
                os.makedirs(f"{windows_path}/OpenTrades", exist_ok=True)
                os.makedirs(f"{windows_path}/CloseTrades", exist_ok=True)
                os.makedirs(f"{windows_path}/DailyReports", exist_ok=True)
                logging.info(f"📁 Windows报告目录已初始化: {windows_path}")
            else:
                logging.warning("⚠️ Windows E盘未挂载，报告将保存到本地")
        except Exception as e:
            logging.error(f"❌ 初始化Windows报告目录失败: {e}")

    def _save_trade_report(self, trade_type, symbol, side, price, size, leverage, pnl=None, pnl_pct=None, reason=None):
        """保存交易报告到Windows E盘"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            date_str = datetime.now().strftime('%Y%m%d')
            
            # 确定保存路径
            if trade_type == 'open':
                folder = f"{self.windows_report_path}/OpenTrades"
                filename = f"{folder}/{date_str}_OPEN_{symbol.replace('/', '_')}_{timestamp}.json"
                report = {
                    'type': 'OPEN',
                    'symbol': symbol,
                    'side': side,
                    'entry_price': price,
                    'size': size,
                    'leverage': leverage,
                    'timestamp': timestamp,
                    'datetime': datetime.now().isoformat()
                }
            else:  # close
                folder = f"{self.windows_report_path}/CloseTrades"
                filename = f"{folder}/{date_str}_CLOSE_{symbol.replace('/', '_')}_{timestamp}.json"
                report = {
                    'type': 'CLOSE',
                    'symbol': symbol,
                    'side': side,
                    'exit_price': price,
                    'size': size,
                    'leverage': leverage,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'exit_reason': reason,
                    'timestamp': timestamp,
                    'datetime': datetime.now().isoformat()
                }
            
            # 保存JSON报告
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            
            # 同时追加到CSV汇总文件
            csv_file = f"{self.windows_report_path}/{date_str}_trades_summary.csv"
            csv_exists = os.path.exists(csv_file)
            
            with open(csv_file, 'a', encoding='utf-8') as f:
                if not csv_exists:
                    f.write("datetime,type,symbol,side,price,size,leverage,pnl,pnl_pct,reason\n")
                
                if trade_type == 'open':
                    f.write(f"{datetime.now().isoformat()},OPEN,{symbol},{side},{price},{size},{leverage},,,\n")
                else:
                    f.write(f"{datetime.now().isoformat()},CLOSE,{symbol},{side},{price},{size},{leverage},{pnl},{pnl_pct},{reason}\n")
            
            logging.info(f"📄 交易报告已保存: {filename}")
        except Exception as e:
            logging.error(f"❌ 保存交易报告失败: {e}")

    def _record_trade_to_db(self, symbol, side, entry_price, exit_price, size, leverage, pnl, pnl_pct, entry_time, exit_time, reason):
        """记录交易到数据库"""
        try:
            if hasattr(self, 'db') and self.db:
                trade_data = {
                    'symbol': symbol,
                    'side': side,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'size': size,
                    'leverage': leverage,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'entry_time': datetime.fromtimestamp(entry_time).isoformat() if entry_time else None,
                    'exit_time': datetime.fromtimestamp(exit_time).isoformat() if exit_time else None,
                    'duration_hours': (exit_time - entry_time) / 3600 if exit_time and entry_time else 0,
                    'exit_reason': reason,
                    'strategy_version': 'v10.0'
                }
                self.db.save_trade(trade_data)
                logging.info(f"💾 交易已记录到数据库: {symbol} {side} PnL:{pnl:.2f}")
        except Exception as e:
            logging.error(f"❌ 记录交易到数据库失败: {e}")

    def execute_trade(self, symbol, side, amount, use_leverage=10, notional_value=0):
        """v13.1 智能执行交易"""
        try:
            if not self.dry_run:
                self.exchange.set_leverage(int(use_leverage), symbol)
            
            pos_side = 'LONG' if side == 'buy' else 'SHORT'
            
            # 使用智能执行算法
            if not self.dry_run and self.twap_executor:
                order = self.twap_executor.execute(
                    symbol, side, amount, use_leverage, pos_side, notional_value
                )
            elif not self.dry_run:
                # 回退到普通市价单
                order = self.exchange.create_market_order(symbol, side, amount, params={'positionSide': pos_side})
            else:
                order = {'id': 'dry_run_trade'}
            
            if order:
                # 获取实际成交价格
                entry_price = order.get('price', 0) if isinstance(order, dict) else 0
                if not entry_price and 'average' in order:
                    entry_price = order['average']
                if not entry_price:
                    # 如果无法获取成交价格，使用当前ticker价格
                    try:
                        ticker = self.exchange.fetch_ticker(symbol)
                        entry_price = ticker['last']
                    except:
                        entry_price = 0
                
                entry_time = time.time()
                self.position_tracking[symbol] = {
                    'max_profit': 0, 'entry_time': entry_time, 'cycles': 0,
                    'entry_price': entry_price, 'side': pos_side, 'atr_stop_price': None
                }
                self._save_position_tracking()
                
                # 记录执行方式
                exec_method = "TWAP+Maker" if self.twap_executor else "市价单"
                msg = f"🚀 [{exec_method}] {pos_side} {symbol}\n数量: {amount}\n杠杆: {use_leverage}x"
                self._notify(f"✅ 开仓成功: {symbol}", msg, "success")
                
                # 保存开仓报告到Windows E盘
                self._save_trade_report('open', symbol, pos_side, entry_price, amount, use_leverage)
                
                # Telegram 通知
                try:
                    ticker = self.exchange.fetch_ticker(symbol)
                    telegram.notify_trade(symbol, side, amount, ticker['last'], use_leverage)
                except:
                    pass
                
            return order
        except Exception as e:
            logging.error(f"❌ Trade Execution Error: {e}")
            return None

    def close_position(self, symbol, reason="Manual"):
        try:
            details = self.get_position_details(symbol)
            if not details:
                logging.warning(f"⚠️ {symbol} 获取不到持仓详情，无法平仓")
                return None

            logging.info(f"🚨 {symbol} 执行平仓: 方向={details['side']}, 数量={details['size']}, 盈亏={details['pnl_pct']:.2f}%, 原因={reason}")

            side = 'sell' if details['side'] == 'LONG' else 'buy'
            if not self.dry_run:
                order = self.exchange.create_market_order(symbol, side, details['size'], params={'positionSide': details['side']})
                logging.info(f"✅ {symbol} 平仓订单已提交: {order}")
            
            pnl = details['unrealized_pnl']
            pnl_pct = details['pnl_pct']
            pnl_str = f"{pnl:+.2f} USDT ({pnl_pct:.2f}%)"
            is_profit = pnl > 0
            
            # 获取持仓追踪数据
            track = self.position_tracking.get(symbol, {})
            entry_price = track.get('entry_price', details.get('entry_price', 0))
            entry_time = track.get('entry_time', 0)
            exit_time = time.time()
            
            # 检查是否是逆势交易平仓
            if hasattr(self, 'counter_positions') and symbol in self.counter_positions:
                counter_info = self.counter_positions.pop(symbol)
                # 通知策略记录逆势交易结果
                self.strategy.on_counter_trend_result(is_profit)
                trade_type = "[逆势]"
            else:
                trade_type = "[顺势]"
            
            self._notify(f"🚨 平仓成功: {symbol}", f"{trade_type} 原因: {reason}\n盈亏: {pnl_str}", "warning")
            
            # 保存平仓报告到Windows E盘
            self._save_trade_report('close', symbol, details['side'], details.get('mark_price', 0), 
                                   details['size'], details['leverage'], pnl, pnl_pct, reason)
            
            # 记录交易到数据库
            self._record_trade_to_db(symbol, details['side'], entry_price, details.get('mark_price', 0),
                                     details['size'], details['leverage'], pnl, pnl_pct,
                                     entry_time, exit_time, reason)
            
            # 记录ML训练数据（用于信号过滤模型训练）
            if hasattr(self.strategy, 'ml_filter') and self.strategy.ml_filter:
                try:
                    # 获取开仓时的DataFrame特征
                    ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe='30m', limit=50)
                    df = self.strategy.calculate_indicators(pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']))
                    self.strategy.ml_filter.record_outcome(df, details['side'], pnl)
                    
                    # 尝试训练模型（如果数据足够）
                    if len(self.strategy.ml_filter.training_data) >= 30:
                        self.strategy.ml_filter.train()
                except Exception as e:
                    logging.error(f"❌ ML训练数据记录失败: {e}")
            
            if pnl < 0:
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
        base_leverage = 20
        
        # 1. 波动率调节 - 适配 5-20x 杠杆范围
        import math
        if symbol_atr and current_price and not math.isnan(symbol_atr) and not math.isnan(current_price):
            volatility_ratio = symbol_atr / current_price
            # 波动率 < 0.3%: 20x, 0.3-0.6%: 15x, 0.6-1%: 10x, 1-2%: 7x, 2-3%: 5x, >3%: 5x
            if volatility_ratio < 0.003:
                vol_adjusted = 20
            elif volatility_ratio < 0.006:
                vol_adjusted = 15
            elif volatility_ratio < 0.01:
                vol_adjusted = 10
            elif volatility_ratio < 0.02:
                vol_adjusted = 7
            else:
                vol_adjusted = 5
        else:
            vol_adjusted = 10
        
        # 2. 资金费率调节 (如果资金费率高，降低杠杆)
        funding_adjusted = vol_adjusted
        if funding_rate > 0.0001:  # 0.01%资金费率
            funding_adjusted = max(5, vol_adjusted - 3)
        elif funding_rate > 0.0005:  # 0.05%资金费率
            funding_adjusted = max(5, vol_adjusted - 5)
        
        # 3. 余额保护 (小账户降低杠杆)
        if balance < 50:
            balance_adjusted = max(5, funding_adjusted - 5)
        elif balance < 100:
            balance_adjusted = max(5, funding_adjusted - 3)
        else:
            balance_adjusted = funding_adjusted
        
        final_leverage = min(base_leverage, balance_adjusted)

        return {
            'leverage': final_leverage,
            'volatility_ratio': volatility_ratio if symbol_atr and current_price else 0
        }

    def _scan_for_entries(self, balance):
        signals = self.strategy.calculate_signals(self.exchange)
        
        # 处理被过滤的信号
        if signals and '_filtered' in signals:
            filtered_list = signals.pop('_filtered')
            for filtered in filtered_list:
                try:
                    telegram.notify_signal_filtered(
                        filtered['symbol'], 
                        filtered['side'], 
                        "CVD订单流过滤 - 假突破"
                    )
                except Exception as e:
                    logging.error(f"Telegram 过滤通知失败: {e}")
        
        if not signals: return
        
        for symbol, signal_info in signals.items():
            if symbol in self.cooldowns and time.time() - self.cooldowns[symbol] < 3600: continue
            
            curr_pos = self.get_open_positions()
            if len(curr_pos) >= 3 or symbol in curr_pos: continue
            
            # 解析信号信息
            side = signal_info.get('side') if isinstance(signal_info, dict) else signal_info
            signal_type = signal_info.get('type', 'trend') if isinstance(signal_info, dict) else 'trend'
            strength = signal_info.get('strength', 'HALF') if isinstance(signal_info, dict) else 'HALF'
            
            try:
                ticker = self.exchange.fetch_ticker(symbol)
                # 简单 ATR 获取
                ohlcv = self.exchange.fetch_ohlcv(symbol, '30m', limit=20)
                if len(ohlcv) < 14:
                    logging.warning(f"⚠️ {symbol} OHLCV 数据不足: {len(ohlcv)} < 14，跳过")
                    continue
                df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
                tr = np.max(pd.concat([df['h']-df['l'], np.abs(df['h']-df['c'].shift()), np.abs(df['l']-df['c'].shift())], axis=1), axis=1)
                atr = tr.rolling(14).mean().iloc[-1]
                if pd.isna(atr):
                    logging.warning(f"⚠️ {symbol} ATR 计算结果为 NaN，跳过")
                    continue
                
                cfg = self.calculate_dynamic_leverage(balance, ticker['last'], atr)
                logging.info(f"📊 杠杆计算: 余额={balance:.2f}, 杠杆={cfg['leverage']}x")
                
                # 逆势交易降低杠杆
                if signal_type == 'counter':
                    cfg['leverage'] = max(3, cfg['leverage'] - 2)  # 逆势降低杠杆
                    logging.info(f"🔄 逆势交易降低杠杆: {cfg['leverage']}x")
                
                # 使用全部可用余额开仓（移除名义价值限制）
                if not ticker.get('last') or ticker['last'] <= 0:
                    logging.error(f"❌ {symbol} 无效价格: {ticker.get('last')}")
                    continue
                
                # 计算开仓数量：使用余额的90%（保留10%作为缓冲）
                position_value = balance * 0.9
                amount = float(self.exchange.amount_to_precision(symbol, position_value / ticker['last']))
                if amount <= 0:
                    logging.error(f"❌ {symbol} 无效数量: {amount}")
                    continue
                
                logging.info(f"🚀 {symbol} 准备开仓: 方向={side}, 数量={amount}, 杠杆={cfg['leverage']}x, 仓位价值={position_value:.2f} USDT")
                result = self.execute_trade(symbol, side, amount, cfg['leverage'], position_value)

                if result:
                    # 开仓成功后发送信号通知
                    try:
                        telegram.notify_signal(symbol, side, strength, signal_type)
                    except Exception as e:
                        logging.error(f"Telegram 信号通知失败: {e}")

                    # 发送开仓结果通知
                    try:
                        telegram.notify_signal_result(symbol, side, "success", f"杠杆{cfg['leverage']}x, 金额{position_value:.2f}USDT")
                    except Exception as e:
                        logging.error(f"Telegram 结果通知失败: {e}")

                # 如果开仓成功，记录信号类型用于后续结果跟踪
                if result and signal_type == 'counter':
                    # 记录逆势交易开仓信息
                    if not hasattr(self, 'counter_positions'):
                        self.counter_positions = {}
                    self.counter_positions[symbol] = {
                        'entry_time': time.time(),
                        'signal_type': 'counter',
                        'side': side
                    }
            except Exception as e:
                import traceback
                logging.error(f"❌ Scan entry error for {symbol}: {e}")
                logging.error(f"   Signal info: {signal_info}")
                logging.error(f"   Balance: {balance}, Side: {side}, Type: {signal_type}")
                if 'ticker' in locals():
                    logging.error(f"   Ticker: {ticker}")
                if 'cfg' in locals():
                    logging.error(f"   CFG: {cfg}")
                logging.error(f"   Traceback: {traceback.format_exc()}")
                continue

    def monitor_positions(self):
        symbols = self.get_open_positions()
        for s in symbols:
            d = self.get_position_details(s)
            if not d: continue

            track = self.position_tracking.get(s, {'max_profit': 0, 'entry_time': 0})
            if d['pnl_pct'] > track['max_profit']:
                track['max_profit'] = d['pnl_pct']
                self.position_tracking[s] = track
                self._save_position_tracking()  # 保存新的 max_profit

            # 方案3: 固定初始止损 (-3%)，盈利后启用移动止损
            # 添加最小持仓时间: 5分钟，避免刚开仓就平仓
            import time
            min_hold_time = 300  # 5分钟
            hold_time = time.time() - track.get('entry_time', 0)
            
            exit_reason = None
            
            # 检查最小持仓时间
            if hold_time < min_hold_time:
                # 持仓时间太短，只检查硬止损
                if d['pnl_pct'] < -5.0:  # 紧急止损-5%
                    exit_reason = f"emergency_stop:{d['pnl_pct']:.2f}%"
            else:
                # 正常止损逻辑 - 3%
                if d['pnl_pct'] < -3.0:
                    exit_reason = f"hard_stop:{d['pnl_pct']:.2f}%"
                elif track.get('max_profit', 0) > 0:
                    # 盈利后启用 ATR 移动止损
                    exit_reason = self.strategy.calculate_exit_signals(self.exchange, s, d['side'], d['entry_price'], track['max_profit'], track)

            if exit_reason:
                logging.info(f"🚪 {s} 触发平仓信号: {exit_reason}, 当前盈亏: {d['pnl_pct']:.2f}%, 最大盈利: {track.get('max_profit', 0):.2f}%, 持仓时间: {hold_time/60:.1f}分钟")
                self.close_position(s, exit_reason)

    def run(self):
        logging.info("🚀 v9.0 Dynamic Dual Filter System Running...")
        logging.info("📊 策略: 纯技术指标规则系统 | 无机器学习成分")
        last_scan = 0
        last_balance = 0
        while True:
            try:
                now = time.time()
                
                # 获取余额，失败时使用上次余额
                try:
                    balance = self.get_balance()
                    if balance > 0:
                        last_balance = balance
                except Exception as e:
                    logging.warning(f"获取余额失败，使用上次余额: {last_balance}")
                    balance = last_balance
                
                pos = self.get_open_positions()
                
                # 检查每日亏损限制
                if balance > 0 and not self.risk.check_daily_limit(balance):
                    logging.warning("🛑 Daily loss limit reached. Trading halted.")
                    time.sleep(300)  # 5分钟后重试
                    continue
                
                # 每 2s 监控与同步
                self.monitor_positions()
                self._update_status_file(pos, balance)
                
                # 每 60s 扫描 (即使余额获取失败也继续扫描)
                if now - last_scan >= 60:
                    if balance > 0:
                        logging.info(f"💰 Account Balance: {balance:.2f} USDT")
                    else:
                        logging.info("💰 Account Balance: 未知 (使用默认仓位)")
                    # 使用最小余额进行扫描，确保策略继续运行
                    scan_balance = balance if balance > 0 else 10
                    self._scan_for_entries(scan_balance)
                    last_scan = now
                
                time.sleep(2)
            except Exception as e:
                logging.error(f"Main Error: {e}")
                time.sleep(10)

if __name__ == "__main__":
    bot = BinanceBot(dry_run='--real' not in sys.argv)
    bot.run()
