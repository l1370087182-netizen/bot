"""
CVD (Cumulative Volume Delta) 订单流分析模块 v2.0
修复: 使用相对变化率，修复卖出信号置信度计算
"""
import logging
import numpy as np
import pandas as pd
from collections import deque

class OrderFlowAnalyzer:
    """
    CVD 订单流分析器 v2.0
    
    核心逻辑：
    1. 计算每根K线的 Delta (主动买单 - 主动卖单估算)
    2. 累积 CVD (Cumulative Volume Delta)
    3. 检测价格与 CVD 的背离 (Divergence)
    4. 使用相对变化率进行比较 (修复v1.0的绝对值问题)
    """
    
    def __init__(self, lookback_period=20):
        self.lookback_period = lookback_period
        self.cvd_history = {}  # {symbol: deque of CVD values}
        self.price_history = {}  # {symbol: deque of price values}
        
    def calculate_delta(self, open_price, high, low, close, volume):
        """
        估算单根K线的买卖压力 (Delta)
        
        使用加权方法：
        - 收盘价靠近高点 → 买方主导
        - 收盘价靠近低点 → 卖方主导
        """
        if volume == 0 or high == low:
            return 0
        
        # 计算K线范围内的位置 (0-1)
        position = (close - low) / (high - low)
        
        # 根据位置估算买卖比例
        buy_ratio = position
        sell_ratio = 1 - position
        
        # 考虑开盘价的因素
        if close > open_price:
            # 阳线，买方更强
            buy_ratio = min(1.0, buy_ratio * 1.2)
            sell_ratio = 1 - buy_ratio
        elif close < open_price:
            # 阴线，卖方更强
            sell_ratio = min(1.0, sell_ratio * 1.2)
            buy_ratio = 1 - sell_ratio
        
        delta = volume * (buy_ratio - sell_ratio)
        return delta
    
    def update_cvd(self, symbol, ohlcv_data):
        """
        更新指定币种的 CVD 数据
        
        Args:
            symbol: 交易对
            ohlcv_data: DataFrame with ['open', 'high', 'low', 'close', 'volume']
        
        Returns:
            dict: 包含 CVD 相关指标
        """
        if symbol not in self.cvd_history:
            self.cvd_history[symbol] = deque(maxlen=self.lookback_period * 2)
            self.price_history[symbol] = deque(maxlen=self.lookback_period * 2)
        
        # 计算最新 CVD
        df = ohlcv_data.copy()
        df['delta'] = df.apply(lambda row: self.calculate_delta(
            row['open'], row['high'], row['low'], row['close'], row['volume']
        ), axis=1)
        df['cvd'] = df['delta'].cumsum()
        
        # 更新历史
        latest_cvd = df['cvd'].iloc[-1]
        latest_price = df['close'].iloc[-1]
        
        self.cvd_history[symbol].append(latest_cvd)
        self.price_history[symbol].append(latest_price)
        
        # 计算 CVD 相关指标
        result = self._calculate_metrics(symbol, df)
        
        return result
    
    def _calculate_metrics(self, symbol, df):
        """计算 CVD 技术指标"""
        if len(df) < self.lookback_period:
            return {
                'cvd': 0,
                'cvd_ma': 0,
                'cvd_slope': 0,
                'cvd_change_pct': 0,  # v2.0: 相对变化率
                'price_change_pct': 0,  # v2.0: 价格相对变化率
                'divergence': 'none',
                'strength': 50
            }
        
        current_cvd = df['cvd'].iloc[-1]
        current_price = df['close'].iloc[-1]
        
        # CVD 移动平均
        cvd_ma = df['cvd'].rolling(self.lookback_period).mean().iloc[-1]
        
        # v2.0: 使用相对变化率而不是绝对斜率
        # CVD 变化率 (%)
        cvd_start = df['cvd'].iloc[-self.lookback_period]
        if abs(cvd_start) > 0:
            cvd_change_pct = (current_cvd - cvd_start) / abs(cvd_start) * 100
        else:
            cvd_change_pct = 0
        
        # 价格变化率 (%)
        price_start = df['close'].iloc[-self.lookback_period]
        if price_start > 0:
            price_change_pct = (current_price - price_start) / price_start * 100
        else:
            price_change_pct = 0
        
        # 保留绝对斜率用于日志，但主要使用相对变化率
        cvd_slope = (current_cvd - cvd_start) / self.lookback_period
        
        # 检测背离
        divergence = self._detect_divergence(df)
        
        # 计算强度 (0-100)
        strength = self._calculate_strength(df, divergence)
        
        return {
            'cvd': current_cvd,
            'cvd_ma': cvd_ma,
            'cvd_slope': cvd_slope,
            'cvd_change_pct': cvd_change_pct,  # v2.0 新增
            'price_change_pct': price_change_pct,  # v2.0 新增
            'divergence': divergence,
            'strength': strength,
            'delta': df['delta'].iloc[-1]
        }
    
    def _detect_divergence(self, df):
        """
        检测价格与 CVD 的背离
        
        Returns:
            'bearish': 价格新高，CVD 未新高 (看跌背离，假突破)
            'bullish': 价格新低，CVD 未新低 (看涨背离，假跌破)
            'none': 无背离
        """
        if len(df) < 10:
            return 'none'
        
        # 获取最近的价格和 CVD
        recent_prices = df['close'].iloc[-10:].values
        recent_cvd = df['cvd'].iloc[-10:].values
        
        # 检测看跌背离 (价格新高，CVD 未新高)
        price_high_idx = np.argmax(recent_prices)
        cvd_high_idx = np.argmax(recent_cvd)
        
        if price_high_idx == len(recent_prices) - 1 and cvd_high_idx < price_high_idx - 2:
            # 价格创了新高，但 CVD 没有同步新高
            price_diff = (recent_prices[-1] - recent_prices[cvd_high_idx]) / recent_prices[cvd_high_idx]
            cvd_diff = (recent_cvd[-1] - recent_cvd[cvd_high_idx]) / (abs(recent_cvd[cvd_high_idx]) + 1)
            
            if price_diff > 0.01 and cvd_diff < 0:  # 价格上涨 >1%，CVD 下降
                return 'bearish'
        
        # 检测看涨背离 (价格新低，CVD 未新低)
        price_low_idx = np.argmin(recent_prices)
        cvd_low_idx = np.argmin(recent_cvd)
        
        if price_low_idx == len(recent_prices) - 1 and cvd_low_idx < price_low_idx - 2:
            # 价格创了新低，但 CVD 没有同步新低
            price_diff = (recent_prices[-1] - recent_prices[cvd_low_idx]) / recent_prices[cvd_low_idx]
            cvd_diff = (recent_cvd[-1] - recent_cvd[cvd_low_idx]) / (abs(recent_cvd[cvd_low_idx]) + 1)
            
            if price_diff < -0.01 and cvd_diff > 0:  # 价格下跌 >1%，CVD 上升
                return 'bullish'
        
        return 'none'
    
    def _calculate_strength(self, df, divergence):
        """计算信号强度 (0-100) - v2.0 修复"""
        if len(df) < 5:
            return 50
        
        recent_delta = df['delta'].iloc[-5:].sum()
        avg_volume = df['volume'].rolling(20).mean().iloc[-1]
        recent_volume = df['volume'].iloc[-5:].mean()
        
        # 基于成交量和 Delta 计算强度
        if avg_volume == 0:
            return 50
        
        volume_ratio = recent_volume / avg_volume
        
        # v2.0: 改进 delta_ratio 计算，避免数值过小
        # 使用相对于平均成交量的比例
        delta_ratio = abs(recent_delta) / (avg_volume + 1)  # 改用avg_volume而不是recent_volume
        
        # 强度计算 - 调整权重使结果更合理
        # volume_ratio: 1.0 = 正常, 2.0 = 2倍成交量
        # delta_ratio: 通常 0-1 之间，表示买卖压力强度
        strength = 50 + (volume_ratio - 1) * 15 + delta_ratio * 50
        
        # 背离时调整强度
        if divergence == 'bearish':
            strength -= 15  # 看跌背离，降低多头信号强度
        elif divergence == 'bullish':
            strength += 15  # 看涨背离，增强多头信号强度
        
        return max(10, min(90, strength))  # v2.0: 限制在10-90之间，避免极端值
    
    def validate_signal(self, symbol, signal_side, ohlcv_data):
        """
        使用 CVD 验证交易信号 - v2.0 修复版
        
        Args:
            symbol: 交易对
            signal_side: 'buy' 或 'sell'
            ohlcv_data: DataFrame with OHLCV data
        
        Returns:
            dict: {
                'valid': bool,  # 信号是否有效
                'confidence': float,  # 置信度 0-100
                'reason': str,  # 验证原因
                'metrics': dict  # CVD 指标详情
            }
        """
        metrics = self.update_cvd(symbol, ohlcv_data)
        
        divergence = metrics['divergence']
        cvd_change_pct = metrics['cvd_change_pct']  # v2.0: 使用相对变化率
        price_change_pct = metrics['price_change_pct']
        strength = metrics['strength']
        
        # v2.0: 基于相对变化率判断CVD趋势方向
        cvd_trend_up = cvd_change_pct > 1.0   # CVD上升超过1%
        cvd_trend_down = cvd_change_pct < -1.0  # CVD下降超过1%
        cvd_flat = not cvd_trend_up and not cvd_trend_down  # CVD平稳
        
        # 验证逻辑
        if signal_side == 'buy':
            # 做多信号验证
            if divergence == 'bearish':
                # 价格新高但 CVD 未新高 → 假突破，拒绝信号
                return {
                    'valid': False,
                    'confidence': 15,
                    'reason': '看跌背离: 价格新高但买盘不足 (大户派发)',
                    'metrics': metrics
                }
            elif divergence == 'bullish':
                # 价格新低但 CVD 上升 → 看涨背离，确认信号
                return {
                    'valid': True,
                    'confidence': 85,
                    'reason': '看涨背离: 价格新低但买盘活跃 (大户吸筹)',
                    'metrics': metrics
                }
            elif cvd_trend_up:
                # CVD 上升，确认买盘主导
                # v2.0: 根据变化率大小调整置信度
                if cvd_change_pct > 5.0:
                    conf = min(85, strength + 10)
                elif cvd_change_pct > 2.0:
                    conf = min(80, strength + 5)
                else:
                    conf = min(75, strength)
                return {
                    'valid': True,
                    'confidence': conf,
                    'reason': f'CVD 上升 {cvd_change_pct:.1f}% (买盘主导)',
                    'metrics': metrics
                }
            elif cvd_flat:
                # CVD 平稳，中性
                return {
                    'valid': True,
                    'confidence': max(45, strength - 10),
                    'reason': f'CVD 平稳 ({cvd_change_pct:.1f}%)，信号中性',
                    'metrics': metrics
                }
            else:  # cvd_trend_down
                # CVD 下降，警告
                return {
                    'valid': True,
                    'confidence': max(25, min(45, strength - 20)),
                    'reason': f'警告: CVD 下降 {cvd_change_pct:.1f}% (存在卖压)',
                    'metrics': metrics
                }
        
        else:  # signal_side == 'sell'
            # 做空信号验证
            if divergence == 'bullish':
                # 价格新低但 CVD 上升 → 假跌破，拒绝信号
                return {
                    'valid': False,
                    'confidence': 15,
                    'reason': '看涨背离: 价格新低但卖盘不足 (大户吸筹)',
                    'metrics': metrics
                }
            elif divergence == 'bearish':
                # 价格新高但 CVD 下降 → 看跌背离，确认信号
                return {
                    'valid': True,
                    'confidence': 85,
                    'reason': '看跌背离: 价格新高但卖盘活跃 (大户派发)',
                    'metrics': metrics
                }
            elif cvd_trend_down:
                # CVD 下降，确认卖盘主导
                # v2.0: 根据变化率大小调整置信度
                if cvd_change_pct < -5.0:
                    conf = min(85, strength + 10)
                elif cvd_change_pct < -2.0:
                    conf = min(80, strength + 5)
                else:
                    conf = min(75, strength)
                return {
                    'valid': True,
                    'confidence': conf,
                    'reason': f'CVD 下降 {abs(cvd_change_pct):.1f}% (卖盘主导)',
                    'metrics': metrics
                }
            elif cvd_flat:
                # CVD 平稳，中性
                return {
                    'valid': True,
                    'confidence': max(45, strength - 10),
                    'reason': f'CVD 平稳 ({cvd_change_pct:.1f}%)，信号中性',
                    'metrics': metrics
                }
            else:  # cvd_trend_up
                # CVD 上升，警告
                return {
                    'valid': True,
                    'confidence': max(25, min(45, strength - 20)),
                    'reason': f'警告: CVD 上升 {cvd_change_pct:.1f}% (存在买盘)',
                    'metrics': metrics
                }


