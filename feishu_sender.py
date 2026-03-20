#!/usr/bin/env python3
"""
飞书消息发送工具
用于从定时任务发送消息到飞书
"""
import json
import sys
import os

def send_feishu_message(user_id, title, content, msg_type="info"):
    """
    发送飞书消息
    由于无法直接调用 OpenClaw API，我们将消息写入特殊格式的日志
    由主程序定期检查并发送
    """
    bot_dir = "/home/administrator/.openclaw/workspace/binance_bot"
    msg_file = os.path.join(bot_dir, ".feishu_msg_pending")
    
    # 构建消息
    message = {
        "user_id": user_id,
        "title": title,
        "content": content,
        "type": msg_type,
        "timestamp": __import__('datetime').datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # 追加到待发送队列
    with open(msg_file, "a") as f:
        f.write(json.dumps(message, ensure_ascii=False) + "\n")
    
    print(f"消息已加入发送队列: {title}")
    return True

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python3 feishu_sender.py <user_id> <title> <content> [type]")
        sys.exit(1)
    
    user_id = sys.argv[1]
    title = sys.argv[2]
    content = sys.argv[3]
    msg_type = sys.argv[4] if len(sys.argv) > 4 else "info"
    
    send_feishu_message(user_id, title, content, msg_type)
