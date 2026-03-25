# Binance Futures Quant Bot

一个面向 Binance USDT 永续合约的量化交易项目，当前包含：

- Binance Testnet / 实盘双环境机器人
- Web 实时监控面板
- 中文 Excel 回测导出
- Walk-Forward 样本外滚动验证
- 币种分层与方向限制
- Testnet 运行记录与周报导出

这个项目的目标不是把回测数据“调得好看”，而是尽量让规则策略更接近未来真实可执行的实盘状态。

## 项目定位

当前仓库已经从“纯规则尝试”进入到“样本外验证 + Testnet 联调验证”的阶段。

核心原则：

- 优先实盘一致性，不优先回测报表
- 优先样本外验证，不优先全样本收益
- 优先减少低质量交易，不优先盲目提高频率
- 优先工程稳定性，不优先堆复杂功能

## 当前策略概览

主框架：

- 主交易周期：`15m`
- 趋势确认周期：`1h`
- 结构类型：趋势跟随 + 结构过滤 + 价格确认
- 最大并发持仓：`2`
- 保本触发：`1.2R`
- 分批止盈：`2.0R / 25%`、`3.0R / 50%`
- 剩余仓位：ATR trailing stop

核心信号组件：

- `ADX`
- `Stoch RSI`
- `EMA200`
- `Funding Rate`
- `CVD`
- 结构过滤
- 价格确认

这套系统不是“每个币一套完全独立策略”，而是：

- 一套统一主框架
- 币种分层
- 方向分层

## 当前币种分层

### 核心池

- `BTC`
- `XRP`
- `AVAX`
- `SUI`

### 条件池

- `ETH`：仅保留空头
- `SOL`：仅保留多头

### 观察池

- `TRX`
- `BNB`

### 暂缓池

- `DOGE`
- `ADA`

## 最新验证结果

### 全样本回测

区间：`2020-01-01` 到 `2025-12-31`

- 收益率：`47.59%`
- 最大回撤：`4.59%`
- 交易笔数：`246`
- 胜率：`31.71%`
- 盈亏比：约 `2.00`

结果文件：

- `E:\量化回测结果_20260325_190608.xlsx`

### Walk-Forward 样本外结果

- 收益率：`16.36%`
- 最大回撤：`3.81%`
- 交易笔数：`150`
- 胜率：`28.67%`
- 盈亏比：约 `1.66`

结果文件：

- `E:\walk_forward结果_20260325_193019.xlsx`

### 压力测试

- `baseline`：`16.36%`
- `execution_stress`：`10.34%`
- `execution_plus_funding`：`1.63%`

这说明当前版本对真实执行摩擦仍然敏感，但已经明显强于前期版本。

## 当前工程状态

Web 当前支持两种环境：

- `Binance Testnet`
- `实盘`

Testnet 使用独立密钥：

- `BINANCE_TESTNET_API_KEY`
- `BINANCE_TESTNET_API_SECRET`

运行目录：

