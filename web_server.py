#!/usr/bin/env python3
"""
币安交易机器人 Web 管理后台 v2.1
优化：高效持仓解析、稳定 WebSocket、系统自愈
"""

import os
import sys
import json
import time
import subprocess
import threading
import re
from datetime import datetime
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from flask_socketio import SocketIO, emit

# 基础路径配置
BOT_DIR = os.path.expanduser('~/.openclaw/workspace/binance_bot')
CONFIG_FILE = os.path.join(BOT_DIR, 'web_config.json')
BOT_PID_FILE = os.path.join(BOT_DIR, 'bot.pid')
BOT_LOG_FILE = os.path.join(BOT_DIR, 'bot.log')

app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = 'binance-bot-secret-key'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except: pass
    return {'server_ip': '127.0.0.1', 'api_port': 8080}

def save_config_file(config):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        return True
    except: return False

def get_bot_pid():
    if os.path.exists(BOT_PID_FILE):
        try:
            with open(BOT_PID_FILE, 'r') as f:
                return int(f.read().strip())
        except: pass
    return None
    return None

def is_bot_running():
    pid = get_bot_pid()
    if pid:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            pass
    return False

def get_bot_uptime():
    if not os.path.exists(BOT_LOG_FILE): return "-"
    try:
        with open(BOT_LOG_FILE, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 50000))
            chunk = f.read().decode('utf-8', errors='ignore')
            starts = list(re.finditer(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*Bot started', chunk))
            if starts:
                start_time = datetime.strptime(starts[-1].group(1), '%Y-%m-%d %H:%M:%S')
                uptime = datetime.now() - start_time
                return f"{uptime.days}天 {uptime.seconds//3600}时 {(uptime.seconds%3600)//60}分"
    except: pass
    return "未知"

def get_balance():
    if not os.path.exists(BOT_LOG_FILE): return "0.00"
    try:
        with open(BOT_LOG_FILE, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 10000))
            lines = f.read().decode('utf-8', errors='ignore').splitlines()
            for line in reversed(lines):
                if 'Account Balance:' in line:
                    m = re.search(r'Balance:\s*([\d.]+)', line)
                    if m: return m.group(1)
    except: pass
    return "0.00"

def get_positions():
    positions = []
    if not os.path.exists(BOT_LOG_FILE): return positions
    try:
        with open(BOT_LOG_FILE, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 50000)) # 读取最后50KB
            chunk = f.read().decode('utf-8', errors='ignore')
            lines = chunk.splitlines()

        # 1. 提取活跃 symbol
        active_symbols = []
        for line in reversed(lines):
            if 'Active Positions:' in line:
                m = re.search(r"Active Positions:\s*(\[.*?\])", line)
                if m:
                    try: active_symbols = eval(m.group(1))
                    except: pass
                break
        
        # 2. 为每个 symbol 寻找详情
        for symbol in active_symbols:
            # 默认值
            p = {'symbol': symbol, 'side': 'UNKNOWN', 'size': 0, 'entry_price': 0, 'mark_price': 0, 
                 'unrealized_pnl': 0, 'pnl_pct': 0, 'leverage': 10, 'margin': 0, 'notional': 0, 'liquidation_price': 0}
            
            # 搜索持仓详情 (Detected Position)
            for line in reversed(lines):
                if symbol in line and 'Detected Position:' in line:
                    # 📍 Detected Position: DOT/USDT:USDT SHORT 49.5 @ 1.528
                    m = re.search(r'Detected Position:.*? (LONG|SHORT)\s+([\d.]+)\s+@\s+([\d.]+)', line)
                    if m:
                        p['side'] = m.group(1)
                        p['size'] = float(m.group(2))
                        p['entry_price'] = float(m.group(3))
                        break
            
            # 如果没搜到 Detected Position，搜 ENTRY ORDER
            if p['size'] == 0:
                for line in reversed(lines):
                    if symbol in line and 'ENTRY ORDER:' in line:
                        m = re.search(r'ENTRY ORDER:\s+(BUY|SELL)\s+([\d.]+)\s+.*?@\s+~?([\d.]+)', line)
                        if m:
                            p['side'] = 'LONG' if m.group(1) == 'BUY' else 'SHORT'
                            p['size'] = float(m.group(2))
                            p['entry_price'] = float(m.group(3))
                            break
            
            # 搜索实时盈亏
            for line in reversed(lines):
                if symbol in line and '盈亏:' in line:
                    # 📊 DOT/USDT:USDT 监控中 | 盈亏: -0.10% | 最高: +0.10%
                    m = re.search(r'盈亏:\s+([+-]?[\d.]+)%', line)
                    if m: p['pnl_pct'] = round(float(m.group(1)), 2)
                    break
            
            for line in reversed(lines):
                if symbol in line and 'PnL:' in line:
                    # PnL: 🔴 -0.01 USDT
                    m = re.search(r'PnL:.*?([+-]?[\d.]+)\s+USDT', line)
                    if m: p['unrealized_pnl'] = round(float(m.group(1)), 4)
                    break

            # 计算衍生值
            p['notional'] = round(p['size'] * p['entry_price'], 2)
            p['margin'] = round(p['notional'] / p['leverage'], 2)
            # 根据 unrealized_pnl 计算 pnl_pct（如果日志中没有）
            if p["pnl_pct"] == 0 and p["unrealized_pnl"] != 0 and p["margin"] > 0:
                p["pnl_pct"] = round((p["unrealized_pnl"] / p["margin"]) * 100, 2)
            p['mark_price'] = round(p['entry_price'] * (1 + p['pnl_pct']/100/p['leverage']), 4) if p['side'] == 'LONG' else round(p['entry_price'] * (1 - p['pnl_pct']/100/p['leverage']), 4)
            p['liquidation_price'] = round(p['entry_price'] * (1 - 0.8/p['leverage']) if p['side'] == 'LONG' else p['entry_price'] * (1 + 0.8/p['leverage']), 4)
            
            if p['size'] > 0: positions.append(p)
            
    except Exception as e: print(f"Parser Error: {e}")
    return positions

