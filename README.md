# Binance Futures Trading Bot v9.0

币安USDT永续合约量化交易机器人 - 动态双过滤器系统

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![CCXT](https://img.shields.io/badge/CCXT-Latest-green.svg)](https://github.com/ccxt/ccxt)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 🚀 核心特性

### 动态双过滤器系统 (Dynamic Dual Filter System)

#### 1. MTF 宏观趋势过滤器 (Multi-Timeframe Trend Filter)
- **1H 周期**: 决定入场执行权
- **4H 周期**: 决定仓位权重 (FULL/HALF)
- **趋势一致性评分**: -2 到 +2，确保多周期共振

#### 2. RVF 相对波动率过滤器 (Relative Volatility Filter)
- **ATR 动态区间**: 0.6x - 3.5x 平均波动率
- **排除死鱼盘**: 波动率过低不交易
- **排除极端行情**: 波动率过高不交易

## 📊 策略逻辑

### 入场条件 (多头)

```
✅ 1H 趋势 = UP
✅ 波动率合格 (0.6x < ATR < 3.5x)
✅ ADX > 10 (趋势强度足够)
✅ 非布林带挤压期
✅ 价格 > EMA200
✅ StochRSI 金叉且 K < 45 (低位金叉)
✅ MFI > 40 (资金流确认)
```

### 入场条件 (空头)

```
✅ 1H 趋势 = DOWN
✅ 波动率合格
✅ ADX > 10
✅ 非挤压期
✅ 价格 < EMA200
✅ 非反弹状态 (RSI过滤)
✅ StochRSI 死叉且 K > 55 (高位死叉)
✅ MFI < 60
```

### 仓位管理

| 4H 趋势 | 1H 趋势 | 仓位强度 |
|---------|---------|----------|
| UP | UP | FULL (100%) |
| UP | DOWN | HALF (50%) |
| DOWN | UP | HALF (50%) |
| DOWN | DOWN | FULL (100%) |

### 智能平仓系统

```
基础止损: ATR 2.8x 移动止损
盈利 1.8%: 保本锁 (0.5%)
盈利 5%: 锁利线 (3%)
硬止损: -15%
```

## ⚡ 性能优化

### 扫描性能

| 指标 | 优化前 | 优化后 | 提升 |
|------|--------|--------|------|
| 扫描速度 | ~90秒 | ~26秒 | 71% |
| 数据同步性 | 2.4分钟延迟 | 实时同步 | 100% |
| 缓存机制 | 无 | 10分钟缓存 | 重复扫描9秒 |

### 关键技术

- **批量预加载**: 统一获取所有币种宏观趋势数据
- **缓存机制**: 10分钟缓存，减少API调用
- **耗时统计**: 每轮扫描显示耗时

## 🛡️ 风控系统

### 1. max_profit 持久化
- 保存到 `.position_tracking` 文件
- 机器人重启后恢复数据
- 避免止损线重置

### 2. 每日亏损限制
- 日亏损达到 10% 自动暂停交易
- 5分钟后自动恢复检查
- 防止连续亏损

### 3. 持仓上限
- 最多同时持有 5 个仓位
- 避免过度分散

## 📁 项目结构

```
binance_bot/
├── bot.py                 # 主程序
├── strategy.py            # 策略核心 (动态双过滤器)
├── risk_manager.py        # 风控管理
├── config.py              # 配置文件
├── web_server.py          # Web面板服务
├── web_dashboard.html     # 监控面板
├── auto_monitor.sh        # 自动监控脚本
├── crontab.txt            # 定时任务配置
├── requirements.txt       # 依赖列表
└── .env                   # 环境变量 (API密钥)
```

## 🚀 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/l1370087182-netizen/bot.git
cd bot
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，填入您的币安API密钥
```

`.env` 文件内容：
```
BINANCE_API_KEY=your_api_key_here
BINANCE_API_SECRET=your_api_secret_here
```

### 4. 启动机器人

```bash
# 测试模式 (模拟交易)
python bot.py

# 实盘模式
python bot.py --real
```

### 5. 自动监控 (推荐)

```bash
# 添加定时任务
crontab crontab.txt

# 手动启动监控
./auto_monitor.sh
```

## 📈 监控面板

启动后访问 Web 面板查看实时状态：

```
http://localhost:8080
```

面板显示：
- 账户余额和盈亏
- 当前持仓详情
- 最近交易记录
- 系统日志

## 🔧 配置说明

### 交易参数 (config.py)

```python
# 交易币种列表 (48个主流币种)
SYMBOLS = ['BTC/USDT:USDT', 'ETH/USDT:USDT', ...]

# 扫描间隔
LOOP_INTERVAL = 60  # 每60秒扫描一次

# 风险控制
MAX_DAILY_LOSS_PCT = 0.10  # 日亏损限制 10%
STOP_LOSS_PCT = 0.02       # 止损 2%
TAKE_PROFIT_PCT = 0.04     # 止盈 4%

# 杠杆设置
LEVERAGE = 10              # 最大10倍杠杆
POSITION_SIZE_PCT = 0.2    # 20%保证金
```

### 过滤器参数 (strategy.py)

```python
# 趋势强度
ADX_THRESHOLD = 10         # ADX > 10 才交易

# 波动率区间
ATR_MIN_MULTIPLIER = 0.6   # 最小0.6倍平均ATR
ATR_MAX_MULTIPLIER = 3.5   # 最大3.5倍平均ATR

# StochRSI参数
STOCH_K_PERIOD = 3
STOCH_D_PERIOD = 3
RSI_PERIOD = 14

# 缓存时间
MACRO_CACHE_TTL = 600      # 10分钟缓存
```

## 📊 日志说明

### 日志文件

- `bot.log`: 主程序日志
- `auto_monitor.log`: 监控脚本日志
- `web_server.log`: Web服务日志

### 关键日志标记

```
🔍 v9.0 动态双过滤器扫描启动 (48 coins)...
⏳ 预加载宏观趋势数据...
📊 BTC/USDT:USDT | 1H:DOWN | Vol:OK | ADX:11.8 | Stoch:10.5
🏁 扫描完成。耗时: 26.3s | 发现信号: 0
🚨 v9.0 BUY: ETH/USDT:USDT | Strength:FULL | 1H:UP 4H:UP
💰 Account Balance: 12.73 USDT
```

## 🔔 通知设置

### Bark iPhone 推送

在 `bot.py` 中配置您的 Bark Key：

```python
bark_url = f"https://api.day.app/YOUR_BARK_KEY/{title}/{content}"
```

推送场景：
- ✅ 开仓成功
- 🚨 平仓成功
- ⚠️ 系统错误

## ⚠️ 风险提示

1. **交易有风险，入市需谨慎**
2. 本机器人仅供学习研究，不构成投资建议
3. 请确保您了解量化交易的风险
4. 建议使用测试网或小资金测试
5. 请妥善保管 API 密钥，不要泄露

## 📝 更新日志

### v9.0 (2026-03-20)
- ✅ 新增动态双过滤器系统
- ✅ 扫描性能优化 (71%提升)
- ✅ max_profit 持久化
- ✅ 每日亏损限制
- ✅ 全面错误处理

### v3.0 (2026-03-19)
- ATR 2.8x 移动止损
- WebSocket 极速面板
- Bark iPhone 推送
- 多仓位并行扫描

### v1.0 (2026-03-16)
- 基础交易功能
- EMA/RSI/MACD 策略
- 风控管理

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License

---

**免责声明**: 本软件仅供学习交流使用，作者不对使用本软件造成的任何损失负责。加密货币交易风险极高，请谨慎决策。
