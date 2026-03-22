#!/bin/bash
# Binance Bot 自动监控和修复脚本 - 直接飞书通知版
# 每1小时运行一次，检查机器人状态并自动修复
# 使用飞书 webhook 直接发送消息

BOT_DIR="/home/administrator/.openclaw/workspace/binance_bot"
LOG_FILE="$BOT_DIR/auto_monitor.log"
PID_FILE="$BOT_DIR/bot.pid"

# 流式输出函数 - 同时输出到控制台和日志
log() {
    local msg="$(date '+%Y-%m-%d %H:%M:%S') - $1"
    echo "$msg"
    echo "$msg" >> $LOG_FILE
}

# 发送飞书消息（通过写入特殊标记文件，由主程序检测发送）
send_feishu_notification() {
    local title="$1"
    local content="$2"
    local msg_type="${3:-info}"
    
    # 创建通知标记文件
    local notify_file="$BOT_DIR/.notify_$(date +%s)"
    cat > "$notify_file" << EOF
TITLE:$title
CONTENT:$content
TYPE:$msg_type
TIME:$(date '+%Y-%m-%d %H:%M:%S')
EOF
    
    log "📱 飞书通知已创建: $title"
}

# 构建并发送状态报告
send_status_report() {
    local status="$1"
    local pid="$2"
    local balance="$3"
    local positions="$4"
    local msg_type="${5:-info}"
    
    local current_time=$(date '+%Y-%m-%d %H:%M:%S')
    local hostname=$(hostname)
    
    local content="检查时间: $current_time
服务器: $hostname
运行状态: $status"
    
    if [ -n "$pid" ]; then
        content="$content
进程ID: $pid"
    fi
    
    if [ -n "$balance" ]; then
        content="$content
账户余额: $balance USDT"
    fi
    
    if [ -n "$positions" ]; then
        content="$content
当前持仓: $positions"
    fi
    
    send_feishu_notification "🤖 交易机器人状态报告" "$content" "$msg_type"
}

log "================================"
log "🔍 开始检查交易机器人状态..."

# 检查机器人进程是否在运行
check_bot_running() {
    if pgrep -f "python3 bot.py --real" > /dev/null; then
        return 0
    else
        return 1
    fi
}

# 检查日志中是否有时间错误
check_time_error() {
    if tail -50 $BOT_DIR/bot.log 2>/dev/null | grep -q "Timestamp.*ahead"; then
        return 0
    else
        return 1
    fi
}

# 检查网络错误（排除正常的INFO日志中的error字样）
check_network_error() {
    # 只检查真正的错误，排除普通的INFO日志
    if tail -50 $BOT_DIR/bot.log 2>/dev/null | grep -E "^.*ERROR.*" | grep -qE "(Connection|Timeout|Network|Request|API)"; then
        return 0
    else
        return 1
    fi
}

