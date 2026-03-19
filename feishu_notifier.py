#!/usr/bin/env python3
"""
飞书通知发送器
读取通知文件并发送消息到飞书
由主程序定期调用
"""
import os
import glob
import sys

BOT_DIR = "/home/administrator/.openclaw/workspace/binance_bot"

def get_pending_notifications():
    """获取所有待发送的通知"""
    notify_files = glob.glob(os.path.join(BOT_DIR, ".notify_*"))
    notifications = []
    
    for filepath in notify_files:
        try:
            with open(filepath, "r") as f:
                lines = f.read().strip().split("\n")
                notification = {}
                for line in lines:
                    if line.startswith("TITLE:"):
                        notification["title"] = line[6:]
                    elif line.startswith("CONTENT:"):
                        notification["content"] = line[8:]
                    elif line.startswith("TYPE:"):
                        notification["type"] = line[5:]
                    elif line.startswith("TIME:"):
                        notification["time"] = line[5:]
                
                if notification:
                    notifications.append(notification)
                    # 删除已读取的文件
                    os.remove(filepath)
        except Exception as e:
            print(f"Error reading {filepath}: {e}")
    
    return notifications

def format_for_feishu(notification):
    """格式化通知为飞书消息格式"""
    title = notification.get("title", "通知")
    content = notification.get("content", "")
    msg_type = notification.get("type", "info")
    time = notification.get("time", "")
    
    # 返回格式化后的字符串
    return f"""
---
## {title}

{content}

*时间: {time}*
---
"""

if __name__ == "__main__":
    notifications = get_pending_notifications()
    
    if notifications:
        print(f"Found {len(notifications)} pending notifications:\n")
        for i, notif in enumerate(notifications, 1):
            print(f"[{i}] {notif.get('title', 'Unknown')}")
            print(format_for_feishu(notif))
    else:
        print("No pending notifications")
        sys.exit(0)
