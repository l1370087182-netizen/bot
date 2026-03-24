"""
Position Sizer - 仓位管理器
核心原则: 单笔风险固定为账户的2%
"""
import logging

class PositionSizer:
    """
    仓位计算器 - 基于风险金额反推仓位大小
    
    公式: 仓位大小 = 风险金额 / 止损距离
    """
    
    def __init__(self, risk_per_trade=0.02):
        """
        Args:
            risk_per_trade: 单笔风险比例 (默认2%)
        """
        self.risk_per_trade = risk_per_trade
        logging.info(f"📊 PositionSizer initialized: {risk_per_trade:.1%} risk per trade")
    
    def calculate_position_size(self, balance, entry_price, stop_loss_price, leverage=10):
        """
        计算仓位大小
        
        Args:
            balance: 账户总余额
            entry_price: 入场价格
            stop_loss_price: 止损价格
            leverage: 杠杆倍数
            
        Returns:
            dict: 仓位信息
        """
        # 1. 计算风险金额 (账户的2%)
        risk_amount = balance * self.risk_per_trade
        
        # 2. 计算止损距离 (%)
        stop_distance = abs(entry_price - stop_loss_price) / entry_price
        
        if stop_distance == 0:
            logging.error("❌ Stop loss distance cannot be zero")
            return None
        
        # 3. 计算名义仓位价值 (风险金额 / 止损距离)
        notional_value = risk_amount / stop_distance
        
        # 4. 计算实际需要的保证金
        margin_required = notional_value / leverage
        
        # 5. 检查保证金是否超过账户20%
        if margin_required > balance * 0.2:
            logging.warning(f"⚠️ Margin {margin_required:.2f} > 20% of balance, reducing size")
            margin_required = balance * 0.2
            notional_value = margin_required * leverage
        
        # 6. 计算币的数量
        position_size = notional_value / entry_price
        
        return {
            'position_size': position_size,      # 币的数量
            'notional_value': notional_value,    # 名义价值
            'margin_required': margin_required,  # 所需保证金
            'risk_amount': risk_amount,          # 风险金额
            'stop_distance': stop_distance,      # 止损距离
            'risk_reward_1r': stop_distance,     # 1R = 止损距离
            'leverage': leverage
        }
    
    def calculate_stop_loss(self, entry_price, side, atr, atr_multiplier=2.0):
        """
        基于ATR计算止损价格
        
        Args:
            entry_price: 入场价格
            side: 'LONG' or 'SHORT'
            atr: ATR值
            atr_multiplier: ATR倍数
            
        Returns:
            float: 止损价格
        """
        stop_distance = atr * atr_multiplier
        
        if side == 'LONG':
            stop_price = entry_price - stop_distance
        else:
            stop_price = entry_price + stop_distance
        
        return stop_price
    
    def validate_position(self, position_info, balance):
        """
        验证仓位是否合理
        
        Returns:
            bool: 是否通过验证
        """
        if not position_info:
            return False
        
        checks = {
            'risk_amount <= 2% balance': position_info['risk_amount'] <= balance * 0.02,
            'margin <= 20% balance': position_info['margin_required'] <= balance * 0.2,
            'position_size > 0': position_info['position_size'] > 0,
            'stop_distance > 0': position_info['stop_distance'] > 0
        }
        
        failed = [k for k, v in checks.items() if not v]
        if failed:
            logging.error(f"❌ Position validation failed: {failed}")
            return False
        
        return True

if __name__ == "__main__":
    # 测试
    sizer = PositionSizer()
    
    balance = 1000
    entry = 100
    stop = 95  # 5% 止损
    
    result = sizer.calculate_position_size(balance, entry, stop)
    print(f"Risk Amount: {result['risk_amount']:.2f} USDT")
    print(f"Position Size: {result['position_size']:.4f} coins")
    print(f"Notional Value: {result['notional_value']:.2f} USDT")
    print(f"Margin Required: {result['margin_required']:.2f} USDT")
