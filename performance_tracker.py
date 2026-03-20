"""
性能指标监控模块
实时计算和记录交易性能
"""
import json
import os
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

class PerformanceTracker:
    def __init__(self, data_file='.performance_data'):
        self.data_file = data_file
        self.trades = []
        self.daily_pnl = {}
        self.load_data()
    
    def load_data(self):
        """加载历史数据"""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                    self.trades = data.get('trades', [])
                    self.daily_pnl = data.get('daily_pnl', {})
            except:
                pass
    
    def save_data(self):
        """保存数据"""
        with open(self.data_file, 'w') as f:
            json.dump({
                'trades': self.trades,
                'daily_pnl': self.daily_pnl
            }, f)
    
    def record_trade(self, symbol, side, entry_price, exit_price, size, pnl, pnl_pct, 
                     entry_time, exit_time, leverage=10):
        """记录交易"""
        trade = {
            'symbol': symbol,
            'side': side,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'size': size,
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'leverage': leverage,
            'entry_time': entry_time,
            'exit_time': exit_time,
            'duration_hours': (exit_time - entry_time) / 3600 if exit_time and entry_time else 0
        }
        self.trades.append(trade)
        
        # 记录日盈亏
        date = datetime.fromtimestamp(exit_time).strftime('%Y-%m-%d')
        if date not in self.daily_pnl:
            self.daily_pnl[date] = 0
        self.daily_pnl[date] += pnl
        
        self.save_data()
    
    def calculate_metrics(self, days=30):
        """计算性能指标"""
        if not self.trades:
            return {"error": "无交易记录"}
        
        # 最近N天数据
        cutoff_date = datetime.now() - timedelta(days=days)
        recent_trades = [t for t in self.trades 
                        if datetime.fromtimestamp(t['exit_time']) > cutoff_date]
        
        if not recent_trades:
            return {"error": f"最近{days}天无交易"}
        
        # 基础统计
        total = len(recent_trades)
        wins = len([t for t in recent_trades if t['pnl'] > 0])
        losses = total - wins
        
        # 胜率
        win_rate = wins / total if total > 0 else 0
        
        # 盈亏
        gross_profit = sum([t['pnl'] for t in recent_trades if t['pnl'] > 0])
        gross_loss = sum([t['pnl'] for t in recent_trades if t['pnl'] < 0])
        net_pnl = gross_profit + gross_loss
        
        # 盈亏比
        avg_win = gross_profit / wins if wins > 0 else 0
        avg_loss = abs(gross_loss) / losses if losses > 0 else 0
        profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0
        
        # Profit Factor
        profit_factor = abs(gross_profit / gross_loss) if gross_loss != 0 else float('inf')
        
        # 平均持仓时间
        avg_duration = np.mean([t['duration_hours'] for t in recent_trades])
        
        # 最大单笔盈亏
        max_win = max([t['pnl'] for t in recent_trades])
        max_loss = min([t['pnl'] for t in recent_trades])
        
        # 最大回撤计算
        daily_returns = []
        sorted_dates = sorted(self.daily_pnl.keys())
        for date in sorted_dates[-days:]:
            daily_returns.append(self.daily_pnl[date])
        
        max_drawdown = self._calculate_max_drawdown(daily_returns)
        
        # Sharpe Ratio (简化版，假设无风险利率为0)
        if len(daily_returns) > 1:
            returns_series = pd.Series(daily_returns)
            sharpe = (returns_series.mean() / returns_series.std()) * np.sqrt(365) if returns_series.std() != 0 else 0
        else:
            sharpe = 0
        
        return {
            '统计周期': f'{days}天',
            '总交易次数': total,
            '盈利次数': wins,
            '亏损次数': losses,
            '胜率': f'{win_rate:.2%}',
            '净利润': f'{net_pnl:.2f} USDT',
            '总盈利': f'{gross_profit:.2f} USDT',
            '总亏损': f'{gross_loss:.2f} USDT',
            '盈亏比': f'{profit_loss_ratio:.2f}',
            'Profit Factor': f'{profit_factor:.2f}',
            '最大单笔盈利': f'{max_win:.2f} USDT',
            '最大单笔亏损': f'{max_loss:.2f} USDT',
            '平均持仓时间': f'{avg_duration:.1f}小时',
            '最大回撤': f'{max_drawdown:.2%}',
            'Sharpe Ratio': f'{sharpe:.2f}'
        }
    
    def _calculate_max_drawdown(self, daily_pnl_list):
        """计算最大回撤"""
        if not daily_pnl_list:
            return 0
        
        cumulative = [0]
        for pnl in daily_pnl_list:
            cumulative.append(cumulative[-1] + pnl)
        
        max_dd = 0
        peak = cumulative[0]
        
        for value in cumulative:
            if value > peak:
                peak = value
            dd = (peak - value) / peak if peak != 0 else 0
            max_dd = max(max_dd, dd)
        
        return max_dd
    
    def get_trade_summary(self):
        """获取交易摘要"""
        if not self.trades:
            return "无交易记录"
        
        last_trade = self.trades[-1]
        return f"最近交易: {last_trade['symbol']} {last_trade['side']} | PnL: {last_trade['pnl']:+.2f} USDT"

if __name__ == "__main__":
    # 测试
    tracker = PerformanceTracker()
    metrics = tracker.calculate_metrics(days=30)
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
