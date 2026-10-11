"""Evidence packs: one zip per case for a prosecutor or a lawful request to an exchange or operator.

The pack holds the case, its leads and decisions, the case graph (entities and links), a timeline,
the case's audit trail and custody record, and a readable report. manifest.json lists the SHA-256
of every file plus the audit-chain head at export time; the pack's own hash is entered in the
custody register, so anyone can later check that nothing was changed.
"""
import hashlib
import html
import io
import json
import zipfile
from datetime import datetime, timezone

import pandas as pd

from . import store

MANIFEST = "manifest.json"


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def case_graph(case_id, hops=1):
    ce = store.case_entities(case_id)
    if ce.empty:
        return ce, pd.DataFrame(), pd.DataFrame()
    ents, links = store.neighbourhood(list(ce["entity_id"]), hops=hops)
    return ce, ents, links


def timeline(case_id, links):
    """Flows between case entities and every recorded action on the case, in time order."""
    _, trail = store.case(case_id)
    rows = []
    if len(links):
        for l in links.itertuples():
            if l.ts and not str(l.tx_id).startswith(("agg:", "trace:")):
                amt = f"{l.amount_usd:,.2f} USD" if l.amount_usd == l.amount_usd and l.amount_usd is not None else \
                    (f"{l.amount:,.2f} {l.asset or ''}" if l.amount == l.amount and l.amount is not None else "")
                rows.append({"ts_utc": pd.Timestamp(l.ts), "type": l.kind, "what": f"{l.src} → {l.dst}",
                             "detail": " · ".join(x for x in [amt, l.detail or "", l.confidence or ""] if x)})
            elif l.ts:
                rows.append({"ts_utc": pd.Timestamp(l.ts), "type": l.kind, "what": f"{l.src} → {l.dst}",
                             "detail": f"first of {l.detail}"})
    for a in trail.itertuples():
        rows.append({"ts_utc": pd.Timestamp(a.ts_utc), "type": "analyst action", "what": f"{a.analyst}: {a.action}",
                     "detail": a.detail or ""})
    if not rows:
        return pd.DataFrame(columns=["ts_utc", "type", "what", "detail"])
    t = pd.DataFrame(rows)
    t["ts_utc"] = pd.to_datetime(t["ts_utc"], utc=True, format="mixed")
    return t.sort_values("ts_utc").reset_index(drop=True)


