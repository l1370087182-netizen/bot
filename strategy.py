import logging
import pandas as pd
import numpy as np
import time

class Strategy:
    def __init__(self, symbols):
        self.symbols = symbols
        self.macro_cache = {}  # 趋势缓存: {symbol: {'data': trends, 'ts': timestamp}}
        self.cache_ttl = 600    # 10分钟缓存，减少 API 压力

    def calculate_indicators(self, df):
        """计算 v8.5 专业级量化因子 (Dynamic Filter Enhanced)"""
        # 1. EMA 200 (基准趋势)
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
        
        # 2. Stochastic RSI (动量)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, 0.001)
        df['rsi'] = 100 - (100 / (1 + rs))
        
        rsi_min = df['rsi'].rolling(window=14).min()
        rsi_max = df['rsi'].rolling(window=14).max()
        stoch_rsi = (df['rsi'] - rsi_min) / (rsi_max - rsi_min).replace(0, 0.001)
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
        plus_dm = df['high'].diff().clip(lower=0)
        minus_dm = (-df['low'].diff()).clip(lower=0)
        tr_smooth = df['tr'].rolling(14).mean()
        plus_di = 100 * (plus_dm.rolling(14).mean() / tr_smooth.replace(0, 0.001))
        minus_di = 100 * (minus_dm.rolling(14).mean() / tr_smooth.replace(0, 0.001))
        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, 0.001)
        df['adx'] = dx.rolling(14).mean()
        
        # 5. MFI (资金流)
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        money_flow = typical_price * df['volume']
        positive_flow = money_flow.where(typical_price > typical_price.shift(1), 0).rolling(14).sum()
        negative_flow = money_flow.where(typical_price < typical_price.shift(1), 0).rolling(14).sum()
        mfi_rs = positive_flow / negative_flow.replace(0, 1)
        df['mfi'] = 100 - (100 / (1 + mfi_rs))
        
        # 6. 布林带挤压
        df['bb_mid'] = df['close'].rolling(20).mean()
        df['bb_std'] = df['close'].rolling(20).std()
        df['bb_upper'] = df['bb_mid'] + (df['bb_std'] * 2)
        df['bb_lower'] = df['bb_mid'] - (df['bb_std'] * 2)
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_mid'].replace(0, 1)
        df['squeeze'] = df['bb_width'] < df['bb_width'].rolling(100).quantile(0.2)
        
        df['vol_ma'] = df['volume'].rolling(window=20).mean()
        return df

    def get_macro_trends_batch(self, exchange, symbols):
        """批量获取宏观趋势，减少API调用次数"""
        now = time.time()
        trends_batch = {}
        
        for symbol in symbols:
            # 检查缓存
            if symbol in self.macro_cache and (now - self.macro_cache[symbol]['ts'] < self.cache_ttl):
                trends_batch[symbol] = self.macro_cache[symbol]['data']
                continue
            
            trends = {'1h': 'UNKNOWN', '4h': 'UNKNOWN', 'score': 0}
            try:
                # 获取 1H 趋势
                ohlcv_1h = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=205)
                df_1h = pd.DataFrame(ohlcv_1h, columns=['t','o','h','l','c','v'])
                ema200_1h = df_1h['c'].ewm(span=200, adjust=False).mean().iloc[-1]
                trends['1h'] = 'UP' if df_1h['c'].iloc[-1] > ema200_1h else 'DOWN'
                
                # 获取 4H 趋势
                ohlcv_4h = exchange.fetch_ohlcv(symbol, timeframe='4h', limit=205)
                df_4h = pd.DataFrame(ohlcv_4h, columns=['t','o','h','l','c','v'])
                ema200_4h = df_4h['c'].ewm(span=200, adjust=False).mean().iloc[-1]
                trends['4h'] = 'UP' if df_4h['c'].iloc[-1] > ema200_4h else 'DOWN'
                
                trends['score'] = (1 if trends['1h'] == 'UP' else -1) + (1 if trends['4h'] == 'UP' else -1)
                self.macro_cache[symbol] = {'data': trends, 'ts': now}
                trends_batch[symbol] = trends
            except Exception as e:
                logging.error(f"Macro Trend Error for {symbol}: {e}")
                trends_batch[symbol] = trends
        
        return trends_batch

    def check_volatility_filter(self, df):
        """动态过滤器 B：RVF 相对波动率过滤器"""
        last = df.iloc[-1]
        atr_avg = df['atr'].rolling(100).mean().iloc[-1]
        
        # 避免波动率过低 (横盘死鱼) 或过高 (剧烈插针)
        # 动态区间: 0.6x - 3.5x
        is_active = last['atr'] > (atr_avg * 0.6)
        is_safe = last['atr'] < (atr_avg * 3.5)
        
        return is_active and is_safe

    def calculate_signals(self, exchange):
        """计算 v9.0 动态双周期过滤器信号 - 优化版"""
        signals = {}
        invalid_symbols = {'MATIC/USDT:USDT', 'TUSD/USDT:USDT', 'USDC/USDT:USDT'}
        scan_symbols = [s for s in self.symbols[:49] if s not in invalid_symbols]
        
        logging.info(f"🔍 v9.0 动态双过滤器扫描启动 ({len(scan_symbols)} coins)...")
        scan_start_time = time.time()
        
        # 预加载所有宏观趋势（带缓存）
        logging.info("⏳ 预加载宏观趋势数据...")
        trends_batch = self.get_macro_trends_batch(exchange, scan_symbols)
        
        for symbol in scan_symbols:
            try:
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe='30m', limit=300)
                if len(ohlcv) < 200: 
                    logging.warning(f"⚠️ {symbol}: 数据不足 {len(ohlcv)} < 200")
                    continue
                    
                df = self.calculate_indicators(pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']))
                
                curr_k = df.iloc[-1] 
                last_closed = df.iloc[-2] 
                prev_closed = df.iloc[-3]
                
                not_squeezing = not last_closed['squeeze']
                trends = trends_batch.get(symbol, {'1h': 'UNKNOWN', '4h': 'UNKNOWN'})
                vol_ok = self.check_volatility_filter(df)
                
                # 记录所有币种指标（全面监控）
                logging.info(f"📊 {symbol} | 1H:{trends['1h']} | Vol:{'OK' if vol_ok else 'LOW'} | ADX:{curr_k['adx']:.1f} | Stoch:{last_closed['stoch_k']:.1f}")

                # --- 多头判定 ---
                if trends['1h'] == 'UP' and vol_ok and curr_k['adx'] > 10 and not_squeezing:
                    if last_closed['close'] > last_closed['ema200']:
                        if last_closed['stoch_k'] < 45 and last_closed['stoch_k'] > last_closed['stoch_d'] and prev_closed['stoch_k'] <= prev_closed['stoch_d']:
                            if last_closed['mfi'] > 40:
                                strength = 'FULL' if trends['4h'] == 'UP' else 'HALF'
                                signals[symbol] = {'side': 'buy', 'strength': strength}
                                logging.info(f"🚨 v9.0 BUY: {symbol} | Strength:{strength} | 1H:UP 4H:{trends['4h']}")

                # --- 空头判定 ---
                if trends['1h'] == 'DOWN' and vol_ok and curr_k['adx'] > 10 and not_squeezing:
                    if last_closed['close'] < last_closed['ema200']:
                        is_rebounding = curr_k['rsi'] > last_closed['rsi'] and curr_k['rsi'] > 30 and any(df['rsi'].tail(5) < 30)
                        if not is_rebounding:
                            if last_closed['stoch_k'] > 55 and last_closed['stoch_k'] < last_closed['stoch_d'] and prev_closed['stoch_k'] >= prev_closed['stoch_d']:
                                if last_closed['mfi'] < 60:
                                    strength = 'FULL' if trends['4h'] == 'DOWN' else 'HALF'
                                    signals[symbol] = {'side': 'sell', 'strength': strength}
                                    logging.info(f"🚨 v9.0 SELL: {symbol} | Strength:{strength} | 1H:DOWN 4H:{trends['4h']}")
                        
            except Exception as e:
                logging.error(f"❌ Signal calculation error for {symbol}: {str(e)}")
                continue
        
        scan_duration = time.time() - scan_start_time
        logging.info(f"🏁 扫描完成。耗时: {scan_duration:.1f}s | 发现信号: {len(signals)}")
        return signals if signals else None

    def calculate_exit_signals(self, exchange, symbol, current_side, entry_price, max_profit_pct=0, position_tracking=None):
        """智能平仓 - v3.0 动态 ATR 止损版"""
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
        df = self.calculate_indicators(pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']))
        curr = df.iloc[-1]
        current_price = curr['close']
        
        pnl = ((current_price - entry_price) / entry_price * 100) if current_side == 'LONG' else ((entry_price - current_price) / entry_price * 100)

        # v3.0 优化: 基础 ATR 2.8x 移动止损
        mult = 2.8
        
        # 盈利后的指数级动态收紧
        if max_profit_pct > 5.0: mult = 2.2
        if max_profit_pct > 10.0: mult = 1.8 
        
        atr_data = self.calculate_atr_trailing_stop(df, current_side, atr_multiplier=mult)
        stop_price = atr_data['stop_price']
        
        # 1. 保本锁 (防止利润回吐到亏损)
        if max_profit_pct >= 1.8:
            be = entry_price * (1 + 0.005) if current_side == 'LONG' else entry_price * (1 - 0.005)
            stop_price = max(stop_price, be) if current_side == 'LONG' else min(stop_price, be)
        
        # 2. 5% 级锁利
        if max_profit_pct >= 5.0:
            l5 = entry_price * (1 + 0.03) if current_side == 'LONG' else entry_price * (1 - 0.03)
            stop_price = max(stop_price, l5) if current_side == 'LONG' else min(stop_price, l5)

        if (current_side == 'LONG' and current_price <= stop_price) or (current_side == 'SHORT' and current_price >= stop_price):
            return f"shield_exit:{pnl:.2f}%"
        
        if pnl < -15.0: return f"hard_stop:{pnl:.2f}%" # 硬止损
        return None

    def calculate_signal_for_symbol(self, exchange, symbol, df):
        """计算单个币种的信号 (供v10.0使用)"""
        try:
            df = self.calculate_indicators(df)
            
            curr = df.iloc[-1]
            last_closed = df.iloc[-2]
            prev_closed = df.iloc[-3]
            
            # 检查数据质量
            if len(df) < 200:
                return None
            
            # 获取宏观趋势
            trends = self.get_macro_trends(exchange, symbol)
            
            # 波动率检查
            vol_ok = self.check_volatility_filter(df)
            if not vol_ok:
                return None
            
            # 布林带挤压
            not_squeezing = not last_closed['squeeze']
            
            signal_data = {
                'symbol': symbol,
                'adx': curr['adx'],
                'trend_1h': trends['1h'],
                'trend_4h': trends['4h'],
                'bb_squeeze': last_closed['squeeze'],
                'volume_surge': curr['volume'] > curr['vol_ma'] * 1.5,
                'funding_rate': 0,  # 需要外部获取
                'atr': curr['atr'],
                'ema200': last_closed['ema200'],
                'close': last_closed['close'],
                'stoch_k': last_closed['stoch_k'],
                'stoch_d': last_closed['stoch_d'],
                'mfi': last_closed['mfi']
            }
            
            # 多头信号
            if trends['1h'] == 'UP' and curr['adx'] > 10 and not_squeezing:
                if last_closed['close'] > last_closed['ema200']:
                    if last_closed['stoch_k'] < 45 and last_closed['stoch_k'] > last_closed['stoch_d']:
                        if last_closed['mfi'] > 40:
                            signal_data['side'] = 'buy'
                            signal_data['strength'] = 'FULL' if trends['4h'] == 'UP' else 'HALF'
                            return signal_data
            
            # 空头信号
            if trends['1h'] == 'DOWN' and curr['adx'] > 10 and not_squeezing:
                if last_closed['close'] < last_closed['ema200']:
                    is_rebounding = curr['rsi'] > last_closed['rsi'] and curr['rsi'] > 30
                    if not is_rebounding:
                        if last_closed['stoch_k'] > 55 and last_closed['stoch_k'] < last_closed['stoch_d']:
                            if last_closed['mfi'] < 60:
                                signal_data['side'] = 'sell'
                                signal_data['strength'] = 'FULL' if trends['4h'] == 'DOWN' else 'HALF'
                                return signal_data
            
            return None
            
        except Exception as e:
            logging.error(f"Signal calculation error for {symbol}: {e}")
            return None

    def calculate_atr_trailing_stop(self, df, current_side, atr_multiplier=2.0):
        last = df.iloc[-1]
        atr = last['atr']
        lookback = 20
        if current_side == 'LONG':
            stop = df['high'].tail(lookback).max() - (atr * atr_multiplier)
        else:
            stop = df['low'].tail(lookback).min() + (atr * atr_multiplier)
        return {'stop_price': stop}
