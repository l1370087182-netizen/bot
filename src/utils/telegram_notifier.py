"""
Telegram Notifier - Telegram Bot通知
比Bark更稳定，支持图表和富文本
"""
import logging
import requests
from datetime import datetime

class TelegramNotifier:
    """
    Telegram Bot 通知器
    
    功能:
    - 开仓/平仓通知
    - 风控警报
    - 每日盈亏报告
    - 系统状态
    """
    
    def __init__(self, bot_token, chat_id):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        
        if not bot_token or not chat_id:
            logging.warning("⚠️ Telegram notifier not configured")
            self.enabled = False
        else:
            self.enabled = True
            logging.info("📱 TelegramNotifier initialized")
    
    def send_message(self, message, parse_mode='HTML'):
        """发送文本消息"""
        if not self.enabled:
            return False
        
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': parse_mode
            }
            
            response = requests.post(url, json=payload, timeout=10)
            
            if response.status_code == 200:
                return True
            else:
                logging.error(f"❌ Telegram send failed: {response.text}")
                return False
                
        except Exception as e:
            logging.error(f"❌ Telegram error: {e}")
            return False
    
    def send_trade_open(self, symbol, side, size, entry_price, leverage, stop_loss):
        """发送开仓通知"""
        emoji = "🟢" if side == 'LONG' else "🔴"
        
        message = f"""
{emoji} <b>开仓成功</b>

<b>币种:</b> <code>{symbol}</code>
<b>方向:</b> {side}
<b>数量:</b> {size:.6f}
<b>入场价:</b> {entry_price:.4f}
<b>杠杆:</b> {leverage}x
<b>止损:</b> {stop_loss:.4f}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """
        
        return self.send_message(message)
    
    def send_trade_close(self, symbol, side, pnl, pnl_pct, exit_reason, duration_hours):
        """发送平仓通知"""
        emoji = "✅" if pnl > 0 else "❌"
        pnl_emoji = "📈" if pnl > 0 else "📉"
        
        message = f"""
{emoji} <b>平仓成功</b>

<b>币种:</b> <code>{symbol}</code>
<b>方向:</b> {side}
<b>盈亏:</b> {pnl_emoji} {pnl:+.2f} USDT ({pnl_pct:+.2f}%)
<b>原因:</b> {exit_reason}
<b>持仓时间:</b> {duration_hours:.1f}小时

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """
        
        return self.send_message(message)
    
    def send_risk_alert(self, alert_type, message, current_drawdown=None):
        """发送风控警报"""
        if alert_type == 'DAILY_LOSS':
            emoji = "⚠️"
            title = "日亏损限制触发"
        elif alert_type == 'SURVIVAL_MODE':
            emoji = "🚨"
            title = "保命模式激活"
        elif alert_type == 'CRITICAL_DRAWDOWN':
            emoji = "🔒"
            title = "账户永久锁定"
        else:
            emoji = "⚡"
            title = "风控警报"
        
        dd_text = f"\n<b>当前回撤:</b> {current_drawdown:.2%}" if current_drawdown else ""
        
        msg = f"""
{emoji} <b>{title}</b> {emoji}

<b>消息:</b> {message}
{dd_text}

🔔 请立即检查账户状态！
        """
        
        return self.send_message(msg)
    
    def send_daily_report(self, metrics):
        """发送每日报告"""
        message = f"""
📊 <b>每日交易报告</b>

<b>交易次数:</b> {metrics.get('total_trades', 0)}
<b>胜率:</b> {metrics.get('win_rate', 0):.1%}
<b>净利润:</b> {metrics.get('net_pnl', 0):+.2f} USDT
<b>盈亏比:</b> {metrics.get('profit_loss_ratio', 0):.2f}
<b>夏普比率:</b> {metrics.get('sharpe_ratio', 0):.2f}

⏰ {datetime.now().strftime('%Y-%m-%d')}
        """
        
        return self.send_message(message)
    
    def send_system_status(self, balance, positions_count, is_running):
        """发送系统状态"""
        status_emoji = "🟢" if is_running else "🔴"
        status_text = "运行中" if is_running else "已停止"
        
        message = f"""
{status_emoji} <b>系统状态</b>

<b>状态:</b> {status_text}
<b>余额:</b> {balance:.2f} USDT
<b>持仓:</b> {positions_count}个

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """
        
        return self.send_message(message)

if __name__ == "__main__":
    # 测试
    notifier = TelegramNotifier(
        bot_token="YOUR_BOT_TOKEN",
        chat_id="YOUR_CHAT_ID"
    )
    
    # 测试发送
    notifier.send_trade_open(
        symbol="ETH/USDT",
        side="LONG",
        size=0.5,
        entry_price=100,
        leverage=10,
        stop_loss=95
    )
