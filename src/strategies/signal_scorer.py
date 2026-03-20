"""
Signal Quality Scorer - 信号质量评分器
核心原则: 只打高赔率机会，入场更"挑食"
"""
import logging

class SignalQualityScorer:
    """
    信号质量评分系统
    
    评分维度:
    1. 趋势强度 (ADX) - 权重30%
    2. 趋势一致性 (1H+4H) - 权重25%
    3. 突破质量 (布林带+成交量) - 权重25%
    4. 资金费率方向 - 权重20%
    
    总分100分，>=70分才允许交易
    """
    
    def __init__(self):
        self.weights = {
            'adx': 0.30,
            'trend_consistency': 0.25,
            'breakout_quality': 0.25,
            'funding_rate': 0.20
        }
        self.min_score = 70  # 最低交易门槛
        logging.info("📊 SignalQualityScorer initialized")
    
    def calculate_score(self, signal_data):
        """
        计算信号质量分数
        
        Args:
            signal_data: {
                'adx': float,
                'trend_1h': 'UP'/'DOWN',
                'trend_4h': 'UP'/'DOWN',
                'bb_squeeze': bool,
                'volume_surge': bool,
                'funding_rate': float,
                'side': 'buy'/'sell'
            }
        
        Returns:
            dict: 评分结果
        """
        scores = {}
        
        # 1. ADX 趋势强度评分 (0-100)
        adx = signal_data.get('adx', 0)
        if adx >= 30:
            scores['adx'] = 100
        elif adx >= 20:
            scores['adx'] = 80
        elif adx >= 15:
            scores['adx'] = 60
        elif adx >= 10:
            scores['adx'] = 40
        else:
            scores['adx'] = 20
        
        # 2. 趋势一致性评分
        trend_1h = signal_data.get('trend_1h')
        trend_4h = signal_data.get('trend_4h')
        
        if trend_1h == trend_4h:
            scores['trend_consistency'] = 100  # 完全一致
        else:
            scores['trend_consistency'] = 50   # 不一致
        
        # 3. 突破质量评分
        bb_squeeze = signal_data.get('bb_squeeze', False)
        volume_surge = signal_data.get('volume_surge', False)
        
        if bb_squeeze and volume_surge:
            scores['breakout_quality'] = 100  # 挤压突破+放量
        elif bb_squeeze or volume_surge:
            scores['breakout_quality'] = 60   # 只有一个条件
        else:
            scores['breakout_quality'] = 30   # 都不是
        
        # 4. 资金费率评分
        funding_rate = signal_data.get('funding_rate', 0)
        side = signal_data.get('side')
        
        if side == 'buy':  # 多头
            if funding_rate < 0:  # 负费率（别人付我）
                scores['funding_rate'] = 100
            elif funding_rate < 0.0001:  # 低费率
                scores['funding_rate'] = 80
            elif funding_rate < 0.0005:  # 中等费率
                scores['funding_rate'] = 50
            else:  # 高费率
                scores['funding_rate'] = 20
        else:  # 空头
            if funding_rate > 0:  # 正费率（别人付我）
                scores['funding_rate'] = 100
            elif funding_rate > -0.0001:
                scores['funding_rate'] = 80
            elif funding_rate > -0.0005:
                scores['funding_rate'] = 50
            else:
                scores['funding_rate'] = 20
        
        # 计算加权总分
        total_score = sum(scores[k] * self.weights[k] for k in scores)
        
        # 确定交易等级
        if total_score >= 80:
            trade_tier = 'PREMIUM'  # 优质信号，最大仓位
            max_position_pct = 0.06  # 6%账户
        elif total_score >= 70:
            trade_tier = 'STANDARD'  # 标准信号，正常仓位
            max_position_pct = 0.04  # 4%账户
        elif total_score >= 60:
            trade_tier = 'REDUCED'   # 降级信号，小仓位
            max_position_pct = 0.02  # 2%账户
        else:
            trade_tier = 'REJECTED'  # 拒绝交易
            max_position_pct = 0
        
        result = {
            'total_score': round(total_score, 1),
            'component_scores': scores,
            'trade_tier': trade_tier,
            'max_position_pct': max_position_pct,
            'can_trade': total_score >= self.min_score
        }
        
        logging.info(f"📊 Signal Score: {total_score:.1f} | Tier: {trade_tier} | "
                    f"ADX:{scores['adx']} Trend:{scores['trend_consistency']} "
                    f"Breakout:{scores['breakout_quality']} Funding:{scores['funding_rate']}")
        
        return result
    
    def get_position_size_multiplier(self, score_result):
        """根据评分获取仓位倍数"""
        tier = score_result['trade_tier']
        multipliers = {
            'PREMIUM': 1.5,    # 1.5倍标准仓位
            'STANDARD': 1.0,   # 标准仓位
            'REDUCED': 0.5,    # 减半仓位
            'REJECTED': 0      # 不交易
        }
        return multipliers.get(tier, 0)

if __name__ == "__main__":
    # 测试
    scorer = SignalQualityScorer()
    
    test_signal = {
        'adx': 35,
        'trend_1h': 'UP',
        'trend_4h': 'UP',
        'bb_squeeze': True,
        'volume_surge': True,
        'funding_rate': -0.0002,  # 负费率，利好多头
        'side': 'buy'
    }
    
    result = scorer.calculate_score(test_signal)
    print(f"Total Score: {result['total_score']}")
    print(f"Tier: {result['trade_tier']}")
    print(f"Can Trade: {result['can_trade']}")
