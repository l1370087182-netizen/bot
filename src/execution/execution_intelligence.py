"""
Execution Intelligence - 智能执行算法模块
优化下单策略以降低滑点和交易成本
"""
import logging
import time
from enum import Enum

class OrderType(Enum):
    MARKET = "market"           # 市价单 - 立即成交
    LIMIT = "limit"             # 限价单 - 指定价格
    IOC = "ioc"                 # 立即成交或取消
    FOK = "fok"                 # 全部成交或取消

class ExecutionStrategy:
    """
    智能执行策略
    
    针对小资金优化的执行逻辑：
    1. 优先使用限价单 (Maker) 获取手续费返还
    2. 如果未成交，动态调整价格追单
    3. 监控滑点，如果过大则暂停执行
    """
    
    def __init__(self, exchange, max_slippage_pct=0.1, max_wait_seconds=10):
        self.exchange = exchange
        self.max_slippage_pct = max_slippage_pct  # 最大允许滑点 0.1%
        self.max_wait_seconds = max_wait_seconds   # 最大等待时间
        
    def get_orderbook_depth(self, symbol):
        """获取订单簿深度"""
        try:
            orderbook = self.exchange.fetch_order_book(symbol, limit=20)
            bids = orderbook['bids']  # [price, amount]
            asks = orderbook['asks']
            
            # 计算买卖盘深度
            bid_depth = sum([b[1] for b in bids])
            ask_depth = sum([a[1] for a in asks])
            
            # 计算买卖价差
            best_bid = bids[0][0] if bids else 0
            best_ask = asks[0][0] if asks else 0
            spread = (best_ask - best_bid) / best_bid if best_bid > 0 else 0
            
            return {
                'best_bid': best_bid,
                'best_ask': best_ask,
                'spread': spread,
                'bid_depth': bid_depth,
                'ask_depth': ask_depth,
                'liquid': spread < 0.001 and bid_depth > 10 and ask_depth > 10
            }
        except Exception as e:
            logging.error(f"获取订单簿深度失败 {symbol}: {e}")
            return None
    
    def calculate_impact_price(self, symbol, side, amount, depth):
        """计算考虑市场冲击的价格"""
        if not depth:
            return None
        
        best_price = depth['best_ask'] if side == 'buy' else depth['best_bid']
        
        # 小资金 (< 100 USDT) 市场冲击可以忽略
        # 但仍需考虑滑点
        if depth['liquid']:
            # 流动性好，使用最优价 + 微小滑点
            slippage = 0.0005  # 0.05%
        else:
            # 流动性差，增加滑点
            slippage = 0.001   # 0.1%
        
        if side == 'buy':
            impact_price = best_price * (1 + slippage)
        else:
            impact_price = best_price * (1 - slippage)
        
        return impact_price
    
    def execute_with_intelligence(self, symbol, side, amount, leverage, position_side, notional_value=0):
        """
        智能执行交易

        策略：
        1. 首先尝试限价单 (Maker) - 获取手续费返还
        2. 如果 3 秒未成交，改为 IOC 限价单
        3. 如果仍未成交，使用市价单
        """
        try:
            # 获取市场深度
            depth = self.get_orderbook_depth(symbol)
            if not depth:
                logging.warning(f"无法获取 {symbol} 市场深度，使用市价单")
                return self._execute_market(symbol, side, amount, leverage, position_side)

            # 检查滑点是否可接受（小资金跳过检查）
            if depth['spread'] > self.max_slippage_pct / 100 and notional_value >= 50:
                logging.warning(f"{symbol} 价差过大: {depth['spread']:.4%}，暂停执行")
                return None
            
            # 计算目标价格
            target_price = self.calculate_impact_price(symbol, side, amount, depth)
            
            logging.info(f"📊 {symbol} 市场深度: 买{depth['bid_depth']:.2f}/卖{depth['ask_depth']:.2f}, "
                        f"价差: {depth['spread']:.4%}, 目标价: {target_price}")
            
            # 阶段 1: 尝试限价单 (Maker)
            order = self._execute_limit(symbol, side, amount, target_price, leverage, position_side)
            if order and order.get('filled', 0) > 0:
                logging.info(f"✅ {symbol} 限价单成交 (Maker)")
                return order
            
            # 阶段 2: 等待 3 秒后检查
            time.sleep(3)
            
            # 检查是否部分成交
            if order and order.get('id'):
                try:
                    order_status = self.exchange.fetch_order(order['id'], symbol)
                    if order_status.get('filled', 0) > 0:
                        logging.info(f"✅ {symbol} 限价单部分成交，取消剩余")
                        self.exchange.cancel_order(order['id'], symbol)
                        return order_status
                except:
                    pass
            
            # 阶段 3: 使用 IOC 限价单
            logging.info(f"⏱️ {symbol} 限价单未成交，改用 IOC")
            order = self._execute_ioc(symbol, side, amount, target_price, leverage, position_side)
            if order and order.get('filled', 0) > 0:
                return order
            
            # 阶段 4: 使用市价单
            logging.info(f"🚀 {symbol} IOC 未成交，使用市价单")
            return self._execute_market(symbol, side, amount, leverage, position_side)
            
        except Exception as e:
            logging.error(f"智能执行失败 {symbol}: {e}")
            # 出错时回退到市价单
            return self._execute_market(symbol, side, amount, leverage, position_side)
    
    def _execute_limit(self, symbol, side, amount, price, leverage, position_side):
        """执行限价单"""
        try:
            # 精度处理
            amount = float(self.exchange.amount_to_precision(symbol, amount))
            price = float(self.exchange.price_to_precision(symbol, price))
            
            order = self.exchange.create_limit_order(
                symbol, side, amount, price,
                params={
                    'positionSide': position_side,
                    'timeInForce': 'GTC'  # Good Till Cancel
                }
            )
            return order
        except Exception as e:
            logging.error(f"限价单失败: {e}")
            return None
    
    def _execute_ioc(self, symbol, side, amount, price, leverage, position_side):
        """执行 IOC 限价单"""
        try:
            amount = float(self.exchange.amount_to_precision(symbol, amount))
            price = float(self.exchange.price_to_precision(symbol, price))
            
            order = self.exchange.create_limit_order(
                symbol, side, amount, price,
                params={
                    'positionSide': position_side,
                    'timeInForce': 'IOC'  # Immediate Or Cancel
                }
            )
            return order
        except Exception as e:
            logging.error(f"IOC 单失败: {e}")
            return None
    
    def _execute_market(self, symbol, side, amount, leverage, position_side):
        """执行市价单 (回退方案)"""
        try:
            amount = float(self.exchange.amount_to_precision(symbol, amount))
            
            order = self.exchange.create_market_order(
                symbol, side, amount,
                params={'positionSide': position_side}
            )
            
            # 记录实际滑点
            if order.get('trades'):
                avg_price = sum(t['price'] * t['amount'] for t in order['trades']) / sum(t['amount'] for t in order['trades'])
                logging.info(f"📈 {symbol} 市价单成交均价: {avg_price}")
            
            return order
        except Exception as e:
            logging.error(f"市价单失败: {e}")
            return None


