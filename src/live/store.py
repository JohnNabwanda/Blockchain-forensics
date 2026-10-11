"""Shared store for the platform (SQLite).

- cases, a hash-chained append-only audit log and a watchlist
- one shared entity graph: every module writes the wallets, contracts, transactions and
  mobile-money accounts it looks at (entities) and the flows between them (links)
- case leads: entities attached to a case, each confirmed or dismissed by an analyst
  (the decisions feed the threshold recalibration in feedback.py)
- risk-band thresholds per module, and a chain-of-custody register for exported evidence
"""
import hashlib
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
    module TEXT NOT NULL,           -- bitcoin | tron | ethereum | contract | mobile_money | crosschain
    subject TEXT NOT NULL,          -- transaction id, wallet address, contract name, ...
    title TEXT NOT NULL,
    risk_score REAL, risk_band TEXT,
    status TEXT NOT NULL DEFAULT 'Open',   -- Open | Escalated | Confirmed | Dismissed | Closed
    assignee TEXT, summary TEXT, evidence TEXT
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL, analyst TEXT NOT NULL, action TEXT NOT NULL,
    case_id INTEGER, module TEXT, subject TEXT, detail TEXT,
    prev_hash TEXT, hash TEXT
);
CREATE TABLE IF NOT EXISTS watchlist (
    address TEXT PRIMARY KEY, label TEXT NOT NULL, source TEXT, added_by TEXT, added_utc TEXT
);
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,            -- chain:address, e.g. tron:T..., eth:0x..., btc:bc1..., btc-tx:<txid>, mm:<account>
    chain TEXT NOT NULL, address TEXT NOT NULL,
    kind TEXT NOT NULL,             -- wallet | contract | transaction | service | mm_account
    label TEXT, risk_score REAL, risk_band TEXT, reasons TEXT,
    module TEXT, added_by TEXT, first_seen_utc TEXT, updated_utc TEXT
);
CREATE TABLE IF NOT EXISTS links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    src TEXT NOT NULL, dst TEXT NOT NULL,
    kind TEXT NOT NULL,             -- transfer | trace | attribution | same_key | cross_chain
    chain TEXT, asset TEXT, amount REAL, amount_usd REAL,
    tx_id TEXT NOT NULL DEFAULT '', ts TEXT,
    module TEXT, confidence TEXT, detail TEXT, added_by TEXT, added_utc TEXT,
    UNIQUE (src, dst, kind, tx_id)
);
CREATE TABLE IF NOT EXISTS case_entities (
    case_id INTEGER NOT NULL, entity_id TEXT NOT NULL,
    role TEXT NOT NULL,             -- subject | lead
    status TEXT NOT NULL DEFAULT 'Pending',  -- Pending | Confirmed | Dismissed
    score_at_review REAL, band_at_review TEXT, module TEXT,
    added_by TEXT, added_utc TEXT, decided_by TEXT, decided_utc TEXT, note TEXT,
    PRIMARY KEY (case_id, entity_id)
);
CREATE TABLE IF NOT EXISTS thresholds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module TEXT NOT NULL, high REAL NOT NULL, medium REAL NOT NULL,
    precision REAL, decisions INTEGER, reason TEXT, updated_by TEXT, updated_utc TEXT
);
CREATE TABLE IF NOT EXISTS custody (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER, ts_utc TEXT NOT NULL, analyst TEXT NOT NULL,
    action TEXT NOT NULL,           -- exported | verified | verification failed
    item TEXT, sha256 TEXT, detail TEXT
);
CREATE INDEX IF NOT EXISTS links_src ON links (src);
CREATE INDEX IF NOT EXISTS links_dst ON links (dst);
"""
STATUSES = ["Open", "Escalated", "Confirmed", "Dismissed", "Closed"]
LEAD_STATUSES = ["Pending", "Confirmed", "Dismissed"]
GENESIS = "0" * 64
_migrated = False


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _migrate(con):
    """Bring a database from the first platform version up to date (adds the audit hash chain)."""
    cols = {r[1] for r in con.execute("PRAGMA table_info(audit)")}
    for c in ("prev_hash", "hash"):
        if c not in cols:
            con.execute(f"ALTER TABLE audit ADD COLUMN {c} TEXT")
    rows = con.execute("SELECT id, ts_utc, analyst, action, case_id, module, subject, detail, hash "
                       "FROM audit ORDER BY id").fetchall()
    prev = GENESIS
    for r in rows:
        if r[8] is None:
            h = _audit_hash(prev, r[1:8])
            con.execute("UPDATE audit SET prev_hash=?, hash=? WHERE id=?", (prev, h, r[0]))
            prev = h
        else:
            prev = r[8]


@contextmanager
def db():
    global _migrated
    config.PLATFORM_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.PLATFORM_DB, timeout=10)
    if not _migrated:
        con.executescript(SCHEMA)
        _migrate(con)
        con.commit()
        _migrated = True
    try:
        yield con
        con.commit()
    finally:
        con.close()


# ---------------------------------------------------------------- audit log (hash-chained)
def _audit_hash(prev, fields):
    """SHA-256 over the previous entry's hash and this entry's fields: editing or deleting any
    earlier entry breaks every hash after it."""
    payload = json.dumps([prev, *[None if f is None else str(f) for f in fields]], ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def log(analyst, action, case_id=None, module=None, subject=None, detail=None):
    detail = detail if isinstance(detail, (str, type(None))) else json.dumps(detail, default=str)
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        prev = (con.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone() or [GENESIS])[0] or GENESIS
        fields = (_now(), analyst, action, case_id, module, subject, detail)
        con.execute("INSERT INTO audit (ts_utc, analyst, action, case_id, module, subject, detail, prev_hash, hash) "
                    "VALUES (?,?,?,?,?,?,?,?,?)", (*fields, prev, _audit_hash(prev, fields)))


def verify_audit():
    """Recompute the whole chain. Returns (ok, entries checked, id of the first broken entry or None, head hash)."""
    with db() as con:
        rows = con.execute("SELECT id, ts_utc, analyst, action, case_id, module, subject, detail, prev_hash, hash "
                           "FROM audit ORDER BY id").fetchall()
    prev = GENESIS
    for r in rows:
        if r[8] != prev or _audit_hash(prev, r[1:8]) != r[9]:
            return False, len(rows), r[0], prev
        prev = r[9]
    return True, len(rows), None, prev


# ---------------------------------------------------------------- cases
def open_case(analyst, module, subject, title, risk_score=None, risk_band=None, summary="", evidence=None,
              entity_id=None):
    """Open a case, or return the existing open case for the same subject. `entity_id` attaches the
    subject's node in the shared graph to the case."""
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
    if entity_id:
        attach(analyst, case_id, [entity_id], role="subject")
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


