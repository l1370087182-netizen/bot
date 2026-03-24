import os
from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# API Configuration
# =============================================================================
BINANCE_API_KEY = os.getenv('BINANCE_API_KEY')
BINANCE_API_SECRET = os.getenv('BINANCE_API_SECRET')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8622569590:AAHmgZHIqP1L50_9mXXch7-jKJ5jz5b_LMI')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '6555213810')

if not BINANCE_API_KEY or not BINANCE_API_SECRET:
    raise ValueError("BINANCE_API_KEY and BINANCE_API_SECRET must be set in .env file")

# =============================================================================
# Trading Symbols - 10大主流币
# =============================================================================
SYMBOLS = [
    "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT",
    "XRP/USDT:USDT", "BNB/USDT:USDT", "DOGE/USDT:USDT",
    "ADA/USDT:USDT", "AVAX/USDT:USDT", "SUI/USDT:USDT",
    "TRX/USDT:USDT"
]

# 信号强度排名：只对前N个币种开仓
MAX_ACTIVE_SYMBOLS = 4

# =============================================================================
# Signal Scoring Weights (信号强度权重)
# 分数 = ADX*0.4 + StochRSI强度*0.3 + CVD强度*0.3 + Funding*0.1
# =============================================================================
SIGNAL_WEIGHTS = {
    'adx': 0.4,
    'stoch_rsi': 0.3,
    'cvd': 0.3,
    'funding': 0.1
}

# =============================================================================
# Multi-Timeframe Settings (多时间框架)
# =============================================================================
TIMEFRAMES = ['15m', '1h']  # 15m信号 + 1h趋势确认
PRIMARY_TIMEFRAME = '15m'   # 主交易周期
CONFIRM_TIMEFRAME = '1h'    # 趋势确认周期

# =============================================================================
# Trading Parameters
# =============================================================================
# 固定12x杠杆（不再动态）
LEVERAGE = 12
LEVERAGE_MIN = 10
LEVERAGE_MAX = 15

POSITION_SIZE_PCT = 0.20
RISK_PER_TRADE = 0.015  # 改回1.5%
MIN_ORDER_VALUE_USDT = 20.0

# =============================================================================
# Risk Management - 三层防护
# =============================================================================
MAX_DAILY_LOSS_PCT = 0.07   # 7% 日亏损限制
MAX_TOTAL_LOSS_PCT = 0.15   # 15% 总亏损限制
MAX_DRAWDOWN_PCT = 0.20     # 20% 最大回撤限制

# =============================================================================
# ATR Dynamic Stop Loss (ATR动态止损 - 最高优先级优化)
# =============================================================================
ATR_STOP_MULTIPLIER = 2.6   # ATR倍数: 2.0-2.8x (默认2.6)
ATR_STOP_MIN = 2.0          # 最小2.0x
ATR_STOP_MAX = 2.8          # 最大2.8x

# =============================================================================
# Breakeven Stop (保本移动止损)
# =============================================================================
BREAKEVEN = {
    'enabled': True,
    'trigger_r': 1.0,  # 盈利达到1R时触发
    'buffer_pct': 0.005  # 保本价+0.5%缓冲
}

# =============================================================================
# Exit Strategy - R-based
# =============================================================================
RR_2R_CLOSE_PCT = 0.20
RR_3R_CLOSE_PCT = 0.50
RR_2R_MULTIPLE = 2.5
RR_3R_MULTIPLE = 3.5

EXIT_STRATEGY = {
    'enabled': True,
    'r_levels': [
        {'r_multiple': RR_2R_MULTIPLE, 'exit_pct': RR_2R_CLOSE_PCT},
        {'r_multiple': RR_3R_MULTIPLE, 'exit_pct': RR_3R_CLOSE_PCT},
    ],
    'trailing_stop': {
        'enabled': True,
        'atr_multiplier': 2.6,
        'timeframe': '15m'
    }
}

