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
        
        # 只扫描主要币种（前20个），排除已知的无效交易对
        invalid_symbols = {'MATIC/USDT:USDT', 'TUSD/USDT:USDT', 'USDC/USDT:USDT'}
        scan_symbols = [s for s in self.symbols[:20] if s not in invalid_symbols]
        
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
                
                # 记录每个币种的诊断信息
                logging.info(f"📊 {symbol} | 价格:{last['close']:.2f} ADX:{last['adx']:.1f} Stoch:{last['stoch_k']:.1f} EMA200:{last['ema200']:.2f}")
                
                # 入场条件：ADX > 15（趋势存在）+ 价格与EMA关系 + StochRSI信号
                adx_ok = last['adx'] > 15
                
                # 做多条件
                if adx_ok and last['close'] > last['ema200']:
                    # 超卖区金叉（标准做多）
                    if last['stoch_k'] < 30 and last['stoch_k'] > last['stoch_d'] and prev['stoch_k'] <= prev['stoch_d']:
                        signals[symbol] = 'buy'
                        logging.info(f"🚨 BUY SIGNAL: {symbol} | 价格: {last['close']:.2f} | ADX: {last['adx']:.1f} | StochRSI: {last['stoch_k']:.1f} (超卖金叉)")
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
                    # 超买区死叉（标准做空）
                    if last['stoch_k'] > 70 and last['stoch_k'] < last['stoch_d'] and prev['stoch_k'] >= prev['stoch_d']:
                        signals[symbol] = 'sell'
                        logging.info(f"🚨 SELL SIGNAL: {symbol} | 价格: {last['close']:.2f} | ADX: {last['adx']:.1f} | StochRSI: {last['stoch_k']:.1f} (超买死叉)")
                        return signals
                    # 趋势延续：反弹到EMA附近后回落
                    elif last['close'] < last['ema200'] * 1.02 and last['stoch_k'] < last['stoch_d']:
                        # 价格在EMA下方2%以内，且StochRSI死叉
                        if prev['close'] > prev['ema200'] * 0.98:
                            signals[symbol] = 'sell'
                            logging.info(f"🚨 SELL SIGNAL: {symbol} | 价格: {last['close']:.2f} | ADX: {last['adx']:.1f} (趋势延续)")
                            return signals
                        
            except Exception as e:
                logging.warning(f"⚠️ Error scanning {symbol}: {str(e)[:50]}")
                continue
        
        logging.info(f"📭 No signals found after scanning {len(scan_symbols)} symbols")
        return None

    def calculate_exit_signals(self, exchange, symbol, current_side, entry_price, max_profit_pct=0):
        """
        智能平仓判断 - 支持动态止盈止损
        
        Args:
            max_profit_pct: 持仓期间达到的最大盈利百分比（用于移动止盈）
        """
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='5m', limit=100)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df = self.calculate_indicators(df)
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 计算当前盈亏百分比
        if current_side == 'LONG':
            current_pnl_pct = ((last['close'] - entry_price) / entry_price) * 100
        else:  # SHORT
            current_pnl_pct = ((entry_price - last['close']) / entry_price) * 100
        
        # ========== 1. 紧急止损（硬止损）==========
        # 亏损超过5%立即止损
        if current_pnl_pct < -5.0:
            return f"emergency_stop_loss:{current_pnl_pct:.2f}%"
        
        # ========== 2. 移动止盈（动态止盈）==========
        # 如果盈利超过3%，启动移动止盈（回撤1.5%止盈）
        if max_profit_pct > 3.0:
            drawdown_from_max = max_profit_pct - current_pnl_pct
            if drawdown_from_max > 1.5:  # 从最高点回撤1.5%
                return f"trailing_stop:{max_profit_pct:.2f}%->{current_pnl_pct:.2f}%"
        
        # 如果盈利超过6%，收紧移动止盈（回撤1%止盈）
        if max_profit_pct > 6.0:
            drawdown_from_max = max_profit_pct - current_pnl_pct
            if drawdown_from_max > 1.0:  # 从最高点回撤1%
                return f"tight_trailing_stop:{max_profit_pct:.2f}%->{current_pnl_pct:.2f}%"
        
        # ========== 3. 趋势反转信号 ==========
        if current_side == 'LONG':
            # 价格跌破EMA200（趋势反转）
            if last['close'] < last['ema200'] * 0.995:  # 允许0.5%的误差
                return "trend_broken_down"
            
            # StochRSI超买区死叉（动量衰竭）
            if last['stoch_k'] > 80 and last['stoch_k'] < last['stoch_d']:
                return "momentum_exhaustion_long"
            
            # 趋势强度大幅减弱
            if last['adx'] < prev['adx'] and last['adx'] < 20:
                return "trend_weakening_long"
            
            # 价格触及布林带上轨且出现反转信号
            if last['close'] > last['bb_upper'] and last['stoch_k'] > 80:
                return "bb_upper_reversal"
                
        elif current_side == 'SHORT':
            # 价格突破EMA200（趋势反转）
            if last['close'] > last['ema200'] * 1.005:  # 允许0.5%的误差
                return "trend_broken_up"
            
            # StochRSI超卖区金叉（动量衰竭）
            if last['stoch_k'] < 20 and last['stoch_k'] > last['stoch_d']:
                return "momentum_exhaustion_short"
            
            # 趋势强度大幅减弱
            if last['adx'] < prev['adx'] and last['adx'] < 20:
                return "trend_weakening_short"
            
            # 价格触及布林带下轨且出现反转信号
            if last['close'] < last['bb_lower'] and last['stoch_k'] < 20:
                return "bb_lower_reversal"

        # ========== 4. 异常波动/情绪 (Volume Spike) ==========
        if last['volume'] > last['vol_ma'] * 3:
            price_move = abs(last['close'] - last['open'])
            if price_move < (last['atr'] * 0.5):  # 巨量小实体，意味着分歧巨大
                return "volume_exhaustion_sentiment"
        
        # ========== 5. 大幅回调预警 ==========
        # 如果短时间内出现大幅回调（1小时内回调超过2%）
        if len(df) >= 12:  # 1小时 = 12个5分钟K线
            recent_high = df['high'].tail(12).max()
            recent_low = df['low'].tail(12).min()
            
            if current_side == 'LONG':
                drop_from_high = ((recent_high - last['close']) / recent_high) * 100
                if drop_from_high > 2.0:  # 1小时内从高点回调超过2%
                    return f"sharp_pullback_long:{drop_from_high:.2f}%"
            else:  # SHORT
                rise_from_low = ((last['close'] - recent_low) / recent_low) * 100
                if rise_from_low > 2.0:  # 1小时内从低点反弹超过2%
                    return f"sharp_pullback_short:{rise_from_low:.2f}%"

        return None
    
    def calculate_dynamic_stop_loss(self, entry_price, current_side, atr_value, volatility_factor=1.5):
        """
        计算动态止损价格
        
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