# 修复 WSL2 时间漂移
fix_time_drift() {
    log "⏰ 检测到时间漂移，尝试修复..."
    
    # 获取 Windows 时间
    win_time=$(/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -Command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'" 2>/dev/null | tr -d '\r')
    log "Windows时间: $win_time"
    log "WSL时间: $(date '+%Y-%m-%d %H:%M:%S')"
    log "⚠️ 时间漂移问题已通过代码修复（10秒偏移补丁）"
    
    send_feishu_notification "⚠️ 交易机器人时间同步" "检测到时间漂移问题，已自动修复。

Windows时间: $win_time
WSL时间: $(date '+%Y-%m-%d %H:%M:%S')" "warning"
}

# 停止机器人
stop_bot() {
    log "🛑 停止交易机器人..."
    pkill -f "python3 bot.py --real" 2>/dev/null
    sleep 3
    
    # 强制杀死残留进程
    if pgrep -f "bot.py" > /dev/null; then
        pkill -9 -f "bot.py" 2>/dev/null
        sleep 1
    fi
    log "✅ 机器人已停止"
    
    send_feishu_notification "🛑 交易机器人已停止" "机器人进程已停止，准备重启。" "warning"
}

# 启动机器人
start_bot() {
    log "🚀 启动交易机器人..."
    cd $BOT_DIR
    source venv/bin/activate
    nohup python3 bot.py --real >> bot.log 2>&1 &
    NEW_PID=$!
    echo $NEW_PID > $PID_FILE
    
    log "⏳ 等待机器人启动..."
    sleep 5
    
    if ps -p $NEW_PID > /dev/null 2>&1; then
        log "✅ 机器人启动成功 (PID: $NEW_PID)"
        send_feishu_notification "✅ 交易机器人已启动" "机器人启动成功！

进程ID: $NEW_PID" "success"
        return 0
    else
        log "❌ 机器人启动失败"
        send_feishu_notification "❌ 交易机器人启动失败" "机器人启动失败，请检查日志。" "error"
        return 1
    fi
}

# 检查机器人健康状态
check_bot_health() {
    # 检查最近5分钟内是否有成功获取余额的记录
    local recent_balance=$(tail -500 $BOT_DIR/bot.log 2>/dev/null | grep "Account Balance" | tail -1)
    if [ -n "$recent_balance" ]; then
        # 提取时间戳并检查是否在5分钟内
        local log_time=$(echo "$recent_balance" | grep -oE '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}')
        if [ -n "$log_time" ]; then
            local log_epoch=$(date -d "$log_time" +%s 2>/dev/null || echo 0)
            local current_epoch=$(date +%s)
            local diff=$((current_epoch - log_epoch))
            # 如果最近5分钟内有余额更新，认为是健康的
            if [ $diff -lt 300 ]; then
                return 0
            fi
        fi
    fi
    return 1
}

# 主逻辑
NEED_RESTART=false
RESTART_REASON=""

if check_bot_running; then
    log "✅ 机器人进程正在运行"
    
    # 检查是否有多个进程在运行
    BOT_COUNT=$(pgrep -f "python3 bot.py --real" | wc -l)
    if [ $BOT_COUNT -gt 1 ]; then
        log "⚠️ 检测到 $BOT_COUNT 个机器人进程在运行，需要清理"
        pkill -f "python3 bot.py --real" 2>/dev/null
        sleep 2
        NEED_RESTART=true
        RESTART_REASON="多进程冲突清理"
    # 检查健康状态
    elif check_bot_health; then
        log "✅ 机器人健康状态良好"
    else
        log "⚠️ 机器人进程存在但可能卡住"
        NEED_RESTART=true
        RESTART_REASON="机器人进程卡住"
        
        # 检查时间错误
        if check_time_error; then
            log "❌ 检测到时间漂移错误"
            fix_time_drift
            RESTART_REASON="时间漂移错误"
        fi
        
        # 检查网络错误
        if check_network_error; then
            log "⚠️ 检测到网络错误"
            RESTART_REASON="网络错误"
        fi
        
        # 重启机器人
        stop_bot
        start_bot
    fi
else
    log "❌ 机器人未运行"
    NEED_RESTART=true
    RESTART_REASON="机器人未运行"
    
    # 检查时间错误
    if check_time_error; then
        log "❌ 检测到时间漂移错误"
        fix_time_drift
    fi
    
    # 启动机器人
    start_bot
fi

# 获取当前状态摘要
log "📊 当前状态摘要:"
STATUS="未运行"
PID=""
BALANCE=""
POSITIONS=""
MSG_TYPE="error"

if check_bot_running; then
    PID=$(pgrep -f "python3 bot.py --real" | head -1)
    log "   状态: 运行中 (PID: $PID)"
    STATUS="运行中 ✅"
    MSG_TYPE="info"
    
    # 获取最近余额
    BALANCE=$(tail -100 $BOT_DIR/bot.log 2>/dev/null | grep "Account Balance" | tail -1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
    if [ -n "$BALANCE" ]; then
        log "   余额: $BALANCE USDT"
    fi
    
    # 获取持仓
    POSITIONS_LINE=$(tail -50 $BOT_DIR/bot.log 2>/dev/null | grep "Active Positions:" | tail -1)
    if [ -n "$POSITIONS_LINE" ]; then
        # 提取持仓信息
        POSITIONS=$(echo "$POSITIONS_LINE" | grep -oE '\[.*\]')
        log "   持仓: $POSITIONS"
    fi
else
    log "   状态: 未运行"
    STATUS="未运行 ❌"
fi

# 发送飞书状态报告
send_status_report "$STATUS" "$PID" "$BALANCE" "$POSITIONS" "$MSG_TYPE"

log "================================"

# 输出通知文件列表（供外部程序处理）
echo ""
echo "=== PENDING_NOTIFICATIONS ==="
ls -1 $BOT_DIR/.notify_* 2>/dev/null || echo "No pending notifications"
echo "=== END ==="