# =============================================================================
# Stop Loss / Take Profit (保留兼容)
# =============================================================================
STOP_LOSS_PCT = 0.02        # 保留但不再使用，改用ATR动态止损
TAKE_PROFIT_PCT = 0.06
SLIPPAGE_PROTECTION = 0.001

# =============================================================================
# Pyramiding - R-based
# =============================================================================
PYRAMID_TRIGGER_1 = 1.0
PYRAMID_TRIGGER_2 = 1.8
PYRAMID_SIZE_1 = 0.30
PYRAMID_SIZE_2 = 0.20

PYRAMIDING = {
    'enabled': True,
    'max_levels': 2,
    'r_based': True,
    'levels': [
        {'r_multiple': PYRAMID_TRIGGER_1, 'size_pct': PYRAMID_SIZE_1},
        {'r_multiple': PYRAMID_TRIGGER_2, 'size_pct': PYRAMID_SIZE_2},
    ]
}

# =============================================================================
# Technical Indicators (信号过滤收紧 - 最高优先级优化)
# =============================================================================
INDICATORS = {
    'ema': {'enabled': True, 'period': 200},
    'stoch_rsi': {
        'enabled': True, 'rsi_period': 14, 'stoch_period': 14,
        'k_period': 3, 'd_period': 3,
        'oversold': 38,   # 放宽: 从35改为38
        'overbought': 62  # 放宽: 从65改为62
    },
    'adx': {'enabled': True, 'period': 14, 'threshold': 22},  # 放宽: 从25改为22
    'bollinger': {'enabled': True, 'period': 20, 'std_dev': 2.0},
    'atr': {'enabled': True, 'period': 14}
}

# =============================================================================
# WebSocket Configuration (v12.0)
# =============================================================================
WEBSOCKET_ENABLED = True
WS_RECONNECT_DELAY = 30
KLINE_CACHE_SIZE = 500

# =============================================================================
# CVD - 订单流分析（加强阈值）
# =============================================================================
CVD = {
    'enabled': True,
    'lookback_period': 20,
    'min_confidence': 45,
    'validation': {
        'enabled': True,
        'cvd_delta_multiplier': 2.0,  # 加强: 2.0
        'cvd_ratio_threshold': 1.3    # 加强: 1.3
    }
}

# =============================================================================
# Funding Rate Filter (资金费率过滤)
# =============================================================================
FUNDING = {
    'enabled': True,
    'threshold': 0.0001,  # 0.01%
    'weight_impact': 10,   # 10%权重
    'prefer_short_when_positive': True,   # >0.01%优先做空
    'prefer_long_when_negative': True     # <-0.01%优先做多
}

# =============================================================================
# Bot Settings
# =============================================================================
LOOP_INTERVAL = 30
TIME_SYNC_INTERVAL = 10
MIN_HOLD_TIME = 300

# =============================================================================
# Web Dashboard
# =============================================================================
WEB_DASHBOARD = {
    'enabled': True,
    'port': 8081,
    'refresh_interval': 5,
    'history_days': 7,
    'timezone': 'Asia/Shanghai',
    'chart_colors': {
        'up': '#00d084',      # 绿色=上涨
        'down': '#ff4757',    # 红色=下跌
        'neutral': '#ffa502'  # 黄色=震荡
    }
}

# =============================================================================
# Notifications
# =============================================================================
NOTIFICATIONS = {
    'bark': {'enabled': True, 'device_key': 'jRTuEZmk2j254haTnwtd7Q'},
    'telegram': {'enabled': False},
    'feishu': {'enabled': False}
}

# =============================================================================
# Backtest
# =============================================================================
BACKTEST = {
    'enabled': True,
    'default_days': 30,
    'fee_rate': 0.0005,
    'slippage': 0.001
}
PROXY_ENABLED = True
PROXY_URL = os.getenv('PROXY_URL', 'http://127.0.0.1:7897')
