#!/usr/bin/env python3
"""
Binance Bot v10.0 - 机构级量化交易系统
核心架构: 三层防护 + 一层放大器
"""
import ccxt
import time
import logging
import os
import sys
import yaml
import asyncio
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path

# 添加src到路径
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from risk.position_sizer import PositionSizer
from risk.pyramiding import PyramidingManager
from risk.exit_manager import ExitManager
from risk.account_guardian import AccountGuardian
from risk.coin_grouper import CoinGrouper
from strategies.signal_scorer import SignalQualityScorer
from strategies.strategy import Strategy
from utils.database import DatabaseManager
from utils.telegram_notifier import TelegramNotifier

# 加载配置
def load_config():
    config_path = Path(__file__).parent / 'config.yaml'
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

CONFIG = load_config()

# 日志设置
logging.basicConfig(
    level=getattr(logging, CONFIG['monitoring']['logging']['level']),
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

class BinanceBotV10:
    """币安量化交易机器人 v10.0"""
    
    def __init__(self):
        self.config = CONFIG
        self.dry_run = self.config['trading']['dry_run']
        self.use_testnet = self.config['trading']['use_testnet']
        
        # 初始化交易所
        self.exchange = self._init_exchange()
        
        # 初始化风控模块
        self.position_sizer = PositionSizer(
            risk_per_trade=self.config['risk_management']['position_sizer']['risk_per_trade']
        )
        self.pyramiding = PyramidingManager()
        self.exit_manager = ExitManager()
        self.guardian = AccountGuardian(
            daily_loss_limit=self.config['risk_management']['account_guardian']['daily_loss_limit'],
            drawdown_limit_1=self.config['risk_management']['account_guardian']['drawdown_limit_1'],
            drawdown_limit_2=self.config['risk_management']['account_guardian']['drawdown_limit_2']
        )
        self.coin_grouper = CoinGrouper()
        
        # 初始化策略模块
        self.strategy = Strategy(self.config['trading']['symbols'])
        self.signal_scorer = SignalQualityScorer()
        
        # 初始化工具模块
        self.db = DatabaseManager(
            self.config['monitoring']['performance']['data_file']
        )
        
        # 初始化通知
        telegram_config = self.config['notifications']['telegram']
        self.notifier = TelegramNotifier(
            telegram_config.get('bot_token'),
            telegram_config.get('chat_id')
        ) if telegram_config.get('enabled') else None
        
        # 状态
        self.positions = {}  # 当前持仓
        self.running = True
        
        logging.info("=" * 60)
        logging.info("🚀 Binance Bot v10.0 Started")
        logging.info(f"   Mode: {'TESTNET' if self.use_testnet else 'LIVE'}")
        logging.info(f"   Dry Run: {self.dry_run}")
        logging.info("=" * 60)
    
    def _init_exchange(self):
        """初始化交易所连接"""
        api_config = {
            'apiKey': os.getenv('BINANCE_API_KEY'),
            'secret': os.getenv('BINANCE_API_SECRET'),
            'options': {
                'adjustForTimeDifference': True,
                'recvWindow': 10000,
                'defaultMarketType': 'future'
            },
            'enableRateLimit': True,
        }
        
        if self.use_testnet:
            api_config['urls'] = {
                'api': {
                    'public': 'https://testnet.binancefuture.com/fapi',
                    'private': 'https://testnet.binancefuture.com/fapi'
                }
            }
            logging.info("🧪 Using Testnet")
        
        return ccxt.binanceusdm(api_config)
    
    def get_balance(self):
        """获取账户余额"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                balance = self.exchange.fetch_balance({'type': 'future'})
                return float(balance['total'].get('USDT', 0))
            except Exception as e:
                logging.error(f"Balance error (attempt {attempt+1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        return 0
    
    def get_funding_rate(self, symbol):
        """获取资金费率"""
        try:
            funding = self.exchange.fetchFundingRate(symbol)
            return funding.get('fundingRate', 0)
        except:
            return 0
    
    def scan_for_signals(self):
        """扫描交易信号"""
        logging.info("🔍 Scanning for signals...")
        
        balance = self.get_balance()
        
        # 检查账户保护
        guard_status = self.guardian.update_balance(balance)
        if not guard_status['can_trade']:
            logging.warning(f"🚫 Trading halted: {guard_status['reason']}")
            return []
        
        # 获取当前持仓
        current_positions = list(self.positions.keys())
        
        signals = []
        symbols = self.config['trading']['symbols']
        
        for symbol in symbols:
            try:
                # 检查币种分组限制
                if not self.coin_grouper.can_open_position(symbol, current_positions):
                    continue
                
                # 获取K线数据
                ohlcv = self.exchange.fetch_ohlcv(
                    symbol, 
                    self.config['trading']['timeframe'], 
                    limit=300
                )
                
                if len(ohlcv) < 200:
                    continue
                
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                
                # 计算信号
                signal_data = self.strategy.calculate_signal_for_symbol(self.exchange, symbol, df)
                
                if not signal_data:
                    continue
                
                # 信号质量评分
                score_result = self.signal_scorer.calculate_score(signal_data)
                
                if score_result['can_trade']:
                    signals.append({
                        'symbol': symbol,
                        'side': signal_data['side'],
                        'score': score_result['total_score'],
                        'tier': score_result['trade_tier'],
                        'data': signal_data
                    })
                    
                    logging.info(f"🎯 Signal: {symbol} | Score: {score_result['total_score']:.1f} | "
                               f"Tier: {score_result['trade_tier']}")
                
            except Exception as e:
                logging.error(f"Error scanning {symbol}: {e}")
                continue
        
        # 按分数排序
        signals.sort(key=lambda x: x['score'], reverse=True)
        
        return signals
    
    def execute_entry(self, signal):
        """执行入场"""
        symbol = signal['symbol']
        side = signal['side']
        data = signal['data']
        
        try:
            # 获取当前价格
            ticker = self.exchange.fetch_ticker(symbol)
            entry_price = ticker['last']
            
            # 计算止损
            stop_price = self.position_sizer.calculate_stop_loss(
                entry_price,
                'LONG' if side == 'buy' else 'SHORT',
                data['atr'],
                2.0  # ATR倍数
            )
            
            # 计算仓位
            balance = self.get_balance()
            position_info = self.position_sizer.calculate_position_size(
                balance,
                entry_price,
                stop_price,
                leverage=10
            )
            
            if not position_info:
                return False
            
            # 验证仓位
            if not self.position_sizer.validate_position(position_info, balance):
                return False
            
            # 执行交易
            if not self.dry_run:
                self.exchange.set_leverage(10, symbol)
                order = self.exchange.create_market_order(
                    symbol,
                    side,
                    position_info['position_size'],
                    params={'positionSide': 'LONG' if side == 'buy' else 'SHORT'}
                )
            
            # 记录持仓
            self.positions[symbol] = {
                'side': 'LONG' if side == 'buy' else 'SHORT',
                'entry_price': entry_price,
                'stop_price': stop_price,
                'size': position_info['position_size'],
                'leverage': 10,
                'entry_time': time.time(),
                'max_profit_pct': 0,
                'additions': [],
                'tier': signal['tier']
            }
            
            # 保存到数据库
            self.db.save_position(symbol, self.positions[symbol])
            
            # 通知
            if self.notifier:
                self.notifier.send_trade_open(
                    symbol, 'LONG' if side == 'buy' else 'SHORT',
                    position_info['position_size'],
                    entry_price, 10, stop_price
                )
            
            logging.info(f"✅ Entry executed: {symbol} | Size: {position_info['position_size']:.4f} | "
                        f"Risk: {position_info['risk_amount']:.2f} USDT")
            
            return True
            
        except Exception as e:
            logging.error(f"❌ Entry error: {e}")
            return False
    
    def manage_positions(self):
        """管理持仓"""
        for symbol, position in list(self.positions.items()):
            try:
                # 获取当前价格
                ticker = self.exchange.fetch_ticker(symbol)
                current_price = ticker['last']
                
                # 计算盈亏
                if position['side'] == 'LONG':
                    pnl_pct = (current_price - position['entry_price']) / position['entry_price'] * 100
                else:
                    pnl_pct = (position['entry_price'] - current_price) / position['entry_price'] * 100
                
                # 更新最大盈利
                if pnl_pct > position['max_profit_pct']:
                    position['max_profit_pct'] = pnl_pct
                    self.positions[symbol] = position
                
                # 检查加仓机会
                if pnl_pct >= 2.0 and len(position.get('additions', [])) < 3:
                    addition = self.pyramiding.check_addition(
                        symbol, pnl_pct, position['size']
                    )
                    if addition:
                        # 执行加仓
                        logging.info(f"📈 Pyramiding: {symbol} | Level {addition['level']}")
                        position['additions'].append(addition)
                
                # 检查退出
                exit_signal = self.exit_manager.check_exit(
                    symbol, pnl_pct, position['size'],
                    position['entry_price'], current_price,
                    position.get('atr', current_price * 0.02)
                )
                
                if exit_signal:
                    # 部分平仓
                    self.execute_partial_exit(symbol, exit_signal)
                
                # 检查止损
                if self.should_stop_loss(position, current_price):
                    self.execute_exit(symbol, 'stop_loss')
                
            except Exception as e:
                logging.error(f"Error managing {symbol}: {e}")
    
    def should_stop_loss(self, position, current_price):
        """检查是否触发止损"""
        if position['side'] == 'LONG':
            return current_price <= position['stop_price']
        else:
            return current_price >= position['stop_price']
    
    def execute_partial_exit(self, symbol, exit_signal):
        """执行部分平仓"""
        logging.info(f"Partial exit: {symbol} | Exit {exit_signal['exit_pct']:.0%}")
        # 实现部分平仓逻辑
    
    def execute_exit(self, symbol, reason):
        """执行完全平仓"""
        position = self.positions.get(symbol)
        if not position:
            return
        
        try:
            if not self.dry_run:
                side = 'sell' if position['side'] == 'LONG' else 'buy'
                self.exchange.create_market_order(
                    symbol, side, position['size'],
                    params={'positionSide': position['side']}
                )
            
            # 计算盈亏
            ticker = self.exchange.fetch_ticker(symbol)
            exit_price = ticker['last']
            
            if position['side'] == 'LONG':
                pnl = (exit_price - position['entry_price']) * position['size']
                pnl_pct = (exit_price - position['entry_price']) / position['entry_price'] * 100
            else:
                pnl = (position['entry_price'] - exit_price) * position['size']
                pnl_pct = (position['entry_price'] - exit_price) / position['entry_price'] * 100
            
            # 记录交易
            trade_data = {
                'symbol': symbol,
                'side': position['side'],
                'entry_price': position['entry_price'],
                'exit_price': exit_price,
                'size': position['size'],
                'leverage': position['leverage'],
                'pnl': pnl,
                'pnl_pct': pnl_pct,
                'entry_time': position['entry_time'],
                'exit_time': time.time(),
                'exit_reason': reason
            }
            
            self.db.save_trade(trade_data)
            
            # 通知
            if self.notifier:
                duration = (time.time() - position['entry_time']) / 3600
                self.notifier.send_trade_close(
                    symbol, position['side'], pnl, pnl_pct, reason, duration
                )
            
            # 清理
            del self.positions[symbol]
            self.pyramiding.clear_additions(symbol)
            self.exit_manager.clear_position(symbol)
            
            logging.info(f"✅ Exit executed: {symbol} | PnL: {pnl:+.2f} USDT ({pnl_pct:+.2f}%) | Reason: {reason}")
            
        except Exception as e:
            logging.error(f"❌ Exit error: {e}")
    
    def run(self):
        """主循环"""
        scan_interval = self.config['trading']['scan_interval']
        
        while self.running:
            try:
                # 管理持仓
                self.manage_positions()
                
                # 扫描信号
                signals = self.scan_for_signals()
                
                # 执行入场
                for signal in signals[:3]:  # 最多同时开3个新仓
                    if len(self.positions) >= 5:
                        break
                    self.execute_entry(signal)
                
                # 显示状态
                balance = self.get_balance()
                logging.info(f"💰 Balance: {balance:.2f} USDT | Positions: {len(self.positions)}")
                
                time.sleep(scan_interval)
                
            except KeyboardInterrupt:
                logging.info("🛑 Bot stopped by user")
                break
            except Exception as e:
                logging.error(f"Main loop error: {e}")
                time.sleep(10)

if __name__ == "__main__":
    bot = BinanceBotV10()
    bot.run()
