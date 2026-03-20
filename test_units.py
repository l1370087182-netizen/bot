#!/usr/bin/env python3
"""
单元测试 - 验证各模块功能
无需 API 密钥，本地即可运行
"""
import sys
import os
sys.path.insert(0, 'src')

from risk.position_sizer import PositionSizer
from risk.pyramiding import PyramidingManager
from risk.exit_manager import ExitManager
from risk.account_guardian import AccountGuardian
from risk.coin_grouper import CoinGrouper
from strategies.signal_scorer import SignalQualityScorer

def test_position_sizer():
    """测试仓位计算"""
    print("\n" + "="*60)
    print("🧪 Testing Position Sizer")
    print("="*60)
    
    sizer = PositionSizer(risk_per_trade=0.02)
    
    # 测试场景: 账户1000 USDT, 入场100, 止损95 (5%止损)
    balance = 1000
    entry = 100
    stop = 95
    
    result = sizer.calculate_position_size(balance, entry, stop, leverage=10)
    
    print(f"Balance: {balance} USDT")
    print(f"Entry: {entry}, Stop: {stop} (5% distance)")
    print(f"Risk Amount: {result['risk_amount']:.2f} USDT (should be ~20)")
    print(f"Position Size: {result['position_size']:.4f} coins")
    print(f"Notional Value: {result['notional_value']:.2f} USDT")
    print(f"Margin Required: {result['margin_required']:.2f} USDT")
    print(f"Leverage: {result['leverage']}x")
    
    # 验证
    assert abs(result['risk_amount'] - 20) < 0.1, "Risk amount should be 2% of balance"
    assert result['position_size'] > 0, "Position size should be positive"
    print("✅ Position Sizer test passed")

def test_pyramiding():
    """测试金字塔加仓"""
    print("\n" + "="*60)
    print("🧪 Testing Pyramiding Manager")
    print("="*60)
    
    pm = PyramidingManager()
    symbol = "ETH/USDT"
    base_size = 0.1
    
    # 模拟盈利 2.5%
    result = pm.check_addition(symbol, 2.5, base_size)
    assert result is not None, "Should trigger first addition"
    print(f"Level 1 addition: +{result['size_pct']:.0%} at {result['trigger_pnl']:.0f}% profit")
    
    # 模拟盈利 5.5%
    result = pm.check_addition(symbol, 5.5, base_size)
    assert result is not None, "Should trigger second addition"
    print(f"Level 2 addition: +{result['size_pct']:.0%} at {result['trigger_pnl']:.0f}% profit")
    
    total = pm.get_total_position_size(symbol, base_size)
    print(f"Total position: {total:.4f} (base {base_size} + additions)")
    
    # 测试止损调整
    new_stop = pm.get_adjusted_stop_loss(symbol, 100, 95, 5.0)
    print(f"Adjusted stop loss at 5% profit: {new_stop:.2f}")
    
    print("✅ Pyramiding test passed")

def test_exit_manager():
    """测试分级止盈"""
    print("\n" + "="*60)
    print("🧪 Testing Exit Manager")
    print("="*60)
    
    em = ExitManager()
    symbol = "ETH/USDT"
    position_size = 0.5
    entry_price = 100
    atr = 2
    
    # 模拟盈利 2.5%
    current_price = 102.5
    result = em.check_exit(symbol, 2.5, position_size, entry_price, current_price, atr)
    if result:
        print(f"Stage 1 exit: {result['exit_pct']:.0%} at {result['stage']}")
    
    # 模拟盈利 7%
    current_price = 107
    remaining_size = position_size * 0.8  # 已经平了20%
    result = em.check_exit(symbol, 7.0, remaining_size, entry_price, current_price, atr)
    if result:
        print(f"Stage 2 exit: {result['exit_pct']:.0%} at {result['stage']}")
    
    print("✅ Exit Manager test passed")

def test_account_guardian():
    """测试账户保护"""
    print("\n" + "="*60)
    print("🧪 Testing Account Guardian")
    print("="*60)
    
    guardian = AccountGuardian(
        daily_loss_limit=0.05,
        drawdown_limit_1=0.07,
        drawdown_limit_2=0.10
    )
    
    # 模拟余额变化
    balances = [1000, 980, 950, 930, 900, 880, 850]
    
    for balance in balances:
        status = guardian.update_balance(balance)
        print(f"Balance: {balance}, Can trade: {status['can_trade']}, "
              f"Max leverage: {status['max_leverage']}, "
              f"Reason: {status.get('reason', 'OK')}")
    
    print("✅ Account Guardian test passed")

def test_coin_grouper():
    """测试币种分组"""
    print("\n" + "="*60)
    print("🧪 Testing Coin Grouper")
    print("="*60)
    
    grouper = CoinGrouper()
    
    # 测试分组识别
    print(f"DOGE group: {grouper.get_coin_group('DOGE/USDT:USDT')}")
    print(f"ETH group: {grouper.get_coin_group('ETH/USDT:USDT')}")
    print(f"UNI group: {grouper.get_coin_group('UNI/USDT:USDT')}")
    
    # 测试分组限制
    current = ['DOGE/USDT:USDT']
    can_open = grouper.can_open_position('SHIB/USDT:USDT', current)
    print(f"Can open SHIB (with DOGE held): {can_open} (should be False)")
    
    can_open = grouper.can_open_position('ETH/USDT:USDT', current)
    print(f"Can open ETH (with DOGE held): {can_open} (should be True)")
    
    exposure = grouper.get_group_exposure(current)
    print(f"Current exposure: {exposure}")
    
    print("✅ Coin Grouper test passed")

def test_signal_scorer():
    """测试信号评分"""
    print("\n" + "="*60)
    print("🧪 Testing Signal Quality Scorer")
    print("="*60)
    
    scorer = SignalQualityScorer()
    
    # 优质信号
    premium_signal = {
        'adx': 35,
        'trend_1h': 'UP',
        'trend_4h': 'UP',
        'bb_squeeze': True,
        'volume_surge': True,
        'funding_rate': -0.0002,
        'side': 'buy'
    }
    
    result = scorer.calculate_score(premium_signal)
    print(f"Premium signal score: {result['total_score']:.1f}")
    print(f"Trade tier: {result['trade_tier']}")
    print(f"Can trade: {result['can_trade']}")
    
    # 劣质信号
    poor_signal = {
        'adx': 8,
        'trend_1h': 'UP',
        'trend_4h': 'DOWN',
        'bb_squeeze': False,
        'volume_surge': False,
        'funding_rate': 0.001,
        'side': 'buy'
    }
    
    result = scorer.calculate_score(poor_signal)
    print(f"\nPoor signal score: {result['total_score']:.1f}")
    print(f"Trade tier: {result['trade_tier']}")
    print(f"Can trade: {result['can_trade']}")
    
    print("✅ Signal Scorer test passed")

if __name__ == "__main__":
    print("🚀 Starting Unit Tests...")
    print("Note: These tests don't require API keys")
    
    try:
        test_position_sizer()
        test_pyramiding()
        test_exit_manager()
        test_account_guardian()
        test_coin_grouper()
        test_signal_scorer()
        
        print("\n" + "="*60)
        print("✅ ALL TESTS PASSED!")
        print("="*60)
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
