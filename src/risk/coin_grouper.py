"""
Coin Grouper - 币种分组管理器
核心原则: 同类币别扎堆，防止系统性风险
"""
import logging

class CoinGrouper:
    """
    币种分组管理器
    
    分组规则:
    - MEME: DOGE, SHIB, PEPE 等 meme币
    - PLATFORM: BNB, SOL, ETH 等平台币
    - DEFI: UNI, AAVE, COMP 等 DeFi
    - LAYER1: BTC, ETH, SOL, ADA 等公链
    - PAYMENT: XRP, LTC, BCH 等支付币
    """
    
    def __init__(self):
        self.groups = {
            'MEME': {
                'coins': ['DOGE/USDT:USDT', 'SHIB/USDT:USDT', 'PEPE/USDT:USDT', 'FLOKI/USDT:USDT'],
                'max_positions': 1,
                'correlation': 'HIGH'  # 高相关性
            },
            'PLATFORM': {
                'coins': ['BNB/USDT:USDT', 'SOL/USDT:USDT', 'ETH/USDT:USDT', 'AVAX/USDT:USDT', 'DOT/USDT:USDT'],
                'max_positions': 2,
                'correlation': 'MEDIUM'
            },
            'DEFI': {
                'coins': ['UNI/USDT:USDT', 'AAVE/USDT:USDT', 'COMP/USDT:USDT', 'MKR/USDT:USDT', 'CRV/USDT:USDT'],
                'max_positions': 1,
                'correlation': 'HIGH'
            },
            'LAYER1': {
                'coins': ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'ADA/USDT:USDT', 'AVAX/USDT:USDT', 'DOT/USDT:USDT', 'NEAR/USDT:USDT', 'APT/USDT:USDT'],
                'max_positions': 2,
                'correlation': 'MEDIUM'
            },
            'PAYMENT': {
                'coins': ['XRP/USDT:USDT', 'LTC/USDT:USDT', 'BCH/USDT:USDT', 'XLM/USDT:USDT'],
                'max_positions': 1,
                'correlation': 'MEDIUM'
            },
            'AI': {
                'coins': ['FET/USDT:USDT', 'AGIX/USDT:USDT', 'OCEAN/USDT:USDT', 'RLC/USDT:USDT'],
                'max_positions': 1,
                'correlation': 'HIGH'
            }
        }
        
        self.active_positions = {}  # {group: [symbols]}
        logging.info("📊 CoinGrouper initialized")
    
    def get_coin_group(self, symbol):
        """获取币种所属分组"""
        for group_name, group_data in self.groups.items():
            if symbol in group_data['coins']:
                return group_name
        return 'OTHERS'
    
    def can_open_position(self, symbol, current_positions):
        """
        检查是否可以开新仓
        
        Args:
            symbol: 要开仓的币种
            current_positions: 当前所有持仓列表
            
        Returns:
            bool: 是否允许开仓
        """
        group = self.get_coin_group(symbol)
        
        if group == 'OTHERS':
            return True  # 其他币种不限制
        
        group_config = self.groups[group]
        max_allowed = group_config['max_positions']
        
        # 统计该组当前持仓
        group_positions = [p for p in current_positions if self.get_coin_group(p) == group]
        current_count = len(group_positions)
        
        if current_count >= max_allowed:
            logging.warning(f"⚠️ {group} group limit reached: {current_count}/{max_allowed}")
            return False
        
        return True
    
    def get_group_exposure(self, current_positions):
        """获取各组暴露情况"""
        exposure = {}
        for group in self.groups:
            group_positions = [p for p in current_positions if self.get_coin_group(p) == group]
            exposure[group] = {
                'count': len(group_positions),
                'max': self.groups[group]['max_positions'],
                'positions': group_positions
            }
        return exposure
    
    def get_diversification_score(self, current_positions):
        """
        计算分散化评分
        
        Returns:
            float: 0-100分
        """
        if not current_positions:
            return 100
        
        groups_used = set()
        for pos in current_positions:
            groups_used.add(self.get_coin_group(pos))
        
        # 使用的分组越多，分数越高
        score = min(100, len(groups_used) * 20)
        return score
    
    def suggest_alternative(self, symbol, current_positions, available_symbols):
        """
        如果某个币不能开仓，建议替代币种
        
        Returns:
            str or None: 建议的替代币种
        """
        target_group = self.get_coin_group(symbol)
        
        # 找不同组的相似币种
        for alt_symbol in available_symbols:
            if alt_symbol in current_positions:
                continue
            
            alt_group = self.get_coin_group(alt_symbol)
            if alt_group != target_group:
                if self.can_open_position(alt_symbol, current_positions):
                    return alt_symbol
        
        return None

if __name__ == "__main__":
    # 测试
    grouper = CoinGrouper()
    
    print("DOGE group:", grouper.get_coin_group('DOGE/USDT:USDT'))
    print("ETH group:", grouper.get_coin_group('ETH/USDT:USDT'))
    
    current = ['DOGE/USDT:USDT']
    can_open = grouper.can_open_position('SHIB/USDT:USDT', current)
    print(f"Can open SHIB: {can_open}")  # 应该为False，同属MEME组
    
    exposure = grouper.get_group_exposure(current)
    print(f"Exposure: {exposure}")
