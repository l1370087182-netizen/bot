"""
Database Manager - SQLite持久化
替代JSON文件，支持复杂查询和历史分析
"""
import sqlite3
import json
import logging
from datetime import datetime
import os

class DatabaseManager:
    """
    SQLite数据库管理器
    
    表结构:
    - trades: 交易记录
    - positions: 持仓记录
    - daily_pnl: 日盈亏统计
    - performance: 性能指标
    """
    
    def __init__(self, db_file='trades.db'):
        self.db_file = db_file
        self.init_database()
        logging.info(f"🗄️ DatabaseManager initialized: {db_file}")
    
    def init_database(self):
        """初始化数据库表"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            
            # 交易记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_price REAL,
                    exit_price REAL,
                    size REAL,
                    leverage INTEGER,
                    pnl REAL,
                    pnl_pct REAL,
                    entry_time TIMESTAMP,
                    exit_time TIMESTAMP,
                    duration_hours REAL,
                    exit_reason TEXT,
                    strategy_version TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 持仓记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL UNIQUE,
                    side TEXT,
                    size REAL,
                    entry_price REAL,
                    leverage INTEGER,
                    max_profit_pct REAL,
                    additions TEXT,  -- JSON格式
                    exit_stages TEXT,  -- JSON格式
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 日盈亏统计表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS daily_pnl (
                    date TEXT PRIMARY KEY,
                    pnl REAL,
                    trades_count INTEGER,
                    winning_trades INTEGER,
                    losing_trades INTEGER,
                    balance_start REAL,
                    balance_end REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 性能指标表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS performance_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT,
                    metric_name TEXT,
                    metric_value REAL,
                    period_days INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.commit()
    
    def save_trade(self, trade_data):
        """保存交易记录"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO trades 
                (symbol, side, entry_price, exit_price, size, leverage, 
                 pnl, pnl_pct, entry_time, exit_time, duration_hours, 
                 exit_reason, strategy_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                trade_data['symbol'],
                trade_data['side'],
                trade_data['entry_price'],
                trade_data['exit_price'],
                trade_data['size'],
                trade_data['leverage'],
                trade_data['pnl'],
                trade_data['pnl_pct'],
                trade_data['entry_time'],
                trade_data['exit_time'],
                trade_data.get('duration_hours', 0),
                trade_data.get('exit_reason', ''),
                trade_data.get('strategy_version', 'v10.0')
            ))
            conn.commit()
            return cursor.lastrowid
    
    def save_position(self, symbol, position_data):
        """保存持仓记录"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO positions 
                (symbol, side, size, entry_price, leverage, max_profit_pct, 
                 additions, exit_stages, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                symbol,
                position_data.get('side'),
                position_data.get('size'),
                position_data.get('entry_price'),
                position_data.get('leverage'),
                position_data.get('max_profit_pct', 0),
                json.dumps(position_data.get('additions', [])),
                json.dumps(position_data.get('exit_stages', {})),
                datetime.now()
            ))
            conn.commit()
    
    def get_position(self, symbol):
        """获取持仓记录"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM positions WHERE symbol = ?', (symbol,))
            row = cursor.fetchone()
            if row:
                return {
                    'symbol': row[1],
                    'side': row[2],
                    'size': row[3],
                    'entry_price': row[4],
                    'leverage': row[5],
                    'max_profit_pct': row[6],
                    'additions': json.loads(row[7]) if row[7] else [],
                    'exit_stages': json.loads(row[8]) if row[8] else {}
                }
            return None
    
    def get_trades(self, days=30, symbol=None):
        """获取交易记录"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            
            if symbol:
                cursor.execute('''
                    SELECT * FROM trades 
                    WHERE symbol = ? 
                    AND exit_time >= datetime('now', '-{} days')
                    ORDER BY exit_time DESC
                '''.format(days), (symbol,))
            else:
                cursor.execute('''
                    SELECT * FROM trades 
                    WHERE exit_time >= datetime('now', '-{} days')
                    ORDER BY exit_time DESC
                '''.format(days))
            
            columns = [description[0] for description in cursor.description]
            rows = cursor.fetchall()
            
            return [dict(zip(columns, row)) for row in rows]
    
    def calculate_metrics(self, days=30):
        """计算性能指标"""
        trades = self.get_trades(days)
        
        if not trades:
            return {'error': 'No trades found'}
        
        total = len(trades)
        winning = len([t for t in trades if t['pnl'] > 0])
        losing = total - winning
        
        gross_profit = sum([t['pnl'] for t in trades if t['pnl'] > 0])
        gross_loss = sum([t['pnl'] for t in trades if t['pnl'] < 0])
        net_pnl = gross_profit + gross_loss
        
        avg_profit = gross_profit / winning if winning > 0 else 0
        avg_loss = abs(gross_loss) / losing if losing > 0 else 0
        
        return {
            'total_trades': total,
            'winning_trades': winning,
            'losing_trades': losing,
            'win_rate': winning / total if total > 0 else 0,
            'net_pnl': net_pnl,
            'gross_profit': gross_profit,
            'gross_loss': gross_loss,
            'profit_factor': abs(gross_profit / gross_loss) if gross_loss != 0 else float('inf'),
            'avg_profit': avg_profit,
            'avg_loss': avg_loss,
            'profit_loss_ratio': avg_profit / avg_loss if avg_loss > 0 else 0
        }

if __name__ == "__main__":
    # 测试
    db = DatabaseManager('test.db')
    
    # 测试保存交易
    trade = {
        'symbol': 'ETH/USDT',
        'side': 'LONG',
        'entry_price': 100,
        'exit_price': 110,
        'size': 1,
        'leverage': 10,
        'pnl': 10,
        'pnl_pct': 10,
        'entry_time': datetime.now(),
        'exit_time': datetime.now(),
        'exit_reason': 'take_profit'
    }
    
    db.save_trade(trade)
    
    # 查询
    metrics = db.calculate_metrics(days=30)
    print(f"Metrics: {metrics}")
