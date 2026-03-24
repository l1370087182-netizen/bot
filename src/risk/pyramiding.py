"""
Pyramiding - 金字塔加仓系统 v2.0
核心原则: 盈利后逐步加仓，最多2级
"""
import logging
import time

class PyramidingManager:
    """
    金字塔加仓管理器 v2.0
    
    加仓规则:
    - 盈利 3% → 加 30% 原仓位
    - 盈利 6% → 再加 20% 原仓位
    - 最多加 2 次
    """
    
    def __init__(self):
        self.additions = {}
        self.max_additions = 2  # 最多2级
        self.addition_levels = [
            {'profit_pct': 0.03, 'size_pct': 0.30},   # 盈利3%，加30%
            {'profit_pct': 0.06, 'size_pct': 0.20},   # 盈利6%，加20%
        ]
        logging.info("📈 PyramidingManager initialized (max 2 levels)")
    
    def check_addition(self, symbol, current_profit_pct, base_position_size):
        """
        检查是否应该加仓
        
        Args:
            symbol: 交易对
            current_profit_pct: 当前盈利百分比（原生，非杠杆）
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
        if current_profit_pct >= level['profit_pct']:
            addition_size = base_position_size * level['size_pct']
            
            addition_info = {
                'level': next_level_idx + 1,
                'trigger_profit': level['profit_pct'],
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
    
    def get_addition_count(self, symbol):
        """获取已加仓次数"""
        if symbol not in self.additions:
            return 0
        return len(self.additions[symbol])
    
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
        return f"{len(adds)}/2 additions, total added: {total_added:.4f}"
