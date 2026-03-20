#!/bin/bash
# 读取通知文件并发送飞书消息

BOT_DIR="/home/administrator/.openclaw/workspace/binance_bot"
NOTIFY_FILE="$BOT_DIR/.notify_msg"

if [ -f "$NOTIFY_FILE" ]; then
    # 读取通知内容
    TITLE=$(cat "$NOTIFY_FILE" | grep '"title"' | cut -d'"' -f4)
    CONTENT=$(cat "$NOTIFY_FILE" | grep '"content"' | cut -d'"' -f4)
    TYPE=$(cat "$NOTIFY_FILE" | grep '"type"' | cut -d'"' -f4)
    
    # 输出到控制台（主程序会捕获并发送）
    echo "[FEISHU_NOTIFY]"
    echo "TITLE: $TITLE"
    echo "CONTENT: $CONTENT"
    echo "TYPE: $TYPE"
    
    # 删除通知文件
    rm -f "$NOTIFY_FILE"
fi
