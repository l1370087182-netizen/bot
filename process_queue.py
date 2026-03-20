#!/usr/bin/env python3
"""
消息队列处理器 - 读取并发送飞书消息
由主程序定期调用
"""
import os
import sys

BOT_DIR = "/home/administrator/.openclaw/workspace/binance_bot"
MSG_QUEUE = os.path.join(BOT_DIR, ".msg_queue")

def process_messages():
    """处理消息队列中的所有消息"""
    if not os.path.exists(MSG_QUEUE):
        return []
    
    messages = []
    with open(MSG_QUEUE, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                parts = line.split("|", 3)
                if len(parts) >= 4:
                    messages.append({
                        "type": parts[0],
                        "title": parts[1],
                        "content": parts[2],
                        "time": parts[3]
                    })
    
    # 清空队列
    os.remove(MSG_QUEUE)
    return messages

if __name__ == "__main__":
    msgs = process_messages()
    if msgs:
        print(f"Found {len(msgs)} messages to send")
        for msg in msgs:
            print(f"\n[{msg['type'].upper()}] {msg['title']}")
            print(f"Time: {msg['time']}")
            print(f"Content: {msg['content']}")
    else:
        print("No pending messages")
