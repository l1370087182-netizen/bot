# Binance Futures Trading Bot v10.1 (Institutional Grade)

币安USDT永续合约量化交易机器人 - **三层防护 + 放大器** 架构 (机构级因子版)

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![CCXT](https://img.shields.io/badge/CCXT-Latest-green.svg)](https://github.com/ccxt/ccxt)
[![SQLite](https://img.shields.io/badge/SQLite-Persistence-orange.svg)](https://sqlite.org/)
[![Web](https://img.shields.io/badge/Web-Dashboard-blueviolet.svg)](http://localhost:8080)

## 🚀 v10.1 核心架构：三层防护 + 放大器

v10.1 引入了全新的模块化风控与盈利增强架构，将简单的技术指标升级为具备自我保护能力的系统化交易方案。

### 1. 🛡️ 三层防护 (Account Guardian)
- **第一层 (日亏损保护)**: 单日亏损达 **5%** 自动暂停交易 24 小时，防止情绪化操作或异常行情。
- **第二层 (回撤保护 - 保命模式)**: 账户回撤达 **7%** 触发 **Survival Mode**：
  - 最大杠杆降至 5x
  - 仓位大小减半
  - 禁止金字塔加仓
- **第三层 (账户硬止损)**: 账户回撤达 **10%** 永久锁定机器人，需管理员手动复核解锁。

### 2. ⚡ 放大器 (Pyramiding Manager)
- **趋势增强**: 仅在盈利后加仓，不摊平亏损。
- **三级加仓**:
  - **Level 1**: 盈利 2% → 加仓原仓位的 40%
  - **Level 2**: 盈利 5% → 加仓原仓位的 30%
  - **Level 3**: 盈利 8% → 加仓原仓位的 20%
- **风险控制**: 总仓位风险严格限制在账户余额的 4-6% 以内。

### 3. 🎯 信号评分系统 (Signal Quality Scorer)
不再是简单的买入/卖出，每个信号都会经过 100 分制评估：
- **ADX 强度 (30%)**: 趋势越强分越高。
- **趋势一致性 (25%)**: 1H/4H/30M 多周期共振。
- **突破质量 (25%)**: 布林带挤压突破 + 成交量激增。
- **资金费率 (20%)**: 费率方向对冲评估。
- **门槛**: **>=60分** 允许交易；**>=75分** 标记为 PREMIUM (1.5x 仓位)。

## 📊 策略逻辑 (v10.1 放宽版)

### 入场条件 (多头/空头)
- **趋势确认**: 1H EMA200 确认大趋势方向。
- **强度过滤**: ADX > 8 (放宽以增加开单率)。
- **动量确认**: StochRSI 金叉 (< 50) 或 死叉 (> 50)。
- **波动率检查**: ATR 动态区间 (0.6x - 3.5x) 排除极端行情。
- **挤压避让**: 避开布林带横盘挤压期。

### 智能出场 (Exit Manager)
- **分级止盈**: 
  - 盈利 3% → 平仓 20%
  - 盈利 5% → 平仓 30%
  - 剩余 50% 采用 **ATR 移动止损 (2.8x)** 追逐趋势。
- **锁利机制**: 
  - **保本锁**: 盈利 1.8% 后将止损移至开仓价 +0.5%。
  - **5% 级锁利**: 盈利 5% 后锁定至少 3% 利润。

## 🛠️ 技术特性

### 1. 动态杠杆 (Dynamic Leverage)
- **波动率自适应**: 根据 14 日 ATR 动态计算杠杆 (10x / 7x / 5x / 3x / 2x)。
- **风险对冲**: 自动根据账户保证金占用比率调整下单规模。

### 2. 币种分组 (Coin Grouper)
- **防相关性过度集中**: 
  - MEME 组 (DOGE, SHIB): 最多 1 个仓位。
  - DEFI/LAYER1 组: 最多 2-3 个仓位。
- 防止单一板块崩盘导致全军覆没。

### 3. 数据持久化 (SQLite)
- 放弃 JSON，迁移至 **SQLite (`trades.db`)**。
- 完整记录：交易 ID、成交价、止盈止损、持仓时间、信号评分等。
- 支持实时性能分析（胜率、盈亏比、夏普比率预览）。

## 📈 Web Dashboard v10.0 Final

全新的监控与管理界面 (Port: 8080/8081)：

- **🎮 机器人控制**: 网页端一键 启动/停止/重启。
- **📜 实时日志**: 颜色区分 (INFO/TRADE/ERROR) 的流式日志查看器。
- **📊 性能看板**: 实时显示胜率、净利润、总交易笔数。
- **🛡️ 风控状态**: 实时显示日亏损进度条及防护模式状态。
- **📱 响应式设计**: 支持手机浏览器随时查看。

## 📁 项目结构 (v10.1)

```
binance_bot/
├── src/                   # v10.0 核心模块
│   ├── risk/              # 风控层 (Guardian, Sizer, Grouper, etc.)
│   ├── strategies/        # 策略层 (Scorer, etc.)
│   └── utils/             # 工具层 (Database, Notifier)
├── bot.py                 # 主程序 (已整合 v10.1 架构)
├── strategy.py            # 策略计算核心
├── config.py              # 基础配置
├── web_server.py          # Flask 后端服务
├── web_dashboard.html     # 前端面板
├── trades.db              # SQLite 数据库
└── .env                   # API 密钥 (需自行配置)
```

## 🚀 快速开始

1. **环境准备**:
   ```bash
   pip install -r requirements.txt
   ```

2. **配置密钥**:
   编辑 `.env`：
   ```
   BINANCE_API_KEY=你的API密钥
   BINANCE_API_SECRET=你的私钥
   ```

3. **运行**:
   ```bash
   # 启动交易机器人
   python3 bot.py --real
   
   # 启动 Web 管理后台
   python3 web_server.py
   ```

4. **访问面板**:
   `http://localhost:8081`

## 📝 评估与建议

- **v10.1 优势**: 在震荡行情中通过放宽 StochRSI 条件增加开单率，同时利用三层防护确保小资金（如 10-100 USDT）的生存能力。
- **策略评估**: 属于“宽进严出”型，依靠金字塔加仓在对的趋势中实现爆发性盈利。
- **建议**: 保持 2% 的单笔风险配置，不要随意手动干预机器人的移动止损线。

---

**免责声明**: 本机器人仅供学习和技术交流使用。加密货币交易具有极高风险，作者不对任何因使用本软件造成的财务损失负责。
