import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


BOT_DIR = Path(__file__).resolve().parent
STATUS_FILE = BOT_DIR / ".bot_status"
PAPER_RUNS_DIR = BOT_DIR / "paper_runs"
TESTNET_RUNS_DIR = BOT_DIR / "testnet_runs"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def mode_label(mode: str) -> str:
    if mode == "testnet":
        return "Binance Testnet"
    if mode == "paper":
        return "本地模拟盘"
    return "实盘"


class RunTracker:
    def __init__(self, mode: str, starting_balance: float = 0.0):
        self.mode = mode
        self.mode_label = mode_label(mode)
        self.starting_balance = float(starting_balance or 0.0)
        self.started_at = now_iso()
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.lock = threading.Lock()

        if mode == "paper":
            self.run_dir = PAPER_RUNS_DIR / self.run_id
            self.db_path = self.run_dir / "paper_trades.db"
            self.data_path = self.run_dir / "paper_run.json"
        elif mode == "testnet":
            self.run_dir = TESTNET_RUNS_DIR / self.run_id
            self.db_path = self.run_dir / "testnet_trades.db"
            self.data_path = self.run_dir / "testnet_run.json"
        else:
            self.run_dir = BOT_DIR
            self.db_path = BOT_DIR / "trades.db"
            self.data_path = BOT_DIR / "live_run_status.json"

        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self.data: Dict[str, Any] = {
            "project": "BinanceUSDT_15m_StructureStrategy",
            "mode": self.mode,
            "mode_label": self.mode_label,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "updated_at": self.started_at,
            "starting_balance": self.starting_balance,
            "database_path": str(self.db_path),
            "data_file_path": str(self.data_path),
            "summary": {},
            "daily_pnl": {},
            "equity_curve": [],
            "trades": [],
            "events": [],
        }
        self._save_data()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_price REAL,
                exit_price REAL,
                size REAL,
                leverage INTEGER,
                pnl REAL,
                pnl_pct REAL,
                entry_time TIMESTAMP,
                exit_time TIMESTAMP,
                duration_hours REAL,
                exit_reason TEXT,
                strategy_version TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL UNIQUE,
                side TEXT,
                size REAL,
                entry_price REAL,
                leverage INTEGER,
                max_profit_pct REAL,
                additions TEXT,
                exit_stages TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_pnl (
                date TEXT PRIMARY KEY,
                pnl REAL,
                trades_count INTEGER,
                winning_trades INTEGER,
                losing_trades INTEGER,
                balance_start REAL,
                balance_end REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS performance_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                metric_name TEXT,
                metric_value REAL,
                period_days INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
        conn.close()

    def _save_data(self) -> None:
        self.data["updated_at"] = now_iso()
        self.data_path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def append_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        with self.lock:
            self.data["events"].append({"timestamp": now_iso(), "event_type": event_type, **payload})
            self._save_data()

    def record_trade(
        self,
        *,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        size: float,
        leverage: int,
        pnl: float,
        pnl_pct: float,
        entry_time: str,
        exit_time: str,
        duration_hours: float,
        exit_reason: str,
        strategy_version: str = "v12.0",
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO trades (
                symbol, side, entry_price, exit_price, size, leverage,
                pnl, pnl_pct, entry_time, exit_time, duration_hours,
                exit_reason, strategy_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                side,
                entry_price,
                exit_price,
                size,
                leverage,
                pnl,
                pnl_pct,
                entry_time,
                exit_time,
                duration_hours,
                exit_reason,
                strategy_version,
            ),
        )
        conn.commit()
        conn.close()

        trade_row = {
            "timestamp": exit_time,
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "size": size,
            "leverage": leverage,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "entry_time": entry_time,
            "exit_time": exit_time,
            "duration_hours": duration_hours,
            "exit_reason": exit_reason,
            "strategy_version": strategy_version,
        }
        if extra:
            trade_row.update(extra)

        with self.lock:
            self.data["trades"].append(trade_row)
            self._save_data()

    def update_snapshot(self, snapshot: Dict[str, Any], append_curve: bool = False) -> None:
        with self.lock:
            self.data["summary"] = snapshot
            if append_curve:
                self.data["equity_curve"].append(
                    {
                        "timestamp": snapshot.get("updated_at", now_iso()),
                        "balance": snapshot.get("balance", 0.0),
                        "equity": snapshot.get("equity", 0.0),
                        "realized_pnl": snapshot.get("realized_pnl", 0.0),
                        "unrealized_pnl": snapshot.get("unrealized_pnl", 0.0),
                        "position_count": snapshot.get("position_count", 0),
                    }
                )
            current_day = datetime.now().strftime("%Y-%m-%d")
            self.data["daily_pnl"][current_day] = {
                "timestamp": snapshot.get("updated_at", now_iso()),
                "balance": snapshot.get("balance", 0.0),
                "equity": snapshot.get("equity", 0.0),
                "realized_pnl": snapshot.get("realized_pnl", 0.0),
                "unrealized_pnl": snapshot.get("unrealized_pnl", 0.0),
                "fees_paid": snapshot.get("fees_paid", 0.0),
                "funding_paid": snapshot.get("funding_paid", 0.0),
            }
            self._save_data()

    def finalize(self, snapshot: Dict[str, Any]) -> None:
        final_snapshot = dict(snapshot)
        final_snapshot["status"] = "stopped"
        final_snapshot["stopped_at"] = now_iso()
        self.update_snapshot(final_snapshot, append_curve=True)


def write_status_file(payload: Dict[str, Any]) -> None:
    STATUS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