@app.route('/api/status')
def api_status():
    p = get_positions()
    return jsonify({'running': is_bot_running(), 'uptime': get_bot_uptime(), 'balance': get_balance(), 'positions': len(p)})

@app.route('/api/bot/start', methods=['POST'])
def api_start():
    os.system(f"cd {BOT_DIR} && ./venv/bin/python3 bot.py --real >> bot.log 2>&1 & echo $! > bot.pid")
    return jsonify({'success': True})

@app.route('/api/bot/stop', methods=['POST'])
def api_stop():
    pid = get_bot_pid()
    if pid: os.system(f"kill {pid} || kill -9 {pid}")
    return jsonify({'success': True})

@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    if request.method == 'GET':
        return jsonify(load_config())
    
    # POST - 保存配置
    data = request.json
    config = load_config()
    
    if 'server_ip' in data:
        config['server_ip'] = data['server_ip']
    if 'api_port' in data:
        config['api_port'] = data['api_port']
    if 'binance_ip' in data:
        config['binance_ip'] = data['binance_ip']
        # 同时更新 .env 文件中的 IP 信息（用于显示）
        try:
            env_file = os.path.join(BOT_DIR, '.env')
            if os.path.exists(env_file):
                with open(env_file, 'r') as f:
                    lines = f.readlines()
                with open(env_file, 'w') as f:
                    for line in lines:
                        if line.startswith('TRADING_IP='):
                            f.write(f"TRADING_IP={data['binance_ip']}\n")
                        else:
                            f.write(line)
                    # 如果没有 TRADING_IP 行，添加它
                    if not any(line.startswith('TRADING_IP=') for line in lines):
                        f.write(f"\nTRADING_IP={data['binance_ip']}\n")
        except Exception as e:
            print(f"Failed to update .env: {e}")
    
    if save_config_file(config):
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Failed to save config'})

@app.route('/api/positions')
def api_pos(): return jsonify(get_positions())

@app.route('/api/logs')
def api_logs():
    if not os.path.exists(BOT_LOG_FILE): return "No logs"
    with open(BOT_LOG_FILE, 'r') as f: return ''.join(f.readlines()[-100:])

@app.route('/')
def index():
    with open(os.path.join(BOT_DIR, 'web_dashboard.html'), 'r') as f: return f.read()

def background_thread():
    while True:
        try:
            p = get_positions()
            socketio.emit('positions_update', {'positions': p, 'count': len(p)})
            socketio.emit('status_update', {'running': is_bot_running(), 'uptime': get_bot_uptime(), 'balance': get_balance()})
        except: pass
        socketio.sleep(2)

@socketio.on('connect')
def on_connect():
    global thread
    with threading.Lock():
        if thread is None:
            thread = socketio.start_background_task(background_thread)

thread = None
if __name__ == '__main__':
    cfg = load_config()
    socketio.run(app, host='0.0.0.0', port=cfg.get('api_port', 8080), allow_unsafe_werkzeug=True)
