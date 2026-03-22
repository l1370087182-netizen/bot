#!/usr/bin/env python3
"""
策略回测脚本 - 评估交易策略在历史数据上的表现
"""

import pandas as pd
import numpy as np
import ccxt
from datetime import datetime, timedelta
import logging
import sys
import os

# 添加策略路径
sys.path.insert(0, '/home/administrator/.openclaw/workspace/binance_bot')
from strategy import Strategy

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)


class BacktestEngine:
    """回测引擎"""
    
    def __init__(self, initial_balance=1000, leverage=4):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.leverage = leverage
        self.positions = {}  # 当前持仓
        self.trades = []  # 交易记录
        self.daily_stats = []
        
    def fetch_historical_data(self, symbol, timeframe='30m', days=30):
        """获取历史K线数据"""
        exchange = ccxt.binanceusdm({'enableRateLimit': True})
        
        since = exchange.parse8601((datetime.utcnow() - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ'))
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
        
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    
    def calculate_signals_for_data(self, df, strategy):
        """为历史数据计算信号"""
        signals = []
        
        # 需要至少200根K线
        if len(df) < 200:
            return signals
        
        # 计算指标
        df = strategy.calculate_indicators(df)
        
        for i in range(200, len(df)):
            window_df = df.iloc[:i+1]
            curr = window_df.iloc[-1]
            last_closed = window_df.iloc[-2]
            prev_closed = window_df.iloc[-3]
            
            # 简化趋势判断（使用EMA200）
            trend = 'UP' if last_closed['close'] > last_closed['ema200'] else 'DOWN'
            
            # 波动率检查
            vol_ok = strategy.check_volatility_filter(window_df)
            
            # Hurst
            hurst = curr['hurst']
            adx_threshold = 5 if hurst > 0.55 else (8 if hurst > 0.45 else 10)
            
            signal = None
            
            # 多头信号
            if trend == 'UP' and vol_ok and curr['adx'] > adx_threshold:
                stoch_ok = last_closed['stoch_k'] < 80
                ema_gap = abs(last_closed['close'] - last_closed['ema200']) / last_closed['ema200']
                ema_ok = last_closed['close'] > last_closed['ema200'] or ema_gap < 0.05
                
                if ema_ok:
                    golden_cross = (last_closed['stoch_k'] > last_closed['stoch_d'] and 
                                   prev_closed['stoch_k'] <= prev_closed['stoch_d'])
                    k_rising = last_closed['stoch_k'] > prev_closed['stoch_k'] and last_closed['stoch_k'] < 50
                    near_cross = abs(last_closed['stoch_k'] - last_closed['stoch_d']) < 15
                    
                    if stoch_ok and (golden_cross or k_rising or near_cross):
                        signal = {'side': 'buy', 'timestamp': curr['timestamp'], 'price': curr['close']}
            
            # 空头信号
            if trend == 'DOWN' and vol_ok and curr['adx'] > adx_threshold:
                stoch_ok = last_closed['stoch_k'] > 20
                ema_gap = abs(last_closed['close'] - last_closed['ema200']) / last_closed['ema200']
                ema_ok = last_closed['close'] < last_closed['ema200'] or ema_gap < 0.05
                
                if ema_ok:
                    dead_cross = (last_closed['stoch_k'] < last_closed['stoch_d'] and 
                                 prev_closed['stoch_k'] >= prev_closed['stoch_d'])
                    k_falling = last_closed['stoch_k'] < prev_closed['stoch_k'] and last_closed['stoch_k'] > 50
                    near_cross = abs(last_closed['stoch_k'] - last_closed['stoch_d']) < 15
                    
                    if stoch_ok and (dead_cross or k_falling or near_cross):
                        signal = {'side': 'sell', 'timestamp': curr['timestamp'], 'price': curr['close']}
            
            if signal:
                signals.append(signal)
        
        return signals
    
    def run_backtest(self, symbol='ETH/USDT:USDT', days=30):
        """运行回测"""
        logger.info(f"开始回测 {symbol}，周期: {days}天")
        
        # 获取历史数据
        df = self.fetch_historical_data(symbol, days=days)
        logger.info(f"获取到 {len(df)} 根K线")
        
        # 初始化策略
        strategy = Strategy([symbol])
        
        # 计算信号
        signals = self.calculate_signals_for_data(df, strategy)
        logger.info(f"发现 {len(signals)} 个交易信号")
        
        # 模拟交易
        for signal in signals:
            # 如果有持仓，先检查是否需要平仓
            if symbol in self.positions:
                position = self.positions[symbol]
                current_price = signal['price']
                
                # 计算盈亏
                if position['side'] == 'LONG':
                    pnl_pct = (current_price - position['entry_price']) / position['entry_price'] * 100
                else:
                    pnl_pct = (position['entry_price'] - current_price) / position['entry_price'] * 100
                
                # 检查止损/止盈条件
                exit_reason = None
                
                # 固定止损 -3%
                if pnl_pct < -3.0:
                    exit_reason = f"stop_loss:{pnl_pct:.2f}%"
                
                # 止盈或反向信号
                if signal['side'] == ('sell' if position['side'] == 'LONG' else 'buy'):
                    exit_reason = f"signal_reverse:{pnl_pct:.2f}%"
                
                if exit_reason:
                    self.close_position(symbol, current_price, exit_reason, signal['timestamp'])
            
            # 开新仓
            if symbol not in self.positions:
                self.open_position(symbol, signal['side'], signal['price'], signal['timestamp'])
        
        # 统计结果
        return self.generate_report()
    
    def open_position(self, symbol, side, price, timestamp):
        """开仓"""
        position_value = self.balance * 0.9  # 使用90%余额
        amount = position_value / price
        
        self.positions[symbol] = {
            'side': 'LONG' if side == 'buy' else 'SHORT',
            'entry_price': price,
            'amount': amount,
            'timestamp': timestamp,
            'value': position_value
        }
        
        logger.info(f"开仓: {symbol} {side} @ {price:.4f}, 数量: {amount:.4f}, 价值: {position_value:.2f} USDT")
    
    def close_position(self, symbol, price, reason, timestamp):
        """平仓"""
        if symbol not in self.positions:
            return
        
        position = self.positions[symbol]
        
        # 计算盈亏
        if position['side'] == 'LONG':
            pnl_pct = (price - position['entry_price']) / position['entry_price'] * 100
        else:
            pnl_pct = (position['entry_price'] - price) / position['entry_price'] * 100
        
        pnl_value = position['value'] * pnl_pct / 100 * self.leverage
        self.balance += pnl_value
        
        trade = {
            'symbol': symbol,
            'side': position['side'],
            'entry_price': position['entry_price'],
            'exit_price': price,
            'pnl_pct': pnl_pct,
            'pnl_value': pnl_value,
            'reason': reason,
            'entry_time': position['timestamp'],
            'exit_time': timestamp,
            'duration': (timestamp - position['timestamp']).total_seconds() / 60  # 分钟
        }
        
        self.trades.append(trade)
        del self.positions[symbol]
        
        logger.info(f"平仓: {symbol} @ {price:.4f}, 盈亏: {pnl_pct:.2f}%, 原因: {reason}")
    
    def generate_report(self):
        """生成回测报告"""
        if not self.trades:
            logger.warning("没有完成任何交易")
            return None
        
        df_trades = pd.DataFrame(self.trades)
        
        # 基础统计
        total_trades = len(df_trades)
        winning_trades = len(df_trades[df_trades['pnl_value'] > 0])
        losing_trades = len(df_trades[df_trades['pnl_value'] <= 0])
        win_rate = winning_trades / total_trades * 100 if total_trades > 0 else 0
        
        total_profit = df_trades[df_trades['pnl_value'] > 0]['pnl_value'].sum()
        total_loss = abs(df_trades[df_trades['pnl_value'] <= 0]['pnl_value'].sum())
        profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')
        
        avg_profit = df_trades[df_trades['pnl_value'] > 0]['pnl_value'].mean() if winning_trades > 0 else 0
        avg_loss = df_trades[df_trades['pnl_value'] <= 0]['pnl_value'].mean() if losing_trades > 0 else 0
        
        max_profit = df_trades['pnl_value'].max()
        max_loss = df_trades['pnl_value'].min()
        
        final_balance = self.balance
        total_return = (final_balance - self.initial_balance) / self.initial_balance * 100
        
        avg_duration = df_trades['duration'].mean()
        
        report = f"""
{'='*60}
📊 回测报告
{'='*60}

💰 资金统计:
  初始资金: {self.initial_balance:.2f} USDT
  最终资金: {final_balance:.2f} USDT
  总收益率: {total_return:.2f}%

📈 交易统计:
  总交易次数: {total_trades}
  盈利次数: {winning_trades} ({win_rate:.1f}%)
  亏损次数: {losing_trades} ({100-win_rate:.1f}%)
  盈亏比: {profit_factor:.2f}

💵 盈亏统计:
  总盈利: +{total_profit:.2f} USDT
  总亏损: {total_loss:.2f} USDT
  平均盈利: +{avg_profit:.2f} USDT
  平均亏损: {avg_loss:.2f} USDT
  最大盈利: +{max_profit:.2f} USDT
  最大亏损: {max_loss:.2f} USDT

⏱ 持仓统计:
  平均持仓时间: {avg_duration:.1f} 分钟

{'='*60}
"""
        
        logger.info(report)
        
        # 保存详细交易记录
        df_trades.to_csv('/home/administrator/.openclaw/workspace/binance_bot/backtest_trades.csv', index=False)
        logger.info("详细交易记录已保存到 backtest_trades.csv")
        
        return {
            'total_trades': total_trades,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'total_return': total_return,
            'final_balance': final_balance
        }


if __name__ == "__main__":
    # 运行回测
    engine = BacktestEngine(initial_balance=1000, leverage=4)
    
    # 测试几个币种
    symbols = ['ETH/USDT:USDT', 'BTC/USDT:USDT', 'SOL/USDT:USDT']
    
    for symbol in symbols:
        try:
            logger.info(f"\n{'='*60}")
            logger.info(f"回测 {symbol}")
            logger.info(f"{'='*60}")
            result = engine.run_backtest(symbol, days=30)
        except Exception as e:
            logger.error(f"回测 {symbol} 失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
