#!/usr/bin/env python3
"""
Testnet 测试 - 在币安测试网验证交易功能
需要: BINANCE_TESTNET_API_KEY 和 BINANCE_TESTNET_SECRET
"""
import os
import sys
sys.path.insert(0, 'src')

print("🧪 Testnet Testing Guide")
print("=" * 60)

print("\n1️⃣ 获取 Testnet API 密钥:")
print("   - 访问: https://testnet.binancefuture.com/")
print("   - 登录后获取 API Key")

print("\n2️⃣ 设置环境变量:")
print("   export BINANCE_API_KEY='your_testnet_key'")
print("   export BINANCE_API_SECRET='your_testnet_secret'")

print("\n3️⃣ 修改 config.yaml:")
print("   trading:")
print("     use_testnet: true")

print("\n4️⃣ 运行测试:")
print("   python3 bot_v10.py")

print("\n5️⃣ 测试检查清单:")
checklist = [
    "✅ 能正常连接 Testnet",
    "✅ 能获取账户余额",
    "✅ 能获取 K 线数据",
    "✅ 信号扫描正常",
    "✅ 能下单（测试小额）",
    "✅ 能平仓",
    "✅ 数据库记录正常",
    "✅ 风控触发正常"
]

for item in checklist:
    print(f"   {item}")

print("\n6️⃣ 常见问题:")
print("   - Testnet 余额不足: 在网站申请充值")
print("   - 连接失败: 检查 API 密钥是否正确")
print("   - 下单失败: 检查最小名义价值（>10 USDT）")

print("\n" + "=" * 60)

# 检查环境
api_key = os.getenv('BINANCE_API_KEY')
api_secret = os.getenv('BINANCE_API_SECRET')

if api_key and api_secret:
    print(f"✅ API Key 已配置: {api_key[:10]}...")
    print(f"✅ API Secret 已配置: {api_secret[:10]}...")
    print("\n🚀 可以开始 Testnet 测试!")
    print("   运行: python3 bot_v10.py")
else:
    print("❌ API 密钥未配置")
    print("   请先设置环境变量")