# ---------------------------------------------------------------- watchlist
def watchlist():
    with db() as con:
        return pd.read_sql_query("SELECT * FROM watchlist ORDER BY added_utc DESC", con)


def watchlist_map():
    with db() as con:
        return dict(con.execute("SELECT address, label FROM watchlist").fetchall())


def norm_address(address):
    a = address.strip()
    return a.lower() if a.lower().startswith("0x") else a


def watch(analyst, address, label, source=""):
    if not label.strip():
        raise ValueError("a label (why this wallet is watched) is required")
    address = norm_address(address)
    with db() as con:
        con.execute("INSERT OR REPLACE INTO watchlist VALUES (?,?,?,?,?)",
                    (address, label.strip(), source.strip(), analyst, _now()))
    log(analyst, "watchlist add", module=chain_of(address), subject=address, detail=f"{label} ({source})")


def unwatch(analyst, address):
    with db() as con:
        con.execute("DELETE FROM watchlist WHERE address=?", (address,))
    log(analyst, "watchlist remove", module=chain_of(address), subject=address)


# ---------------------------------------------------------------- shared entity graph
def chain_of(address):
    """Which chain an address belongs to, from its format."""
    a = address.strip()
    if len(a) == 34 and a.startswith("T") and a.isalnum():
        return "tron"
    if a.lower().startswith("0x") and len(a) == 42:
        return "eth"
    if a.lower().startswith(("bc1", "1", "3")) and 26 <= len(a) <= 62 and a.isalnum():
        return "btc"
    return None


def eid(chain, address):
    return f"{chain}:{norm_address(address)}"


