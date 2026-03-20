#!/usr/bin/env python3
"""
测试脚本 - 验证 Binance Bot 修复
"""
import sys
import os

# 添加项目路径
sys.path.insert(0, '/home/administrator/.openclaw/workspace/binance_bot')

from config import *

print("=" * 60)
print("Binance Bot 修复验证测试")
print("=" * 60)

# 1. 检查 API 配置
print("\n[1] API 配置检查")
if BINANCE_API_KEY and BINANCE_API_SECRET:
    print(f"  ✅ API Key: {BINANCE_API_KEY[:8]}...{BINANCE_API_KEY[-4:]}")
    print(f"  ✅ API Secret: {BINANCE_API_SECRET[:8]}...{BINANCE_API_SECRET[-4:]}")
else:
    print("  ❌ API 密钥未设置")
    sys.exit(1)

# 2. 测试 CCXT 导入和交易所初始化
print("\n[2] CCXT 交易所初始化")
try:
    import ccxt
    print(f"  ✅ CCXT 版本: {ccxt.__version__}")
    
    # 使用 binanceusdm 而不是 binance
    exchange = ccxt.binanceusdm({
        'apiKey': BINANCE_API_KEY,
        'secret': BINANCE_API_SECRET,
        'options': {
            'adjustForTimeDifference': True,
            'recvWindow': 60000,
        },
        'enableRateLimit': True,
    })
    print(f"  ✅ 交易所实例创建成功: {exchange.id}")
except Exception as e:
    print(f"  ❌ 交易所初始化失败: {e}")
    sys.exit(1)

# 3. 测试市场加载 (跳过需要额外权限的接口)
print("\n[3] 市场数据加载")
try:
    # 使用公共API加载市场数据，不需要额外权限
    markets = exchange.fetch_markets()
    print(f"  ✅ 市场数据加载成功")
    print(f"  📊 支持的交易对数量: {len(markets)}")
    
    # 检查目标交易对
    market_symbols = [m['symbol'] for m in markets]
    for symbol in SYMBOLS:
        if symbol in market_symbols:
            print(f"  ✅ {symbol} 可用")
        else:
            print(f"  ⚠️  {symbol} 不可用，尝试查找替代...")
            # 尝试不带 :USDT 后缀的格式
            alt_symbol = symbol.replace(':USDT', '')
            if alt_symbol in market_symbols:
                print(f"     找到替代: {alt_symbol}")
except Exception as e:
    print(f"  ❌ 市场加载失败: {e}")
    sys.exit(1)

# 4. 测试时间同步
print("\n[4] 时间同步测试")
try:
    server_time = exchange.fetch_time()
    import time
    local_time = int(time.time() * 1000)
    time_diff = server_time - local_time
    print(f"  ✅ 服务器时间: {server_time}")
    print(f"  ✅ 本地时间: {local_time}")
    print(f"  ✅ 时间差: {time_diff}ms")
    
    # 设置时间偏移
    exchange.options['timeDifference'] = time_diff - 3000
    print(f"  ✅ 时间偏移已设置: {exchange.options['timeDifference']}ms")
except Exception as e:
    print(f"  ❌ 时间同步失败: {e}")
    sys.exit(1)

# 5. 测试余额获取 (带重试)
print("\n[5] 账户余额测试")
try:
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # 每次尝试前重新同步时间
            server_time = exchange.fetch_time()
            local_time = int(time.time() * 1000)
            time_diff = server_time - local_time - 5000  # 更大的安全缓冲
            exchange.options['timeDifference'] = time_diff
            
            balance = exchange.fetch_balance()
            usdt_balance = balance['total'].get('USDT', 0)
            print(f"  ✅ USDT 余额: {usdt_balance}")
            
            # 显示其他主要资产
            assets = ['BTC', 'ETH', 'BNB']
            for asset in assets:
                bal = balance['total'].get(asset, 0)
                if bal > 0:
                    print(f"  📊 {asset} 余额: {bal}")
            break
        except Exception as e:
            if "-1021" in str(e) and attempt < max_retries - 1:
                print(f"  ⚠️  时间戳错误，重试中... ({attempt + 1}/{max_retries})")
                time.sleep(1)
                continue
            raise
except Exception as e:
    print(f"  ❌ 余额获取失败: {e}")
    print(f"     错误详情: {str(e)[:200]}")
    sys.exit(1)

# 6. 测试行情数据
print("\n[6] 行情数据测试")
try:
    for symbol in SYMBOLS:
        ticker = exchange.fetch_ticker(symbol)
        print(f"  ✅ {symbol}:")
        print(f"     最新价: {ticker['last']}")
        print(f"     买一: {ticker['bid']}, 卖一: {ticker['ask']}")
        print(f"     24h 涨跌: {ticker.get('percentage', 'N/A')}%")
except Exception as e:
    print(f"  ❌ 行情获取失败: {e}")
    sys.exit(1)

# 7. 测试 K 线数据（策略需要）
print("\n[7] K 线数据测试 (30m)")
try:
    for symbol in SYMBOLS:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='30m', limit=50)
        print(f"  ✅ {symbol}: 获取 {len(ohlcv)} 条 K 线数据")
        if len(ohlcv) > 0:
            print(f"     最新: 开={ohlcv[-1][1]}, 收={ohlcv[-1][4]}")
except Exception as e:
    print(f"  ❌ K 线获取失败: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("✅ 所有测试通过！Bot 可以正常运行。")
print("=" * 60)
print("\n启动命令:")
print("  cd /home/administrator/.openclaw/workspace/binance_bot")
print("  python3 bot.py")
