"""SQLite 元数据管理。"""

import json
import sqlite3
import threading
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "storage" / "metadata.db"
_LOCK = threading.Lock()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _LOCK:
        c = _conn()
        c.execute(
            """CREATE TABLE IF NOT EXISTS cases (
                case_id TEXT PRIMARY KEY,
                review_module TEXT NOT NULL,
                contract_type TEXT NOT NULL,
                review_role TEXT NOT NULL,
                change_pattern TEXT,
                risk_name TEXT,
                data_json TEXT NOT NULL
            )"""
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_module ON cases(review_module)")
        c.commit()
        c.close()


def upsert_case(case: dict) -> None:
    with _LOCK:
        c = _conn()
        c.execute(
            """INSERT OR REPLACE INTO cases
               (case_id, review_module, contract_type, review_role, change_pattern, risk_name, data_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                case["case_id"],
                case.get("review_module", ""),
                json.dumps(case.get("contract_type", []), ensure_ascii=False),
                json.dumps(case.get("review_role", []), ensure_ascii=False),
                case.get("change_pattern", ""),
                case.get("risk_name", ""),
                json.dumps(case, ensure_ascii=False),
            ),
        )
        c.commit()
        c.close()


def filter_ids(
    review_module: str | None = None,
    contract_type: str | None = None,
    review_role: str | None = None,
) -> set[str]:
    with _LOCK:
        c = _conn()
        where = ["1=1"]
        params: list[str] = []
        if review_module:
            where.append("review_module = ?")
            params.append(review_module)
        if contract_type:
            where.append(
                "EXISTS (SELECT 1 FROM json_each(contract_type) WHERE value = ?)"
            )
            params.append(contract_type)
        if review_role:
            where.append(
                "EXISTS (SELECT 1 FROM json_each(review_role) WHERE value = ?)"
            )
            params.append(review_role)
        ids = {
            row[0]
            for row in c.execute(
                f"SELECT case_id FROM cases WHERE {' AND '.join(where)}", params
            ).fetchall()
        }
        c.close()
        return ids


def load_cases(case_ids: list[str]) -> list[dict]:
    if not case_ids:
        return []
    with _LOCK:
        c = _conn()
        placeholders = ",".join("?" for _ in case_ids)
        rows = c.execute(
            f"SELECT data_json FROM cases WHERE case_id IN ({placeholders})",
            case_ids,
        ).fetchall()
        case_map = {json.loads(row[0])["case_id"]: json.loads(row[0]) for row in rows}
        c.close()
        return [case_map[cid] for cid in case_ids if cid in case_map]
