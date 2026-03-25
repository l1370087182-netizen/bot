#!/usr/bin/env python3
"""Walk-forward 回测框架，使用有限候选参数集做滚动样本外验证。"""

from __future__ import annotations

import argparse
import math
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd

# 避免 config.py 在回测时校验真实密钥
os.environ.setdefault("BINANCE_API_KEY", "backtest")
os.environ.setdefault("BINANCE_API_SECRET", "backtest")

import config  # noqa: E402
import backtest_to_excel as bt  # noqa: E402
from backtest_to_excel import BacktestEngine  # noqa: E402


@dataclass
class CandidatePreset:
    name: str
    description: str
    overrides: Dict[str, object]


@dataclass
class StressScenario:
    name: str
    description: str
    fee_multiplier: float = 1.0
    slippage_multiplier: float = 1.0
    funding_shift: float = 0.0


def build_candidate_presets() -> List[CandidatePreset]:
    """候选集尽量少而有代表性，避免 walk-forward 本身变成大规模调参。"""
    return [
        CandidatePreset(
            name="current_default",
            description="当前默认版：双持仓 + 盘中价格确认 + 提前保本/分批止盈",
            overrides={},
        ),
        CandidatePreset(
            name="single_slot",
            description="更保守：只允许单持仓，其他保持当前默认",
            overrides={"MAX_ACTIVE_SYMBOLS": 1},
        ),
        CandidatePreset(
            name="strict_quality",
            description="更严格的分数门槛，减少中等质量信号",
            overrides={
                "SIGNAL_QUALITY": {
                    "long_min_score": 93.0,
                    "long_full_risk_score": 97.0,
                    "short_min_score": 100.0,
                    "short_full_risk_score": 100.0,
                }
            },
        ),
        CandidatePreset(
            name="profit_hold",
            description="更偏趋势持有：延后保本，止盈档位后移",
            overrides={
                "BREAKEVEN": {"trigger_r": 1.5},
                "RR_LEVELS": [(2.5, 0.20), (3.5, 0.50)],
            },
        ),
    ]


def build_stress_scenarios() -> List[StressScenario]:
    """压力测试只放几种典型实盘恶化场景，避免再走向参数美化。"""
    return [
        StressScenario(
            name="baseline",
            description="基线样本外结果，不额外放大执行摩擦",
        ),
        StressScenario(
            name="execution_stress",
            description="手续费和滑点同时恶化，模拟成交质量变差",
            fee_multiplier=1.5,
            slippage_multiplier=1.5,
        ),
        StressScenario(
            name="execution_plus_funding",
            description="手续费、滑点恶化，并对 funding 加不利偏移",
            fee_multiplier=1.5,
            slippage_multiplier=1.5,
            funding_shift=0.0001,
        ),
    ]