class TWAPExecutor:
    """
    TWAP (Time Weighted Average Price) 拆单执行器
    
    针对小资金的简化 TWAP：
    - 如果单笔金额 < 50 USDT，不拆单
    - 如果单笔金额 >= 50 USDT，拆成 2-3 份
    """
    
    def __init__(self, exchange, num_slices=3, interval_seconds=5):
        self.exchange = exchange
        self.num_slices = num_slices
        self.interval_seconds = interval_seconds
        self.smart_exec = ExecutionStrategy(exchange)
    
    def execute(self, symbol, side, total_amount, leverage, position_side, notional_value):
        """
        执行 TWAP 拆单
        
        Args:
            notional_value: 名义价值 (USDT)
        """
        # 小资金不拆单
        if notional_value < 50:
            logging.info(f"💰 {symbol} 金额 {notional_value:.2f} USDT < 50，不拆单")
            return self.smart_exec.execute_with_intelligence(
                symbol, side, total_amount, leverage, position_side, notional_value
            )
        
        # 拆单执行
        slice_amount = total_amount / self.num_slices
        results = []
        
        logging.info(f"📦 {symbol} TWAP 拆单: {self.num_slices} 份，每份 {slice_amount:.4f}")
        
        for i in range(self.num_slices):
            logging.info(f"📤 {symbol} TWAP 第 {i+1}/{self.num_slices} 份")

            result = self.smart_exec.execute_with_intelligence(
                symbol, side, slice_amount, leverage, position_side, notional_value
            )
            
            if result:
                results.append(result)
            
            # 最后一份不等待
            if i < self.num_slices - 1:
                time.sleep(self.interval_seconds)
        
        # 合并结果
        if results:
            return {
                'slices': results,
                'total_filled': sum(r.get('filled', 0) for r in results),
                'avg_price': sum(r.get('price', 0) * r.get('filled', 0) for r in results) / 
                           sum(r.get('filled', 0) for r in results) if sum(r.get('filled', 0) for r in results) > 0 else 0
            }
        
        return None