- `D:\binance_bot\testnet_runs\<run_id>\`

主要产物：

- `testnet_run.json`
- `testnet_trades.db`
- `测试盘周报_<run_id>.xlsx`

## 连接层现状

当前连接层已经做过一轮重构，目标是提高 Testnet 阶段的稳定性：

- `bot.py` 已拆分为：
  - `exchange_market`
  - `exchange_account`
- 行情流与账户流不再强耦合
- K 线监听采用“少量分组 task”模式，而不是 `20` 条独立 watcher 并发硬顶 Testnet
- funding 获取优先使用 `exchange_market`
- Testnet 账户同步当前降级为低频 REST：
  - `fetch_balance`
  - `fetch_positions`

这样做的原因是：Binance Testnet 的账户 WebSocket 链路稳定性明显弱于实盘，低频 REST 虽然实时性略差，但更适合当前 7 天 Testnet 观察阶段。

## Web 面板能力

当前 Web 面板支持：

- 机器人运行状态
- 当前环境模式
- Binance 连接状态
- 当前持仓
- 做多 / 做空排行榜
- 市场局势
- 币种扫描诊断
- 实时日志
- Testnet 周报导出

日志区当前支持：

- 固定顺序扫描日志
- 滚动式追加
- 最多保留 `100` 条
- `自滚动` 开关
- 每次刷新黄色分隔线

## 已完成的重要修复

仓库已经修过一批会直接影响实盘或监控体验的问题，包括：

- `ccxt.pro` 异步兼容问题
- 开仓方向映射错误
- 分批止盈重复触发
- ATR trailing stop 逻辑错误
- 代理配置与 Binance 连接问题
- Web 排行榜 / 扫描诊断 / 市场局势刷新问题
- 日志乱码与日志刷新问题
- Binance 限频后的退避保护
- Testnet / 实盘模式切换问题
- Web 扫描链路高频请求导致的不稳定问题

## 主要文件说明

### 交易与策略

- `bot.py`
  交易主程序，负责交易所连接、K 线监听、账户同步、下单、持仓管理、运行状态写入

- `strategy.py`
  策略核心逻辑，负责指标计算、信号构建、评分、结构过滤、止盈止损和风控判断

- `config.py`
  全部核心参数、币种分层、方向限制、风控参数、代理配置

### 回测与验证

- `backtest_to_excel.py`
  全样本离线回测，并导出中文 Excel 报告

- `walk_forward_backtest.py`
  Walk-Forward 样本外验证与压力测试

### 运行记录

- `runtime_tracking.py`
  运行状态、权益曲线、交易明细记录

- `paper_run_export.py`
  Testnet / 模拟运行结果导出 Excel

### Web

- `web_server.py`
  Web 后端服务

- `web_dashboard.html`
  Web 面板前端

### 文档

- `docs/PROJECT_SUMMARY.md`
  当前策略、验证结果、工程状态和下一步方向

- `docs/PROJECT_MEMORY.md`
  项目长期记忆锚点

- `AGENTS.md`
  本项目协作指令

## 环境要求

- Windows
- Python 3.10+
- 可访问 Binance HTTP / WebSocket 的稳定网络或代理

## 安装

```bash
pip install -r requirements.txt
```

## 配置

1. 复制环境变量模板

```bash
copy .env.example .env
```

2. 填写你的实盘与 Testnet API Key / Secret

3. 如需代理，配置：

```env
PROXY_ENABLED=true
PROXY_URL=http://127.0.0.1:7897
```

## 运行方式

### 启动 Web 面板

```bash
python web_server.py
```

打开：

- [http://127.0.0.1:8081](http://127.0.0.1:8081)

### 启动机器人

建议优先在 Web 面板里直接切环境并启动。

命令行方式：

- Testnet：

```bash
python bot.py --real --testnet
```

- 实盘：

```bash
python bot.py --real
```

## 回测

### 全样本回测

```bash
python backtest_to_excel.py --start 2020-01-01 --end 2025-12-31 --output-dir E:\
```

### Walk-Forward

```bash
python walk_forward_backtest.py --output-dir E:\
```

## 推荐使用顺序

建议按这个顺序推进：

1. 先跑离线回测
2. 再看 Walk-Forward 样本外
3. 再跑 Binance Testnet 观察
4. 最后再考虑极小资金实盘

不建议直接跳过 Testnet 上实盘。

## 关于 ML / AI

当前项目还没有把 ML / AI 正式接到交易主链路中。

后续更推荐的接入方向是：

- AI 作为退出增强器
- AI 作为风险分层器
- AI 作为市场状态分类器

而不是直接替代现有规则策略。

## 注意事项

- 本项目当前仍处于持续验证阶段，不应视为无风险实盘系统
- Testnet 结果不等于真实实盘结果
- 回测结果只用于验证方向，不代表未来收益保证
- 请勿把真实 API Key / Secret 提交到 Git

