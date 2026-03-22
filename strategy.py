import logging
import pandas as pd
import numpy as np
import time
import sys

# 添加 src 路径以导入 CVD 模块
sys.path.insert(0, 'src')

try:
    from orderflow.cvd_analyzer import CVDFilter
    CVD_AVAILABLE = True
except ImportError as e:
    CVD_AVAILABLE = False
    # 延迟到实例化时再记录日志
    _cvd_import_error = e

# 导入ML信号过滤器
try:
    from ml.ml_signal_filter import MLSignalFilter
    ML_AVAILABLE = True
except ImportError as e:
    ML_AVAILABLE = False
    _ml_import_error = e

class Strategy:
    def __init__(self, symbols):
        self.symbols = symbols
        self.macro_cache = {}  # 趋势缓存: {symbol: {'data': trends, 'ts': timestamp}}
        self.cache_ttl = 600    # 10分钟缓存，减少 API 压力
        
        # 逆势交易风控状态
        self.counter_trend_state = {
            'enabled': True,           # 逆势交易是否启用
            'daily_loss_triggered': False,  # 今日是否已亏损
            'loss_date': None,         # 亏损发生的日期
            'today_loss_count': 0,     # 今日逆势亏损次数
            'today_profit_count': 0    # 今日逆势盈利次数
        }
        
        # CVD 订单流过滤器 (放宽置信度到 45%)
        if CVD_AVAILABLE:
            self.cvd_filter = CVDFilter(min_confidence=45)
            logging.info("📊 CVD 订单流分析器已启用 (最小置信度: 45%)")
        else:
            self.cvd_filter = None
            if '_cvd_import_error' in globals():
                logging.warning(f"⚠️ CVD 订单流分析器未启用: {_cvd_import_error}")
            else:
                logging.warning("⚠️ CVD 订单流分析器未启用")
        
        # ML信号过滤器
        if ML_AVAILABLE:
            self.ml_filter = MLSignalFilter(min_samples=30)
            if self.ml_filter.is_trained:
                logging.info("🤖 ML信号过滤器已启用 (模型已训练)")
            else:
                logging.info("🤖 ML信号过滤器已启用 (等待收集训练数据)")
        else:
            self.ml_filter = None
            if '_ml_import_error' in globals():
                logging.warning(f"⚠️ ML信号过滤器未启用: {_ml_import_error}")
            else:
                logging.warning("⚠️ ML信号过滤器未启用")

    def calculate_hurst_exponent(self, prices, max_lag=50):
        """
        计算 Hurst 指数 - 使用RS方法 (Rescaled Range)
        H > 0.5: 趋势性市场 (持久性)
        H = 0.5: 随机游走
        H < 0.5: 均值回归 (反持久性)
        """
        try:
            prices = np.array(prices)
            n = len(prices)
            
            if n < 100:
                return 0.5  # 数据不足
            
            # 计算对数收益率
            log_returns = np.diff(np.log(prices))
            log_returns = log_returns[~np.isnan(log_returns)]
            log_returns = log_returns[~np.isinf(log_returns)]
            
            if len(log_returns) < 50:
                return 0.5
            
            # RS方法
            lags = [10, 20, 30, 40, 50]
            rs_values = []
            
            for lag in lags:
                if lag >= len(log_returns):
                    continue
                    
                # 分段计算
                segments = len(log_returns) // lag
                rs_list = []
                
                for i in range(segments):
                    segment = log_returns[i*lag:(i+1)*lag]
                    if len(segment) < lag:
                        continue
                    
                    mean_return = np.mean(segment)
                    cumdev = np.cumsum(segment - mean_return)
                    R = np.max(cumdev) - np.min(cumdev)
                    S = np.std(segment)
                    
                    if S > 0:
                        rs_list.append(R / S)
                
                if rs_list:
                    rs_values.append((lag, np.mean(rs_list)))
            
            if len(rs_values) < 3:
                return 0.5
            
            # 对数回归
            log_lags = np.log([x[0] for x in rs_values])
            log_rs = np.log([x[1] for x in rs_values])
            
            # 线性回归计算 Hurst
            slope, _ = np.polyfit(log_lags, log_rs, 1)
            hurst = slope
            
            # 限制在合理范围
            return np.clip(hurst, 0.1, 0.9)
            
        except Exception as e:
            logging.warning(f"Hurst计算错误: {e}")
            return 0.5  # 出错时返回随机游走

    def calculate_indicators(self, df):
        """计算 v12.0 自适应量化因子 (Hurst + 波动率挤压增强)"""
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
        
        # 限制 StochRSI 在 0-1 范围内，防止异常值
        stoch_rsi = stoch_rsi.clip(0, 1)
        
        df['stoch_k'] = stoch_rsi.rolling(window=3).mean() * 100
        df['stoch_d'] = df['stoch_k'].rolling(window=3).mean() * 100
        
        # 再次限制 K 和 D 在 0-100 范围内
        df['stoch_k'] = df['stoch_k'].clip(0, 100)
        df['stoch_d'] = df['stoch_d'].clip(0, 100)
        
        # 3. ATR (波动率) - 基础计算
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
        
        # 6. 布林带挤压 (v12.0 增强版)
        df['bb_mid'] = df['close'].rolling(20).mean()
        df['bb_std'] = df['close'].rolling(20).std()
        df['bb_upper'] = df['bb_mid'] + (df['bb_std'] * 2)
        df['bb_lower'] = df['bb_mid'] - (df['bb_std'] * 2)
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_mid'].replace(0, 1)
        
        # v12.0: 动态挤压阈值 - 基于历史分位数
        df['bb_width_percentile'] = df['bb_width'].rolling(100).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1] if len(x) > 0 else 0.5, raw=False)
        df['squeeze'] = df['bb_width_percentile'] < 0.15  # 挤压 = 宽度在历史底部 15%
        df['squeeze_release'] = (df['bb_width_percentile'].shift(1) < 0.15) & (df['bb_width_percentile'] >= 0.15)  # 挤压释放信号
        
        # 7. Hurst 指数 (v12.0 新增)
        df['hurst'] = df['close'].rolling(window=100).apply(lambda x: self.calculate_hurst_exponent(x.values) if len(x) >= 50 else 0.5, raw=False)
        
        # 8. 自适应 ATR 乘数 (基于 Hurst)
        df['atr_multiplier'] = df['hurst'].apply(lambda h: 2.2 if h > 0.55 else (2.8 if h > 0.45 else 3.5))
        
        df['vol_ma'] = df['volume'].rolling(window=20).mean()
        return df

    def get_macro_trends_batch(self, exchange, symbols):
        """批量获取宏观趋势，减少API调用次数"""
        now = time.time()
        trends_batch = {}
        total = len(symbols)
        
        for i, symbol in enumerate(symbols):
            # 检查缓存
            if symbol in self.macro_cache and (now - self.macro_cache[symbol]['ts'] < self.cache_ttl):
                trends_batch[symbol] = self.macro_cache[symbol]['data']
                continue
            
            # 每 10 个币种打印一次进度
            if i % 10 == 0:
                logging.info(f"⏳ 预加载宏观趋势进度: {i}/{total}...")
            
            trends = {'1h': 'UNKNOWN', '4h': 'UNKNOWN', 'score': 0}
            try:
                # 间隔 0.05s 防止频率限制
                time.sleep(0.05)
                
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
                # 遇到错误多等一会儿
                time.sleep(1)
        
        logging.info("✅ 宏观趋势数据预加载完成。")
        return trends_batch

    def check_volatility_filter(self, df):
        """v12.0 自适应波动率过滤器 (Hurst 增强)"""
        last = df.iloc[-1]
        atr_avg = df['atr'].rolling(100).mean().iloc[-1]
        hurst = last['hurst']
        
        # 基于 Hurst 指数调整波动率容忍度
        if hurst > 0.55:
            # 强趋势市场：允许更高波动率，更积极交易
            min_mult, max_mult = 0.2, 5.0
        elif hurst < 0.45:
            # 均值回归市场：严格限制波动率，减少交易
            min_mult, max_mult = 0.5, 3.5
        else:
            # 随机游走：标准设置
            min_mult, max_mult = 0.3, 4.0
        
        is_active = last['atr'] > (atr_avg * min_mult)
        is_safe = last['atr'] < (atr_avg * max_mult)
        
        return is_active and is_safe
    
    def check_squeeze_release_filter(self, df):
        """v12.0 波动率挤压释放过滤器"""
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 挤压释放条件：之前处于挤压状态，现在突破
        was_squeezed = prev['bb_width_percentile'] < 0.15
        now_expanding = last['bb_width_percentile'] >= 0.20
        
        # 同时要求价格突破布林带
        price_breakout = (last['close'] > last['bb_upper']) or (last['close'] < last['bb_lower'])
        
        return was_squeezed and now_expanding and price_breakout

    def check_counter_trend_allowed(self):
        """检查今日是否允许逆势交易"""
        from datetime import datetime
        today = datetime.now().strftime('%Y-%m-%d')
        
        # 如果日期变了，重置状态
        if self.counter_trend_state['loss_date'] != today:
            self.counter_trend_state['daily_loss_triggered'] = False
            self.counter_trend_state['loss_date'] = None
            self.counter_trend_state['today_loss_count'] = 0
            self.counter_trend_state['today_profit_count'] = 0
            logging.info("📅 新的一天，重置逆势交易状态")
        
        return not self.counter_trend_state['daily_loss_triggered']
    
    def on_counter_trend_result(self, is_profit):
        """记录逆势交易结果"""
        from datetime import datetime
        today = datetime.now().strftime('%Y-%m-%d')
        
        if is_profit:
            self.counter_trend_state['today_profit_count'] += 1
            logging.info(f"✅ 逆势交易盈利，今日逆势盈利次数: {self.counter_trend_state['today_profit_count']}")
        else:
            self.counter_trend_state['daily_loss_triggered'] = True
            self.counter_trend_state['loss_date'] = today
            self.counter_trend_state['today_loss_count'] += 1
            logging.warning(f"🛑 逆势交易亏损！今日逆势交易已暂停。亏损次数: {self.counter_trend_state['today_loss_count']}")

    def calculate_signals(self, exchange):
        """计算 v12.0 自适应双周期 + Hurst + 波动率挤压策略"""
        signals = {}
        invalid_symbols = {'MATIC/USDT:USDT', 'TUSD/USDT:USDT', 'USDC/USDT:USDT'}
        scan_symbols = [s for s in self.symbols[:49] if s not in invalid_symbols]
        
        # 检查逆势交易状态
        counter_trend_allowed = self.check_counter_trend_allowed()
        if not counter_trend_allowed:
            logging.warning("⚠️ 今日逆势交易已因亏损暂停，仅扫描顺势信号")
        
        logging.info(f"🔍 v12.0 自适应Hurst+挤压释放扫描 ({len(scan_symbols)} coins)...")
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
                hurst = curr_k['hurst']
                
                # 记录所有币种指标（全面监控）
                logging.info(f"📊 {symbol} | 1H:{trends['1h']} | H:{hurst:.2f} | 波动率:{'正常' if vol_ok else '过低'} | ADX:{curr_k['adx']:.1f} | Stoch:{last_closed['stoch_k']:.1f} | 挤压:{'是' if last_closed['squeeze'] else '否'}")

                # ========== v12.0 波动率挤压释放启动机制 ==========
                squeeze_release = self.check_squeeze_release_filter(df)
                
                # 基于 Hurst 调整 ADX 阈值（放宽）
                adx_threshold = 3 if hurst > 0.55 else (5 if hurst > 0.45 else 8)
                
                # ========== v14.0 多时间框架趋势过滤 ==========
                # 放宽条件：1H和4H趋势一致，或4H为UNKNOWN时允许1H趋势
                trend_aligned = (trends['1h'] == trends['4h'] and trends['1h'] != 'UNKNOWN') or \
                               (trends['4h'] == 'UNKNOWN' and trends['1h'] != 'UNKNOWN')
                
                if not trend_aligned:
                    continue  # 趋势不一致，跳过
                
                if trends['1h'] == 'UP' and vol_ok and curr_k['adx'] > adx_threshold:
                    # 放宽 StochRSI 条件
                    stoch_threshold = 85 if squeeze_release else 80
                    stoch_ok = last_closed['stoch_k'] < stoch_threshold
                    
                    # 放宽EMA条件：价格在EMA200上方 或 差距<5%
                    ema_gap = abs(last_closed['close'] - last_closed['ema200']) / last_closed['ema200']
                    ema_ok = last_closed['close'] > last_closed['ema200'] or ema_gap < 0.05
                    
                    if ema_ok:
                        # 极度放宽金叉条件：K在D上方 或 K持续上升 或 KD接近
                        golden_cross = (last_closed['stoch_k'] > last_closed['stoch_d'] and prev_closed['stoch_k'] <= prev_closed['stoch_d'])
                        k_rising = last_closed['stoch_k'] > prev_closed['stoch_k'] and last_closed['stoch_k'] < 50
                        near_cross = abs(last_closed['stoch_k'] - last_closed['stoch_d']) < 15
                        
                        # 信号质量检查：放宽KD差距范围
                        kd_gap = abs(last_closed['stoch_k'] - last_closed['stoch_d'])
                        if kd_gap < 3 or kd_gap > 50:
                            continue  # KD差距太小或太大，信号质量低
                        
                        if stoch_ok and (golden_cross or k_rising or near_cross):
                            strength = '全仓' if trends['4h'] == 'UP' else '半仓'
                            signal_type = '挤压' if squeeze_release else '趋势'
                            signals[symbol] = {'side': 'buy', 'strength': strength, 'type': signal_type, 'hurst': hurst}
                            logging.info(f"🚨 [{signal_type}] 买入信号: {symbol} | 强度:{strength} | H:{hurst:.2f} | Stoch:{last_closed['stoch_k']:.1f} | KD差:{kd_gap:.1f}")

                if trends['1h'] == 'DOWN' and vol_ok and curr_k['adx'] > adx_threshold:
                    stoch_threshold = 15 if squeeze_release else 20
                    stoch_ok = last_closed['stoch_k'] > stoch_threshold
                    
                    # 放宽EMA条件
                    ema_gap = abs(last_closed['close'] - last_closed['ema200']) / last_closed['ema200']
                    ema_ok = last_closed['close'] < last_closed['ema200'] or ema_gap < 0.05
                    
                    if ema_ok:
                        # 极度放宽死叉条件
                        dead_cross = (last_closed['stoch_k'] < last_closed['stoch_d'] and prev_closed['stoch_k'] >= prev_closed['stoch_d'])
                        k_falling = last_closed['stoch_k'] < prev_closed['stoch_k'] and last_closed['stoch_k'] > 50
                        near_cross = abs(last_closed['stoch_k'] - last_closed['stoch_d']) < 15
                        
                        # 信号质量检查：放宽KD差距范围
                        kd_gap = abs(last_closed['stoch_k'] - last_closed['stoch_d'])
                        if kd_gap < 3 or kd_gap > 50:
                            continue
                        
                        if stoch_ok and (dead_cross or k_falling or near_cross):
                            strength = '全仓' if trends['4h'] == 'DOWN' else '半仓'
                            signal_type = '挤压' if squeeze_release else '趋势'
                            signals[symbol] = {'side': 'sell', 'strength': strength, 'type': signal_type, 'hurst': hurst}
                            logging.info(f"🚨 [{signal_type}] 卖出信号: {symbol} | 强度:{strength} | H:{hurst:.2f} | Stoch:{last_closed['stoch_k']:.1f} | KD差:{kd_gap:.1f}")
                
                # ========== 逆势交易信号 (仅当允许时) ==========
                if counter_trend_allowed and vol_ok and not_squeezing:
                    # 逆势条件：ADX < 25，StochRSI 极端值
                    
                    if trends['1h'] == 'UP' and curr_k['adx'] < 25:
                        if last_closed['stoch_k'] > 85 and last_closed['stoch_k'] < last_closed['stoch_d'] and prev_closed['stoch_k'] >= prev_closed['stoch_d']:
                            signals[symbol] = {'side': 'sell', 'strength': 'COUNTER', 'type': 'counter', 'hurst': hurst}
                            logging.info(f"🔄 [逆势] SELL: {symbol} | 超买回调 | Stoch:{last_closed['stoch_k']:.1f} | H:{hurst:.2f}")
                    
                    if trends['1h'] == 'DOWN' and curr_k['adx'] < 25:
                        if last_closed['stoch_k'] < 15 and last_closed['stoch_k'] > last_closed['stoch_d'] and prev_closed['stoch_k'] <= prev_closed['stoch_d']:
                            signals[symbol] = {'side': 'buy', 'strength': 'COUNTER', 'type': 'counter', 'hurst': hurst}
                            logging.info(f"🔄 [逆势] BUY: {symbol} | 超卖反弹 | Stoch:{last_closed['stoch_k']:.1f} | H:{hurst:.2f}")
                        
            except Exception as e:
                logging.error(f"❌ Signal calculation error for {symbol}: {str(e)}")
                continue
        
        scan_duration = time.time() - scan_start_time
        
        # ========== v13.0: CVD 订单流过滤 ==========
        filtered_symbols = []  # 记录被过滤的信号
        if signals and self.cvd_filter:
            logging.info("📊 启动 CVD 订单流验证...")
            original_count = len(signals)
            original_signals = signals.copy()  # 保存原始信号
            signals = self.cvd_filter.filter_signals(signals, exchange)
            filtered_count = original_count - len(signals)
            if filtered_count > 0:
                logging.warning(f"🛑 CVD 过滤: 拦截 {filtered_count} 个假突破信号")
                # 找出被过滤的信号
                for sym in original_signals:
                    if sym == '_filtered':  # 跳过特殊键
                        continue
                    if sym not in signals:
                        signal_data = original_signals[sym]
                        # 确保信号数据是字典类型
                        if isinstance(signal_data, dict):
                            filtered_symbols.append({
                                'symbol': sym,
                                'side': signal_data.get('side', 'unknown'),
                                'type': signal_data.get('type', 'unknown')
                            })
        
        # ========== v14.0: ML信号过滤 ==========
        if signals and self.ml_filter and self.ml_filter.is_trained:
            logging.info("🤖 启动 ML 信号过滤...")
            ml_filtered = []
            for sym in list(signals.keys()):
                if sym == '_filtered':
                    continue
                signal_info = signals[sym]
                side = signal_info.get('side') if isinstance(signal_info, dict) else signal_info
                
                # 获取该币种的DataFrame进行ML预测
                try:
                    ohlcv = exchange.fetch_ohlcv(sym, timeframe='30m', limit=50)
                    df = self.calculate_indicators(pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']))
                    
                    ml_result = self.ml_filter.predict(df, side)
                    
                    if not ml_result['should_trade']:
                        logging.warning(f"🛑 ML过滤: {sym} | 置信度: {ml_result['confidence']:.1%} | {ml_result['reason']}")
                        ml_filtered.append({
                            'symbol': sym,
                            'side': side,
                            'type': signal_info.get('type', 'unknown') if isinstance(signal_info, dict) else 'unknown',
                            'ml_confidence': ml_result['confidence'],
                            'ml_reason': ml_result['reason']
                        })
                        del signals[sym]
                    else:
                        logging.info(f"✅ ML通过: {sym} | 置信度: {ml_result['confidence']:.1%} | {ml_result['reason']}")
                        # 添加ML信息到信号
                        if isinstance(signal_info, dict):
                            signal_info['ml_confidence'] = ml_result['confidence']
                            signal_info['ml_reason'] = ml_result['reason']
                except Exception as e:
                    logging.error(f"❌ ML过滤错误 {sym}: {e}")
                    continue
            
            if ml_filtered:
                logging.warning(f"🛑 ML过滤: 拦截 {len(ml_filtered)} 个低置信度信号")
                filtered_symbols.extend(ml_filtered)
        
        signal_types = {'趋势': 0, '挤压': 0, 'counter': 0}
        for sym, s in signals.items():
            if sym == '_filtered':  # 跳过特殊键
                continue
            if isinstance(s, dict):
                signal_types[s.get('type', '趋势')] += 1
        logging.info(f"🏁 扫描完成。耗时: {scan_duration:.1f}s | 发现信号: {len(signals)} (顺势:{signal_types['趋势']}, 挤压:{signal_types['挤压']}, 逆势:{signal_types['counter']})")
        
        # 返回信号和被过滤的信号列表
        result = signals if signals else None
        if result and filtered_symbols:
            # 将过滤列表附加到结果中（通过特殊键）
            result['_filtered'] = filtered_symbols
        return result

    def calculate_exit_signals(self, exchange, symbol, current_side, entry_price, max_profit_pct=0, position_tracking=None):
        """智能平仓 - v12.0 Hurst 自适应 ATR 止损版"""
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
        df = self.calculate_indicators(pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']))
        curr = df.iloc[-1]
        current_price = curr['close']
        hurst = curr['hurst']
        
        pnl = ((current_price - entry_price) / entry_price * 100) if current_side == 'LONG' else ((entry_price - current_price) / entry_price * 100)

        # v12.0: 基于 Hurst 的自适应 ATR 乘数
        # H > 0.55 (强趋势): 更紧的止损，让利润奔跑
        # H < 0.45 (均值回归): 更宽的止损，避免噪音
        if hurst > 0.55:
            base_mult = 2.2
        elif hurst < 0.45:
            base_mult = 3.5
        else:
            base_mult = 2.8
        
        # 盈利后的指数级动态收紧
        mult = base_mult
        if max_profit_pct > 5.0: mult = base_mult * 0.8
        if max_profit_pct > 10.0: mult = base_mult * 0.65
        
        atr_data = self.calculate_atr_trailing_stop(df, current_side, atr_multiplier=mult)
        stop_price = atr_data['stop_price']
        
        # 1. 保本锁 - 4% 盈利启动，保护 2% 利润
        if max_profit_pct >= 4.0:
            be = entry_price * (1 + 0.02) if current_side == 'LONG' else entry_price * (1 - 0.02)
            stop_price = max(stop_price, be) if current_side == 'LONG' else min(stop_price, be)
        
        # 2. 8% 级锁利 - 保护 5% 利润
        if max_profit_pct >= 8.0:
            l8 = entry_price * (1 + 0.05) if current_side == 'LONG' else entry_price * (1 - 0.05)
            stop_price = max(stop_price, l8) if current_side == 'LONG' else min(stop_price, l8)
        
        # 3. 12% 级锁利 - 保护 8% 利润
        if max_profit_pct >= 12.0:
            l12 = entry_price * (1 + 0.08) if current_side == 'LONG' else entry_price * (1 - 0.08)
            stop_price = max(stop_price, l12) if current_side == 'LONG' else min(stop_price, l12)
        
        # 4. 16% 级锁利 - 保护 12% 利润
        if max_profit_pct >= 16.0:
            l16 = entry_price * (1 + 0.12) if current_side == 'LONG' else entry_price * (1 - 0.12)
            stop_price = max(stop_price, l16) if current_side == 'LONG' else min(stop_price, l16)
        
        # 5. Hurst 均值回归保护: 大幅放宽，避免过早止盈
        if hurst < 0.30 and max_profit_pct > 8.0:
            return f"hurst_take_profit:{pnl:.2f}%"

        if (current_side == 'LONG' and current_price <= stop_price) or (current_side == 'SHORT' and current_price >= stop_price):
            return f"shield_exit:{pnl:.2f}%"
        
        if pnl < -15.0: return f"hard_stop:{pnl:.2f}%"
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