def _report(c, ce, ents, links, tl, exported_by, exported_utc, chain):
    e = lambda x: html.escape("" if x is None or x != x else str(x))
    def table(df, cols):
        if df is None or df.empty:
            return "<p><i>None.</i></p>"
        head = "".join(f"<th>{e(k)}</th>" for k in cols)
        body = "".join("<tr>" + "".join(f"<td>{e(r.get(k))}</td>" for k in cols) + "</tr>" for r in df.to_dict("records"))
        return f"<table><tr>{head}</tr>{body}</table>"
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Evidence pack, case #{c['id']}</title>
<style>body{{font:14px/1.5 system-ui,sans-serif;max-width:1100px;margin:24px auto;padding:0 16px;color:#111}}
table{{border-collapse:collapse;width:100%;font-size:12px;margin:8px 0 20px}}td,th{{border:1px solid #ccc;padding:4px 6px;text-align:left;vertical-align:top;word-break:break-all}}
th{{background:#f2f4f7}}h1{{margin-bottom:0}}.meta{{color:#555}}.note{{background:#fff7e6;border:1px solid #f0c36d;padding:8px 12px;border-radius:6px}}</style></head><body>
<h1>Case #{c['id']}: {e(c['title'])}</h1>
<p class="meta">Status {e(c['status'])} · assigned to {e(c['assignee'])} · opened {e(c['created_utc'])} UTC<br>
Exported by {e(exported_by)} at {e(exported_utc)} UTC · audit chain {'intact' if chain[0] else 'BROKEN at entry ' + e(chain[2])}
({chain[1]} entries, head {e(chain[3][:16])}…)</p>
<p class="note">Scores and indicators are investigative leads, not findings of fact. Each lead below shows whether an analyst
confirmed or dismissed it and why. Verify file integrity against manifest.json (SHA-256).</p>
<h2>Summary</h2><p>{e(c['summary'])}</p>
<h2>Subjects and leads</h2>{table(ce, ['role', 'entity_id', 'kind', 'label', 'risk_score', 'risk_band', 'status', 'decided_by', 'note'])}
<h2>Entities in the case graph</h2>{table(ents, ['id', 'kind', 'label', 'risk_score', 'risk_band', 'reasons', 'module'])}
<h2>Links</h2>{table(links, ['src', 'dst', 'kind', 'asset', 'amount', 'amount_usd', 'tx_id', 'ts', 'confidence', 'detail'])}
<h2>Timeline</h2>{table(tl.astype({'ts_utc': str}) if len(tl) else tl, ['ts_utc', 'type', 'what', 'detail'])}
</body></html>"""


def build(analyst, case_id):
    """Build the pack. Returns (zip bytes, pack sha256, file name). Records the export in custody."""
    c, trail = store.case(case_id)
    if c is None:
        raise ValueError(f"no case #{case_id}")
    ce, ents, links = case_graph(case_id)
    tl = timeline(case_id, links)
    chain = store.verify_audit()
    exported_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
    files = {
        "case.json": json.dumps(c.to_dict(), default=str, indent=1).encode(),
        "leads.csv": ce.to_csv(index=False).encode(),
        "entities.csv": ents.to_csv(index=False).encode(),
        "links.csv": links.to_csv(index=False).encode(),
        "timeline.csv": tl.to_csv(index=False).encode(),
        "audit_trail.csv": trail.to_csv(index=False).encode(),
        "custody.csv": store.custody_log(case_id).to_csv(index=False).encode(),
        "report.html": _report(c, ce, ents, links, tl, analyst, exported_utc, chain).encode(),
    }
    manifest = {"case_id": int(case_id), "exported_by": analyst, "exported_utc": exported_utc,
                "audit_chain": {"intact": chain[0], "entries": chain[1], "head_sha256": chain[3]},
                "files": {name: sha256(b) for name, b in files.items()}}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, b in files.items():
            z.writestr(name, b)
        z.writestr(MANIFEST, json.dumps(manifest, indent=1))
    data = buf.getvalue()
    digest = sha256(data)
    name = f"case_{case_id}_evidence_{exported_utc[:10]}.zip"
    store.custody(analyst, case_id, "exported", name, digest, f"{len(files)} files")
    return data, digest, name


def verify(analyst, data, name="uploaded pack"):
    """Check a pack: every file against manifest.json, and the pack hash against the custody register."""
    digest = sha256(data)
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        manifest = json.loads(z.read(MANIFEST))
    except Exception as e:
        return {"ok": False, "sha256": digest, "problems": [f"not an evidence pack: {e}"], "registered": False}
    problems = []
    for f, h in manifest["files"].items():
        try:
            if sha256(z.read(f)) != h:
                problems.append(f"{f}: content changed")
        except KeyError:
            problems.append(f"{f}: missing")
    extra = set(z.namelist()) - set(manifest["files"]) - {MANIFEST}
    problems += [f"{f}: not in manifest" for f in sorted(extra)]
    reg = store.custody_log(manifest.get("case_id"))
    registered = bool(len(reg) and ((reg["action"] == "exported") & (reg["sha256"] == digest)).any())   # only exports count
    ok = not problems
    store.custody(analyst, manifest.get("case_id"), "verified" if ok else "verification failed", name, digest,
                  "registered export" if registered else "pack hash not in custody register")
    return {"ok": ok, "sha256": digest, "problems": problems, "registered": registered, "manifest": manifest}
