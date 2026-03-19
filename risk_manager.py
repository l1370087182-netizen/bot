import datetime

class RiskManager:
    def __init__(self, max_daily_loss_pct, stop_loss_pct, take_profit_pct=0.04):
        self.max_daily_loss_pct = max_daily_loss_pct
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.daily_start_balance = None
        self.last_reset_date = None

    def check_daily_limit(self, current_balance):
        """
        Check if the daily loss limit has been hit.
        Returns True if trading is allowed, False if halted.
        """
        today = datetime.date.today()
        
        # Reset daily baseline if it's a new day
        if self.last_reset_date != today:
            self.daily_start_balance = current_balance
            self.last_reset_date = today
            print(f"RiskManager: New day detected. Baseline balance: {self.daily_start_balance}")

        if self.daily_start_balance == 0:
            return False

        current_loss_pct = (self.daily_start_balance - current_balance) / self.daily_start_balance
        
        if current_loss_pct >= self.max_daily_loss_pct:
            print(f"CRITICAL: Daily loss limit hit ({current_loss_pct*100:.2f}%). Trading halted.")
            return False
            
        return True

    def calculate_stop_loss_price(self, side, entry_price):
        """Calculate stop loss price"""
        if side == 'buy':
            return entry_price * (1 - self.stop_loss_pct)
        else:
            return entry_price * (1 + self.stop_loss_pct)

    def calculate_take_profit_price(self, side, entry_price):
        """Calculate take profit price"""
        if side == 'buy':
            return entry_price * (1 + self.take_profit_pct)
        else:
            return entry_price * (1 - self.take_profit_pct)

    def validate_slippage(self, expected_price, actual_price, max_slippage):
        """Check if slippage is within acceptable bounds"""
        slippage = abs(actual_price - expected_price) / expected_price
        return slippage <= max_slippage
    
    def calculate_trailing_stop(self, entry_price, current_price, max_price, side, trailing_pct=0.015):
        """
        计算移动止损价格
        
        Args:
            entry_price: 入场价格
            current_price: 当前价格
            max_price: 持仓期间达到的最高/最低价格（做多是最高，做空是最低）
            side: 'LONG' 或 'SHORT'
            trailing_pct: 回撤百分比（默认1.5%）
        """
        if side == 'LONG':
            # 做多：从最高点回撤 trailing_pct 时止损
            trigger_price = max_price * (1 - trailing_pct)
            return trigger_price
        else:  # SHORT
            # 做空：从最低点反弹 trailing_pct 时止损
            trigger_price = max_price * (1 + trailing_pct)
            return trigger_price
    
    def should_trigger_trailing_stop(self, current_price, max_price, side, trailing_pct=0.015):
        """
        判断是否触发移动止损
        
        Returns:
            bool: 是否触发止损
        """
        if side == 'LONG':
            # 做多：当前价格是否从最高点回撤超过 trailing_pct
            drawdown = (max_price - current_price) / max_price
            return drawdown >= trailing_pct
        else:  # SHORT
            # 做空：当前价格是否从最低点反弹超过 trailing_pct
            drawup = (current_price - max_price) / max_price
            return drawup >= trailing_pct
