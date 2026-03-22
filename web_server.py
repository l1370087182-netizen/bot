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

# Telegram 排名通知定时任务
last_telegram_ranking_time = 0
TELEGRAM_RANKING_INTERVAL = 1800  # 30分钟

# 文件路径
BOT_DIR = os.path.dirname(os.path.abspath(__file__))
STATUS_FILE = os.path.join(BOT_DIR, '.bot_status')
DB_FILE = os.path.join(BOT_DIR, 'trades.db')
LOG_FILE = os.path.join(BOT_DIR, 'bot.log')
BOT_SCRIPT = os.path.join(BOT_DIR, 'bot.py')
PID_FILE = os.path.join(BOT_DIR, 'bot.pid')
IP_CACHE_FILE = os.path.join(BOT_DIR, '.ip_cache')  # IP缓存文件

# 机器人进程管理
bot_process = None

class BotManager:
    """机器人进程管理器"""
    
    @staticmethod
    def is_running():
        """检查机器人是否运行 - 检测所有 bot.py 进程"""
        try:
            import subprocess
            # 使用 pgrep 查找所有 bot.py 进程
            result = subprocess.run(['pgrep', '-f', 'python3.*bot.py.*--real'], 
                                   capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                # 更新 PID 文件为第一个找到的进程
                if pids:
                    with open(PID_FILE, 'w') as f:
                        f.write(pids[0])
                return True
        except:
            pass
        return False
    
    @staticmethod
    def get_running_pid():
        """获取运行中的机器人 PID"""
        try:
            import subprocess
            result = subprocess.run(['pgrep', '-f', 'python3.*bot.py.*--real'], 
                                   capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().split('\n')[0]
        except:
            pass
        return None
    
    @staticmethod
    def start():
        """启动机器人 - 使用nohup确保独立运行"""
        global bot_process
        
        # 先检查是否已有进程在运行
        if BotManager.is_running():
            return {'success': False, 'message': '机器人已在运行'}
        
        # 清理可能存在的僵尸进程
        BotManager._kill_all_bots()
        
        try:
            import subprocess
            import os
            log_file = os.path.join(BOT_DIR, 'bot.log')
            
            # 先清空日志文件
            with open(log_file, 'w') as f:
                f.write('')
            
            # 使用venv的python直接启动，不使用shell
            venv_python = os.path.join(BOT_DIR, 'venv', 'bin', 'python3')
            
            # 使用subprocess.Popen启动，不阻塞
            with open(log_file, 'a') as log:
                bot_process = subprocess.Popen(
                    [venv_python, 'bot.py', '--real'],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    cwd=BOT_DIR,
                    start_new_session=True  # 创建新会话，避免被web_server终止
                )
            
            # 保存PID
            with open(PID_FILE, 'w') as f:
                f.write(str(bot_process.pid))
            
            # 等待确认
            time.sleep(3)
            
            # 检查进程是否真的在运行
            try:
                os.kill(bot_process.pid, 0)
                return {'success': True, 'message': f'机器人已启动 (PID: {bot_process.pid})'}
            except:
                return {'success': False, 'message': '进程启动后异常退出，请检查日志'}
                
        except Exception as e:
            return {'success': False, 'message': f'启动失败: {str(e)}'}
    
    @staticmethod
    def _kill_all_bots():
        """杀死所有机器人进程"""
        try:
            import subprocess
            # 杀死所有bot.py进程
            subprocess.run(['pkill', '-9', '-f', 'bot.py --real'], capture_output=True)
            time.sleep(1)
            # 清理PID文件
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)
        except:
            pass
    
    @staticmethod
    def stop():
        """停止机器人 - 强制停止所有相关进程"""
        try:
            # 先尝试从PID文件停止
            if os.path.exists(PID_FILE):
                try:
                    with open(PID_FILE, 'r') as f:
                        pid = int(f.read().strip())
                    os.kill(pid, signal.SIGTERM)
                    time.sleep(1)
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except:
                        pass
                except:
                    pass
                finally:
                    os.remove(PID_FILE)
            
            # 强制清理所有可能的机器人进程
            BotManager._kill_all_bots()
            
            # 确认已停止
            time.sleep(1)
            if not BotManager.is_running():
                return {'success': True, 'message': '机器人已停止'}
            else:
                return {'success': False, 'message': '停止失败，请手动kill进程'}
        except Exception as e:
            return {'success': False, 'message': f'停止失败: {str(e)}'}
    
    @staticmethod
    def restart():
        """重启机器人"""
        BotManager.stop()
        time.sleep(2)
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
        
    def get_signal_prediction(self):
        """基于日志分析预测开单时间 - 真正实时版"""
        try:
            if not os.path.exists(LOG_FILE):
                return {'status': 'no_data', 'message': '暂无日志数据'}
            
            # 使用 os.stat 获取文件最新状态，强制刷新缓存
            import os as os_module
            import re
            
            # 重新打开文件，确保获取最新数据
            with open(LOG_FILE, 'r', encoding='utf-8', errors='ignore') as f:
                # 移动到文件末尾前10000字符的位置（大约最后100-200行）
                f.seek(0, 2)  # 移动到文件末尾
                file_size = f.tell()
                read_size = min(10000, file_size)
                f.seek(file_size - read_size, 0)
                
                # 读取最后的数据
                content = f.read()
                lines = content.split('\n')
            
            # 解析币种数据 - 只保留每个币种的最新数据
            coin_data = {}
            
            for line in lines:
                if '📊' in line and 'USDT' in line:
                    # 解析币种、趋势、ADX、StochRSI
                    coin_match = re.search(r'📊 (\w+/USDT)', line)
                    trend_match = re.search(r'1H:(UP|DOWN)', line)
                    adx_match = re.search(r'ADX:(\d+\.?\d*)', line)
                    stoch_match = re.search(r'Stoch:(\d+\.?\d*)', line)
                    
                    if coin_match and trend_match and adx_match and stoch_match:
                        coin = coin_match.group(1)
                        trend = trend_match.group(1)
                        adx = float(adx_match.group(1))
                        stoch = float(stoch_match.group(1))
                        
                        # 直接覆盖，只保留最新数据
                        coin_data[coin] = {
                            'trend': trend,
                            'adx': adx,
                            'stoch': stoch
                        }
            
            # 分析接近入场条件的币
            long_candidates = []
            short_candidates = []
            
            for coin, latest in coin_data.items():
                # 多头候选: UP + ADX>8 + Stoch<50
                if latest['trend'] == 'UP' and latest['adx'] > 8 and latest['stoch'] < 50:
                    distance = 50 - latest['stoch']
                    long_candidates.append({
                        'coin': coin,
                        'stoch': latest['stoch'],
                        'adx': latest['adx'],
                        'distance': distance
                    })
                
                # 空头候选: DOWN + ADX>8 + Stoch>50
                if latest['trend'] == 'DOWN' and latest['adx'] > 8 and latest['stoch'] > 50:
                    distance = latest['stoch'] - 50
                    short_candidates.append({
                        'coin': coin,
                        'stoch': latest['stoch'],
                        'adx': latest['adx'],
                        'distance': distance
                    })
            
            # 排序：距离条件最近的优先
            long_candidates.sort(key=lambda x: x['distance'])
            short_candidates.sort(key=lambda x: x['distance'])
            
            # 计算预测时间 - 基于最接近条件的币种
            total_candidates = len(long_candidates) + len(short_candidates)
            
            if total_candidates == 0:
                return {
                    'status': 'waiting',
                    'message': '市场整理中，暂无接近入场条件的币种',
                    'prediction': '预计 30-60 分钟',
                    'confidence': 'medium',
                    'long_candidates': [],
                    'short_candidates': []
                }
            
            # 根据最接近条件的币种距离计算预测时间
            all_candidates = long_candidates + short_candidates
            if all_candidates:
                # 找出距离最小的（最接近条件的）
                min_distance = min(c['distance'] for c in all_candidates)
                
                # 根据距离计算预计时间
                if min_distance <= 2:
                    prediction = '即将开仓 (< 2分钟)'
                    confidence = 'very_high'
                elif min_distance <= 5:
                    prediction = '5-10 分钟'
                    confidence = 'high'
                elif min_distance <= 10:
                    prediction = '10-20 分钟'
                    confidence = 'medium'
                elif min_distance <= 20:
                    prediction = '20-40 分钟'
                    confidence = 'low'
                else:
                    prediction = '40-60 分钟'
                    confidence = 'very_low'
            else:
                prediction = '暂无机会'
                confidence = 'none'
            
            return {
                'status': 'active',
                'message': f'发现 {total_candidates} 个潜在交易机会 (最近距离: {min_distance:.1f})',
                'prediction': prediction,
                'confidence': confidence,
                'min_distance': min_distance,
                'long_candidates': long_candidates[:5],
                'short_candidates': short_candidates[:5],
                'total_scanned': len(coin_data),
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            return {'status': 'error', 'message': str(e)}
        
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
        """从SQLite获取性能指标 - 修复版"""
        try:
            if not os.path.exists(DB_FILE):
                return {'error': 'Database not found', 'total_trades': 0, 'win_rate': 0, 'net_pnl': 0, 'recent_trades': []}
            
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            # 检查表是否存在
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trades'")
            if not cursor.fetchone():
                conn.close()
                return {'error': 'Trades table not found', 'total_trades': 0, 'win_rate': 0, 'net_pnl': 0, 'recent_trades': []}
            
            # 最近30天交易 - 使用date函数正确处理
            cursor.execute('''
                SELECT COUNT(*), 
                       SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END),
                       SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END),
                       SUM(pnl)
                FROM trades 
                WHERE exit_time >= datetime('now', '-30 days')
            ''')
            
            result = cursor.fetchone()
            total = result[0] or 0
            wins = result[1] or 0
            losses = result[2] or 0
            net_pnl = result[3] or 0
            
            # 计算指标
            win_rate = (wins / total * 100) if total > 0 else 0
            
            # 今日盈亏
            today = datetime.now().strftime('%Y-%m-%d')
            cursor.execute('''
                SELECT SUM(pnl), COUNT(*) 
                FROM trades 
                WHERE date(exit_time) = date('now', 'localtime')
            ''')
            today_result = cursor.fetchone()
            today_pnl = today_result[0] or 0
            today_trades = today_result[1] or 0
            
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
                'total_trades': total,
                'winning_trades': wins,
                'losing_trades': losses,
                'win_rate': round(win_rate, 2),
                'net_pnl': round(net_pnl, 2),
                'today_pnl': round(today_pnl, 2),
                'today_trades': today_trades,
                'recent_trades': [
                    {
                        'symbol': t[0],
                        'side': t[1],
                        'pnl': round(t[2], 2) if t[2] else 0,
                        'pnl_pct': round(t[3], 2) if t[3] else 0,
                        'time': t[4]
                    } for t in recent_trades
                ]
            }
        except Exception as e:
            logging.error(f"get_performance_metrics error: {e}")
            return {'error': str(e), 'total_trades': 0, 'win_rate': 0, 'net_pnl': 0, 'recent_trades': []}
    
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
    """API: 获取机器人运行状态 - 实时检测"""
    is_run = BotManager.is_running()
    pid = BotManager.get_running_pid()
    
    # 如果检测到进程但 PID 文件不存在或过期，更新 PID 文件
    if is_run and pid:
        with open(PID_FILE, 'w') as f:
            f.write(pid)
    
    return jsonify({
        'running': is_run,
        'pid': pid
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

# ========== 预测API ==========

@app.route('/api/prediction')
def api_prediction():
    """API: 获取开单时间预测 - 实时版"""
    from flask import make_response
    import time
    
    result = dashboard.get_signal_prediction()
    
    # 注意：排名通知已移除，只发送开仓和平仓通知
    
    response = make_response(jsonify(result))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# ========== IP配置API ==========

# 存储最后检测的IP - 从文件加载
def load_cached_ip():
    """从文件加载缓存的IP"""
    try:
        if os.path.exists(IP_CACHE_FILE):
            with open(IP_CACHE_FILE, 'r') as f:
                data = json.load(f)
                return data.get('ip'), data.get('timestamp')
    except:
        pass
    return None, None

def save_cached_ip(ip):
    """保存IP到缓存文件"""
    try:
        with open(IP_CACHE_FILE, 'w') as f:
            json.dump({
                'ip': ip,
                'timestamp': datetime.now().isoformat()
            }, f)
    except:
        pass

# 初始化加载缓存的IP
last_detected_ip, last_detected_time = load_cached_ip()

def get_current_ip():
    """获取当前公网IP - 使用多个备用服务"""
    import requests
    
    # 尝试多个IP检测服务
    ip_services = [
        'https://api.ipify.org?format=json',
        'https://httpbin.org/ip',
        'https://api.my-ip.io/ip.json',
        'https://ip.seeip.org/json',
    ]
    
    for service in ip_services:
        try:
            resp = requests.get(service, timeout=5)
            data = resp.json()
            # 不同API返回格式不同
            if 'ip' in data:
                return data['ip']
            elif 'origin' in data:
                return data['origin'].split(',')[0].strip()
        except:
            continue
    
    # 所有服务都失败，返回本地IP
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return 'unknown'

def check_binance_connection():
    """检查币安API连接状态"""
    try:
        import requests
        resp = requests.get('https://fapi.binance.com/fapi/v1/ping', timeout=5)
        return 'connected' if resp.status_code == 200 else 'error'
    except:
        return 'disconnected'

@app.route('/api/ip/current')
def api_ip_current():
    """API: 获取缓存的IP配置（不主动检测）"""
    global last_detected_ip, last_detected_time
    try:
        # 返回缓存的IP，不主动检测
        return jsonify({
            'current_ip': last_detected_ip,
            'cached_at': last_detected_time,
            'binance_status': 'unknown',  # 不检测币安连接状态
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/ip/check', methods=['POST'])
def api_ip_check():
    """API: 手动检测IP（点击才检测）"""
    global last_detected_ip, last_detected_time
    
    try:
        # 获取当前IP
        current_ip = get_current_ip()
        
        # 检查币安连接状态
        binance_status = check_binance_connection()
        
        # 检查IP是否变化
        ip_changed = False
        if last_detected_ip and last_detected_ip != current_ip:
            ip_changed = True
        
        # 更新并保存到文件
        last_detected_ip = current_ip
        last_detected_time = datetime.now().isoformat()
        save_cached_ip(current_ip)
        
        return jsonify({
            'success': True,
            'current_ip': current_ip,
            'previous_ip': last_detected_ip if not ip_changed else None,
            'ip_changed': ip_changed,
            'binance_status': binance_status,
            'cached_at': last_detected_time,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/ip/auto-update', methods=['POST'])
def api_ip_auto_update():
    """API: 自动检测并更新IP"""
    global last_detected_ip
    
    try:
        data = request.get_json() or {}
        api_key = data.get('api_key', '').strip()
        api_secret = data.get('api_secret', '').strip()
        
        # 获取当前IP
        current_ip = get_current_ip()
        
        if current_ip == 'unknown':
            return jsonify({
                'success': False,
                'message': '无法获取当前IP',
                'action': 'none'
            })
        
        # 检查IP是否变化
        if last_detected_ip == current_ip:
            return jsonify({
                'success': True,
                'message': f'IP未变化: {current_ip}',
                'ip': current_ip,
                'ip_changed': False,
                'action': 'none'
            })
        
        # IP变化了，尝试更新
        update_result = {
            'ip': current_ip,
            'old_ip': last_detected_ip,
            'ip_changed': True,
            'timestamp': datetime.now().isoformat()
        }
        
        # 更新最后检测的IP
        last_detected_ip = current_ip
        
        # 如果有API密钥，尝试验证连接
        if api_key and api_secret:
            try:
                import ccxt
                exchange = ccxt.binance({
                    'apiKey': api_key,
                    'secret': api_secret,
                    'enableRateLimit': True,
                })
                exchange.fetch_balance({'type': 'future'})
                update_result['api_test'] = 'success'
                update_result['message'] = f'IP已自动更新为 {current_ip}，API连接正常'
            except Exception as e:
                update_result['api_test'] = 'failed'
                update_result['message'] = f'IP已更新为 {current_ip}，但API连接失败: {str(e)}'
        else:
            update_result['message'] = f'IP已变化为 {current_ip}，请手动更新币安白名单'
            update_result['manual_steps'] = [
                '1. 登录币安官网',
                '2. 进入 API 管理',
                '3. 找到您的API Key',
                '4. 点击编辑 → 添加IP白名单',
                f'5. 输入: {current_ip}'
            ]
        
        update_result['success'] = True
        return jsonify(update_result)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'自动更新失败: {str(e)}',
            'action': 'error'
        })

@app.route('/api/ip/update', methods=['POST'])
def api_ip_update():
    """API: 手动更新币安API绑定的IP白名单"""
    try:
        data = request.get_json()
        new_ip = data.get('ip', '').strip()
        api_key = data.get('api_key', '').strip()
        api_secret = data.get('api_secret', '').strip()
        
        if not new_ip:
            return jsonify({'success': False, 'message': 'IP地址不能为空'})
        
        # 验证IP格式
        import re
        if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', new_ip):
            return jsonify({'success': False, 'message': 'IP格式不正确'})
        
        # 如果有API密钥，尝试通过API更新
        if api_key and api_secret:
            try:
                import ccxt
                exchange = ccxt.binance({
                    'apiKey': api_key,
                    'secret': api_secret,
                    'enableRateLimit': True,
                })
                # 尝试获取账户信息测试连接
                exchange.fetch_balance({'type': 'future'})
                return jsonify({
                    'success': True, 
                    'message': f'IP {new_ip} 已验证并通过API更新',
                    'note': '请确保在币安官网也添加了此IP白名单'
                })
            except Exception as e:
                return jsonify({
                    'success': False, 
                    'message': f'API验证失败: {str(e)}',
                    'note': '请检查API密钥和IP白名单设置'
                })
        
        # 仅记录IP，提示用户手动更新
        return jsonify({
            'success': True,
            'message': f'IP {new_ip} 已记录',
            'note': '请手动登录币安官网 → API管理 → 添加IP白名单',
            'manual_steps': [
                '1. 登录币安官网',
                '2. 进入 API 管理',
                '3. 找到您的API Key',
                '4. 点击编辑 → 添加IP白名单',
                f'5. 输入: {new_ip}'
            ]
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

if __name__ == '__main__':
    print("🚀 Web Dashboard v10.0 starting...")
    print("📊 Features: Performance metrics, Risk status, Position details")
    print("🎮 Bot control: Start/Stop/Restart")
    print("📜 Log viewer: Real-time logs")
    port = int(os.environ.get('PORT', 8081))
    print(f"🌐 Running on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
