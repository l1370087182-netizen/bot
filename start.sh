#!/bin/bash
# 币安交易机器人一键启动脚本

echo "🚀 币安交易机器人启动脚本"
echo "=========================="

# 设置工作目录
BOT_DIR="$HOME/.openclaw/workspace/binance_bot"
cd "$BOT_DIR" || exit 1

# 激活虚拟环境
source venv/bin/activate

# 检查参数
if [ "$1" == "bot" ] || [ "$1" == "" ]; then
    echo "📊 启动交易机器人..."
    
    # 检查是否已在运行
    if [ -f bot.pid ]; then
        PID=$(cat bot.pid)
        if ps -p $PID > /dev/null 2>&1; then
            echo "⚠️  交易机器人已在运行 (PID: $PID)"
            echo "   如需重启，请先停止: ./start.sh stop"
            exit 1
        fi
    fi
    
    # 启动机器人
    nohup python3 bot.py --real >> bot.log 2>&1 &
    echo $! > bot.pid
    sleep 2
    
    if ps -p $(cat bot.pid) > /dev/null 2>&1; then
        echo "✅ 交易机器人启动成功!"
        echo "   PID: $(cat bot.pid)"
        echo "   日志: tail -f $BOT_DIR/bot.log"
    else
        echo "❌ 交易机器人启动失败"
        exit 1
    fi

elif [ "$1" == "web" ]; then
    echo "🌐 启动Web管理面板..."
    
    # 检查是否已在运行
    if [ -f web_server.pid ]; then
        PID=$(cat web_server.pid)
        if ps -p $PID > /dev/null 2>&1; then
            echo "⚠️  Web服务器已在运行 (PID: $PID)"
            echo "   访问: http://127.0.0.1:8080"
            exit 1
        fi
    fi
    
    # 启动Web服务器
    nohup python3 web_server.py >> web_server.log 2>&1 &
    echo $! > web_server.pid
    sleep 2
    
    if ps -p $(cat web_server.pid) > /dev/null 2>&1; then
        echo "✅ Web管理面板启动成功!"
        echo "   PID: $(cat web_server.pid)"
        echo "   访问: http://127.0.0.1:8080"
    else
        echo "❌ Web服务器启动失败"
        exit 1
    fi

elif [ "$1" == "all" ]; then
    echo "🚀 启动交易机器人 + Web管理面板..."
    ./start.sh bot
    echo ""
    ./start.sh web

elif [ "$1" == "stop" ]; then
    echo "⏹ 停止服务..."
    
    # 停止交易机器人
    if [ -f bot.pid ]; then
        PID=$(cat bot.pid)
        if ps -p $PID > /dev/null 2>&1; then
            kill $PID
            echo "✅ 交易机器人已停止"
        fi
        rm -f bot.pid
    fi
    
    # 停止Web服务器
    if [ -f web_server.pid ]; then
        PID=$(cat web_server.pid)
        if ps -p $PID > /dev/null 2>&1; then
            kill $PID
            echo "✅ Web服务器已停止"
        fi
        rm -f web_server.pid
    fi

elif [ "$1" == "status" ]; then
    echo "📊 服务状态"
    echo "==========="
    
    # 检查交易机器人
    if [ -f bot.pid ]; then
        PID=$(cat bot.pid)
        if ps -p $PID > /dev/null 2>&1; then
            echo "🤖 交易机器人: ✅ 运行中 (PID: $PID)"
        else
            echo "🤖 交易机器人: ⏹ 已停止"
        fi
    else
        echo "🤖 交易机器人: ⏹ 未启动"
    fi
    
    # 检查Web服务器
    if [ -f web_server.pid ]; then
        PID=$(cat web_server.pid)
        if ps -p $PID > /dev/null 2>&1; then
            echo "🌐 Web服务器: ✅ 运行中 (PID: $PID)"
            echo "   访问: http://127.0.0.1:8080"
        else
            echo "🌐 Web服务器: ⏹ 已停止"
        fi
    else
        echo "🌐 Web服务器: ⏹ 未启动"
    fi

elif [ "$1" == "log" ]; then
    echo "📜 显示日志 (按 Ctrl+C 退出)..."
    tail -f bot.log

elif [ "$1" == "help" ] || [ "$1" == "-h" ]; then
    echo "使用方法: ./start.sh [命令]"
    echo ""
    echo "命令:"
    echo "  (空) 或 bot   启动交易机器人"
    echo "  web           启动Web管理面板"
    echo "  all           启动机器人和Web面板"
    echo "  stop          停止所有服务"
    echo "  status        查看服务状态"
    echo "  log           查看实时日志"
    echo "  help          显示帮助"
    echo ""
    echo "示例:"
    echo "  ./start.sh              # 启动交易机器人"
    echo "  ./start.sh web          # 启动Web面板"
    echo "  ./start.sh all          # 启动所有服务"
    echo "  ./start.sh stop         # 停止所有服务"
    echo "  ./start.sh status       # 查看状态"

else
    echo "❌ 未知命令: $1"
    echo "使用 './start.sh help' 查看帮助"
    exit 1
fi

echo ""
echo "✨ 完成!"