"""
ML Signal Filter - 本地轻量级机器学习信号过滤模块
使用scikit-learn训练分类器，预测信号可靠性
零Token消耗，完全本地运行
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
import pickle
import os
import logging
from datetime import datetime, timedelta

class MLSignalFilter:
    """
    ML信号过滤器
    
    功能：
    1. 基于历史技术指标训练模型
    2. 预测当前信号的胜率
    3. 过滤低质量信号
    """
    
    def __init__(self, model_path='.ml_model.pkl', min_samples=50):
        self.model_path = model_path
        self.min_samples = min_samples  # 最小训练样本数
        self.model = None
        self.scaler = StandardScaler()
        self.training_data = []  # 训练数据缓存
        self.is_trained = False
        
        # 尝试加载已有模型
        self._load_model()
    
    def _load_model(self):
        """加载已有模型"""
        try:
            if os.path.exists(self.model_path):
                with open(self.model_path, 'rb') as f:
                    data = pickle.load(f)
                    self.model = data['model']
                    self.scaler = data['scaler']
                    self.is_trained = True
                    logging.info(f"🤖 ML模型已加载: {self.model_path}")
        except Exception as e:
            logging.warning(f"⚠️ ML模型加载失败: {e}")
            self.model = None
            self.is_trained = False
    
    def _save_model(self):
        """保存模型"""
        try:
            with open(self.model_path, 'wb') as f:
                pickle.dump({
                    'model': self.model,
                    'scaler': self.scaler
                }, f)
            logging.info(f"💾 ML模型已保存: {self.model_path}")
        except Exception as e:
            logging.error(f"❌ ML模型保存失败: {e}")
    
    def extract_features(self, df, signal_side):
        """
        从DataFrame提取特征
        
        Args:
            df: DataFrame with OHLCV and indicators
            signal_side: 'buy' or 'sell'
        
        Returns:
            feature_vector: numpy array
        """
        try:
            if len(df) < 50:
                return None
            
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            
            # 基础特征
            features = {
                # 趋势特征
                'price_above_ema200': 1 if latest['close'] > latest['ema200'] else 0,
                'price_above_ema50': 1 if latest['close'] > df['close'].ewm(span=50).mean().iloc[-1] else 0,
                'ema_slope': (latest['ema200'] - df['ema200'].iloc[-10]) / df['ema200'].iloc[-10] * 100 if df['ema200'].iloc[-10] != 0 else 0,
                
                # 动量特征
                'rsi': latest['rsi'] if 'rsi' in latest else 50,
                'stoch_k': latest['stoch_k'] if 'stoch_k' in latest else 50,
                'stoch_d': latest['stoch_d'] if 'stoch_d' in latest else 50,
                'stoch_cross': 1 if latest['stoch_k'] > latest['stoch_d'] and prev['stoch_k'] <= prev['stoch_d'] else 0,
                
                # 波动率特征
                'atr_pct': (latest['atr'] / latest['close'] * 100) if 'atr' in latest and latest['close'] != 0 else 0,
                'bb_width': latest['bb_width'] if 'bb_width' in latest else 0,
                'bb_position': (latest['close'] - latest['bb_lower']) / (latest['bb_upper'] - latest['bb_lower']) if 'bb_upper' in latest and latest['bb_upper'] != latest['bb_lower'] else 0.5,
                
                # 趋势强度
                'adx': latest['adx'] if 'adx' in latest else 20,
                'adx_trending': 1 if latest['adx'] > 25 else 0,
                
                # 成交量特征
                'volume_ma_ratio': latest['volume'] / df['volume'].rolling(20).mean().iloc[-1] if df['volume'].rolling(20).mean().iloc[-1] > 0 else 1,
                'volume_trend': 1 if latest['volume'] > prev['volume'] else 0,
                
                # 信号方向
                'signal_buy': 1 if signal_side == 'buy' else 0,
                
                # 时间特征
                'hour': datetime.now().hour,
                'day_of_week': datetime.now().weekday(),
            }
            
            # 转换为numpy数组
            feature_names = [
                'price_above_ema200', 'price_above_ema50', 'ema_slope',
                'rsi', 'stoch_k', 'stoch_d', 'stoch_cross',
                'atr_pct', 'bb_width', 'bb_position',
                'adx', 'adx_trending',
                'volume_ma_ratio', 'volume_trend',
                'signal_buy',
                'hour', 'day_of_week'
            ]
            
            return np.array([features[name] for name in feature_names])
        
        except Exception as e:
            logging.error(f"❌ 特征提取失败: {e}")
            return None
    
    def predict(self, df, signal_side):
        """
        预测信号胜率
        
        Returns:
            dict: {
                'confidence': float (0-1),
                'should_trade': bool,
                'reason': str
            }
        """
        if not self.is_trained or self.model is None:
            return {
                'confidence': 0.5,
                'should_trade': True,
                'reason': 'ML模型未训练，使用默认策略'
            }
        
        try:
            features = self.extract_features(df, signal_side)
            if features is None:
                return {
                    'confidence': 0.5,
                    'should_trade': True,
                    'reason': '特征提取失败，使用默认策略'
                }
            
            # 标准化
            features_scaled = self.scaler.transform(features.reshape(1, -1))
            
            # 预测概率
            proba = self.model.predict_proba(features_scaled)[0]
            
            # 对于买入信号，预测类别1（盈利）的概率
            # 对于卖出信号，同样预测盈利概率（模型训练时统一处理）
            win_probability = proba[1] if len(proba) > 1 else proba[0]
            
            # 决策阈值
            if win_probability >= 0.6:
                return {
                    'confidence': win_probability,
                    'should_trade': True,
                    'reason': f'ML预测胜率: {win_probability:.1%} - 高置信度'
                }
            elif win_probability >= 0.45:
                return {
                    'confidence': win_probability,
                    'should_trade': True,
                    'reason': f'ML预测胜率: {win_probability:.1%} - 中等置信度'
                }
            else:
                return {
                    'confidence': win_probability,
                    'should_trade': False,
                    'reason': f'ML预测胜率: {win_probability:.1%} - 低置信度，建议观望'
                }
        
        except Exception as e:
            logging.error(f"❌ ML预测失败: {e}")
            return {
                'confidence': 0.5,
                'should_trade': True,
                'reason': f'预测出错: {e}，使用默认策略'
            }
    
    def record_outcome(self, df, signal_side, pnl):
        """
        记录交易结果用于训练
        
        Args:
            df: 信号时的DataFrame
            signal_side: 'buy' or 'sell'
            pnl: 实际盈亏（正数表示盈利）
        """
        try:
            features = self.extract_features(df, signal_side)
            if features is not None:
                label = 1 if pnl > 0 else 0  # 1=盈利, 0=亏损
                self.training_data.append((features, label))
                
                # 限制缓存大小
                if len(self.training_data) > 1000:
                    self.training_data = self.training_data[-500:]
                
                logging.info(f"📝 ML训练数据已记录: {signal_side} PnL={pnl:.2f} Label={label}")
        except Exception as e:
            logging.error(f"❌ 记录训练数据失败: {e}")
    
    def train(self, force=False):
        """
        训练模型
        
        Args:
            force: 是否强制重新训练
        """
        if len(self.training_data) < self.min_samples and not force:
            logging.info(f"⏳ ML训练数据不足: {len(self.training_data)}/{self.min_samples}")
            return False
        
        try:
            # 准备数据
            X = np.array([d[0] for d in self.training_data])
            y = np.array([d[1] for d in self.training_data])
            
            # 标准化
            self.scaler = StandardScaler()
            X_scaled = self.scaler.fit_transform(X)
            
            # 训练模型 - 使用GradientBoosting，效果通常比RandomForest好
            self.model = GradientBoostingClassifier(
                n_estimators=100,
                max_depth=3,
                learning_rate=0.1,
                random_state=42
            )
            self.model.fit(X_scaled, y)
            
            # 计算训练集准确率
            train_accuracy = self.model.score(X_scaled, y)
            
            self.is_trained = True
            self._save_model()
            
            logging.info(f"✅ ML模型训练完成! 样本数: {len(y)}, 准确率: {train_accuracy:.2%}")
            return True
        
        except Exception as e:
            logging.error(f"❌ ML模型训练失败: {e}")
            return False
    
    def get_feature_importance(self):
        """获取特征重要性"""
        if not self.is_trained or self.model is None:
            return {}
        
        try:
            feature_names = [
                'price_above_ema200', 'price_above_ema50', 'ema_slope',
                'rsi', 'stoch_k', 'stoch_d', 'stoch_cross',
                'atr_pct', 'bb_width', 'bb_position',
                'adx', 'adx_trending',
                'volume_ma_ratio', 'volume_trend',
                'signal_buy',
                'hour', 'day_of_week'
            ]
            
            importance = self.model.feature_importances_
            return dict(sorted(zip(feature_names, importance), key=lambda x: x[1], reverse=True))
        except:
            return {}


# 简单的模拟训练数据生成器（用于冷启动）
def generate_mock_training_data():
    """生成模拟训练数据用于冷启动"""
    np.random.seed(42)
    n_samples = 100
    
    data = []
    for _ in range(n_samples):
        # 随机特征
        features = np.random.randn(17)
        # 简单规则：RSI低 + 价格在EMA上方 = 盈利概率高
        if features[3] < -0.5 and features[0] > 0:  # RSI低 + price_above_ema200
            label = 1 if np.random.random() > 0.3 else 0  # 70%盈利
        else:
            label = 1 if np.random.random() > 0.6 else 0  # 40%盈利
        
        data.append((features, label))
    
    return data


if __name__ == "__main__":
    # 测试
    ml_filter = MLSignalFilter()
    
    # 如果没有模型，生成模拟数据训练
    if not ml_filter.is_trained:
        print("生成模拟训练数据...")
        ml_filter.training_data = generate_mock_training_data()
        ml_filter.train()
    
    # 测试预测
    import pandas as pd
    test_df = pd.DataFrame({
        'close': [100, 101, 102, 103, 104],
        'high': [101, 102, 103, 104, 105],
        'low': [99, 100, 101, 102, 103],
        'volume': [1000, 1100, 1200, 1300, 1400],
        'ema200': [98, 99, 100, 101, 102],
        'rsi': [45, 48, 52, 55, 58],
        'stoch_k': [30, 35, 40, 45, 50],
        'stoch_d': [25, 30, 35, 40, 45],
        'atr': [1.5, 1.6, 1.7, 1.8, 1.9],
        'bb_upper': [105, 106, 107, 108, 109],
        'bb_lower': [95, 96, 97, 98, 99],
        'bb_width': [0.1, 0.1, 0.1, 0.1, 0.1],
        'adx': [20, 22, 24, 26, 28]
    })
    
    result = ml_filter.predict(test_df, 'buy')
    print(f"预测结果: {result}")
    
    # 特征重要性
    importance = ml_filter.get_feature_importance()
    print(f"\n特征重要性:")
    for name, imp in list(importance.items())[:5]:
        print(f"  {name}: {imp:.3f}")
