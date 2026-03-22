# Binance Futures Trading Bot v10.2 (AI Enhanced)

币安USDT永续合约量化交易机器人 - **AI增强 + 三层防护** 架构

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![CCXT](https://img.shields.io/badge/CCXT-Latest-green.svg)](https://github.com/ccxt/ccxt)
[![SQLite](https://img.shields.io/badge/SQLite-Persistence-orange.svg)](https://sqlite.org/)
[![Web](https://img.shields.io/badge/Web-Dashboard-blueviolet.svg)](http://localhost:8080)
[![ML](https://img.shields.io/badge/ML-Scikit--Learn-red.svg)](https://scikit-learn.org/)

## 🚀 v10.2 核心架构：AI增强 + 三层防护

v10.2 在v10.1基础上引入了**机器学习信号过滤**和**Windows报告导出**功能，实现更智能的交易决策和更便捷的交易记录管理。

### 1. 🤖 ML信号过滤器 (零Token消耗)
- **本地运行**: 使用scikit-learn，完全免费，不调用任何API
- **自学习机制**: 每笔交易自动记录特征和结果，积累数据后自动重训练
- **双层过滤**: CVD订单流过滤 → ML胜率预测
- **特征工程**: 17维特征包括趋势、动量、波动率、成交量、时间等
- **预测输出**: 胜率概率 + 交易建议（高/中/低置信度）

**Top 5 重要特征**:
1. StochRSI K值 (动量)
2. ADX趋势强度
3. ATR波动率
4. StochRSI D值
5. 成交量比率

### 2. 🛡️ 三层防护 (Account Guardian)
- **第一层 (日亏损保护)**: 单日亏损达 **5%** 自动暂停交易 24 小时
- **第二层 (回撤保护 - 保命模式)**: 账户回撤达 **7%** 触发 **Survival Mode**
- **第三层 (账户硬止损)**: 账户回撤达 **10%** 永久锁定机器人

### 3. ⚡ 放大器 (Pyramiding Manager)
- **趋势增强**: 仅在盈利后加仓，不摊平亏损
- **三级加仓**: 盈利2%/5%/8%时分级加仓
- **风险控制**: 总仓位风险严格限制在账户余额的 4-6% 以内

## 📊 策略逻辑 (v10.2 智能版)

### 信号生成流程
1. **技术指标筛选** → EMA/StochRSI/ADX/布林带
2. **CVD订单流验证** → 检测假突破/假跌破
3. **ML胜率预测** → AI判断信号可靠性
4. **风控检查** → 杠杆/仓位/相关性检查
5. **执行交易** → 只有通过全部过滤的信号才会交易

### 智能出场
- **分级止盈**: 3%/5%分级平仓 + ATR移动止损
- **锁利机制**: 4%/8%/12%/16%多级锁利
- **动态止损**: 基于Hurst指数的ATR自适应止损

## 🛠️ 技术特性

### 1. 动态杠杆 (5x-20x)
- **波动率自适应**: 根据ATR动态计算杠杆
- **范围**: 低波动20x → 高波动5x

### 2. Windows报告导出
- **自动保存**: 每次开仓/平仓自动生成报告
- **保存位置**: `E:\TradingReports\`
- **文件格式**: JSON详细报告 + CSV汇总表
- **目录结构**:
  ```
  TradingReports/
  ├── OpenTrades/      # 开仓报告
  ├── CloseTrades/     # 平仓报告
  └── YYYYMMDD_trades_summary.csv  # 日汇总
  ```

### 3. 数据持久化 (SQLite)
- 完整交易记录：价格、盈亏、持仓时间、信号评分等
- 支持实时性能分析（胜率、净利润、夏普比率）

## 📈 Web Dashboard v10.2

监控与管理界面 (Port: 8081)：

- **🎮 机器人控制**: 一键启动/停止/重启
- **📜 实时日志**: 流式日志查看器
- **📊 性能看板**: 胜率、净利润、今日盈亏、总交易笔数
- **🔮 开单预测**: AI预测下次开单时间和币种排名
- **🛡️ 风控状态**: 实时显示防护模式状态
- **🌐 IP配置**: 币安API白名单管理

## 🤖 ML模块详解

### 训练数据收集
- 每笔平仓自动记录17维特征
- 记录实际盈亏作为标签
- 积累30笔数据后自动重训练

### 模型类型
- **算法**: Gradient Boosting Classifier
- **准确率**: 训练集准确率实时显示
- **预测输出**:
  - 胜率 >= 60%: 高置信度，允许交易
  - 胜率 45-60%: 中等置信度，允许交易
  - 胜率 < 45%: 低置信度，建议观望

### 冷启动
- 内置模拟数据生成器
- 首次运行自动生成200条训练数据
- 模型立即可用，随交易持续优化

## 📁 项目结构 (v10.2)

```
binance_bot/
├── src/
│   ├── risk/              # 风控层
│   ├── strategies/        # 策略层
│   ├── orderflow/         # CVD订单流分析
│   ├── ml/                # 机器学习模块 ⭐NEW
│   │   └── ml_signal_filter.py
│   └── utils/             # 工具层
├── bot.py                 # 主程序
├── strategy.py            # 策略核心
├── config.py              # 配置
├── web_server.py          # Web服务
├── web_dashboard.html     # 前端面板
├── telegram_notifier.py   # Telegram通知
├── ml_bootstrap.py        # ML冷启动脚本 ⭐NEW
├── trades.db              # SQLite数据库
└── .env                   # API密钥
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
   TELEGRAM_BOT_TOKEN=你的Telegram Bot Token (可选)
   TELEGRAM_CHAT_ID=你的Telegram Chat ID (可选)
   ```

3. **ML冷启动** (首次运行):
   ```bash
   python3 ml_bootstrap.py
   ```

4. **运行**:
   ```bash
   # 启动交易机器人
   python3 bot.py --real
   
   # 启动Web管理后台
   python3 web_server.py
   ```

5. **访问面板**:
   `http://localhost:8081`

## 📝 更新日志

### v10.2 (2026-03-22)
- ✅ 新增ML信号过滤器（零Token消耗）
- ✅ 新增Windows E盘交易报告导出
- ✅ 新增多级锁利机制（4%/8%/12%/16%）
- ✅ 修复CVD分析器bug
- ✅ 修复Web页面今日盈亏显示
- ✅ 优化Telegram通知（移除重复排名）
- ✅ 动态杠杆范围调整为5x-20x

### v10.1 (2026-03-20)
- ✅ 三层防护架构
- ✅ 金字塔加仓系统
- ✅ CVD订单流过滤
- ✅ SQLite数据持久化

## ⚠️ 风险提示

1. **杠杆风险**: 5x-20x杠杆可能放大亏损
2. **ML预测限制**: 机器学习基于历史数据，无法预测黑天鹅事件
3. **网络风险**: API连接中断可能导致交易失败
4. **建议**: 先用小资金测试，熟悉后再增加投入

---

**免责声明**: 本机器人仅供学习和技术交流使用。加密货币交易具有极高风险，作者不对任何因使用本软件造成的财务损失负责。