def month_start(ts: pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(year=ts.year, month=ts.month, day=1)


def inclusive_window_end(start: pd.Timestamp, months: int) -> pd.Timestamp:
    return month_start(start + pd.DateOffset(months=months)) - pd.Timedelta(days=1)


def build_walk_forward_windows(
    start: str,
    end: str,
    train_months: int,
    test_months: int,
    step_months: int,
) -> List[dict]:
    start_ts = month_start(pd.Timestamp(start))
    end_ts = pd.Timestamp(end)
    windows: List[dict] = []
    anchor = start_ts
    idx = 1
    while True:
        train_start = anchor
        train_end = inclusive_window_end(train_start, train_months)
        test_start = month_start(train_start + pd.DateOffset(months=train_months))
        test_end = inclusive_window_end(test_start, test_months)
        if test_end > end_ts:
            break
        windows.append(
            {
                "window_id": idx,
                "train_start": train_start,
                "train_end": train_end,
                "test_start": test_start,
                "test_end": test_end,
            }
        )
        anchor = month_start(anchor + pd.DateOffset(months=step_months))
        idx += 1
    return windows


@contextmanager
def temporary_overrides(overrides: Dict[str, object]):
    original = {
        "MAX_ACTIVE_SYMBOLS": config.MAX_ACTIVE_SYMBOLS,
        "ENTRY_RULES": dict(config.ENTRY_RULES),
        "SIGNAL_QUALITY": dict(config.SIGNAL_QUALITY),
        "BREAKEVEN": dict(config.BREAKEVEN),
        "EXIT_R_LEVELS": [dict(x) for x in config.EXIT_STRATEGY["r_levels"]],
        "EXIT_TRAILING": dict(config.EXIT_STRATEGY["trailing_stop"]),
        "RR_2R_MULTIPLE": bt.RR_2R_MULTIPLE,
        "RR_3R_MULTIPLE": bt.RR_3R_MULTIPLE,
    }
    try:
        config.MAX_ACTIVE_SYMBOLS = int(overrides.get("MAX_ACTIVE_SYMBOLS", original["MAX_ACTIVE_SYMBOLS"]))
        bt.MAX_ACTIVE_SYMBOLS = config.MAX_ACTIVE_SYMBOLS

        config.ENTRY_RULES.clear()
        config.ENTRY_RULES.update(original["ENTRY_RULES"])
        config.ENTRY_RULES.update(overrides.get("ENTRY_RULES", {}))

        config.SIGNAL_QUALITY.clear()
        config.SIGNAL_QUALITY.update(original["SIGNAL_QUALITY"])
        config.SIGNAL_QUALITY.update(overrides.get("SIGNAL_QUALITY", {}))
        bt.SIGNAL_QUALITY = config.SIGNAL_QUALITY

        config.BREAKEVEN.clear()
        config.BREAKEVEN.update(original["BREAKEVEN"])
        config.BREAKEVEN.update(overrides.get("BREAKEVEN", {}))
        bt.BREAKEVEN = config.BREAKEVEN

        config.EXIT_STRATEGY["r_levels"] = [dict(x) for x in original["EXIT_R_LEVELS"]]
        config.EXIT_STRATEGY["trailing_stop"] = dict(original["EXIT_TRAILING"])
        bt.RR_2R_MULTIPLE = original["RR_2R_MULTIPLE"]
        bt.RR_3R_MULTIPLE = original["RR_3R_MULTIPLE"]

        if "RR_LEVELS" in overrides:
            (r2, pct2), (r3, pct3) = overrides["RR_LEVELS"]
            config.EXIT_STRATEGY["r_levels"] = [
                {"r_multiple": float(r2), "exit_pct": float(pct2)},
                {"r_multiple": float(r3), "exit_pct": float(pct3)},
            ]
            bt.RR_2R_MULTIPLE = float(r2)
            bt.RR_3R_MULTIPLE = float(r3)

        bt.EXIT_STRATEGY = config.EXIT_STRATEGY
        yield
    finally:
        config.MAX_ACTIVE_SYMBOLS = original["MAX_ACTIVE_SYMBOLS"]
        bt.MAX_ACTIVE_SYMBOLS = original["MAX_ACTIVE_SYMBOLS"]

        config.ENTRY_RULES.clear()
        config.ENTRY_RULES.update(original["ENTRY_RULES"])

        config.SIGNAL_QUALITY.clear()
        config.SIGNAL_QUALITY.update(original["SIGNAL_QUALITY"])
        bt.SIGNAL_QUALITY = config.SIGNAL_QUALITY

        config.BREAKEVEN.clear()
        config.BREAKEVEN.update(original["BREAKEVEN"])
        bt.BREAKEVEN = config.BREAKEVEN

        config.EXIT_STRATEGY["r_levels"] = [dict(x) for x in original["EXIT_R_LEVELS"]]
        config.EXIT_STRATEGY["trailing_stop"] = dict(original["EXIT_TRAILING"])
        bt.EXIT_STRATEGY = config.EXIT_STRATEGY
        bt.RR_2R_MULTIPLE = original["RR_2R_MULTIPLE"]
        bt.RR_3R_MULTIPLE = original["RR_3R_MULTIPLE"]


@contextmanager
def temporary_execution_stress(fee_multiplier: float = 1.0, slippage_multiplier: float = 1.0):
    original_backtest = dict(config.BACKTEST)
    original_bt_backtest = dict(bt.BACKTEST)
    try:
        config.BACKTEST["fee_rate"] = float(original_backtest.get("fee_rate", 0.0005)) * fee_multiplier
        config.BACKTEST["slippage"] = float(original_backtest.get("slippage", 0.001)) * slippage_multiplier
        bt.BACKTEST = config.BACKTEST
        yield
    finally:
        config.BACKTEST.clear()
        config.BACKTEST.update(original_backtest)
        bt.BACKTEST = dict(original_bt_backtest)


def patch_funding_loader(
    engine: BacktestEngine,
    cache_only_funding: bool,
    funding_shift: float = 0.0,
) -> BacktestEngine:
    if cache_only_funding:
        def base_loader(symbol: str, start_ts: pd.Timestamp, end_ts: pd.Timestamp) -> pd.DataFrame:
            cached = engine._read_cached_funding(symbol)
            if cached.empty:
                return cached
            return cached[
                (cached["fundingTime"] >= pd.Timestamp(start_ts))
                & (cached["fundingTime"] <= pd.Timestamp(end_ts))
            ].reset_index(drop=True)
    else:
        original_loader = engine._load_funding_history

        def base_loader(symbol: str, start_ts: pd.Timestamp, end_ts: pd.Timestamp) -> pd.DataFrame:
            return original_loader(symbol, start_ts, end_ts)

    def adjusted_loader(symbol: str, start_ts: pd.Timestamp, end_ts: pd.Timestamp) -> pd.DataFrame:
        funding_df = base_loader(symbol, start_ts, end_ts)
        if funding_df.empty or funding_shift == 0.0:
            return funding_df
        out = funding_df.copy()
        out["fundingRate"] = out["fundingRate"].astype(float) + float(funding_shift)
        return out

    engine._load_funding_history = adjusted_loader
    return engine


def run_engine(
    data_dir: Path,
    output_dir: Path,
    start: pd.Timestamp,
    end: pd.Timestamp,
    symbols: Optional[List[str]],
    initial_balance: float,
    cache_only_funding: bool,
    stress: Optional[StressScenario] = None,
) -> tuple[BacktestEngine, dict]:
    scenario = stress or StressScenario(name="baseline", description="baseline")
    with temporary_execution_stress(
        fee_multiplier=scenario.fee_multiplier,
        slippage_multiplier=scenario.slippage_multiplier,
    ):
        engine = BacktestEngine(
            data_dir=data_dir,
            output_dir=output_dir,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            symbols=symbols,
            initial_balance=initial_balance,
        )
        patch_funding_loader(engine, cache_only_funding=cache_only_funding, funding_shift=scenario.funding_shift)
        engine._load_data()
        return engine, engine._backtest()


def calc_objective(result: dict) -> float:
    ret_pct = float(result["收益率"]) * 100
    dd_pct = float(result["最大回撤"]) * 100
    win_pct = float(result["胜率"]) * 100
    fee_pct = float(result["手续费合计"]) / float(result["初始资金"]) * 100 if result["初始资金"] else 0.0
    trade_count = int(result["交易笔数"])
    trade_penalty = 0.0 if trade_count >= 20 else (20 - trade_count) * 1.5
    return ret_pct - dd_pct * 1.6 + win_pct * 0.35 - fee_pct * 0.4 - trade_penalty


def summarize_result(result: dict) -> dict:
    return {
        "收益率": float(result["收益率"]),
        "最大回撤": float(result["最大回撤"]),
        "交易笔数": int(result["交易笔数"]),
        "胜率": float(result["胜率"]),
        "盈亏比": result["盈亏比"],
        "手续费合计": float(result["手续费合计"]),
        "最终资金": float(result["最终资金"]),
    }


def scale_curve(curve_df: pd.DataFrame, capital_scale: float) -> pd.DataFrame:
    if curve_df is None or curve_df.empty:
        return pd.DataFrame(columns=["日期", "余额", "权益", "回撤比例", "持仓数"])
    curve = curve_df.copy()
    curve["余额"] = curve["余额"] * capital_scale
    curve["权益"] = curve["权益"] * capital_scale
    return curve


def build_combined_curve(curves: Iterable[pd.DataFrame], initial_balance: float) -> pd.DataFrame:
    combined_rows = []
    peak = initial_balance
    for curve in curves:
        if curve is None or curve.empty:
            continue
        for _, row in curve.iterrows():
            equity = float(row["权益"])
            peak = max(peak, equity)
            dd = 0.0 if peak <= 0 else (peak - equity) / peak
            combined_rows.append(
                {
                    "日期": row["日期"],
                    "余额": row["余额"],
                    "权益": equity,
                    "回撤比例": round(dd, 6),
                    "持仓数": row.get("持仓数", 0),
                }
            )
    return pd.DataFrame(combined_rows)


def build_year_summary(trades_df: pd.DataFrame) -> pd.DataFrame:
    if trades_df.empty:
        return pd.DataFrame()
    tmp = trades_df.copy()
    tmp["年"] = pd.to_datetime(tmp["平仓时间"]).dt.year.astype(str)
    return (
        tmp.groupby("年")
        .agg(
            交易笔数=("交易ID", "count"),
            净收益=("净收益", "sum"),
            手续费=("手续费", "sum"),
            胜率=("结果", lambda x: (x == "盈利").mean()),
        )
        .reset_index()
        .sort_values("年")
    )


def build_month_summary(trades_df: pd.DataFrame) -> pd.DataFrame:
    if trades_df.empty:
        return pd.DataFrame()
    tmp = trades_df.copy()
    tmp["月"] = pd.to_datetime(tmp["平仓时间"]).dt.to_period("M").astype(str)
    return (
        tmp.groupby("月")
        .agg(
            交易笔数=("交易ID", "count"),
            净收益=("净收益", "sum"),
            手续费=("手续费", "sum"),
            胜率=("结果", lambda x: (x == "盈利").mean()),
        )
        .reset_index()
        .sort_values("月")
    )


def build_symbol_summary(trades_df: pd.DataFrame) -> pd.DataFrame:
    if trades_df.empty:
        return pd.DataFrame()
    return (
        trades_df.groupby("币种")
        .agg(
            交易笔数=("交易ID", "count"),
            净收益=("净收益", "sum"),
            手续费=("手续费", "sum"),
            平均净收益=("净收益", "mean"),
            平均持仓小时=("持仓小时", "mean"),
            胜率=("结果", lambda x: (x == "盈利").mean()),
        )
        .reset_index()
        .sort_values("净收益", ascending=False)
    )


def build_symbol_diagnostic(trades_df: pd.DataFrame) -> pd.DataFrame:
    if trades_df.empty:
        return pd.DataFrame()

    rows: List[dict] = []
    for symbol, group in trades_df.groupby("币种"):
        long_group = group[group["方向"] == "LONG"]
        short_group = group[group["方向"] == "SHORT"]
        rows.append(
            {
                "币种": symbol,
                "总交易数": int(len(group)),
                "总净收益": round(float(group["净收益"].sum()), 6),
                "总手续费": round(float(group["手续费"].sum()), 6),
                "总胜率": round(float((group["净收益"] > 0).mean()), 6),
                "多头交易数": int(len(long_group)),
                "多头净收益": round(float(long_group["净收益"].sum()), 6) if not long_group.empty else 0.0,
                "多头胜率": round(float((long_group["净收益"] > 0).mean()), 6) if not long_group.empty else 0.0,
                "空头交易数": int(len(short_group)),
                "空头净收益": round(float(short_group["净收益"].sum()), 6) if not short_group.empty else 0.0,
                "空头胜率": round(float((short_group["净收益"] > 0).mean()), 6) if not short_group.empty else 0.0,
                "平均持仓小时": round(float(group["持仓小时"].mean()), 4) if "持仓小时" in group else 0.0,
            }
        )
    return pd.DataFrame(rows).sort_values("总净收益", ascending=False).reset_index(drop=True)


def export_walk_forward_excel(
    output_dir: Path,
    summary_rows: List[dict],
    window_rows: List[dict],
    candidate_rows: List[dict],
    stress_summary_rows: List[dict],
    stress_window_rows: List[dict],
    trades_df: pd.DataFrame,
    curve_df: pd.DataFrame,
    year_df: pd.DataFrame,
    month_df: pd.DataFrame,
    symbol_df: pd.DataFrame,
    symbol_diag_df: pd.DataFrame,
    settings_df: pd.DataFrame,
) -> Path:
    out_path = output_dir / f"walk_forward结果_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    output_dir.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name="WalkForward汇总", index=False)
        pd.DataFrame(window_rows).to_excel(writer, sheet_name="窗口结果", index=False)
        pd.DataFrame(candidate_rows).to_excel(writer, sheet_name="训练候选", index=False)
        pd.DataFrame(stress_summary_rows).to_excel(writer, sheet_name="压力测试汇总", index=False)
        pd.DataFrame(stress_window_rows).to_excel(writer, sheet_name="压力测试窗口", index=False)
        settings_df.to_excel(writer, sheet_name="参数设置", index=False)
        symbol_df.to_excel(writer, sheet_name="样本外品种汇总", index=False)
        symbol_diag_df.to_excel(writer, sheet_name="样本外币种诊断", index=False)
        year_df.to_excel(writer, sheet_name="样本外年度汇总", index=False)
        month_df.to_excel(writer, sheet_name="样本外月度汇总", index=False)
        trades_df.to_excel(writer, sheet_name="样本外交易明细", index=False)
        curve_df.to_excel(writer, sheet_name="样本外资金曲线", index=False)
        for ws in writer.book.worksheets:
            ws.freeze_panes = "A2"
            for col_cells in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in col_cells[:200])
                ws.column_dimensions[col_cells[0].column_letter].width = min(max(width + 2, 10), 32)
    return out_path


