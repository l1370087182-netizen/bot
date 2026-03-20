#!/bin/bash
# Fix WSL2 time drift and restart trading bot

echo "=== Fixing WSL2 Time Drift ==="

# Method 1: Try to sync time using hwclock
sudo hwclock -s 2>/dev/null || true

# Method 2: Alternative time sync
sudo date -s "$(curl -s --head http://www.google.com | grep ^Date: | sed 's/Date: //g')" 2>/dev/null || true

echo "=== Time Sync Complete ==="
date

echo "=== Restarting Trading Bot ==="
cd /home/administrator/.openclaw/workspace/binance_bot
pkill -f "bot.py" 2>/dev/null
sleep 2
source venv/bin/activate
nohup python3 bot.py --real >> bot.log 2>&1 &
echo "Bot started with PID: $!"
sleep 3
ps aux | grep "bot.py" | grep -v grep
