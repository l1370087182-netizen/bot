"""
Account Guardian - 账户级硬保护系统
核心原则: 铁壁总开关，保护整体账户
"""
import logging
import time
from datetime import datetime, timedelta

class AccountGuardian:
    """
    账户守护者 - 三层硬保护
    
    保护层级:
    1. 日亏损 5-10% → 全部平仓 + 24小时禁止交易
    2. 回撤 7-8% → 保命模式（5x杠杆，HALF仓位，禁止加仓）
    3. 回撤 10-12% → 永久锁死（需手动解锁）
    """
    
    def __init__(self, daily_loss_limit=0.05, drawdown_limit_1=0.07, drawdown_limit_2=0.10):
        """
        Args:
            daily_loss_limit: 日亏损限制 (5%)
            drawdown_limit_1: 一级回撤限制 (7%)
            drawdown_limit_2: 二级回撤限制 (10%)
        """
        self.daily_loss_limit = daily_loss_limit
        self.drawdown_limit_1 = drawdown_limit_1
        self.drawdown_limit_2 = drawdown_limit_2
        
        self.daily_start_balance = None
        self.last_reset_date = None
        self.peak_balance = 0
        self.current_drawdown = 0
        
        # 状态
        self.is_locked = False
        self.lock_reason = None
        self.lock_until = 0
        self.survival_mode = False
        
        logging.info(f"🛡️ AccountGuardian initialized: "
                    f"DailyLoss {daily_loss_limit:.1%}, "
                    f"DD1 {drawdown_limit_1:.1%}, "
                    f"DD2 {drawdown_limit_2:.1%}")
    
    def update_balance(self, current_balance):
        """
        更新余额并检查保护条件
        
        Returns:
            dict: 保护状态
        """
        today = datetime.now().date()
        
        # 初始化或重置日统计
        if self.last_reset_date != today:
            self.daily_start_balance = current_balance
            self.last_reset_date = today
            logging.info(f"📅 New day: Daily baseline balance: {self.daily_start_balance:.2f}")
        
        # 更新峰值
        if current_balance > self.peak_balance:
            self.peak_balance = current_balance
        
        # 计算回撤
        if self.peak_balance > 0:
            self.current_drawdown = (self.peak_balance - current_balance) / self.peak_balance
        
        # 检查保护条件
        status = self._check_protection(current_balance)
        
        return status
    
    def _check_protection(self, current_balance):
        """检查并执行保护"""
        status = {
            'can_trade': True,
            'max_leverage': 10,
            'position_strength': 'FULL',
            'allow_pyramiding': True,
            'reason': None
        }
        
        # 检查是否被锁死
        if self.is_locked:
            if self.lock_reason == 'CRITICAL_DRAWDOWN':
                status['can_trade'] = False
                status['reason'] = f"CRITICAL: Account locked due to {self.lock_reason}"
                return status
            elif time.time() < self.lock_until:
                status['can_trade'] = False
                status['reason'] = f"Locked until {datetime.fromtimestamp(self.lock_until)}"
                return status
            else:
                # 解锁
                self.is_locked = False
                self.lock_reason = None
                logging.info("🔓 Account auto-unlocked")
        
        # 检查日亏损
        if self.daily_start_balance and self.daily_start_balance > 0:
            daily_loss = (self.daily_start_balance - current_balance) / self.daily_start_balance
            
            if daily_loss >= self.daily_loss_limit:
                self._trigger_daily_loss_protection()
                status['can_trade'] = False
                status['reason'] = f"Daily loss limit hit: {daily_loss:.2%}"
                return status
        
        # 检查回撤层级
        if self.current_drawdown >= self.drawdown_limit_2:
            # 三级保护：永久锁死
            self._trigger_critical_drawdown()
            status['can_trade'] = False
            status['reason'] = f"CRITICAL DRAWDOWN: {self.current_drawdown:.2%}"
            
        elif self.current_drawdown >= self.drawdown_limit_1:
            # 二级保护：保命模式
            self._trigger_survival_mode()
            status['max_leverage'] = 5
            status['position_strength'] = 'HALF'
            status['allow_pyramiding'] = False
            status['reason'] = f"Survival mode: Drawdown {self.current_drawdown:.2%}"
        
        return status
    
    def _trigger_daily_loss_protection(self):
        """触发日亏损保护"""
        self.is_locked = True
        self.lock_until = time.time() + 86400  # 24小时
        self.lock_reason = 'DAILY_LOSS_LIMIT'
        
        logging.critical(f"🚨🚨🚨 DAILY LOSS PROTECTION TRIGGERED 🚨🚨🚨")
        logging.critical(f"   Daily loss limit: {self.daily_loss_limit:.1%}")
        logging.critical(f"   Locked for 24 hours")
        
        # 这里应该触发全部平仓
        return True
    
    def _trigger_survival_mode(self):
        """触发保命模式"""
        if not self.survival_mode:
            self.survival_mode = True
            logging.warning(f"⚠️⚠️⚠️ SURVIVAL MODE ACTIVATED ⚠️⚠️⚠️")
            logging.warning(f"   Drawdown: {self.current_drawdown:.2%}")
            logging.warning(f"   Max leverage: 5x")
            logging.warning(f"   Position strength: HALF")
            logging.warning(f"   Pyramiding: DISABLED")
    
    def _trigger_critical_drawdown(self):
        """触发永久锁死"""
        self.is_locked = True
        self.lock_reason = 'CRITICAL_DRAWDOWN'
        
        logging.critical(f"🔒🔒🔒 ACCOUNT PERMANENTLY LOCKED 🔒🔒🔒")
        logging.critical(f"   Critical drawdown: {self.current_drawdown:.2%}")
        logging.critical(f"   Manual unlock required")
        
        # 发送紧急通知
        return True
    
    def manual_unlock(self, password=None):
        """手动解锁（需要密码或确认）"""
        if self.lock_reason == 'CRITICAL_DRAWDOWN':
            # 这里应该验证密码
            self.is_locked = False
            self.lock_reason = None
            self.survival_mode = False
            self.current_drawdown = 0
            self.peak_balance = 0
            
            logging.info("🔓 Account manually unlocked")
            return True
        return False
    
    def get_status(self):
        """获取当前保护状态"""
        return {
            'is_locked': self.is_locked,
            'lock_reason': self.lock_reason,
            'survival_mode': self.survival_mode,
            'current_drawdown': self.current_drawdown,
            'peak_balance': self.peak_balance,
            'daily_start_balance': self.daily_start_balance
        }

if __name__ == "__main__":
    # 测试
    guardian = AccountGuardian()
    
    # 模拟余额变化
    balances = [1000, 980, 950, 930, 900, 880]
    
    for balance in balances:
        status = guardian.update_balance(balance)
        print(f"Balance: {balance}, Can trade: {status['can_trade']}, Reason: {status.get('reason')}")
