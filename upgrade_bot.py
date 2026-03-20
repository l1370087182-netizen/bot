#!/usr/bin/env python3
"""
Bot Upgrade Script - 将v10.0架构整合到现有bot.py
保留所有原有功能，添加新架构模块
"""

# 读取现有bot.py
with open('bot.py', 'r') as f:
    original = f.read()

# 在import部分添加新模块
import_section = """from performance_tracker import PerformanceTracker

# ========== v10.0 新架构模块 ==========
import sys
sys.path.insert(0, 'src')

try:
    from risk.position_sizer import PositionSizer
    from risk.pyramiding import PyramidingManager
    from risk.exit_manager import ExitManager
    from risk.account_guardian import AccountGuardian
    from risk.coin_grouper import CoinGrouper
    from strategies.signal_scorer import SignalQualityScorer
    from utils.database import DatabaseManager
    V10_AVAILABLE = True
except ImportError as e:
    V10_AVAILABLE = False
    print(f"v10.0 modules not available: {e}")
# ========== v10.0 模块结束 ==========
"""

# 找到插入点（在from config import *之后）
insert_point = "from risk_manager import RiskManager"
if insert_point in original:
    original = original.replace(insert_point, import_section + "\n" + insert_point)

# 在__init__中添加新模块初始化
init_code = """
        # ========== v10.0 新架构初始化 ==========
        if V10_AVAILABLE:
            self.position_sizer = PositionSizer(risk_per_trade=0.02)
            self.pyramiding = PyramidingManager()
            self.exit_manager = ExitManager()
            self.guardian = AccountGuardian(
                daily_loss_limit=0.05,
                drawdown_limit_1=0.07,
                drawdown_limit_2=0.10
            )
            self.coin_grouper = CoinGrouper()
            self.signal_scorer = SignalQualityScorer()
            self.db = DatabaseManager('trades.db')
            self.v10_mode = True
            logging.info("🚀 v10.0 Mode: Three-layer protection + Amplifier")
        else:
            self.v10_mode = False
            self.position_sizer = None
        # ========== v10.0 初始化结束 ==========
"""

# 找到插入点（在RiskManager初始化之后）
init_insert = "self.risk = RiskManager(MAX_DAILY_LOSS_PCT, STOP_LOSS_PCT, TAKE_PROFIT_PCT)"
if init_insert in original:
    original = original.replace(init_insert, init_insert + init_code)

# 更新版本号
original = original.replace(
    "Binance Bot - 智能交易监控系统 v7.0",
    "Binance Bot - 智能交易监控系统 v10.0"
)

# 保存升级后的文件
with open('bot.py', 'w') as f:
    f.write(original)

print("✅ bot.py upgraded to v10.0")
print("   - New architecture modules integrated")
print("   - Backward compatible with existing API")
print("   - Run: python3 bot.py --real")
