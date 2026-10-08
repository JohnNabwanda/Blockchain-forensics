"""Shared case store for the platform: cases, an append-only audit log and a wallet watchlist (SQLite)."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

import pandas as pd

from .. import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_utc TEXT NOT NULL, updated_utc TEXT NOT NULL,
    module TEXT NOT NULL,           -- bitcoin | tron | contract | mobile_money
    subject TEXT NOT NULL,          -- transaction id, wallet address, contract name, ...
    title TEXT NOT NULL,
    risk_score REAL, risk_band TEXT,
    status TEXT NOT NULL DEFAULT 'Open',   -- Open | Escalated | Confirmed | Dismissed | Closed
    assignee TEXT, summary TEXT, evidence TEXT
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL, analyst TEXT NOT NULL, action TEXT NOT NULL,
    case_id INTEGER, module TEXT, subject TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS watchlist (
    address TEXT PRIMARY KEY, label TEXT NOT NULL, source TEXT, added_by TEXT, added_utc TEXT
);
"""
STATUSES = ["Open", "Escalated", "Confirmed", "Dismissed", "Closed"]


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def db():
    config.PLATFORM_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.PLATFORM_DB)
    con.executescript(SCHEMA)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def log(analyst, action, case_id=None, module=None, subject=None, detail=None):
    with db() as con:
        con.execute("INSERT INTO audit (ts_utc, analyst, action, case_id, module, subject, detail) "
                    "VALUES (?,?,?,?,?,?,?)", (_now(), analyst, action, case_id, module, subject,
                                               detail if isinstance(detail, (str, type(None))) else json.dumps(detail)))


def open_case(analyst, module, subject, title, risk_score=None, risk_band=None, summary="", evidence=None):
    """Open a case, or return the existing open case for the same subject."""
    with db() as con:
        row = con.execute("SELECT id FROM cases WHERE module=? AND subject=? AND status NOT IN ('Closed','Dismissed')",
                          (module, subject)).fetchone()
        if row:
            return row[0], False
        cur = con.execute(
            "INSERT INTO cases (created_utc, updated_utc, module, subject, title, risk_score, risk_band, assignee, "
            "summary, evidence) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (_now(), _now(), module, subject, title, risk_score, risk_band, analyst, summary,
             json.dumps(evidence or {}, default=str)))
        case_id = cur.lastrowid
    log(analyst, "case opened", case_id, module, subject, title)
    return case_id, True


def update_case(analyst, case_id, status=None, note=None, assignee=None):
    if status is not None and status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    if status in ("Confirmed", "Dismissed", "Closed") and not (note or "").strip():
        raise ValueError("a justification is required to confirm, dismiss or close a case")
    with db() as con:
        sets, vals = ["updated_utc=?"], [_now()]
        if status:
            sets.append("status=?"); vals.append(status)
        if assignee:
            sets.append("assignee=?"); vals.append(assignee)
        con.execute(f"UPDATE cases SET {', '.join(sets)} WHERE id=?", (*vals, case_id))
        module, subject = con.execute("SELECT module, subject FROM cases WHERE id=?", (case_id,)).fetchone()
    action = f"status -> {status}" if status else "note added"
    log(analyst, action, case_id, module, subject, (note or "").strip() or None)


def cases(status=None, module=None):
    q, args = "SELECT * FROM cases WHERE 1=1", []
    if status:
        q += f" AND status IN ({','.join('?' * len(status))})"; args += list(status)
    if module:
        q += " AND module=?"; args.append(module)
    with db() as con:
        return pd.read_sql_query(q + " ORDER BY updated_utc DESC", con, params=args)


def case(case_id):
    with db() as con:
        c = pd.read_sql_query("SELECT * FROM cases WHERE id=?", con, params=[case_id])
        a = pd.read_sql_query("SELECT ts_utc, analyst, action, detail FROM audit WHERE case_id=? ORDER BY id",
                              con, params=[case_id])
    return (c.iloc[0] if len(c) else None), a


def audit(limit=500):
    with db() as con:
        return pd.read_sql_query("SELECT * FROM audit ORDER BY id DESC LIMIT ?", con, params=[limit])


def watchlist():
    with db() as con:
        return pd.read_sql_query("SELECT * FROM watchlist ORDER BY added_utc DESC", con)


def watchlist_map():
    with db() as con:
        return dict(con.execute("SELECT address, label FROM watchlist").fetchall())


def watch(analyst, address, label, source=""):
    if not label.strip():
        raise ValueError("a label (why this wallet is watched) is required")
    with db() as con:
        con.execute("INSERT OR REPLACE INTO watchlist VALUES (?,?,?,?,?)",
                    (address.strip(), label.strip(), source.strip(), analyst, _now()))
    log(analyst, "watchlist add", module="tron", subject=address.strip(), detail=f"{label} ({source})")


def unwatch(analyst, address):
    with db() as con:
        con.execute("DELETE FROM watchlist WHERE address=?", (address,))
    log(analyst, "watchlist remove", module="tron", subject=address)