def run_walk_forward(
    data_dir: Path,
    output_dir: Path,
    start: str,
    end: str,
    train_months: int,
    test_months: int,
    step_months: int,
    symbols: Optional[List[str]],
    initial_balance: float,
    cache_only_funding: bool,
) -> Path:
    candidates = build_candidate_presets()
    stress_scenarios = build_stress_scenarios()
    windows = build_walk_forward_windows(start, end, train_months, test_months, step_months)
    if not windows:
        raise RuntimeError("没有生成任何 walk-forward 窗口，请检查日期范围与窗口参数。")

    current_capital = float(initial_balance)
    candidate_rows: List[dict] = []
    window_rows: List[dict] = []
    stress_summary_rows: List[dict] = []
    stress_window_rows: List[dict] = []
    oos_trades: List[pd.DataFrame] = []
    oos_curves: List[pd.DataFrame] = []
    selected_windows: List[dict] = []

    for window in windows:
        best_candidate = None
        best_train_result = None
        best_score = -math.inf

        for candidate in candidates:
            with temporary_overrides(candidate.overrides):
                _, train_result = run_engine(
                    data_dir=data_dir,
                    output_dir=output_dir,
                    start=window["train_start"],
                    end=window["train_end"],
                    symbols=symbols,
                    initial_balance=initial_balance,
                    cache_only_funding=cache_only_funding,
                    stress=stress_scenarios[0],
                )
            train_score = calc_objective(train_result)
            train_stats = summarize_result(train_result)
            candidate_rows.append(
                {
                    "窗口ID": window["window_id"],
                    "训练开始": window["train_start"],
                    "训练结束": window["train_end"],
                    "测试开始": window["test_start"],
                    "测试结束": window["test_end"],
                    "候选方案": candidate.name,
                    "说明": candidate.description,
                    "训练目标分": round(train_score, 4),
                    "训练收益率": round(train_stats["收益率"], 6),
                    "训练最大回撤": round(train_stats["最大回撤"], 6),
                    "训练交易笔数": train_stats["交易笔数"],
                    "训练胜率": round(train_stats["胜率"], 6),
                    "训练手续费": round(train_stats["手续费合计"], 4),
                }
            )
            if train_score > best_score:
                best_score = train_score
                best_candidate = candidate
                best_train_result = train_result

        assert best_candidate is not None and best_train_result is not None

        with temporary_overrides(best_candidate.overrides):
            _, test_result = run_engine(
                data_dir=data_dir,
                output_dir=output_dir,
                start=window["test_start"],
                end=window["test_end"],
                symbols=symbols,
                initial_balance=initial_balance,
                cache_only_funding=cache_only_funding,
                stress=stress_scenarios[0],
            )

        train_stats = summarize_result(best_train_result)
        test_stats = summarize_result(test_result)
        test_return = test_stats["收益率"]
        scale = current_capital / initial_balance
        scaled_curve = scale_curve(test_result["资金曲线"], scale)
        oos_curves.append(scaled_curve)
        current_capital = current_capital * (1 + test_return)

        test_trades = test_result["交易明细"].copy()
        if not test_trades.empty:
            test_trades.insert(0, "窗口ID", window["window_id"])
            test_trades.insert(1, "候选方案", best_candidate.name)
            oos_trades.append(test_trades)

        window_rows.append(
            {
                "窗口ID": window["window_id"],
                "训练开始": window["train_start"],
                "训练结束": window["train_end"],
                "测试开始": window["test_start"],
                "测试结束": window["test_end"],
                "最佳方案": best_candidate.name,
                "方案说明": best_candidate.description,
                "训练目标分": round(best_score, 4),
                "训练收益率": round(train_stats["收益率"], 6),
                "训练最大回撤": round(train_stats["最大回撤"], 6),
                "训练交易笔数": train_stats["交易笔数"],
                "训练胜率": round(train_stats["胜率"], 6),
                "测试收益率": round(test_stats["收益率"], 6),
                "测试最大回撤": round(test_stats["最大回撤"], 6),
                "测试交易笔数": test_stats["交易笔数"],
                "测试胜率": round(test_stats["胜率"], 6),
                "测试手续费": round(test_stats["手续费合计"], 4),
                "测试期末资金(复利拼接后)": round(current_capital, 4),
            }
        )
        selected_windows.append({"window": window, "candidate": best_candidate})

    trades_df = pd.concat(oos_trades, ignore_index=True) if oos_trades else pd.DataFrame()
    curve_df = build_combined_curve(oos_curves, initial_balance)
    final_equity = float(curve_df["权益"].iloc[-1]) if not curve_df.empty else initial_balance
    max_dd = float(curve_df["回撤比例"].max()) if not curve_df.empty else 0.0
    wins = int((trades_df["净收益"] > 0).sum()) if not trades_df.empty else 0
    losses = int((trades_df["净收益"] <= 0).sum()) if not trades_df.empty else 0
    win_rate = float((trades_df["净收益"] > 0).mean()) if not trades_df.empty else 0.0
    gp = float(trades_df.loc[trades_df["净收益"] > 0, "净收益"].sum()) if not trades_df.empty else 0.0
    gl = float(trades_df.loc[trades_df["净收益"] < 0, "净收益"].sum()) if not trades_df.empty else 0.0
    pf = abs(gp / gl) if gl != 0 else (math.inf if gp > 0 else None)

    summary_rows = [
        {"指标": "样本外初始资金", "数值": initial_balance},
        {"指标": "样本外最终资金", "数值": round(final_equity, 4)},
        {"指标": "样本外净收益", "数值": round(final_equity - initial_balance, 4)},
        {"指标": "样本外收益率", "数值": round((final_equity - initial_balance) / initial_balance, 6) if initial_balance else 0.0},
        {"指标": "样本外最大回撤", "数值": round(max_dd, 6)},
        {"指标": "样本外交易笔数", "数值": len(trades_df)},
        {"指标": "样本外盈利笔数", "数值": wins},
        {"指标": "样本外亏损笔数", "数值": losses},
        {"指标": "样本外胜率", "数值": round(win_rate, 6)},
        {"指标": "样本外盈亏比", "数值": round(pf, 6) if pf is not None and not math.isinf(pf) else pf},
        {"指标": "样本外手续费合计", "数值": round(float(trades_df["手续费"].sum()), 4) if not trades_df.empty else 0.0},
        {"指标": "Walk-Forward窗口数", "数值": len(windows)},
        {"指标": "训练月数", "数值": train_months},
        {"指标": "测试月数", "数值": test_months},
        {"指标": "滚动步长月数", "数值": step_months},
        {"指标": "候选方案数", "数值": len(candidates)},
        {"指标": "Funding模式", "数值": "仅缓存" if cache_only_funding else "允许下载"},
    ]

    settings_df = pd.DataFrame(
        [
            {"参数": "回测开始", "取值": start},
            {"参数": "回测结束", "取值": end},
            {"参数": "训练窗口(月)", "取值": train_months},
            {"参数": "测试窗口(月)", "取值": test_months},
            {"参数": "滚动步长(月)", "取值": step_months},
            {"参数": "初始资金", "取值": initial_balance},
            {"参数": "候选方案", "取值": ", ".join(candidate.name for candidate in candidates)},
            {"参数": "压力场景", "取值": ", ".join(s.name for s in stress_scenarios)},
            {"参数": "目标函数", "取值": "收益率 - 1.6*最大回撤 + 0.35*胜率 - 0.4*手续费占比 - 低交易惩罚"},
            {"参数": "说明", "取值": "使用有限候选集做滚动训练/样本外测试，避免把 walk-forward 本身做成大规模暴力调参。"},
        ]
    )

    for scenario in stress_scenarios:
        stress_capital = float(initial_balance)
        stress_curves: List[pd.DataFrame] = []
        stress_trades: List[pd.DataFrame] = []
        for selected in selected_windows:
            window = selected["window"]
            candidate = selected["candidate"]
            with temporary_overrides(candidate.overrides):
                _, stress_result = run_engine(
                    data_dir=data_dir,
                    output_dir=output_dir,
                    start=window["test_start"],
                    end=window["test_end"],
                    symbols=symbols,
                    initial_balance=initial_balance,
                    cache_only_funding=cache_only_funding,
                    stress=scenario,
                )

            stress_stats = summarize_result(stress_result)
            stress_scale = stress_capital / initial_balance
            stress_curves.append(scale_curve(stress_result["资金曲线"], stress_scale))
            stress_capital = stress_capital * (1 + stress_stats["收益率"])

            scenario_trades = stress_result["交易明细"].copy()
            if not scenario_trades.empty:
                scenario_trades.insert(0, "压力场景", scenario.name)
                scenario_trades.insert(1, "窗口ID", window["window_id"])
                scenario_trades.insert(2, "候选方案", candidate.name)
                stress_trades.append(scenario_trades)

            stress_window_rows.append(
                {
                    "压力场景": scenario.name,
                    "场景说明": scenario.description,
                    "窗口ID": window["window_id"],
                    "测试开始": window["test_start"],
                    "测试结束": window["test_end"],
                    "候选方案": candidate.name,
                    "测试收益率": round(stress_stats["收益率"], 6),
                    "测试最大回撤": round(stress_stats["最大回撤"], 6),
                    "测试交易笔数": stress_stats["交易笔数"],
                    "测试胜率": round(stress_stats["胜率"], 6),
                    "测试手续费": round(stress_stats["手续费合计"], 4),
                    "测试期末资金(复利拼接后)": round(stress_capital, 4),
                }
            )

        scenario_curve_df = build_combined_curve(stress_curves, initial_balance)
        scenario_trades_df = pd.concat(stress_trades, ignore_index=True) if stress_trades else pd.DataFrame()
        scenario_final_equity = float(scenario_curve_df["权益"].iloc[-1]) if not scenario_curve_df.empty else initial_balance
        scenario_max_dd = float(scenario_curve_df["回撤比例"].max()) if not scenario_curve_df.empty else 0.0
        scenario_win_rate = float((scenario_trades_df["净收益"] > 0).mean()) if not scenario_trades_df.empty else 0.0
        stress_summary_rows.append(
            {
                "压力场景": scenario.name,
                "场景说明": scenario.description,
                "样本外最终资金": round(scenario_final_equity, 4),
                "样本外收益率": round((scenario_final_equity - initial_balance) / initial_balance, 6) if initial_balance else 0.0,
                "样本外最大回撤": round(scenario_max_dd, 6),
                "样本外交易笔数": len(scenario_trades_df),
                "样本外胜率": round(scenario_win_rate, 6),
                "样本外手续费合计": round(float(scenario_trades_df["手续费"].sum()), 4) if not scenario_trades_df.empty else 0.0,
                "手续费倍率": scenario.fee_multiplier,
                "滑点倍率": scenario.slippage_multiplier,
                "Funding偏移": scenario.funding_shift,
            }
        )

    out_path = export_walk_forward_excel(
        output_dir=output_dir,
        summary_rows=summary_rows,
        window_rows=window_rows,
        candidate_rows=candidate_rows,
        stress_summary_rows=stress_summary_rows,
        stress_window_rows=stress_window_rows,
        trades_df=trades_df,
        curve_df=curve_df,
        year_df=build_year_summary(trades_df),
        month_df=build_month_summary(trades_df),
        symbol_df=build_symbol_summary(trades_df),
        symbol_diag_df=build_symbol_diagnostic(trades_df),
        settings_df=settings_df,
    )
    return out_path


