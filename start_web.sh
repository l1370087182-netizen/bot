#!/bin/bash
# 币安交易机器人Web管理后台启动脚本

echo "🚀 启动交易机器人Web管理后台..."

# 进入项目目录
cd ~/.openclaw/workspace/binance_bot

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "❌ 虚拟环境不存在，请先安装依赖"
    exit 1
fi

# 激活虚拟环境
source venv/bin/activate

# 检查Flask是否安装
if ! python3 -c "import flask" 2>/dev/null; then
    echo "📦 安装Flask..."
    pip install flask flask-cors -q
fi

# 启动Web服务器
echo "✅ 启动Web服务器..."
echo "📱 访问地址: http://localhost:8080"
echo "🌐 局域网地址: http://$(hostname -I | awk '{print $1}'):8080"
echo ""
echo "按 Ctrl+C 停止服务器"
echo ""

python3 web_server.py