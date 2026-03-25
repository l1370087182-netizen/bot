import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd


def _safe_read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Run data file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _table_df(db_path: Path, table_name: str) -> pd.DataFrame:
    if not db_path.exists():
        return pd.DataFrame()
    conn = sqlite3.connect(db_path)
    try:
        return pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
    except Exception:
        return pd.DataFrame()
    finally:
        conn.close()


def export_paper_run(run_data_file: str | Path) -> str:
    run_data_path = Path(run_data_file)
    data = _safe_read_json(run_data_path)
    run_dir = run_data_path.parent
    db_path = Path(data.get("database_path") or (run_dir / "paper_trades.db"))
    run_id = data.get("run_id") or datetime.now().strftime("%Y%m%d_%H%M%S")
    mode = data.get("mode") or "paper"
    report_prefix = "测试盘周报" if mode == "testnet" else "模拟盘周报"

    summary = data.get("summary", {}) or {}
    trades = data.get("trades", []) or []
    events = data.get("events", []) or []
    equity_curve = data.get("equity_curve", []) or []
    daily_pnl = data.get("daily_pnl", {}) or {}

    start_balance = float(data.get("starting_balance", 0.0) or 0.0)
    final_equity = float(summary.get("equity", summary.get("balance", start_balance)) or start_balance)
    realized_pnl = float(summary.get("realized_pnl", 0.0) or 0.0)
    unrealized_pnl = float(summary.get("unrealized_pnl", 0.0) or 0.0)
    fees_paid = float(summary.get("fees_paid", 0.0) or 0.0)
    funding_paid = float(summary.get("funding_paid", 0.0) or 0.0)
    total_return_pct = ((final_equity - start_balance) / start_balance * 100) if start_balance else 0.0

    trades_df = pd.DataFrame(trades)
    if trades_df.empty:
        trades_df = _table_df(db_path, "trades")

    if not trades_df.empty:
        trades_df["pnl"] = pd.to_numeric(trades_df.get("pnl"), errors="coerce").fillna(0.0)
        total_trades = len(trades_df)
        wins = int((trades_df["pnl"] > 0).sum())
        losses = int((trades_df["pnl"] < 0).sum())
        win_rate = (wins / total_trades * 100) if total_trades else 0.0
        gross_profit = float(trades_df.loc[trades_df["pnl"] > 0, "pnl"].sum())
        gross_loss = abs(float(trades_df.loc[trades_df["pnl"] < 0, "pnl"].sum()))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0
    else:
        total_trades = wins = losses = 0
        win_rate = gross_profit = gross_loss = profit_factor = 0.0

    equity_df = pd.DataFrame(equity_curve)
    max_drawdown_pct = 0.0
    if not equity_df.empty and "equity" in equity_df:
        equity_df["equity"] = pd.to_numeric(equity_df["equity"], errors="coerce").ffill()
        running_peak = equity_df["equity"].cummax()
        drawdown = (equity_df["equity"] - running_peak) / running_peak.replace(0, pd.NA)
        max_drawdown_pct = abs(float(drawdown.min() * 100)) if not drawdown.empty else 0.0

    summary_df = pd.DataFrame(
        [
            {"指标": "项目标识", "数值": data.get("project", "")},
            {"指标": "运行模式", "数值": data.get("mode_label", data.get("mode", ""))},
            {"指标": "运行ID", "数值": run_id},
            {"指标": "开始时间", "数值": data.get("started_at", "")},
            {"指标": "最近更新时间", "数值": data.get("updated_at", "")},
            {"指标": "起始资金", "数值": round(start_balance, 4)},
            {"指标": "最终权益", "数值": round(final_equity, 4)},
            {"指标": "累计收益", "数值": round(final_equity - start_balance, 4)},
            {"指标": "收益率%", "数值": round(total_return_pct, 2)},
            {"指标": "已实现盈亏", "数值": round(realized_pnl, 4)},
            {"指标": "未实现盈亏", "数值": round(unrealized_pnl, 4)},
            {"指标": "手续费", "数值": round(fees_paid, 4)},
            {"指标": "Funding影响", "数值": round(funding_paid, 4)},
            {"指标": "交易笔数", "数值": total_trades},
            {"指标": "盈利笔数", "数值": wins},
            {"指标": "亏损笔数", "数值": losses},
            {"指标": "胜率%", "数值": round(win_rate, 2)},
            {"指标": "Profit Factor", "数值": round(profit_factor, 4)},
            {"指标": "最大回撤%", "数值": round(max_drawdown_pct, 2)},
            {"指标": "运行数据文件", "数值": str(run_data_path)},
            {"指标": "交易数据库", "数值": str(db_path)},
        ]
    )

    daily_df = pd.DataFrame(
        [
            {"日期": key, **(value or {})}
            for key, value in sorted(daily_pnl.items(), key=lambda item: item[0])
        ]
    )
    if not daily_df.empty:
        rename_map = {
            "timestamp": "记录时间",
            "balance": "余额",
            "equity": "权益",
            "realized_pnl": "已实现盈亏",
            "unrealized_pnl": "未实现盈亏",
            "fees_paid": "手续费累计",
            "funding_paid": "Funding累计",
        }
        daily_df.rename(columns=rename_map, inplace=True)

    events_df = pd.DataFrame(events)
    if not events_df.empty:
        events_df.rename(
            columns={
                "timestamp": "时间",
                "event_type": "事件类型",
                "symbol": "币种",
                "side": "方向",
                "price": "成交价",
                "mark_price": "标记价",
                "size": "数量",
                "fee": "手续费",
                "reason": "原因",
                "remaining_size": "剩余数量",
            },
            inplace=True,
        )

    if not trades_df.empty:
        trades_df = trades_df.rename(
            columns={
                "symbol": "币种",
                "side": "方向",
                "entry_price": "入场价",
                "exit_price": "离场价",
                "size": "数量",
                "leverage": "杠杆",
                "pnl": "盈亏",
                "pnl_pct": "盈亏%",
                "entry_time": "入场时间",
                "exit_time": "离场时间",
                "duration_hours": "持仓小时",
                "exit_reason": "离场原因",
                "strategy_version": "策略版本",
            }
        )

    if not equity_df.empty:
        equity_df = equity_df.rename(
            columns={
                "timestamp": "时间",
                "balance": "余额",
                "equity": "权益",
                "realized_pnl": "已实现盈亏",
                "unrealized_pnl": "未实现盈亏",
                "position_count": "持仓数",
            }
        )

    positions_df = _table_df(db_path, "positions")
    daily_pnl_db_df = _table_df(db_path, "daily_pnl")

    output_path = run_dir / f"{report_prefix}_{run_id}.xlsx"
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="绩效汇总", index=False)
        daily_df.to_excel(writer, sheet_name="每日收益", index=False)
        equity_df.to_excel(writer, sheet_name="权益曲线", index=False)
        trades_df.to_excel(writer, sheet_name="交易明细", index=False)
        events_df.to_excel(writer, sheet_name="事件明细", index=False)
        positions_df.to_excel(writer, sheet_name="当前持仓快照", index=False)
        daily_pnl_db_df.to_excel(writer, sheet_name="数据库日统计", index=False)

    return str(output_path)
