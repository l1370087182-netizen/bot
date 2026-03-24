"""
Exit Manager - R-based 止盈止损管理器
核心原则: 2R平20%, 3R平50%, 剩余30%用ATR trailing stop
"""
import logging

class ExitManager:
    """
    智能退出管理器 v2.0
    
    止盈规则:
    - 利润达到2R时，平仓20%
    - 利润达到3R时，再平仓50%（累计平70%）
    - 剩余30%使用ATR trailing stop (2.2x)
    """
    
    def __init__(self):
        self.r_levels = [
            {'r_multiple': 2.0, 'exit_pct': 0.20},   # 2R平20%
            {'r_multiple': 3.0, 'exit_pct': 0.50},   # 3R平50%（累计70%）
        ]
        self.trailing_atr_mult = 2.2  # ATR倍数
        self.position_exits = {}  # {symbol: [已执行的R级别]}
        logging.info("🚪 ExitManager initialized (R-based)")
    
    def check_exit(self, symbol, current_r_multiple, position_size, entry_price, current_price, atr):
        """
        检查是否应该部分或全部平仓
        
        Returns:
            dict or None: 退出指令
        """
        if symbol not in self.position_exits:
            self.position_exits[symbol] = []
        
        executed_exits = self.position_exits[symbol]
        
        # 检查R级别止盈
        for level in self.r_levels:
            r_mult = level['r_multiple']
            if current_r_multiple >= r_mult and r_mult not in executed_exits:
                exit_size = position_size * level['exit_pct']
                self.position_exits[symbol].append(r_mult)
                
                logging.info(f"🎯 R-based Exit: {symbol} | {r_mult}R | Exit {level['exit_pct']:.0%}")
                
                return {
                    'action': 'PARTIAL_EXIT',
                    'r_multiple': r_mult,
                    'exit_size': exit_size,
                    'exit_pct': level['exit_pct'],
                    'remaining_size': position_size - exit_size
                }
        
        # 检查ATR trailing stop（剩余仓位）
        if len(executed_exits) >= len(self.r_levels):
            return self._check_trailing_stop(symbol, current_price, entry_price, atr)
        
        return None
    
    def _check_trailing_stop(self, symbol, current_price, entry_price, atr):
        """检查ATR追踪止损"""
        # 简化实现，实际应在bot.py中根据持仓方向判断
        return None
    
    def get_trailing_stop_price(self, side, highest_price, lowest_price, atr):
        """
        计算ATR追踪止损价格
        
        Args:
            side: 'LONG' or 'SHORT'
            highest_price: 持仓期间最高价
            lowest_price: 持仓期间最低价
            atr: ATR值
        """
        if side == 'LONG':
            stop_price = highest_price - (atr * self.trailing_atr_mult)
        else:
            stop_price = lowest_price + (atr * self.trailing_atr_mult)
        
        return stop_price
    
    def clear_position(self, symbol):
        """平仓后清除记录"""
        if symbol in self.position_exits:
            del self.position_exits[symbol]
            logging.info(f"📝 Cleared exit records for {symbol}")
    
    def get_exit_summary(self, symbol):
        """获取退出摘要"""
        if symbol not in self.position_exits:
            return "No exits executed"
        
        executed = self.position_exits[symbol]
        total_exited = sum([l['exit_pct'] for l in self.r_levels if l['r_multiple'] in executed])
        
        if total_exited >= 0.7:
            return f"Final trailing stage (ATR {self.trailing_atr_mult}x)"
        
        return f"Exited {total_exited:.0%}, waiting for next R level"