def parse_args():
    parser = argparse.ArgumentParser(description="Walk-forward 样本外回测并导出中文 Excel")
    parser.add_argument("--data-dir", default=r"D:\huice", help="数据目录")
    parser.add_argument("--output-dir", default=r"E:\\", help="Excel 输出目录")
    parser.add_argument("--start", default="2020-01-01", help="开始日期，例如 2020-01-01")
    parser.add_argument("--end", default="2025-12-31", help="结束日期，例如 2025-12-31")
    parser.add_argument("--train-months", type=int, default=24, help="训练窗口月数")
    parser.add_argument("--test-months", type=int, default=12, help="测试窗口月数")
    parser.add_argument("--step-months", type=int, default=12, help="窗口滚动步长（月）")
    parser.add_argument("--symbols", default=None, help="币种列表，如 BTCUSDT,ETHUSDT")
    parser.add_argument("--initial-balance", type=float, default=1000.0, help="初始资金")
    parser.add_argument("--allow-funding-download", action="store_true", help="允许 funding 缺失时联网补齐")
    return parser.parse_args()


def main():
    args = parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] if args.symbols else None
    out = run_walk_forward(
        data_dir=Path(args.data_dir),
        output_dir=Path(args.output_dir),
        start=args.start,
        end=args.end,
        train_months=args.train_months,
        test_months=args.test_months,
        step_months=args.step_months,
        symbols=symbols,
        initial_balance=args.initial_balance,
        cache_only_funding=not args.allow_funding_download,
    )
    print(f"Walk-forward completed, Excel exported: {out}")


if __name__ == "__main__":
    main()
