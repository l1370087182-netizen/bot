import logging
import pandas as pd
import numpy as np
import time
import sys

# 添加 src 路径以导入 CVD 模块
sys.path.insert(0, 'src')

from config import (SYMBOLS, INDICATORS, CVD, EXIT_STRATEGY, PYRAMIDING, MAX_ACTIVE_SYMBOLS,
                    SIGNAL_WEIGHTS, TIMEFRAMES, PRIMARY_TIMEFRAME, CONFIRM_TIMEFRAME, FUNDING)

try:
    from orderflow.cvd_analyzer import CVDFilter
    CVD_AVAILABLE = True
except ImportError as e:
    CVD_AVAILABLE = False
    _cvd_import_error = e


class Strategy:
    def __init__(self, symbols=None):
        self.symbols = symbols or SYMBOLS
        self.macro_cache = {}
        self.cache_ttl = 600
        
        # CVD 订单流过滤器
        if CVD_AVAILABLE and CVD['enabled']:
            self.cvd_filter = CVDFilter(min_confidence=CVD['min_confidence'])
            logging.info(f"📊 CVD 订单流分析器已启用 (最小置信度: {CVD['min_confidence']}%)")
        else:
            self.cvd_filter = None
            if not CVD_AVAILABLE:
                logging.warning(f"⚠️ CVD 订单流分析器未启用")

    def get_risk_amount(self, balance):
        """计算R值 - 每笔交易的风险金额"""
        from config import RISK_PER_TRADE
        return balance * RISK_PER_TRADE

    def calculate_indicators(self, df):
        """计算技术指标 - 只保留EMA + StochRSI + ADX + 布林带"""
        # 1. EMA
        ema_period = INDICATORS['ema']['period']
        df['ema200'] = df['close'].ewm(span=ema_period, adjust=False).mean()

        # 2. Stochastic RSI (动量)
        rsi_period = INDICATORS['stoch_rsi']['rsi_period']
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_period).mean()
        rs = gain / loss.replace(0, 0.001)
        df['rsi'] = 100 - (100 / (1 + rs))

        rsi_min = df['rsi'].rolling(window=rsi_period).min()
        rsi_max = df['rsi'].rolling(window=rsi_period).max()
        stoch_rsi = (df['rsi'] - rsi_min) / (rsi_max - rsi_min).replace(0, 0.001)
        stoch_rsi = stoch_rsi.clip(0, 1)

        k_period = INDICATORS['stoch_rsi']['k_period']
        d_period = INDICATORS['stoch_rsi']['d_period']
        df['stoch_k'] = stoch_rsi.rolling(window=k_period).mean() * 100
        df['stoch_d'] = df['stoch_k'].rolling(window=d_period).mean() * 100
        df['stoch_k'] = df['stoch_k'].clip(0, 100)
        df['stoch_d'] = df['stoch_d'].clip(0, 100)

        # 3. ATR (波动率)
        atr_period = INDICATORS['atr']['period']
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        df['tr'] = np.max(ranges, axis=1)
        df['atr'] = df['tr'].rolling(atr_period).mean()

        # 4. ADX (趋势强度)
        adx_period = INDICATORS['adx']['period']
        plus_dm = df['high'].diff().clip(lower=0)
        minus_dm = (-df['low'].diff()).clip(lower=0)
        tr_smooth = df['tr'].rolling(adx_period).mean()
        plus_di = 100 * (plus_dm.rolling(adx_period).mean() / tr_smooth.replace(0, 0.001))
        minus_di = 100 * (minus_dm.rolling(adx_period).mean() / tr_smooth.replace(0, 0.001))
        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, 0.001)
        df['adx'] = dx.rolling(adx_period).mean()
        df['plus_di'] = plus_di
        df['minus_di'] = minus_di

        # 5. 布林带
        bb_period = INDICATORS['bollinger']['period']
        bb_std = INDICATORS['bollinger']['std_dev']
        df['bb_mid'] = df['close'].rolling(bb_period).mean()
        df['bb_std'] = df['close'].rolling(bb_period).std()
        df['bb_upper'] = df['bb_mid'] + (df['bb_std'] * bb_std)
        df['bb_lower'] = df['bb_mid'] - (df['bb_std'] * bb_std)
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_mid'].replace(0, 1)

        # 成交量MA
        df['vol_ma'] = df['volume'].rolling(window=20).mean()
        return df

    def get_macro_trends_batch(self, exchange, symbols):
        """批量获取宏观趋势"""
        now = time.time()
        trends_batch = {}
        total = len(symbols)

        for i, symbol in enumerate(symbols):
            if symbol in self.macro_cache and (now - self.macro_cache[symbol]['ts'] < self.cache_ttl):
                trends_batch[symbol] = self.macro_cache[symbol]['data']
                continue

            if i % 5 == 0:
                logging.info(f"⏳ 预加载宏观趋势进度: {i}/{total}...")

            trends = {'1h': 'UNKNOWN', '4h': 'UNKNOWN', 'score': 0}
            try:
                time.sleep(0.05)

                # 1H趋势
                ohlcv_1h = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=205)
                df_1h = pd.DataFrame(ohlcv_1h, columns=['t','o','h','l','c','v'])
                ema200_1h = df_1h['c'].ewm(span=200, adjust=False).mean().iloc[-1]
                trends['1h'] = 'UP' if df_1h['c'].iloc[-1] > ema200_1h else 'DOWN'

                # 4H趋势
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
                time.sleep(1)

        logging.info("✅ 宏观趋势数据预加载完成。")
        return trends_batch

    def check_volatility_filter(self, df):
        """波动率过滤器"""
        last = df.iloc[-1]
        atr_avg = df['atr'].rolling(100).mean().iloc[-1]
        
        min_mult, max_mult = 0.3, 4.0
        is_active = last['atr'] > (atr_avg * min_mult)
        is_safe = last['atr'] < (atr_avg * max_mult)
        return is_active and is_safe

    def calculate_signal_score(self, adx, stoch_k, cvd_strength, funding_rate, side):
        """
        计算信号强度分数
        分数 = ADX*0.4 + StochRSI强度*0.3 + CVD强度*0.3 + Funding*0.1
        """
        from config import SIGNAL_WEIGHTS, FUNDING
        
        # ADX分数 (0-100)
        adx_score = min(adx, 50) * 2  # 归一化到0-100
        
        # StochRSI强度 (做多时越低越好，做空时越高越好)
        if side == 'buy':
            stoch_score = (50 - stoch_k) * 2  # 超卖区分数高
        else:
            stoch_score = (stoch_k - 50) * 2  # 超买区分数高
        stoch_score = max(0, min(100, stoch_score))
        
        # CVD强度 (0-100)
        cvd_score = cvd_strength if cvd_strength else 50
        
        # Funding分数
        funding_score = 50
        if FUNDING['enabled'] and funding_rate is not None:
            threshold = FUNDING['threshold']
            if side == 'buy' and funding_rate < -threshold:
                funding_score = 100  # 负资金费率，做多有利
            elif side == 'sell' and funding_rate > threshold:
                funding_score = 100  # 正资金费率，做空有利
            else:
                funding_score = 30
        
        # 加权总分
        total_score = (
            adx_score * SIGNAL_WEIGHTS['adx'] +
            stoch_score * SIGNAL_WEIGHTS['stoch_rsi'] +
            cvd_score * SIGNAL_WEIGHTS['cvd'] +
            funding_score * SIGNAL_WEIGHTS['funding']
        )
        
        return total_score

    async def get_funding_rate(self, exchange, symbol):
        """获取资金费率"""
        try:
            funding = await exchange.fetch_funding_rate(symbol)
            return funding.get('fundingRate', 0) if funding else 0
        except:
            return 0

    async def check_multitimeframe_confirm(self, exchange, symbol, signal_side, df_primary=None, df_confirm=None):
        """
        多时间框架确认 - 放宽优化版
        15m信号 + 1h趋势一致时才开仓
        1h趋势判断使用ADX方向（1h ADX > 20 且方向与15m一致）
        """
        from config import TIMEFRAMES, PRIMARY_TIMEFRAME, CONFIRM_TIMEFRAME
        
        try:
            if df_primary is None:
                ohlcv_primary = await exchange.fetch_ohlcv(symbol, timeframe=PRIMARY_TIMEFRAME, limit=100)
                df_primary = self.calculate_indicators(pd.DataFrame(ohlcv_primary, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']))
            
            if df_confirm is None:
                ohlcv_confirm = await exchange.fetch_ohlcv(symbol, timeframe=CONFIRM_TIMEFRAME, limit=100)
                df_confirm = self.calculate_indicators(pd.DataFrame(ohlcv_confirm, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']))
            
            last_primary = df_primary.iloc[-1]
            last_confirm = df_confirm.iloc[-1]
            
            # 1h ADX 阈值检查 (>20)
            adx_1h_threshold = 20
            if last_confirm['adx'] < adx_1h_threshold:
                logging.info(f"❌ {symbol} 1h确认: ADX {last_confirm['adx']:.1f} < {adx_1h_threshold} (趋势不够强)")
                return False
            
            # 使用 ADX 方向判断趋势 (+DI > -DI 为多头，反之空头)
            primary_trend_up = last_primary['plus_di'] > last_primary['minus_di']
            confirm_trend_up = last_confirm['plus_di'] > last_confirm['minus_di']
            
            # 检查趋势一致性
            if signal_side == 'buy':
                # 做多需要两个时间框架都是多头趋势
                is_aligned = primary_trend_up and confirm_trend_up
                if not is_aligned:
                    logging.info(f"❌ {symbol} 1h确认: 方向不一致 | 15m:+DI{'>' if primary_trend_up else '<'}-DI | 1h:+DI{'>' if confirm_trend_up else '<'}-DI (需要都是多头)")
            else:
                # 做空需要两个时间框架都是空头趋势
                is_aligned = (not primary_trend_up) and (not confirm_trend_up)
                if not is_aligned:
                    logging.info(f"❌ {symbol} 1h确认: 方向不一致 | 15m:+DI{'<' if not primary_trend_up else '>'}-DI | 1h:+DI{'<' if not confirm_trend_up else '>'}-DI (需要都是空头)")
            
            if is_aligned:
                logging.info(f"✅ {symbol} 1h确认通过: ADX {last_confirm['adx']:.1f} | 15m+1h方向一致")
            
            return is_aligned
            
        except Exception as e:
            logging.warning(f"多时间框架确认失败 {symbol}: {e}")
            return True  # 失败时默认通过

    async def calculate_signals(self, exchange):
        """
        计算交易信号 - 信号强度排名版
        分数 = ADX*0.4 + StochRSI*0.3 + CVD*0.3 + Funding*0.1
        只保留前MAX_ACTIVE_SYMBOLS个
        """
        signals = {}
        signal_scores = []

        logging.info(f"🔍 扫描 {len(self.symbols)} 个主流币种 (多时间框架: {TIMEFRAMES})...")
        scan_start_time = time.time()

        for symbol in self.symbols:
            try:
                # 获取主时间框架数据
                ohlcv = await exchange.fetch_ohlcv(symbol, timeframe=PRIMARY_TIMEFRAME, limit=300)
                if len(ohlcv) < 200:
                    continue

                df = self.calculate_indicators(pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']))
                curr = df.iloc[-1]
                last_closed = df.iloc[-2]
                prev_closed = df.iloc[-3]

                # 获取资金费率
                funding_rate = await self.get_funding_rate(exchange, symbol)

                # 计算CVD强度
                cvd_strength = 50
                if self.cvd_filter:
                    try:
                        df['delta'] = df.apply(lambda row: 
                            row['volume'] * ((row['close'] - row['low']) / (row['high'] - row['low']) - 0.5) * 2 
                            if row['high'] != row['low'] else 0, axis=1)
                        df['cvd'] = df['delta'].cumsum()
                        cvd_delta = abs(df['cvd'].iloc[-1] - df['cvd'].iloc[-20])
                        avg_volume = df['volume'].rolling(20).mean().iloc[-1]
                        cvd_ratio = cvd_delta / avg_volume if avg_volume > 0 else 0
                        cvd_strength = min(100, cvd_ratio * 50)
                    except:
                        pass

                vol_ok = self.check_volatility_filter(df)
                adx_threshold = INDICATORS['adx']['threshold']

                # 记录指标
                logging.info(f"📊 {symbol} | 价格:${last_closed['close']:.2f} | EMA200:${last_closed['ema200']:.2f} | ADX:{curr['adx']:.1f} | Stoch:{last_closed['stoch_k']:.1f} | Funding:{funding_rate:.4%}")

                # 检查做多信号
                long_checks = []
                if vol_ok:
                    long_checks.append(f"✅波动率")
                else:
                    long_checks.append(f"❌波动率")
                    
                if curr['adx'] > adx_threshold:
                    long_checks.append(f"✅ADX({curr['adx']:.1f}>{adx_threshold})")
                else:
                    long_checks.append(f"❌ADX({curr['adx']:.1f}<{adx_threshold})")
                    
                stoch_ok = last_closed['stoch_k'] < INDICATORS['stoch_rsi']['oversold']
                ema_ok = last_closed['close'] > last_closed['ema200']
                golden_cross = (last_closed['stoch_k'] > last_closed['stoch_d'] and 
                               prev_closed['stoch_k'] <= prev_closed['stoch_d'])
                
                if stoch_ok:
                    long_checks.append(f"✅Stoch({last_closed['stoch_k']:.1f}<{INDICATORS['stoch_rsi']['oversold']})")
                else:
                    long_checks.append(f"❌Stoch({last_closed['stoch_k']:.1f}>{INDICATORS['stoch_rsi']['oversold']})")
                    
                if ema_ok:
                    long_checks.append(f"✅EMA(价格{last_closed['close']:.2f}>EMA{last_closed['ema200']:.2f})")
                else:
                    long_checks.append(f"❌EMA(价格{last_closed['close']:.2f}<EMA{last_closed['ema200']:.2f})")
                    
                if golden_cross:
                    long_checks.append(f"✅金叉")
                else:
                    long_checks.append(f"❌金叉")
                
                if vol_ok and curr['adx'] > adx_threshold and stoch_ok and ema_ok and golden_cross:
                    # 多时间框架确认
                    if await self.check_multitimeframe_confirm(exchange, symbol, 'buy'):
                        score = self.calculate_signal_score(
                            curr['adx'], last_closed['stoch_k'], cvd_strength, funding_rate, 'buy'
                        )
                        signal_data = {
                            'side': 'buy',
                            'score': score,
                            'adx': curr['adx'],
                            'stoch': last_closed['stoch_k'],
                            'funding': funding_rate
                        }
                        signal_scores.append((symbol, score, signal_data))
                        logging.info(f"🚀 {symbol} 做多信号通过: {' | '.join(long_checks)}")
                    else:
                        logging.info(f"⏸️ {symbol} 做多-1h确认失败: {' | '.join(long_checks)}")
                else:
                    # 条件不满足，显示原因
                    fail_reasons = []
                    if not vol_ok:
                        fail_reasons.append("波动率")
                    if not (curr['adx'] > adx_threshold):
                        fail_reasons.append(f"ADX({curr['adx']:.1f}<{adx_threshold})")
                    if not stoch_ok:
                        fail_reasons.append(f"Stoch({last_closed['stoch_k']:.1f}>{INDICATORS['stoch_rsi']['oversold']})")
                    if not ema_ok:
                        fail_reasons.append(f"EMA(价格{last_closed['close']:.2f}<EMA{last_closed['ema200']:.2f})")
                    if not golden_cross:
                        fail_reasons.append(f"金叉(K{last_closed['stoch_k']:.1f}不大于D{last_closed['stoch_d']:.1f})")
                    logging.info(f"⏸️ {symbol} 做多条件不满足: {' | '.join(fail_reasons)}")

                # 检查做空信号
                short_checks = []
                if vol_ok:
                    short_checks.append(f"✅波动率")
                else:
                    short_checks.append(f"❌波动率")
                    
                if curr['adx'] > adx_threshold:
                    short_checks.append(f"✅ADX({curr['adx']:.1f}>{adx_threshold})")
                else:
                    short_checks.append(f"❌ADX({curr['adx']:.1f}<{adx_threshold})")
                    
                stoch_ok_short = last_closed['stoch_k'] > INDICATORS['stoch_rsi']['overbought']
                ema_ok_short = last_closed['close'] < last_closed['ema200']
                dead_cross = (last_closed['stoch_k'] < last_closed['stoch_d'] and 
                             prev_closed['stoch_k'] >= prev_closed['stoch_d'])
                
                if stoch_ok_short:
                    short_checks.append(f"✅Stoch({last_closed['stoch_k']:.1f}>{INDICATORS['stoch_rsi']['overbought']})")
                else:
                    short_checks.append(f"❌Stoch({last_closed['stoch_k']:.1f}<{INDICATORS['stoch_rsi']['overbought']})")
                    
                if ema_ok_short:
                    short_checks.append(f"✅EMA(价格{last_closed['close']:.2f}<EMA{last_closed['ema200']:.2f})")
                else:
                    short_checks.append(f"❌EMA(价格{last_closed['close']:.2f}>EMA{last_closed['ema200']:.2f})")
                    
                if dead_cross:
                    short_checks.append(f"✅死叉")
                else:
                    short_checks.append(f"❌死叉")
                
                # 添加死叉到检查列表
                if dead_cross:
                    short_checks.append(f"✅死叉")
                else:
                    short_checks.append(f"❌死叉(K{last_closed['stoch_k']:.1f}<D{last_closed['stoch_d']:.1f})")
                
                if vol_ok and curr['adx'] > adx_threshold and stoch_ok_short and ema_ok_short and dead_cross:
                    # 多时间框架确认
                    logging.info(f"🔍 {symbol} 做空-尝试1h确认...")
                    if await self.check_multitimeframe_confirm(exchange, symbol, 'sell'):
                        score = self.calculate_signal_score(
                            curr['adx'], last_closed['stoch_k'], cvd_strength, funding_rate, 'sell'
                        )
                        signal_data = {
                            'side': 'sell',
                            'score': score,
                            'adx': curr['adx'],
                            'stoch': last_closed['stoch_k'],
                            'funding': funding_rate
                        }
                        signal_scores.append((symbol, score, signal_data))
                        logging.info(f"🚀 {symbol} 做空信号通过: {' | '.join(short_checks)}")
                    else:
                        logging.info(f"⏸️ {symbol} 做空-1h确认失败: {' | '.join(short_checks)}")
                        logging.info(f"⏸️ {symbol} 做空-1h确认失败: {' | '.join(short_checks)}")
                else:
                    # 条件不满足，显示原因
                    fail_reasons = []
                    if not vol_ok:
                        fail_reasons.append("波动率")
                    if not (curr['adx'] > adx_threshold):
                        fail_reasons.append(f"ADX({curr['adx']:.1f}<{adx_threshold})")
                    if not stoch_ok_short:
                        fail_reasons.append(f"Stoch({last_closed['stoch_k']:.1f}<{INDICATORS['stoch_rsi']['overbought']})")
                    if not ema_ok_short:
                        fail_reasons.append(f"EMA(价格{last_closed['close']:.2f}>EMA{last_closed['ema200']:.2f})")
                    if not dead_cross:
                        fail_reasons.append(f"死叉(K{last_closed['stoch_k']:.1f}不小于D{last_closed['stoch_d']:.1f})")
                    logging.info(f"⏸️ {symbol} 做空条件不满足: {' | '.join(fail_reasons)}")

            except Exception as e:
                logging.error(f"❌ Signal calculation error for {symbol}: {str(e)}")
                continue

        # 按信号强度排序，只保留前MAX_ACTIVE_SYMBOLS个
        signal_scores.sort(key=lambda x: x[1], reverse=True)
        top_signals = signal_scores[:MAX_ACTIVE_SYMBOLS]

        for symbol, score, signal_data in top_signals:
            signals[symbol] = signal_data
            logging.info(f"🚨 信号: {symbol} | 方向:{signal_data['side']} | 分数:{score:.1f}")

        scan_duration = time.time() - scan_start_time

        # ========== CVD 订单流过滤 ==========
        if signals and self.cvd_filter:
            logging.info("📊 启动 CVD 订单流验证...")
            original_count = len(signals)
            
            # 加强CVD验证
            for symbol in list(signals.keys()):
                try:
                    ohlcv = await exchange.fetch_ohlcv(symbol, timeframe='30m', limit=50)
                    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    
                    # 计算CVD相关指标
                    df['delta'] = df.apply(lambda row: 
                        row['volume'] * ((row['close'] - row['low']) / (row['high'] - row['low']) - 0.5) * 2 
                        if row['high'] != row['low'] else 0, axis=1)
                    df['cvd'] = df['delta'].cumsum()
                    
                    cvd_delta = abs(df['cvd'].iloc[-1] - df['cvd'].iloc[-20])
                    avg_volume = df['volume'].rolling(20).mean().iloc[-1]
                    cvd_ratio = cvd_delta / avg_volume if avg_volume > 0 else 0
                    
                    # 加强验证条件
                    if cvd_delta > CVD['validation']['cvd_delta_multiplier'] * avg_volume and \
                       cvd_ratio > CVD['validation']['cvd_ratio_threshold']:
                        logging.info(f"✅ CVD验证通过: {symbol} | delta:{cvd_delta:.0f} | ratio:{cvd_ratio:.2f}")
                    else:
                        logging.warning(f"❌ CVD过滤: {symbol} | delta:{cvd_delta:.0f} | ratio:{cvd_ratio:.2f}")
                        del signals[symbol]
                        
                except Exception as e:
                    logging.error(f"CVD验证错误 {symbol}: {e}")
            
            filtered_count = original_count - len(signals)
            if filtered_count > 0:
                logging.warning(f"🛑 CVD 过滤: 拦截 {filtered_count} 个信号")

        logging.info(f"🏁 扫描完成。耗时: {scan_duration:.1f}s | 发现信号: {len(signals)}")
        return signals if signals else None

    def calculate_r_multiple(self, entry_price, current_price, side, stop_loss_pct):
        """计算当前R倍数"""
        if side == 'LONG':
            price_change_pct = (current_price - entry_price) / entry_price
        else:
            price_change_pct = (entry_price - current_price) / entry_price
        
        # R倍数 = 价格变动百分比 / 止损百分比
        r_multiple = price_change_pct / stop_loss_pct if stop_loss_pct > 0 else 0
        return r_multiple, price_change_pct

    def calculate_atr_stop_loss(self, entry_price, atr, side, atr_multiplier=None):
        """计算ATR动态止损价格"""
        from config import ATR_STOP_MULTIPLIER
        
        if atr_multiplier is None:
            atr_multiplier = ATR_STOP_MULTIPLIER
        
        if side == 'LONG':
            stop_price = entry_price - (atr * atr_multiplier)
        else:
            stop_price = entry_price + (atr * atr_multiplier)
        
        return stop_price

    async def check_exit_and_pyramiding(self, exchange, symbol, current_side, entry_price, 
                                    position_size, balance, executed_exits=None, current_additions=0,
                                    breakeven_triggered=False, df=None):
        """
        R-based 加仓和平仓逻辑（最高优先级优化版）
        优先级：止损(ATR动态/Breakeven) > 加仓(1R/1.8R) > 部分平仓(2.5R/3.5R) > ATR trailing
        
        Args:
            executed_exits: 已执行的平仓R级别列表 [2.5, 3.5]
            current_additions: 已加仓次数
            breakeven_triggered: 是否已触发保本止损
        
        Returns:
            dict: {'action': 'PYRAMID'|'PARTIAL_EXIT'|'CLOSE_ALL'|None, ...}
        """
        from config import (EXIT_STRATEGY, STOP_LOSS_PCT, PYRAMIDING, 
                           RR_2R_MULTIPLE, RR_3R_MULTIPLE,
                           PYRAMID_TRIGGER_1, PYRAMID_TRIGGER_2,
                           ATR_STOP_MULTIPLIER, BREAKEVEN)
        
        if executed_exits is None:
            executed_exits = []
        
        if df is None:
            ohlcv = await exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
            df = self.calculate_indicators(pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']))
        curr = df.iloc[-1]
        current_price = curr['close']
        atr = curr['atr']

        # 计算R值和R倍数
        r_amount = self.get_risk_amount(balance)
        r_multiple, price_change_pct = self.calculate_r_multiple(entry_price, current_price, current_side, STOP_LOSS_PCT)

        # ========== 1. ATR动态止损检查（最高优先级）==========
        if price_change_pct < 0:
            # 计算ATR止损价格
            atr_stop_price = self.calculate_atr_stop_loss(entry_price, atr, current_side, ATR_STOP_MULTIPLIER)
            
            # 检查是否触及ATR止损
            if current_side == 'LONG' and current_price <= atr_stop_price:
                return {'action': 'CLOSE_ALL', 'reason': f'atr_stop:{atr_stop_price:.4f}', 'r_multiple': r_multiple}
            elif current_side == 'SHORT' and current_price >= atr_stop_price:
                return {'action': 'CLOSE_ALL', 'reason': f'atr_stop:{atr_stop_price:.4f}', 'r_multiple': r_multiple}
            
            # 检查是否触及保本止损（如果已触发Breakeven）
            if breakeven_triggered and BREAKEVEN['enabled']:
                breakeven_price = entry_price * (1 + BREAKEVEN['buffer_pct']) if current_side == 'LONG' else entry_price * (1 - BREAKEVEN['buffer_pct'])
                if current_side == 'LONG' and current_price <= breakeven_price:
                    return {'action': 'CLOSE_ALL', 'reason': f'breakeven_stop:{breakeven_price:.4f}', 'r_multiple': r_multiple}
                elif current_side == 'SHORT' and current_price >= breakeven_price:
                    return {'action': 'CLOSE_ALL', 'reason': f'breakeven_stop:{breakeven_price:.4f}', 'r_multiple': r_multiple}

        # ========== 2. Breakeven保本止损设置（盈利1R后）==========
        if BREAKEVEN['enabled'] and not breakeven_triggered and r_multiple >= BREAKEVEN['trigger_r']:
            # 返回设置保本止损的信号，由bot.py处理
            return {
                'action': 'SET_BREAKEVEN',
                'trigger_r': BREAKEVEN['trigger_r'],
                'buffer_pct': BREAKEVEN['buffer_pct'],
                'r_multiple': r_multiple
            }

        # ========== 2. 金字塔加仓检查（盈利时优先加仓）==========
        if PYRAMIDING['enabled'] and current_additions < PYRAMIDING['max_levels']:
            pyramid_levels = [
                {'r_multiple': PYRAMID_TRIGGER_1, 'size_pct': PYRAMIDING['levels'][0]['size_pct']},
                {'r_multiple': PYRAMID_TRIGGER_2, 'size_pct': PYRAMIDING['levels'][1]['size_pct']},
            ]
            
            for i, level in enumerate(pyramid_levels):
                if current_additions <= i and r_multiple >= level['r_multiple']:
                    addition_size = position_size * level['size_pct']
                    return {
                        'action': 'PYRAMID',
                        'level': i + 1,
                        'size': addition_size,
                        'r_multiple': r_multiple,
                        'reason': f"pyramiding_{level['r_multiple']}R"
                    }

        # ========== 3. R-based分级止盈（加仓完成后才平仓）==========
        if EXIT_STRATEGY['enabled']:
            exit_levels = [
                {'r_multiple': RR_2R_MULTIPLE, 'exit_pct': EXIT_STRATEGY['r_levels'][0]['exit_pct']},
                {'r_multiple': RR_3R_MULTIPLE, 'exit_pct': EXIT_STRATEGY['r_levels'][1]['exit_pct']},
            ]
            
            for level in exit_levels:
                if r_multiple >= level['r_multiple'] and level['r_multiple'] not in executed_exits:
                    exit_size = position_size * level['exit_pct']
                    return {
                        'action': 'PARTIAL_EXIT',
                        'exit_pct': level['exit_pct'],
                        'exit_size': exit_size,
                        'r_multiple_level': level['r_multiple'],
                        'current_r_multiple': r_multiple,
                        'reason': f"r_take_profit_{level['r_multiple']}R"
                    }

        # ========== 4. ATR Trailing Stop（最后）==========
        if EXIT_STRATEGY['trailing_stop']['enabled']:
            atr_mult = EXIT_STRATEGY['trailing_stop']['atr_multiplier']
            
            # 只在已经部分平仓后才启用trailing stop
            if len(executed_exits) >= len(EXIT_STRATEGY['r_levels']):
                stop_price = self.calculate_atr_trailing_stop(df, current_side, atr_mult)['stop_price']
                if current_side == 'LONG':
                    if current_price <= stop_price:
                        return {'action': 'CLOSE_ALL', 'reason': f'atr_trailing_stop:{stop_price:.4f}', 'r_multiple': r_multiple}
                else:
                    if current_price >= stop_price:
                        return {'action': 'CLOSE_ALL', 'reason': f'atr_trailing_stop:{stop_price:.4f}', 'r_multiple': r_multiple}

        return None

    def check_pyramiding(self, symbol, current_r_multiple, base_position_size, current_additions=0):
        """
        检查金字塔加仓条件 - R-based优化版
        
        Args:
            current_r_multiple: 当前R倍数
        """
        from config import PYRAMIDING, PYRAMID_TRIGGER_1, PYRAMID_TRIGGER_2
        
        if not PYRAMIDING['enabled']:
            return None
            
        if current_additions >= PYRAMIDING['max_levels']:
            return None
        
        # R-based 加仓触发点
        pyramid_triggers = [PYRAMID_TRIGGER_1, PYRAMID_TRIGGER_2]
        
        if current_additions < len(pyramid_triggers):
            trigger_r = pyramid_triggers[current_additions]
            if current_r_multiple >= trigger_r:
                size_pct = PYRAMIDING['levels'][current_additions]['size_pct']
                addition_size = base_position_size * size_pct
                return {
                    'level': current_additions + 1,
                    'size': addition_size,
                    'r_multiple': current_r_multiple,
                    'trigger_r': trigger_r,
                    'reason': f"pyramiding_{trigger_r}R"
                }
        
        return None

    def calculate_atr_trailing_stop(self, df, current_side, atr_multiplier=2.2):
        """计算ATR追踪止损"""
        last = df.iloc[-1]
        atr = last['atr']
        lookback = 20
        
        if current_side == 'LONG':
            stop = df['high'].tail(lookback).max() - (atr * atr_multiplier)
        else:
            stop = df['low'].tail(lookback).min() + (atr * atr_multiplier)
        
        return {'stop_price': stop}
