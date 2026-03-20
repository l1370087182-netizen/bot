#!/bin/bash
# Binance Bot 运行脚本 (虚拟环境版)

VENV_PATH="/home/administrator/.openclaw/workspace/binance_bot/venv"

# 检查虚拟环境
if [ ! -d "$VENV_PATH" ]; then
    echo "错误: 虚拟环境未就绪！"
    exit 1
fi

# 检查 .env 文件
if [ ! -f .env ]; then
    echo "错误: 未找到 .env 文件！"
    echo "请根据 .env.template 创建 .env 文件并填入您的 API Key。"
    exit 1
fi

echo "正在启动 Binance 套利交易系统..."
"$VENV_PATH/bin/python3" bot.py
