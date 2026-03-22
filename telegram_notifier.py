"""
Telegram 通知模块
用于发送交易机器人消息到 Telegram
"""
import requests
import logging
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

class TelegramNotifier:
    def __init__(self):
        self.bot_token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.enabled = bool(self.bot_token and self.chat_id)
        
    def send_message(self, message, parse_mode='HTML'):
        """发送消息到 Telegram"""
        if not self.enabled:
            logging.warning("Telegram 未配置，跳过发送")
            return False
            
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': parse_mode,
                'disable_web_page_preview': True
            }
            response = requests.post(url, json=payload, timeout=10)
            
            if response.status_code == 200:
                logging.info("Telegram 消息发送成功")
                return True
            else:
                logging.error(f"Telegram 发送失败: {response.text}")
                return False
        except Exception as e:
            logging.error(f"Telegram 发送错误: {e}")
            return False
    
    def notify_trade(self, symbol, side, amount, price, leverage, pnl=None):
        """发送交易通知"""
        emoji = "🟢" if side == "buy" else "🔴"
        pnl_text = f"\n💰 盈亏: {pnl:+.2f} USDT" if pnl else ""
        
        message = f"""
{emoji} <b>交易执行</b>

📊 币种: {symbol}
📈 方向: {"做多" if side == "buy" else "做空"}
💵 数量: {amount}
💲 价格: {price}
⚡ 杠杆: {leverage}x{pnl_text}
        """
        return self.send_message(message)
    
    def notify_signal(self, symbol, side, strength, signal_type):
        """发送信号通知"""
        emoji = "🟢" if side == "buy" else "🔴"
        
        message = f"""
{emoji} <b>交易信号</b>

📊 币种: {symbol}
📈 方向: {"做多" if side == "buy" else "做空"}
💪 强度: {strength}
📡 类型: {signal_type}
        """
        return self.send_message(message)
    
    def notify_risk(self, message, level='warning'):
        """发送风控通知"""
        emoji = "⚠️" if level == 'warning' else "🚨"
        
        msg = f"""
{emoji} <b>风控提醒</b>

{message}
        """
        return self.send_message(msg)
    
    def notify_daily_report(self, balance, pnl, trades_count):
        """发送每日报告"""
        emoji = "🟢" if pnl >= 0 else "🔴"
        
        message = f"""
📊 <b>每日交易报告</b>

💰 账户余额: {balance:.2f} USDT
{emoji} 今日盈亏: {pnl:+.2f} USDT
📈 交易次数: {trades_count}
        """
        return self.send_message(message)
    
    def notify_ranking(self, long_candidates, short_candidates, min_distance, prediction):
        """发送排名更新"""
        # 多头排名
        long_text = ""
        for i, c in enumerate(long_candidates[:3], 1):
            long_text += f"\n{i}. {c['coin']} | Stoch:{c['stoch']:.1f} | 距离:{c['distance']:.1f}"
        
        # 空头排名
        short_text = ""
        for i, c in enumerate(short_candidates[:3], 1):
            short_text += f"\n{i}. {c['coin']} | Stoch:{c['stoch']:.1f} | 距离:{c['distance']:.1f}"
        
        message = f"""
📊 <b>交易机会排名</b>

🟢 <b>做多机会 (Top 3)</b>{long_text if long_text else "\n暂无"}

🔴 <b>做空机会 (Top 3)</b>{short_text if short_text else "\n暂无"}

⏱ 预测: {prediction}
📏 最近距离: {min_distance:.1f}
        """
        return self.send_message(message)
    
    def notify_signal_filtered(self, symbol, side, reason):
        """发送信号被过滤通知"""
        emoji = "🚫"
        
        message = f"""
{emoji} <b>信号被过滤</b>

📊 币种: {symbol}
📈 方向: {"做多" if side == "buy" else "做空"}
🛑 原因: {reason}
        """
        return self.send_message(message)
    
    def notify_signal_result(self, symbol, side, result, reason=""):
        """发送信号结果通知"""
        if result == "success":
            emoji = "✅"
            status = "真开仓 - 已执行"
        elif result == "filtered":
            emoji = "🚫"
            status = "假突破 - 被过滤"
        elif result == "failed":
            emoji = "❌"
            status = "执行失败"
        else:
            emoji = "⚠️"
            status = "未知状态"
        
        reason_text = f"\n📋 原因: {reason}" if reason else ""
        
        message = f"""
{emoji} <b>信号结果</b>

📊 币种: {symbol}
📈 方向: {"做多" if side == "buy" else "做空"}
📊 结果: {status}{reason_text}
        """
        return self.send_message(message)

# 全局实例
telegram = TelegramNotifier()
