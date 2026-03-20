#!/bin/bash
# Binance Bot 监控脚本 - 确保机器人持续运行

BOT_DIR="/home/administrator/.openclaw/workspace/binance_bot"
LOG_FILE="$BOT_DIR/monitor.log"
PID_FILE="$BOT_DIR/bot.pid"

echo "$(date): 🔍 Checking bot status..." >> $LOG_FILE

# 检查 bot.py 是否在运行
if pgrep -f "python3 bot.py --real" > /dev/null; then
    echo "$(date): ✅ Bot is running" >> $LOG_FILE
    exit 0
fi

echo "$(date): ⚠️ Bot is not running. Restarting..." >> $LOG_FILE

# 清理旧的进程
pkill -f "bot.py" 2>/dev/null
sleep 2

# 启动机器人
cd $BOT_DIR
source venv/bin/activate
nohup python3 bot.py --real >> bot.log 2>&1 &
NEW_PID=$!

# 保存 PID
echo $NEW_PID > $PID_FILE

echo "$(date): 🚀 Bot restarted with PID: $NEW_PID" >> $LOG_FILE

# 等待几秒确认启动
sleep 5
if ps -p $NEW_PID > /dev/null; then
    echo "$(date): ✅ Bot confirmed running (PID: $NEW_PID)" >> $LOG_FILE
else
    echo "$(date): ❌ Bot failed to start!" >> $LOG_FILE
fi
