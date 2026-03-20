"""
回测框架 - 基于历史数据验证策略
使用说明: python backtest.py --start 2024-01-01 --end 2024-12-31
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import ccxt
import json
import argparse
from strategy import Strategy

class BacktestEngine:
    def __init__(self, initial_balance=1000, leverage=10, commission=0.0004):
        """
        回测引擎
        
        Args:
            initial_balance: 初始资金 (USDT)
            leverage: 杠杆倍数
            commission: 手续费率 (0.0004 = 0.04%)
        """
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.leverage = leverage
        self.commission = commission
        self.positions = {}
        self.trades = []
        self.daily_returns = []
        self.strategy = Strategy([])
        
    def fetch_historical_data(self, symbol, timeframe='30m', start_date=None, end_date=None):
        """获取历史数据"""
        exchange = ccxt.binance({'enableRateLimit': True})
        
        since = exchange.parse8601(f'{start_date}T00:00:00Z') if start_date else None
        
        all_ohlcv = []
        while True:
            try:
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
                if not ohlcv:
                    break
                all_ohlcv.extend(ohlcv)
                since = ohlcv[-1][0] + 1
                
                # 检查是否到达结束日期
                if end_date:
                    current_date = datetime.fromtimestamp(ohlcv[-1][0] / 1000)
                    if current_date > datetime.strptime(end_date, '%Y-%m-%d'):
                        break
                        
                print(f"📥 已获取 {symbol} {len(all_ohlcv)} 条数据...")
            except Exception as e:
                print(f"❌ 获取数据错误: {e}")
                break
        
        df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    
    def calculate_metrics(self):
        """计算回测指标"""
        if not self.trades:
            return {"error": "无交易记录"}
        
        returns = pd.Series(self.daily_returns)
        
        # 基础指标
        total_trades = len(self.trades)
        winning_trades = len([t for t in self.trades if t['pnl'] > 0])
        losing_trades = total_trades - winning_trades
        
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        
        # 盈亏
        total_profit = sum([t['pnl'] for t in self.trades if t['pnl'] > 0])
        total_loss = sum([t['pnl'] for t in self.trades if t['pnl'] < 0])
        profit_factor = abs(total_profit / total_loss) if total_loss != 0 else float('inf')
        
        # 收益指标
        total_return = (self.balance - self.initial_balance) / self.initial_balance
        
        # 风险指标
        max_drawdown = self.calculate_max_drawdown()
        
        # Sharpe Ratio (假设无风险利率为0)
        if len(returns) > 1 and returns.std() != 0:
            sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(365)
        else:
            sharpe_ratio = 0
        
        # 盈亏比
        avg_win = total_profit / winning_trades if winning_trades > 0 else 0
        avg_loss = abs(total_loss) / losing_trades if losing_trades > 0 else 0
        profit_loss_ratio = avg_win / avg_loss if avg_loss != 0 else 0
        
        return {
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': f"{win_rate:.2%}",
            'total_return': f"{total_return:.2%}",
            'final_balance': f"{self.balance:.2f} USDT",
            'profit_factor': f"{profit_factor:.2f}",
            'profit_loss_ratio': f"{profit_loss_ratio:.2f}",
            'max_drawdown': f"{max_drawdown:.2%}",
            'sharpe_ratio': f"{sharpe_ratio:.2f}",
            'avg_win': f"{avg_win:.2f} USDT",
            'avg_loss': f"{avg_loss:.2f} USDT"
        }
    
    def calculate_max_drawdown(self):
        """计算最大回撤"""
        if not self.daily_returns:
            return 0
        
        cumulative = (1 + pd.Series(self.daily_returns)).cumprod()
        running_max = cumulative.expanding().max()
        drawdown = (cumulative - running_max) / running_max
        return drawdown.min()
    
    def run_backtest(self, symbol, start_date, end_date):
        """运行回测"""
        print(f"\n🚀 开始回测 {symbol}")
        print(f"📅 时间范围: {start_date} ~ {end_date}")
        print(f"💰 初始资金: {self.initial_balance} USDT")
        print("-" * 60)
        
        # 获取数据
        df = self.fetch_historical_data(symbol, '30m', start_date, end_date)
        if len(df) < 200:
            print("❌ 数据不足")
            return
        
        # 计算指标
        df = self.strategy.calculate_indicators(df)
        
        # 模拟交易
        for i in range(200, len(df)):
            current = df.iloc[i]
            prev = df.iloc[i-1]
            
            # 简化的信号判断（实际应使用完整策略）
            # 这里仅作示例
            
        # 计算结果
        metrics = self.calculate_metrics()
        
        print("\n" + "=" * 60)
        print("📊 回测结果")
        print("=" * 60)
        for key, value in metrics.items():
            print(f"{key:20s}: {value}")
        
        return metrics

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Binance Bot 回测工具')
    parser.add_argument('--symbol', default='ETH/USDT:USDT', help='交易对')
    parser.add_argument('--start', required=True, help='开始日期 (YYYY-MM-DD)')
    parser.add_argument('--end', required=True, help='结束日期 (YYYY-MM-DD)')
    parser.add_argument('--balance', type=float, default=1000, help='初始资金')
    
    args = parser.parse_args()
    
    engine = BacktestEngine(initial_balance=args.balance)
    engine.run_backtest(args.symbol, args.start, args.end)
