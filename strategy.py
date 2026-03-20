import logging
import pandas as pd
import numpy as np

class Strategy:
    def __init__(self, symbols):
        self.symbols = symbols

    def calculate_indicators(self, df):
        """计算核心技术指标"""
        # 1. EMA 200 (大趋势)
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
        
        # 2. Stochastic RSI (动量)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        rsi_min = df['rsi'].rolling(window=14).min()
        rsi_max = df['rsi'].rolling(window=14).max()
        stoch_rsi = (df['rsi'] - rsi_min) / (rsi_max - rsi_min)
        df['stoch_k'] = stoch_rsi.rolling(window=3).mean() * 100
        df['stoch_d'] = df['stoch_k'].rolling(window=3).mean() * 100
        
        # 3. ATR (波动率)
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        df['tr'] = np.max(ranges, axis=1)
        df['atr'] = df['tr'].rolling(14).mean()
        
        # 4. ADX (趋势强度)
        plus_dm = df['high'].diff()
        minus_dm = df['low'].diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm > 0] = 0
        minus_dm = np.abs(minus_dm)
        
        tr_smooth = df['tr'].rolling(14).sum()
        plus_di = 100 * (plus_dm.rolling(14).sum() / tr_smooth)
        minus_di = 100 * (minus_dm.rolling(14).sum() / tr_smooth)
        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
        df['adx'] = dx.rolling(14).mean()
        
        # 5. 成交量均线
        df['vol_ma'] = df['volume'].rolling(window=20).mean()
        
        # 6. 布林带 (用于判断超买超卖)
        df['bb_middle'] = df['close'].rolling(window=20).mean()
        bb_std = df['close'].rolling(window=20).std()
        df['bb_upper'] = df['bb_middle'] + (bb_std * 2)
        df['bb_lower'] = df['bb_middle'] - (bb_std * 2)
        
        return df

    def calculate_signals(self, exchange):
        """计算入场信号 - 扫描所有交易对"""
        signals = {}
        
        # 扫描前50个币种，增加交易机会
        invalid_symbols = {'MATIC/USDT:USDT', 'TUSD/USDT:USDT', 'USDC/USDT:USDT'}
        scan_symbols = [s for s in self.symbols[:50] if s not in invalid_symbols]
        
        logging.info(f"🔍 Scanning {len(scan_symbols)} symbols: {scan_symbols[:5]}...")
        
        for symbol in scan_symbols:
            try:
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe='30m', limit=300)
                if len(ohlcv) < 200:  # 数据不足，跳过
                    logging.debug(f"⏭️ {symbol}: insufficient data ({len(ohlcv)} candles)")
                    continue
                    
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df = self.calculate_indicators(df)
                
                last = df.iloc[-1]
                prev = df.iloc[-2]
                
                # 入场条件：ADX > 12（趋势存在，放宽条件）+ 价格与EMA关系 + StochRSI信号
                adx_ok = last['adx'] > 12
                adx_strong = last['adx'] > 30  # 强趋势
                
                # 优化日志：只有在 ADX 达标或 StochRSI 处于极端区域时记录，减少刷屏
                is_interesting = adx_ok or last['stoch_k'] < 30 or last['stoch_k'] > 70
                if is_interesting:
                    logging.info(f"📊 {symbol} | 价格:{last['close']:.2f} ADX:{last['adx']:.1f} Stoch:{last['stoch_k']:.1f} EMA200:{last['ema200']:.2f}")
                
                # 做多条件
                if adx_ok and last['close'] > last['ema200']:
                    # 超卖区金叉（标准做多）
                    if last['stoch_k'] < 35 and last['stoch_k'] > last['stoch_d'] and prev['stoch_k'] <= prev['stoch_d']:
                        signals[symbol] = 'buy'
                        logging.info(f"🚨 BUY SIGNAL: {symbol} | 价格: {last['close']:.2f} | ADX: {last['adx']:.1f} | StochRSI: {last['stoch_k']:.1f} (超卖金叉)")
                        return signals
                    # 强趋势下的放宽条件：StochRSI 从高位回落到 50 附近即可入场
                    elif adx_strong and last['stoch_k'] > 45 and last['stoch_k'] < 65 and last['stoch_k'] > last['stoch_d'] and prev['stoch_k'] <= prev['stoch_d']:
                        signals[symbol] = 'buy'
                        logging.info(f"🚨 BUY SIGNAL: {symbol} | 价格: {last['close']:.2f} | ADX: {last['adx']:.1f} | StochRSI: {last['stoch_k']:.1f} (强趋势放宽)")
                        return signals
                    # 趋势延续：回调到EMA附近后反弹
                    elif last['close'] > last['ema200'] * 0.98 and last['stoch_k'] > last['stoch_d']:
                        # 价格在EMA上方2%以内，且StochRSI金叉
                        if prev['close'] < prev['ema200'] * 1.02:
                            signals[symbol] = 'buy'
                            logging.info(f"🚨 BUY SIGNAL: {symbol} | 价格: {last['close']:.2f} | ADX: {last['adx']:.1f} (趋势延续)")
                            return signals
                
                # 做空条件
                if adx_ok and last['close'] < last['ema200']:
                    # 超买区死叉（标准做空）- StochRSI > 70
                    if last['stoch_k'] > 70 and last['stoch_k'] < last['stoch_d'] and prev['stoch_k'] >= prev['stoch_d']:
                        signals[symbol] = 'sell'
                        logging.info(f"🚨 SELL SIGNAL: {symbol} (超买死叉)")
                        return signals
                    # 强趋势下的放宽条件：StochRSI 从低位反弹到 50 附近即可入场做空
                    elif adx_strong and last['stoch_k'] > 35 and last['stoch_k'] < 55 and last['stoch_k'] < last['stoch_d'] and prev['stoch_k'] >= prev['stoch_d']:
                        signals[symbol] = 'sell'
                        logging.info(f"🚨 SELL SIGNAL: {symbol} | 价格: {last['close']:.2f} | ADX: {last['adx']:.1f} | StochRSI: {last['stoch_k']:.1f} (强趋势放宽)")
                        return signals
                    # 趋势延续死叉 (StochRSI > 50)
                    elif last['stoch_k'] > 50 and last['stoch_k'] < last['stoch_d'] and prev['stoch_k'] >= prev['stoch_d']:
                        # 确保价格在EMA下方一段距离，确认弱势
                        if last['close'] < last['ema200'] * 0.99:
                            signals[symbol] = 'sell'
                            logging.info(f"🚨 SELL SIGNAL: {symbol} (趋势延续死叉)")
                            return signals
                    # 趋势延续：反弹到EMA附近后回落
                    elif last['close'] < last['ema200'] * 1.03 and last['stoch_k'] < last['stoch_d'] and prev['stoch_k'] >= prev['stoch_d']:
                        # 价格在EMA下方3%以内，且StochRSI死叉
                        signals[symbol] = 'sell'
                        logging.info(f"🚨 SELL SIGNAL: {symbol} | 价格: {last['close']:.2f} | ADX: {last['adx']:.1f} (趋势延续)")
                        return signals
                        
            except Exception as e:
                logging.warning(f"⚠️ Error scanning {symbol}: {str(e)[:50]}")
                continue
        
        logging.info(f"📭 No signals found after scanning {len(scan_symbols)} symbols")
        return None

    def calculate_exit_signals(self, exchange, symbol, current_side, entry_price, max_profit_pct=0, position_tracking=None):
        """
        智能平仓判断 - 3+1 精简策略
        
        核心逻辑：
        1. ATR 动态移动止损 (主要机制)
        2. 趋势反转 (EMA200 突破)
        3. 紧急硬止损 (最后防线)
        4. 放量异常 (情绪指标)
        
        Args:
            max_profit_pct: 持仓期间达到的最大盈利百分比
            position_tracking: 持仓追踪数据
        """
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='5m', limit=100)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df = self.calculate_indicators(df)
        
        last = df.iloc[-1]
        current_price = last['close']
        
        # 计算当前盈亏百分比
        if current_side == 'LONG':
            current_pnl_pct = ((current_price - entry_price) / entry_price) * 100
        else:  # SHORT
            current_pnl_pct = ((entry_price - current_price) / entry_price) * 100
        
        # ========== 1. ATR 动态移动止损 (核心机制) ==========
        atr_data = self.calculate_atr_trailing_stop(df, current_side, atr_multiplier=2.0)
        
        # 更新持仓追踪中的最高/最低价和ATR止损线
        if position_tracking is not None:
            if current_side == 'LONG':
                if position_tracking.get('highest_price', 0) == 0:
                    position_tracking['highest_price'] = current_price
                else:
                    position_tracking['highest_price'] = max(position_tracking['highest_price'], current_price)
                
                new_stop = atr_data['stop_price']
                if 'atr_stop_price' not in position_tracking:
                    position_tracking['atr_stop_price'] = new_stop
                else:
                    # 止损线只上升不下降
                    position_tracking['atr_stop_price'] = max(position_tracking['atr_stop_price'], new_stop)
                    
            else:  # SHORT
                if position_tracking.get('lowest_price', float('inf')) == float('inf'):
                    position_tracking['lowest_price'] = current_price
                else:
                    position_tracking['lowest_price'] = min(position_tracking['lowest_price'], current_price)
                
                new_stop = atr_data['stop_price']
                if 'atr_stop_price' not in position_tracking:
                    position_tracking['atr_stop_price'] = new_stop
                else:
                    # 止损线只下降不上升
                    position_tracking['atr_stop_price'] = min(position_tracking['atr_stop_price'], new_stop)
            
            atr_stop_price = position_tracking['atr_stop_price']
        else:
            atr_stop_price = atr_data['stop_price']
        
        # 检查是否触发ATR移动止损
        if current_side == 'LONG':
            if current_price <= atr_stop_price:
                return f"atr_trailing_stop: price={current_price:.2f} stop={atr_stop_price:.2f}"
        else:  # SHORT
            if current_price >= atr_stop_price:
                return f"atr_trailing_stop: price={current_price:.2f} stop={atr_stop_price:.2f}"
        
        # ========== 2. 趋势反转 (盈利>5%时生效) ==========
        if current_pnl_pct > 5.0:
            if current_side == 'LONG' and last['close'] < last['ema200'] * 0.99:
                return "trend_broken_down"
            elif current_side == 'SHORT' and last['close'] > last['ema200'] * 1.01:
                return "trend_broken_up"

        # ========== 3. 紧急硬止损 (最后防线) ==========
        if current_pnl_pct < -10.0:
            return f"emergency_stop:{current_pnl_pct:.2f}%"
        
        # ========== 4. 放量异常 (情绪指标) ==========
        if last['volume'] > last['vol_ma'] * 3:
            price_move = abs(last['close'] - last['open'])
            if price_move < (last['atr'] * 0.5):
                return "volume_exhaustion"

        return None
    
    def calculate_atr_trailing_stop(self, df, current_side, atr_multiplier=2.0):
        """
        计算 ATR 动态移动止损 (ATR Trailing Stop)
        
        原理：
        - 做多时：止损线 = 最高价 - ATR * multiplier，止损线只上升不下降
        - 做空时：止损线 = 最低价 + ATR * multiplier，止损线只下降不上升
        
        Args:
            df: DataFrame with OHLCV data
            current_side: 'LONG' 或 'SHORT'
            atr_multiplier: ATR倍数（默认2.0倍ATR）
        
        Returns:
            dict: {
                'stop_price': 当前止损价格,
                'atr_value': 当前ATR值,
                'highest_high': 持仓期间最高价（做多）,
                'lowest_low': 持仓期间最低价（做空）
            }
        """
        # 确保有ATR数据
        if 'atr' not in df.columns:
            high_low = df['high'] - df['low']
            high_close = np.abs(df['high'] - df['close'].shift())
            low_close = np.abs(df['low'] - df['close'].shift())
            ranges = pd.concat([high_low, high_close, low_close], axis=1)
            df['tr'] = np.max(ranges, axis=1)
            df['atr'] = df['tr'].rolling(14).mean()
        
        last = df.iloc[-1]
        atr_value = last['atr']
        
        # 获取最近N根K线的最高/最低价（用于计算移动止损）
        lookback = min(20, len(df))  # 最近20根K线
        recent_highs = df['high'].tail(lookback)
        recent_lows = df['low'].tail(lookback)
        
        highest_high = recent_highs.max()
        lowest_low = recent_lows.min()
        
        if current_side == 'LONG':
            # 做多：止损 = 最高价 - ATR * multiplier
            stop_price = highest_high - (atr_value * atr_multiplier)
        else:  # SHORT
            # 做空：止损 = 最低价 + ATR * multiplier
            stop_price = lowest_low + (atr_value * atr_multiplier)
        
        return {
            'stop_price': stop_price,
            'atr_value': atr_value,
            'highest_high': highest_high,
            'lowest_low': lowest_low,
            'atr_multiplier': atr_multiplier
        }
    
    def check_atr_trailing_stop_trigger(self, current_price, trailing_stop_data, current_side):
        """
        检查是否触发 ATR 移动止损
        
        Args:
            current_price: 当前价格
            trailing_stop_data: calculate_atr_trailing_stop 返回的数据
            current_side: 'LONG' 或 'SHORT'
        
        Returns:
            bool: 是否触发止损
        """
        stop_price = trailing_stop_data['stop_price']
        
        if current_side == 'LONG':
            # 做多：当前价格跌破止损线时触发
            return current_price <= stop_price
        else:  # SHORT
            # 做空：当前价格涨破止损线时触发
            return current_price >= stop_price
    
    def calculate_dynamic_stop_loss(self, entry_price, current_side, atr_value, volatility_factor=1.5):
        """
        计算动态止损价格（基于入场时的ATR）
        
        Args:
            entry_price: 入场价格
            current_side: 'LONG' 或 'SHORT'
            atr_value: ATR值
            volatility_factor: 波动率倍数（默认1.5倍ATR）
        """
        stop_distance = atr_value * volatility_factor
        
        if current_side == 'LONG':
            return entry_price - stop_distance
        else:  # SHORT
            return entry_price + stop_distance
    
    def calculate_dynamic_take_profit(self, entry_price, current_side, atr_value, risk_reward_ratio=2.0):
        """
        计算动态止盈价格
        
        Args:
            entry_price: 入场价格
            current_side: 'LONG' 或 'SHORT'
            atr_value: ATR值
            risk_reward_ratio: 盈亏比（默认2:1）
        """
        stop_distance = atr_value * 1.5  # 假设止损是1.5倍ATR
        profit_distance = stop_distance * risk_reward_ratio
        
        if current_side == 'LONG':
            return entry_price + profit_distance
        else:  # SHORT
            return entry_price - profit_distance
