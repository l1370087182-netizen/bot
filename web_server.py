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
import subprocess
import signal
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
BOT_SCRIPT = os.path.join(BOT_DIR, 'bot.py')
PID_FILE = os.path.join(BOT_DIR, 'bot.pid')

# 机器人进程管理
bot_process = None

class BotManager:
    """机器人进程管理器"""
    
    @staticmethod
    def is_running():
        """检查机器人是否运行"""
        try:
            if os.path.exists(PID_FILE):
                with open(PID_FILE, 'r') as f:
                    pid = int(f.read().strip())
                # 检查进程是否存在
                os.kill(pid, 0)
                return True
        except:
            pass
        return False
    
    @staticmethod
    def start():
        """启动机器人"""
        global bot_process
        if BotManager.is_running():
            return {'success': False, 'message': '机器人已在运行'}
        
        try:
            # 使用nohup启动机器人
            bot_process = subprocess.Popen(
                ['python3', BOT_SCRIPT, '--real'],
                stdout=open(os.path.join(BOT_DIR, 'bot.log'), 'a'),
                stderr=subprocess.STDOUT,
                cwd=BOT_DIR
            )
            
            # 保存PID
            with open(PID_FILE, 'w') as f:
                f.write(str(bot_process.pid))
            
            return {'success': True, 'message': f'机器人已启动 (PID: {bot_process.pid})'}
        except Exception as e:
            return {'success': False, 'message': f'启动失败: {str(e)}'}
    
    @staticmethod
    def stop():
        """停止机器人"""
        try:
            if os.path.exists(PID_FILE):
                with open(PID_FILE, 'r') as f:
                    pid = int(f.read().strip())
                
                # 发送终止信号
                os.kill(pid, signal.SIGTERM)
                
                # 等待进程结束
                time.sleep(2)
                
                # 强制结束
                try:
                    os.kill(pid, signal.SIGKILL)
                except:
                    pass
                
                # 删除PID文件
                os.remove(PID_FILE)
                
                return {'success': True, 'message': '机器人已停止'}
            else:
                return {'success': False, 'message': '机器人未运行'}
        except Exception as e:
            return {'success': False, 'message': f'停止失败: {str(e)}'}
    
    @staticmethod
    def restart():
        """重启机器人"""
        BotManager.stop()
        time.sleep(3)
        return BotManager.start()

class LogReader:
    """日志读取器"""
    
    @staticmethod
    def get_recent_logs(lines=100):
        """获取最近日志"""
        try:
            if not os.path.exists(LOG_FILE):
                return []
            
            with open(LOG_FILE, 'r') as f:
                all_logs = f.readlines()
            
            # 返回最后N行
            recent_logs = all_logs[-lines:]
            
            # 解析日志
            parsed = []
            for line in recent_logs:
                line = line.strip()
                if line:
                    # 简单解析日志级别
                    level = 'INFO'
                    if 'ERROR' in line or '❌' in line:
                        level = 'ERROR'
                    elif 'WARNING' in line or '⚠️' in line:
                        level = 'WARNING'
                    elif 'CRITICAL' in line or '🚨' in line:
                        level = 'CRITICAL'
                    elif 'BUY' in line or 'SELL' in line or '🎯' in line:
                        level = 'TRADE'
                    
                    parsed.append({
                        'line': line,
                        'level': level,
                        'timestamp': line[:19] if len(line) > 19 else ''
                    })
            
            return parsed
        except Exception as e:
            return [{'line': f'读取日志错误: {str(e)}', 'level': 'ERROR'}]
    
    @staticmethod
    def search_logs(keyword, lines=50):
        """搜索日志"""
        try:
            if not os.path.exists(LOG_FILE):
                return []
            
            with open(LOG_FILE, 'r') as f:
                all_logs = f.readlines()
            
            # 搜索关键词
            matched = [line.strip() for line in all_logs if keyword in line]
            
            return matched[-lines:]
        except Exception as e:
            return [f'搜索错误: {str(e)}']

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
    return send_file('web_dashboard.html')

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
        'bot_running': BotManager.is_running(),
        'timestamp': datetime.now().isoformat()
    })

# ========== 机器人控制API ==========

@app.route('/api/bot/status')
def api_bot_status():
    """API: 获取机器人运行状态"""
    return jsonify({
        'running': BotManager.is_running(),
        'pid': open(PID_FILE).read().strip() if os.path.exists(PID_FILE) else None
    })

@app.route('/api/bot/start', methods=['POST'])
def api_bot_start():
    """API: 启动机器人"""
    result = BotManager.start()
    return jsonify(result)

@app.route('/api/bot/stop', methods=['POST'])
def api_bot_stop():
    """API: 停止机器人"""
    result = BotManager.stop()
    return jsonify(result)

@app.route('/api/bot/restart', methods=['POST'])
def api_bot_restart():
    """API: 重启机器人"""
    result = BotManager.restart()
    return jsonify(result)

# ========== 日志API ==========

@app.route('/api/logs')
def api_logs():
    """API: 获取最近日志"""
    lines = request.args.get('lines', 100, type=int)
    logs = LogReader.get_recent_logs(lines)
    return jsonify({'logs': logs})

@app.route('/api/logs/search')
def api_logs_search():
    """API: 搜索日志"""
    keyword = request.args.get('keyword', '')
    lines = request.args.get('lines', 50, type=int)
    logs = LogReader.search_logs(keyword, lines)
    return jsonify({'logs': logs})

if __name__ == '__main__':
    print("🚀 Web Dashboard v10.0 starting...")
    print("📊 Features: Performance metrics, Risk status, Position details")
    print("🎮 Bot control: Start/Stop/Restart")
    print("📜 Log viewer: Real-time logs")
    port = int(os.environ.get('PORT', 8081))
    print(f"🌐 Running on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
