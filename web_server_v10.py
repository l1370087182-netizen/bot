#!/usr/bin/env python3
"""
币安交易机器人 Web 管理后台 v10.0
新增: v10.0架构数据展示、性能指标、风控状态
"""

import os
import sys
import json
import time
import sqlite3
import threading
from datetime import datetime
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

# 添加src路径
sys.path.insert(0, 'src')

app = Flask(__name__)
CORS(app)

# 文件路径
BOT_DIR = os.path.dirname(os.path.abspath(__file__))
STATUS_FILE = os.path.join(BOT_DIR, '.bot_status')
DB_FILE = os.path.join(BOT_DIR, 'trades.db')
LOG_FILE = os.path.join(BOT_DIR, 'bot.log')

class WebDashboard:
    def __init__(self):
        self.cache = {}
        self.cache_time = 0
        
    def get_bot_status(self):
        """获取机器人状态"""
        try:
            if os.path.exists(STATUS_FILE):
                with open(STATUS_FILE, 'r') as f:
                    return json.load(f)
        except:
            pass
        return {'status': 'unknown', 'balance': 0, 'positions': []}
    
    def get_performance_metrics(self):
        """从SQLite获取性能指标"""
        try:
            if not os.path.exists(DB_FILE):
                return {'error': 'Database not found'}
            
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            # 最近30天交易
            cursor.execute('''
                SELECT COUNT(*), 
                       SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END),
                       SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END),
                       SUM(pnl)
                FROM trades 
                WHERE exit_time >= datetime('now', '-30 days')
            ''')
            
            total, wins, losses, net_pnl = cursor.fetchone()
            
            # 计算指标
            win_rate = (wins / total * 100) if total > 0 else 0
            
            # 最近10笔交易
            cursor.execute('''
                SELECT symbol, side, pnl, pnl_pct, exit_time
                FROM trades
                ORDER BY exit_time DESC
                LIMIT 10
            ''')
            recent_trades = cursor.fetchall()
            
            conn.close()
            
            return {
                'total_trades': total or 0,
                'winning_trades': wins or 0,
                'losing_trades': losses or 0,
                'win_rate': round(win_rate, 2),
                'net_pnl': round(net_pnl or 0, 2),
                'recent_trades': [
                    {
                        'symbol': t[0],
                        'side': t[1],
                        'pnl': round(t[2], 2),
                        'pnl_pct': round(t[3], 2),
                        'time': t[4]
                    } for t in recent_trades
                ]
            }
        except Exception as e:
            return {'error': str(e)}
    
    def get_account_protection_status(self):
        """获取账户保护状态"""
        try:
            # 从日志解析风控状态
            if os.path.exists(LOG_FILE):
                with open(LOG_FILE, 'r') as f:
                    logs = f.readlines()[-100:]  # 最近100行
                
                status = {
                    'daily_loss_triggered': any('DAILY LOSS PROTECTION' in l for l in logs),
                    'survival_mode': any('SURVIVAL MODE' in l for l in logs),
                    'account_locked': any('PERMANENTLY LOCKED' in l for l in logs),
                    'last_check': datetime.now().isoformat()
                }
                return status
        except:
            pass
        return {'status': 'normal'}
    
    def get_position_details(self):
        """获取持仓详情"""
        status = self.get_bot_status()
        positions = status.get('positions', [])
        
        enriched = []
        for pos in positions:
            # 添加v10.0特有的字段
            enriched.append({
                'symbol': pos.get('symbol'),
                'side': pos.get('side'),
                'size': pos.get('size'),
                'entry_price': pos.get('entry_price'),
                'mark_price': pos.get('mark_price'),
                'pnl': pos.get('unrealized_pnl'),
                'pnl_pct': pos.get('pnl_pct'),
                'leverage': pos.get('leverage'),
                'liquidation_price': pos.get('liquidation_price'),
                'liquidation_risk': pos.get('liquidation_risk', 'UNKNOWN'),
                # v10.0新增
                'max_profit_pct': pos.get('max_profit_pct', 0),
                'additions_count': len(pos.get('additions', [])),
                'tier': pos.get('tier', 'STANDARD')
            })
        
        return enriched

dashboard = WebDashboard()

@app.route('/')
def index():
    return send_file('web_dashboard_v10.html')

@app.route('/api/status')
def api_status():
    """API: 获取状态"""
    return jsonify(dashboard.get_bot_status())

@app.route('/api/performance')
def api_performance():
    """API: 获取性能指标"""
    return jsonify(dashboard.get_performance_metrics())

@app.route('/api/protection')
def api_protection():
    """API: 获取风控状态"""
    return jsonify(dashboard.get_account_protection_status())

@app.route('/api/positions')
def api_positions():
    """API: 获取持仓详情"""
    return jsonify(dashboard.get_position_details())

@app.route('/api/summary')
def api_summary():
    """API: 获取综合摘要"""
    return jsonify({
        'status': dashboard.get_bot_status(),
        'performance': dashboard.get_performance_metrics(),
        'protection': dashboard.get_account_protection_status(),
        'positions': dashboard.get_position_details(),
        'timestamp': datetime.now().isoformat()
    })

if __name__ == '__main__':
    print("🚀 Web Dashboard v10.0 starting...")
    print("📊 Features: Performance metrics, Risk status, Position details")
    app.run(host='0.0.0.0', port=8080, debug=False)
