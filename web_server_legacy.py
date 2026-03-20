#!/usr/bin/env python3
"""
币安交易机器人 Web 管理后台 v3.0
优化内容：极速实时更新 (1s 级)、精简控制、自动状态同步
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
STATUS_FILE = os.path.join(BOT_DIR, '.bot_status')
BOT_PID_FILE = os.path.join(BOT_DIR, 'bot.pid')
BOT_LOG_FILE = os.path.join(BOT_DIR, 'bot.log')

app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = 'binance-bot-secret-key-v3'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

def load_web_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except: pass
    return {'binance_ip': ''}

def save_web_config(config):
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

def is_bot_running():
    pid = get_bot_pid()
    if pid:
        try:
            os.kill(pid, 0)
            return True
        except OSError: pass
    return False

def get_live_data():
    """从 .bot_status 读取最灵敏的实时数据"""
    data = {
        'running': is_bot_running(),
        'uptime': '-',
        'balance': '0.00',
        'positions': [],
        'count': 0
    }
    
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, 'r') as f:
                status = json.load(f)
                data['balance'] = f"{float(status.get('balance', 0)):.2f}"
                data['positions'] = status.get('positions', [])
                data['count'] = len(data['positions'])
                
                # 计算运行时间
                timestamp = status.get('timestamp')
                if timestamp:
                    # 这里的 timestamp 是机器人上次更新状态的时间
                    # 我们需要从 bot.pid 的修改时间来推断启动时间更准确
                    start_time_ts = os.path.getmtime(BOT_PID_FILE) if os.path.exists(BOT_PID_FILE) else timestamp
                    uptime = datetime.now() - datetime.fromtimestamp(start_time_ts)
                    data['uptime'] = f"{uptime.days}天 {uptime.seconds//3600}时 {(uptime.seconds%3600)//60}分"
        except: pass
    
    return data

@app.route('/api/status')
def api_status():
    return jsonify(get_live_data())

@app.route('/api/bot/start', methods=['POST'])
def api_start():
    # 强制清理可能残留的进程
    api_stop()
    time.sleep(0.5)
    # 启动机器人并手动记录 PID
    cmd = f"cd {BOT_DIR} && nohup ./venv/bin/python3 bot.py --real >> bot.log 2>&1 & echo $! > {BOT_PID_FILE}"
    os.system(cmd)
    return jsonify({'success': True, 'message': '正在启动机器人...'})

@app.route('/api/bot/stop', methods=['POST'])
def api_stop():
    pid = get_bot_pid()
    if pid:
        try: os.kill(pid, 15) # SIGTERM
        except: pass
    # 兜底清理
    os.system("ps aux | grep 'python3 bot.py' | grep -v grep | awk '{print $2}' | xargs kill -9 2>/dev/null")
    return jsonify({'success': True, 'message': '指令已发送'})

@app.route('/api/bot/restart', methods=['POST'])
def api_restart():
    api_stop()
    time.sleep(1)
    return api_start()

@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    if request.method == 'GET':
        return jsonify(load_web_config())
    
    data = request.json
    config = load_web_config()
    
    if 'binance_ip' in data:
        config['binance_ip'] = data['binance_ip']
        # 更新 .env 用于记录
        try:
            env_file = os.path.join(BOT_DIR, '.env')
            if os.path.exists(env_file):
                with open(env_file, 'r') as f: lines = f.readlines()
                with open(env_file, 'w') as f:
                    found = False
                    for line in lines:
                        if line.startswith('TRADING_IP='):
                            f.write(f"TRADING_IP={data['binance_ip']}\n")
                            found = True
                        else: f.write(line)
                    if not found: f.write(f"\nTRADING_IP={data['binance_ip']}\n")
        except: pass
    
    if save_web_config(config):
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': '保存失败'})

@app.route('/api/logs')
def api_logs():
    if not os.path.exists(BOT_LOG_FILE): return "日志文件暂未生成"
    try:
        with open(BOT_LOG_FILE, 'r', encoding='utf-8', errors='ignore') as f:
            # 读取最后 100 行
            return "".join(f.readlines()[-100:])
    except: return "读取日志失败"

@app.route('/')
def index():
    return send_file(os.path.join(BOT_DIR, 'web_dashboard.html'))

def background_thread():
    """实时推送线程：1秒/次"""
    while True:
        try:
            data = get_live_data()
            socketio.emit('status_update', {
                'running': data['running'],
                'uptime': data['uptime'],
                'balance': data['balance']
            })
            socketio.emit('positions_update', {
                'positions': data['positions'],
                'count': data['count']
            })
        except Exception as e:
            print(f"Push Error: {e}")
        socketio.sleep(1) # 每秒更新一次

@socketio.on('connect')
def on_connect():
    global thread
    with threading.Lock():
        if thread is None:
            thread = socketio.start_background_task(background_thread)

thread = None
if __name__ == '__main__':
    # 强制固定 8080 端口，不再允许修改
    socketio.run(app, host='0.0.0.0', port=8081, allow_unsafe_werkzeug=True)
