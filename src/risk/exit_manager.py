"""
Exit Manager - 分级止盈管理器
核心原则: 分阶段放手，让利润奔跑
"""
import logging
import time

class ExitManager:
    """
    智能退出管理器
    
    止盈规则:
    - 盈利 2% → 平掉 20%，止损移到保本
    - 盈利 6% → 再平掉 30%，止损收紧
    - 剩余 50% → 永不主动平仓，用0.8x ATR追踪止损
    """
    
    def __init__(self):
        self.exit_stages = [
            {'pnl_pct': 2.0, 'exit_pct': 0.20, 'atr_mult': 2.0},   # 20%仓位，2x ATR
            {'pnl_pct': 6.0, 'exit_pct': 0.30, 'atr_mult': 1.5},   # 30%仓位，1.5x ATR
            {'pnl_pct': 10.0, 'exit_pct': 0.0, 'atr_mult': 0.8},  # 剩余50%，0.8x ATR贴身
        ]
        self.position_stages = {}  # {symbol: current_stage}
        logging.info("🚪 ExitManager initialized")
    
    def check_exit(self, symbol, current_pnl_pct, position_size, entry_price, current_price, atr):
        """
        检查是否应该部分止盈
        
        Returns:
            dict or None: 退出指令
        """
        if symbol not in self.position_stages:
            self.position_stages[symbol] = 0
        
        current_stage = self.position_stages[symbol]
        
        # 检查是否所有阶段都已完成
        if current_stage >= len(self.exit_stages):
            # 只检查追踪止损
            return self._check_trailing_stop(symbol, current_price, entry_price, atr, 0.8)
        
        stage = self.exit_stages[current_stage]
        
        # 检查是否达到止盈条件
        if current_pnl_pct >= stage['pnl_pct']:
            # 计算退出数量
            if stage['exit_pct'] > 0:
                exit_size = position_size * stage['exit_pct']
                
                self.position_stages[symbol] += 1
                
                logging.info(f"🎯 Exit signal for {symbol}: "
                            f"Stage {current_stage + 1} | "
                            f"PnL {current_pnl_pct:.1f}% | "
                            f"Exit {stage['exit_pct']:.0%} | "
                            f"Size: {exit_size:.4f}")
                
                return {
                    'action': 'PARTIAL_EXIT',
                    'stage': current_stage + 1,
                    'exit_size': exit_size,
                    'remaining_size': position_size - exit_size,
                    'exit_pct': stage['exit_pct'],
                    'new_atr_mult': stage['atr_mult']
                }
            else:
                # 进入最终追踪阶段
                self.position_stages[symbol] += 1
                logging.info(f"🏃 {symbol} Entering final trailing stage with 0.8x ATR")
                return None
        
        # 检查追踪止损
        if current_stage > 0:
            prev_stage = self.exit_stages[current_stage - 1]
            return self._check_trailing_stop(symbol, current_price, entry_price, atr, prev_stage['atr_mult'])
        
        return None
    
    def _check_trailing_stop(self, symbol, current_price, entry_price, atr, atr_mult):
        """检查追踪止损"""
        # 这里简化处理，实际应该记录最高价/最低价
        # 返回追踪止损价格
        return None
    
    def get_trailing_stop_price(self, symbol, side, highest_price, lowest_price, atr, atr_mult=0.8):
        """
        计算追踪止损价格
        
        Args:
            highest_price: 持仓期间最高价（多头）
            lowest_price: 持仓期间最低价（空头）
            atr: ATR值
            atr_mult: ATR倍数（最终阶段用0.8）
        """
        if side == 'LONG':
            # 多头：从最高价回撤 atr_mult * ATR
            stop_price = highest_price - (atr * atr_mult)
        else:
            # 空头：从最低价反弹 atr_mult * ATR
            stop_price = lowest_price + (atr * atr_mult)
        
        return stop_price
    
    def clear_position(self, symbol):
        """平仓后清除记录"""
        if symbol in self.position_stages:
            del self.position_stages[symbol]
            logging.info(f"📝 Cleared exit stages for {symbol}")
    
    def get_exit_summary(self, symbol):
        """获取退出阶段摘要"""
        if symbol not in self.position_stages:
            return "No active position"
        
        stage = self.position_stages[symbol]
        if stage >= len(self.exit_stages):
            return "Final trailing stage (0.8x ATR)"
        
        next_stage = self.exit_stages[stage]
        return f"Stage {stage + 1}: Exit {next_stage['exit_pct']:.0%} at {next_stage['pnl_pct']:.0f}% profit"

if __name__ == "__main__":
    # 测试
    em = ExitManager()
    
    symbol = "ETH/USDT"
    position_size = 0.5
    entry_price = 100
    atr = 2
    
    # 模拟盈利2.5%
    current_price = 102.5
    pnl_pct = 2.5
    
    result = em.check_exit(symbol, pnl_pct, position_size, entry_price, current_price, atr)
    if result:
        print(f"Exit {result['exit_pct']:.0%} at stage {result['stage']}")
    
    # 模拟盈利7%
    current_price = 107
    pnl_pct = 7.0
    remaining_size = position_size * 0.8  # 已经平了20%
    
    result = em.check_exit(symbol, pnl_pct, remaining_size, entry_price, current_price, atr)
    if result:
        print(f"Exit {result['exit_pct']:.0%} at stage {result['stage']}")
