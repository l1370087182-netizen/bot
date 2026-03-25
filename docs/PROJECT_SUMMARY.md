# 项目摘要

- 当前日期：`2026-03-26`
- 项目目录：`D:\binance_bot`
- 项目标识：`BinanceUSDT_15m_StructureStrategy`

## 当前结论

- 当前主线不是继续为了回测数字调参，而是优先完成 `Binance Testnet` 的真实环境联调与 7 天模拟验证。
- 规则策略已经进入“可观察、可小步修补”的阶段，后续优化应优先服务实盘一致性、执行稳定性和可维护性。
- 当前所有项目相关回复都应默认带前缀：
  `[项目记忆已唤醒：BinanceUSDT_15m_StructureStrategy]`

## 策略核心逻辑

- 主交易周期：`15m`
- 趋势确认周期：`1h`
- 结构类型：趋势跟随 + 结构过滤 + 价格确认
- 止损：ATR 动态止损
- 止盈：分批止盈 + ATR trailing stop
- 保本：`1.2R`
- 最大并发持仓：`2`
- 同币种冷却：`540` 分钟

## 币种分层

- 核心池：`BTC / XRP / AVAX / SUI`
- 条件池：`ETH(仅空) / SOL(仅多)`
- 观察池：`TRX / BNB`
- 暂缓池：`DOGE / ADA`

## 方向限制

- `ETHUSDT`：禁多，保留空头
- `DOGEUSDT`：禁多
- `ADAUSDT`：禁多
- `SOLUSDT`：禁空，保留多头

## 最新参数基线

| 参数 | 当前值 |
| --- | --- |
| `MAX_ACTIVE_SYMBOLS` | `2` |
| `PRIMARY_TIMEFRAME` | `15m` |
| `CONFIRM_TIMEFRAME` | `1h` |
| `LEVERAGE` | `12` |
| `RISK_PER_TRADE` | `0.015` |
| `signal_cooldown_minutes` | `540` |
| `BREAKEVEN.trigger_r` | `1.2` |
| `RR_2R_MULTIPLE` | `2.0` |
| `RR_3R_MULTIPLE` | `3.0` |

## 历史验证结果

### 全样本回测

- 文件：`E:\量化回测结果_20260325_190608.xlsx`
- 区间：`2020-01-01` 到 `2025-12-31`
- 收益率：`47.59%`
- 最大回撤：`4.59%`
- 交易笔数：`246`
- 胜率：`31.71%`
- 盈亏比：约 `2.00`

### Walk-Forward 样本外

- 文件：`E:\walk_forward结果_20260325_193019.xlsx`
- 样本外收益率：`16.36%`
- 样本外最大回撤：`3.81%`
- 样本外交易笔数：`150`
- 样本外胜率：`28.67%`
- 样本外盈亏比：约 `1.66`

### 样本外压力测试

| 场景 | 收益率 | 最大回撤 |
| --- | ---: | ---: |
| `baseline` | `16.36%` | `3.81%` |
| `execution_stress` | `10.34%` | `4.21%` |
| `execution_plus_funding` | `1.63%` | `9.69%` |

## 当前工程状态

- Web 当前支持两种环境：
  - `Binance Testnet`
  - `实盘`
- Testnet 使用独立密钥：
  - `BINANCE_TESTNET_API_KEY`
  - `BINANCE_TESTNET_API_SECRET`
- Testnet 运行目录：
  - `D:\binance_bot\testnet_runs\<run_id>\`
- 主要产物：
  - `testnet_run.json`
  - `testnet_trades.db`
  - `测试盘周报_<run_id>.xlsx`

## 最近 Web / 扫描链路优化

- 将模式切换 UI 从下拉框改为两个相邻按钮：
  - `Binance Testnet`
  - `实盘`
- 修复了模式切换时旧状态覆盖的问题，后端优先以真实运行进程决定当前模式。
- 修复了日志时间的北京时间转换错误。
- 日志区改成滚动式追加，最多保留 `100` 条，并支持 `自滚动` 开关。
- 扫描日志输出顺序固定为配置币种顺序，不再每轮乱序。
- Web 扫描链路增加了：
  - 市场上下文缓存
  - K 线近缓存
  - 较低的扫描并发
  - 单币请求失败时回退到上一轮有效扫描结果
- 当 Binance 公共接口短时超时或代理抖动时，页面不再整屏刷成 0 分。
- 当前 Web 刷新节奏已进一步收紧：
  - 扫描快照刷新：`8s`
  - 日志前端拉取：`5s`
  - 扫描并发上限：`2`
- 机器人 WebSocket 异常重连也已放缓，避免断线后立即高频重连放大链路压力。

## 最近连接层重构

- `bot.py` 已拆分为：
  - `exchange_market`
  - `exchange_account`
- 原有下单、持仓管理、策略评分与风控逻辑保持不变，只调整了连接组织方式。
- `watch_klines()` 当前已调整为“少量分组 task”模式：
  - 保留了市场/账户双 exchange 分离
  - 放弃了 `20` 条独立 watcher task 的激进版本
  - 当前按 `2` 组 K 线流运行，更适合 Binance Testnet
- 账户流继续单独监听：
  - `watch_balance`
  - `watch_positions`
- funding 获取也改为优先使用 `exchange_market`
- Testnet 账户同步当前已降级为低频 REST：
  - 原因是 `ccxt.pro` Testnet 账户流会落到不稳定的 `fstream.binancefuture.com`
  - 当前改为 `fetch_balance + fetch_positions` 的低频同步，更稳但实时性略低于 WS

## 已知风险

- 当前策略仍然是趋势型低到中等胜率策略，不是高胜率均值回归策略。
- 样本外表现虽然稳定，但仍然强依赖执行质量、代理稳定性和交易所接口可用性。
- Binance Testnet 更接近真实链路，但仍不等于真实实盘撮合环境。
- `BNB / TRX` 不是明显拖累，但也还不足以上升为核心池。

## 当前任务状态

- 当前正在准备 / 运行 `7` 天 Binance Testnet 模拟验证。
- 一周后会基于：
  - 绩效汇总
  - 每日收益
  - 交易明细
  - equity curve
  - 周报导出结果
  做正式复盘分析。
- 在一周验证结束前，不再做大规模策略参数优化，只做必要的小范围工程修补。