def upsert_entity(analyst, chain, address, kind="wallet", label=None, risk_score=None, risk_band=None,
                  reasons=None, module=None):
    """Add or refresh a node in the shared graph. Later scores replace earlier ones; labels are kept."""
    i = eid(chain, address)
    with db() as con:
        con.execute(
            "INSERT INTO entities (id, chain, address, kind, label, risk_score, risk_band, reasons, module, added_by, "
            "first_seen_utc, updated_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, label=COALESCE(excluded.label, label), "
            "risk_score=COALESCE(excluded.risk_score, risk_score), risk_band=COALESCE(excluded.risk_band, risk_band), "
            "reasons=COALESCE(excluded.reasons, reasons), module=COALESCE(excluded.module, module), "
            "updated_utc=excluded.updated_utc",
            (i, chain, norm_address(address), kind, label, risk_score, risk_band,
             None if reasons is None else json.dumps(reasons, default=str), module, analyst, _now(), _now()))
    return i


def add_links(analyst, rows, module):
    """Insert flows into the shared graph. Each row: src, dst (entity ids), kind, and optionally chain,
    asset, amount, amount_usd, tx_id, ts, confidence, detail. Existing links are left as they are."""
    if not rows:
        return 0
    with db() as con:
        before = con.total_changes
        con.executemany(
            "INSERT OR IGNORE INTO links (src, dst, kind, chain, asset, amount, amount_usd, tx_id, ts, module, "
            "confidence, detail, added_by, added_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(r["src"], r["dst"], r["kind"], r.get("chain"), r.get("asset"), r.get("amount"), r.get("amount_usd"),
              r.get("tx_id") or "", None if r.get("ts") is None else str(r["ts"]), module, r.get("confidence"),
              None if r.get("detail") is None else str(r["detail"]), analyst, _now()) for r in rows])
        return con.total_changes - before


def ensure_entities(analyst, ids, module=None):
    """Create bare nodes for link endpoints that are not in the graph yet."""
    with db() as con:
        known = {r[0] for r in con.execute(
            f"SELECT id FROM entities WHERE id IN ({','.join('?' * len(ids))})", list(ids))} if ids else set()
    for i in set(ids) - known:
        chain, address = i.split(":", 1)
        kind = {"btc-tx": "transaction", "mm": "mm_account", "contract": "contract"}.get(chain, "wallet")
        upsert_entity(analyst, chain, address, kind=kind, module=module)


def entity(entity_id):
    with db() as con:
        e = pd.read_sql_query("SELECT * FROM entities WHERE id=?", con, params=[entity_id])
    return e.iloc[0] if len(e) else None


def entities(ids=None):
    with db() as con:
        if ids is None:
            return pd.read_sql_query("SELECT * FROM entities ORDER BY updated_utc DESC", con)
        ids = list(ids)
        if not ids:
            return pd.read_sql_query("SELECT * FROM entities WHERE 0", con)
        return pd.read_sql_query(f"SELECT * FROM entities WHERE id IN ({','.join('?' * len(ids))})", con, params=ids)


def neighbourhood(seeds, hops=2, max_nodes=80):
    """Entities and links within `hops` of the seed entities in the shared graph (both directions)."""
    seen, frontier = set(seeds), set(seeds)
    with db() as con:
        for _ in range(hops):
            if not frontier or len(seen) >= max_nodes:
                break
            f = list(frontier)
            q = ",".join("?" * len(f))
            rows = con.execute(f"SELECT src, dst FROM links WHERE src IN ({q}) OR dst IN ({q})", f + f).fetchall()
            nxt = {n for r in rows for n in r} - seen
            nxt = set(list(nxt)[:max(max_nodes - len(seen), 0)])
            seen |= nxt
            frontier = nxt
        ids = list(seen)
        q = ",".join("?" * len(ids))
        links = pd.read_sql_query(f"SELECT * FROM links WHERE src IN ({q}) AND dst IN ({q}) ORDER BY ts",
                                  con, params=ids + ids) if ids else pd.DataFrame()
    return entities(ids), links


