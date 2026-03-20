"""
Pyramiding - 金字塔加仓系统
核心原则: 盈利后逐步加仓，让利润奔跑
"""
import logging
import time

class PyramidingManager:
    """
    金字塔加仓管理器
    
    加仓规则:
    - 盈利 2% → 加 30-50% 原仓位
    - 盈利 5-6% → 再加 20-40% 原仓位
    - 最多加 2-3 次
    - 总仓位控制在账户 4-6% 以内
    """
    
    def __init__(self):
        self.additions = {}  # {symbol: [addition1, addition2, ...]}
        self.max_additions = 3
        self.addition_levels = [
            {'pnl_pct': 2.0, 'size_pct': 0.40},   # 盈利2%，加40%
            {'pnl_pct': 5.0, 'size_pct': 0.30},   # 盈利5%，再加30%
            {'pnl_pct': 8.0, 'size_pct': 0.20},   # 盈利8%，再加20%
        ]
        logging.info("📈 PyramidingManager initialized")
    
    def check_addition(self, symbol, current_pnl_pct, base_position_size):
        """
        检查是否应该加仓
        
        Args:
            symbol: 交易对
            current_pnl_pct: 当前盈利百分比
            base_position_size: 基础仓位大小
            
        Returns:
            dict or None: 加仓信息
        """
        if symbol not in self.additions:
            self.additions[symbol] = []
        
        current_additions = self.additions[symbol]
        
        # 检查是否超过最大加仓次数
        if len(current_additions) >= self.max_additions:
            return None
        
        # 获取下一个加仓级别
        next_level_idx = len(current_additions)
        if next_level_idx >= len(self.addition_levels):
            return None
        
        level = self.addition_levels[next_level_idx]
        
        # 检查是否达到加仓条件
        if current_pnl_pct >= level['pnl_pct']:
            addition_size = base_position_size * level['size_pct']
            
            addition_info = {
                'level': next_level_idx + 1,
                'trigger_pnl': level['pnl_pct'],
                'size_pct': level['size_pct'],
                'addition_size': addition_size,
                'timestamp': time.time()
            }
            
            self.additions[symbol].append(addition_info)
            
            logging.info(f"🎯 Pyramiding signal for {symbol}: "
                        f"Level {addition_info['level']} | "
                        f"Add {addition_info['size_pct']:.0%} | "
                        f"Size: {addition_size:.4f}")
            
            return addition_info
        
        return None
    
    def get_total_position_size(self, symbol, base_size):
        """
        获取总仓位大小（基础+所有加仓）
        """
        if symbol not in self.additions:
            return base_size
        
        total = base_size
        for add in self.additions[symbol]:
            total += add['addition_size']
        
        return total
    
    def get_adjusted_stop_loss(self, symbol, entry_price, current_stop, current_pnl_pct):
        """
        根据盈利情况调整止损（抬高到保本或盈利）
        """
        # 盈利 2% 以上 → 止损移到保本
        if current_pnl_pct >= 2.0:
            breakeven = entry_price * 1.005  # 保本价 + 0.5% 缓冲
            if current_stop < breakeven:
                logging.info(f"🛡️ {symbol} Stop moved to breakeven: {current_stop:.4f} → {breakeven:.4f}")
                return breakeven
        
        # 盈利 5% 以上 → 锁定 3% 利润
        if current_pnl_pct >= 5.0:
            lock_profit_price = entry_price * 1.03
            if current_stop < lock_profit_price:
                logging.info(f"🔒 {symbol} Stop locked at 3% profit: {lock_profit_price:.4f}")
                return lock_profit_price
        
        # 盈利 10% 以上 → 锁定 7% 利润
        if current_pnl_pct >= 10.0:
            lock_profit_price = entry_price * 1.07
            if current_stop < lock_profit_price:
                logging.info(f"🔒 {symbol} Stop locked at 7% profit: {lock_profit_price:.4f}")
                return lock_profit_price
        
        return current_stop
    
    def clear_additions(self, symbol):
        """平仓后清除加仓记录"""
        if symbol in self.additions:
            del self.additions[symbol]
            logging.info(f"📝 Cleared pyramiding history for {symbol}")
    
    def get_addition_summary(self, symbol):
        """获取加仓摘要"""
        if symbol not in self.additions or not self.additions[symbol]:
            return "No additions"
        
        adds = self.additions[symbol]
        total_added = sum([a['addition_size'] for a in adds])
        return f"{len(adds)} additions, total added: {total_added:.4f}"

if __name__ == "__main__":
    # 测试
    pm = PyramidingManager()
    
    symbol = "ETH/USDT"
    base_size = 0.1
    
    # 模拟盈利2%
    result = pm.check_addition(symbol, 2.5, base_size)
    if result:
        print(f"Add {result['size_pct']:.0%} at level {result['level']}")
    
    # 模拟盈利5%
    result = pm.check_addition(symbol, 5.5, base_size)
    if result:
        print(f"Add {result['size_pct']:.0%} at level {result['level']}")
    
    total = pm.get_total_position_size(symbol, base_size)
    print(f"Total position: {total:.4f}")
