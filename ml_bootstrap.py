#!/usr/bin/env python3
"""
ML冷启动训练脚本
生成初始训练数据让ML模型快速可用
"""
import sys
sys.path.insert(0, '/home/administrator/.openclaw/workspace/binance_bot')
sys.path.insert(0, '/home/administrator/.openclaw/workspace/binance_bot/src')

import numpy as np
from ml.ml_signal_filter import MLSignalFilter
import logging

logging.basicConfig(level=logging.INFO)

def generate_realistic_training_data():
    """
    生成 realistic 的训练数据
    基于常见交易规则模拟盈亏分布
    """
    np.random.seed(42)
    data = []
    
    # 特征名称对应索引
    # 0:price_above_ema200, 1:price_above_ema50, 2:ema_slope
    # 3:rsi, 4:stoch_k, 5:stoch_d, 6:stoch_cross
    # 7:atr_pct, 8:bb_width, 9:bb_position
    # 10:adx, 11:adx_trending
    # 12:volume_ma_ratio, 13:volume_trend
    # 14:signal_buy, 15:hour, 16:day_of_week
    
    for _ in range(200):
        # 生成合理的特征值
        features = np.array([
            np.random.choice([0, 1]),  # price_above_ema200
            np.random.choice([0, 1]),  # price_above_ema50
            np.random.randn() * 2,      # ema_slope
            np.random.uniform(20, 80),  # rsi
            np.random.uniform(10, 90),  # stoch_k
            np.random.uniform(10, 90),  # stoch_d
            np.random.choice([0, 1]),  # stoch_cross
            np.random.uniform(0.5, 5),  # atr_pct
            np.random.uniform(0.05, 0.3),  # bb_width
            np.random.uniform(0.2, 0.8),   # bb_position
            np.random.uniform(10, 50),  # adx
            np.random.choice([0, 1]),  # adx_trending
            np.random.uniform(0.5, 2),  # volume_ma_ratio
            np.random.choice([0, 1]),  # volume_trend
            np.random.choice([0, 1]),  # signal_buy
            np.random.randint(0, 24),  # hour
            np.random.randint(0, 7),   # day_of_week
        ])
        
        # 基于规则生成标签（模拟真实交易结果）
        score = 0
        
        # 买入信号规则
        if features[14] == 1:  # buy signal
            if features[0] == 1:  # price above ema200
                score += 0.3
            if features[3] < 40:  # rsi low
                score += 0.2
            if features[4] < 30:  # stoch_k low
                score += 0.2
            if features[10] > 25:  # adx trending
                score += 0.15
            if features[12] > 1.2:  # high volume
                score += 0.15
        else:  # sell signal
            if features[0] == 0:  # price below ema200
                score += 0.3
            if features[3] > 60:  # rsi high
                score += 0.2
            if features[4] > 70:  # stoch_k high
                score += 0.2
            if features[10] > 25:  # adx trending
                score += 0.15
            if features[12] > 1.2:  # high volume
                score += 0.15
        
        # 添加噪声
        score += np.random.randn() * 0.2
        
        # 生成标签 (1=盈利, 0=亏损)
        label = 1 if score > 0.5 else 0
        
        data.append((features, label))
    
    return data

def main():
    print("🚀 ML冷启动训练...")
    
    # 创建ML过滤器
    ml_filter = MLSignalFilter(min_samples=30)
    
    if ml_filter.is_trained:
        print("✅ ML模型已存在，跳过冷启动")
        return
    
    # 生成训练数据
    print("📊 生成初始训练数据...")
    ml_filter.training_data = generate_realistic_training_data()
    
    # 训练模型
    print("🎓 训练模型...")
    success = ml_filter.train()
    
    if success:
        print(f"✅ ML模型训练完成！")
        print(f"   训练样本: {len(ml_filter.training_data)}")
        
        # 显示特征重要性
        importance = ml_filter.get_feature_importance()
        print(f"\n📈 Top 5 重要特征:")
        for i, (name, imp) in enumerate(list(importance.items())[:5], 1):
            print(f"   {i}. {name}: {imp:.3f}")
    else:
        print("❌ 训练失败")

if __name__ == "__main__":
    main()
