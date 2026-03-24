# Binance Futures Quant Bot

一个基于 `ccxt.pro` 的 Binance U 本位合约量化交易项目，包含实时 K 线监听、策略打分、仓位管理、Web 监控面板，以及代理接入支持。

## 项目特点

- 实盘与模拟盘双模式
- 15m 主周期 + 1h 确认周期的多时间框架策略
- 基于 ADX、Stoch RSI、EMA200、Funding、CVD 的信号评分
- 支持分批止盈、保本止损、ATR 动态止损、金字塔加仓
- Web 仪表盘可查看持仓、日志、排行榜、市场局势、币种扫描诊断
- 支持通过 HTTP / WebSocket 代理访问 Binance
- 已针对 Binance 限频做了账户侧退避保护，并优先使用 WebSocket 数据流

## 目录说明

- `bot.py`
  实盘机器人主程序，负责交易所连接、K 线监听、账户同步、下单与持仓管理。
- `strategy.py`
  策略指标、信号评分、多时间框架确认、止盈止损和加仓逻辑。
- `config.py`
  交易参数、代理配置、指标阈值、风控参数。
- `web_server.py`
  Web 后端，提供仪表盘页面和数据接口。
- `web_dashboard.html`
  Web 仪表盘前端页面。
- `requirements.txt`
  Python 依赖列表。
- `src/`
  项目补充模块目录。
- `.env.example`
  环境变量配置模板。

## 环境要求

- Windows
- Python 3.10+
- 可访问 Binance 的代理

## 安装

```bash
pip install -r requirements.txt
```

## 配置

1. 复制环境变量模板：

```bash
copy .env.example .env
```

2. 填写你自己的 Binance API Key / Secret

3. 按需要配置代理

项目默认支持通过 `PROXY_URL` 走代理，例如：

```env
PROXY_ENABLED=true
PROXY_URL=http://127.0.0.1:7897
```

## 运行方式

实盘：

```bash
python bot.py --real
```

测试网：

```bash
python bot.py --real --testnet
```

启动 Web 面板：

```bash
python web_server.py
```

默认地址：

```text
http://127.0.0.1:8081
```

## 策略概览

当前策略核心使用以下条件做方向筛选与评分：

- `ADX`
  判断趋势强度
- `Stoch RSI`
  判断超买超卖和金叉死叉
- `EMA200`
  判断中期趋势方向
- `Funding Rate`
  过滤过热或过冷方向
- `CVD`
  辅助评估买卖盘主动性

开仓后支持：

- 保本止损
- ATR 动态止损
- 分级止盈
- 金字塔加仓

## Web 仪表盘

仪表盘支持查看：

- 机器人运行状态
- 连接状态
- 当前持仓
- 做多 / 做空排行榜
- 市场局势图
- 币种扫描诊断
- 实时日志

## 已做优化

最近版本已处理这些关键问题：

- 修复 `ccxt.pro` 异步调用兼容问题
- 修复买卖方向映射错误
- 修复分批止盈重复触发
- 修复 ATR trailing stop 逻辑
- 修复 Web 端排行榜和扫描诊断刷新逻辑
- 修复页面乱码和状态误判
- 降低高频 REST 轮询，优先改用 WebSocket / 缓存数据

## 注意事项

- 不要把 `.env`、日志、数据库文件提交到仓库
- Binance Futures 对账户类 REST 请求有限频，建议优先走用户数据流
- 如果代理出口 IP 被限频封禁，公共行情接口和交易账户接口的可用性可能不同

## 免责声明

本项目仅供学习与研究使用。实盘交易有风险，请先在测试环境和小资金条件下验证。