class CVDFilter:
    """
    CVD 信号过滤器 - 集成到策略中 v2.0
    """
    
    def __init__(self, min_confidence=45):
        self.analyzer = OrderFlowAnalyzer()
        self.min_confidence = min_confidence  # 最小置信度阈值
        
    def filter_signals(self, signals, exchange):
        """
        过滤信号列表，只保留通过 CVD 验证的信号
        
        Args:
            signals: dict of {symbol: signal_info}
            exchange: ccxt exchange instance
        
        Returns:
            filtered_signals: dict of validated signals
        """
        if not signals:
            return {}
        
        filtered = {}
        
        for symbol, signal_info in signals.items():
            try:
                # 获取 30m 数据用于 CVD 计算
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe='30m', limit=50)
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                
                side = signal_info.get('side') if isinstance(signal_info, dict) else signal_info
                
                # CVD 验证
                validation = self.analyzer.validate_signal(symbol, side, df)
                
                metrics = validation['metrics']
                # v2.0: 日志显示相对变化率而不是绝对斜率
                logging.info(f"📊 CVD分析 {symbol}: 背离={metrics['divergence']}, "
                           f"CVD变化={metrics['cvd_change_pct']:.1f}%, 价格变化={metrics['price_change_pct']:.1f}%, "
                           f"强度={metrics['strength']:.0f}")
                
                if validation['valid'] and validation['confidence'] >= self.min_confidence:
                    # 添加 CVD 信息到信号
                    signal_info['cvd_confidence'] = validation['confidence']
                    signal_info['cvd_reason'] = validation['reason']
                    filtered[symbol] = signal_info
                    logging.info(f"✅ CVD验证通过: {symbol} | 置信度: {validation['confidence']}% | {validation['reason']}")
                else:
                    logging.warning(f"❌ CVD过滤: {symbol} | 置信度: {validation['confidence']}% | {validation['reason']}")
                    
            except Exception as e:
                logging.error(f"CVD分析错误 {symbol}: {e}")
                # 出错时保留原信号（保守策略）
                filtered[symbol] = signal_info
        
        return filtered
