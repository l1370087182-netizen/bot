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
MAX_ACTIVE_SYMBOLS = 2

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

ENTRY_RULES = {
    'stoch_lookback': 5,
    'ema_buffer_pct': 0.005,
    'soft_confirm_di_ratio': 0.9,
    'confirm_long_adx_threshold': 20,
    'confirm_short_adx_threshold': 30,
    'require_confirm_ema_alignment': True,
    'price_confirm_enabled': True,
    'price_confirm_use_close': False,
    'price_confirm_buffer_pct': 0.0005,
    'long_trigger_k_max': 40,
    'short_trigger_k_min': 58,
    'short_rally_lookback': 4,
    'signal_cooldown_minutes': 540,
}

SIGNAL_QUALITY = {
    'min_score': 88.0,
    'full_risk_score': 94.0,
    'reduced_risk_multiplier': 0.15,
    'enable_long': True,
    'enable_short': True,
    'long_min_score': 92.0,
    'long_full_risk_score': 96.0,
    'long_reduced_risk_multiplier': 0.10,
    'short_min_score': 99.0,
    'short_full_risk_score': 100.0,
    'short_reduced_risk_multiplier': 0.02,
}

# =============================================================================
# Symbol Signal Profiles (币种分层门槛)
# 目的：不直接删币，而是对样本外持续拖累的一侧提高门槛
# 2026-03-25 当前结论：
# - DOGE / ADA / ETH 主要是做多拖累
# - SOL 主要是做空拖累
# =============================================================================
SYMBOL_SIGNAL_PROFILES = {
    'BTCUSDT': {
        'long_min_score': 90.0,
        'long_full_risk_score': 95.0,
        'long_reduced_risk_multiplier': 0.18,
    },
    'SUIUSDT': {
        'long_min_score': 90.0,
        'long_full_risk_score': 95.0,
        'long_reduced_risk_multiplier': 0.18,
    },
    'AVAXUSDT': {
        'long_min_score': 90.0,
        'long_full_risk_score': 95.0,
        'long_reduced_risk_multiplier': 0.18,
    },
    'XRPUSDT': {
        'long_min_score': 91.0,
        'long_full_risk_score': 95.0,
        'long_reduced_risk_multiplier': 0.15,
    },
    'DOGEUSDT': {
        'enable_long': False,
        'long_min_score': 96.0,
        'long_full_risk_score': 99.0,
        'long_reduced_risk_multiplier': 0.05,
    },
    'ADAUSDT': {
        'enable_long': False,
        'long_min_score': 96.0,
        'long_full_risk_score': 99.0,
        'long_reduced_risk_multiplier': 0.05,
    },
    'ETHUSDT': {
        'enable_long': False,
        'long_min_score': 95.0,
        'long_full_risk_score': 98.0,
        'long_reduced_risk_multiplier': 0.05,
    },
    'SOLUSDT': {
        'enable_short': False,
        'short_min_score': 100.0,
        'short_full_risk_score': 100.0,
        'short_reduced_risk_multiplier': 0.0,
    },
}


def normalize_symbol_key(symbol: str) -> str:
    if not symbol:
        return ''
    return symbol.replace('/USDT:USDT', 'USDT').replace('/', '').replace(':', '').upper()


def get_signal_quality_for_symbol(symbol: str | None = None) -> dict:
    quality = dict(SIGNAL_QUALITY)
    symbol_key = normalize_symbol_key(symbol) if symbol else ''
    if symbol_key:
        quality.update(SYMBOL_SIGNAL_PROFILES.get(symbol_key, {}))
    return quality

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
    'trigger_r': 1.2,  # 盈利达到1.2R时提前保本，减少回撤并提升胜率
    'buffer_pct': 0.005  # 保本价+0.5%缓冲
}

# =============================================================================
# Exit Strategy - R-based
# =============================================================================
RR_2R_CLOSE_PCT = 0.25
RR_3R_CLOSE_PCT = 0.50
RR_2R_MULTIPLE = 2.0
RR_3R_MULTIPLE = 3.0

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
# Market Regime Filter (市场环境过滤)
# =============================================================================
MARKET_REGIME = {
    'enabled': True,
    'leader_symbol': 'BTCUSDT',
    'short_requires_bearish_regime': True,
    'adx_threshold': 20,
}

# =============================================================================
# Symbol Structure Filter (币种结构过滤)
# 目的：过滤高噪音、低效率的时段，而不是按历史盈亏直接拉黑币种
# 基于 1h 结构特征：成交额、实体效率、DI 主导度、EMA 偏离、ATR 占比、趋势效率
# =============================================================================
SYMBOL_STRUCTURE_FILTER = {
    'enabled': True,
    'apply_to_long': True,
    'apply_to_short': False,
    'volume_window': 24,            # 1h 成交额滚动中位数窗口
    'quality_window': 8,            # 1h 结构质量滚动中位数窗口
    'trend_lookback': 12,           # 1h 趋势效率观察长度
    'min_quote_volume': 3_000_000,  # 最近结构期最小成交额中位数
    'min_body_efficiency': 0.38,    # K线实体效率下限
    'min_di_dominance': 0.53,       # DI 主导度下限
    'min_ema_gap_pct': 0.025,       # 与 EMA200 的最小有效偏离
    'min_atr_pct': 0.007,           # ATR / Price 下限
    'min_trend_efficiency': 0.24,   # 趋势效率下限
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