def graph_stats():
    with db() as con:
        n = dict(con.execute("SELECT chain, COUNT(*) FROM entities GROUP BY chain").fetchall())
        l = dict(con.execute("SELECT kind, COUNT(*) FROM links GROUP BY kind").fetchall())
    return n, l


# ---------------------------------------------------------------- case leads (review queue)
def attach(analyst, case_id, entity_ids, role="lead"):
    """Attach graph entities to a case. Each one gets a lead record for an analyst to confirm or dismiss."""
    ents = entities(entity_ids).set_index("id")
    added = 0
    with db() as con:
        for i in entity_ids:
            e = ents.loc[i] if i in ents.index else None
            cur = con.execute(
                "INSERT OR IGNORE INTO case_entities (case_id, entity_id, role, score_at_review, band_at_review, module, "
                "added_by, added_utc) VALUES (?,?,?,?,?,?,?,?)",
                (case_id, i, role, None if e is None else e["risk_score"], None if e is None else e["risk_band"],
                 None if e is None else e["module"], analyst, _now()))
            added += cur.rowcount
    if added:
        log(analyst, f"{added} {role}(s) attached", case_id, detail=", ".join(entity_ids[:20]))
    return added


def case_entities(case_id):
    with db() as con:
        return pd.read_sql_query(
            "SELECT ce.*, e.chain, e.address, e.kind, e.label, e.risk_score, e.risk_band, e.reasons "
            "FROM case_entities ce LEFT JOIN entities e ON e.id = ce.entity_id WHERE ce.case_id=? "
            "ORDER BY ce.role DESC, e.risk_score DESC", con, params=[case_id])


def decide_lead(analyst, case_id, entity_id, status, note):
    if status not in ("Confirmed", "Dismissed"):
        raise ValueError("status must be Confirmed or Dismissed")
    if not (note or "").strip():
        raise ValueError("a justification is required")
    with db() as con:
        con.execute("UPDATE case_entities SET status=?, decided_by=?, decided_utc=?, note=? WHERE case_id=? AND entity_id=?",
                    (status, analyst, _now(), note.strip(), case_id, entity_id))
    log(analyst, f"lead {status.lower()}", case_id, subject=entity_id, detail=note.strip())


def decisions(module=None):
    """Every confirmed or dismissed lead with the score it had, for recalibration."""
    q = ("SELECT ce.*, COALESCE(ce.module, e.module) AS mod FROM case_entities ce "
         "LEFT JOIN entities e ON e.id = ce.entity_id WHERE ce.status != 'Pending' AND ce.score_at_review IS NOT NULL")
    with db() as con:
        d = pd.read_sql_query(q, con)
    return d[d["mod"] == module] if module else d


# ---------------------------------------------------------------- thresholds and custody
def thresholds(module):
    with db() as con:
        r = con.execute("SELECT high, medium FROM thresholds WHERE module=? ORDER BY id DESC LIMIT 1", (module,)).fetchone()
    return r


def threshold_history():
    with db() as con:
        return pd.read_sql_query("SELECT * FROM thresholds ORDER BY id DESC", con)


def set_thresholds(analyst, module, high, medium, precision, n, reason):
    with db() as con:
        con.execute("INSERT INTO thresholds (module, high, medium, precision, decisions, reason, updated_by, updated_utc) "
                    "VALUES (?,?,?,?,?,?,?,?)", (module, high, medium, precision, n, reason, analyst, _now()))
    log(analyst, "risk thresholds recalibrated", module=module, detail=f"High >= {high:g}, Medium >= {medium:g}: {reason}")


def custody(analyst, case_id, action, item, sha256, detail=None):
    with db() as con:
        con.execute("INSERT INTO custody (case_id, ts_utc, analyst, action, item, sha256, detail) VALUES (?,?,?,?,?,?,?)",
                    (case_id, _now(), analyst, action, item, sha256, detail))
    log(analyst, f"evidence {action}", case_id, subject=item, detail=f"sha256 {sha256}" + (f"; {detail}" if detail else ""))


def custody_log(case_id=None):
    with db() as con:
        if case_id is None:
            return pd.read_sql_query("SELECT * FROM custody ORDER BY id DESC", con)
        return pd.read_sql_query("SELECT * FROM custody WHERE case_id=? ORDER BY id", con, params=[case_id])
