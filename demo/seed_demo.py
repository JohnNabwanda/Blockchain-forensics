"""Build the demo database (data/demo.db) from real, public blockchain data.

    .venv/bin/python demo/seed_demo.py            # then: PLATFORM_DB=data/demo.db .venv/bin/streamlit run app.py

Everything goes through the same code the pages use, so the demo exercises the real system:
  * watchlist: OFAC-listed addresses from demo/watchlist_ofac_sample.csv
  * cases: live lookups and traces on TRON, Ethereum and Bitcoin, a contract audit and a cross-chain run
  * leads: traced wallets are scored and attached; a fixed, written rule decides some of them
    (sanctioned or watchlisted -> Confirmed, exchange or large service -> Dismissed), the rest stay
    Pending so a tester can decide them in the Review queue
  * an evidence pack for the first case, plus a deliberately altered copy for the tamper test

The real database (data/platform.db) is never touched. Results reflect the chains on the day the
script runs; the addresses are public examples of patterns, not allegations about their owners.
"""
import csv
import io
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("PLATFORM_DB", "data/demo.db")
sys.path.insert(0, str(ROOT))

from src import config                                                            # noqa: E402
from src.live import (bitcoin_live, contracts, crosschain, ethereum, evidence, feedback, flows,  # noqa: E402
                      store, tron)

if config.PLATFORM_DB.name == "platform.db":
    sys.exit("Refusing to seed the real database. Unset PLATFORM_DB or point it at data/demo.db.")

DEMO = ROOT / "demo"
OUT = DEMO / "output"
INV, SUP = "investigator", "supervisor"

CASES = [   # (chain, address, title, trace direction, hops, top_k)
    ("eth", "0x098B716B8Aaf21512996dC57EB0615e2383E2f96", "Ronin bridge exploiter: follow the stolen funds", "out", 1, 5),
    ("tron", "TTjHn8qNVxazB3UroiekGRPuM2w2GwvNbn", "Sanctioned TRON wallet: who funds it", "in", 1, 6),
    ("btc", "34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo", "Bitcoin address with CoinJoin activity", "in", 1, 4),
]
CROSS_CHAIN = {"eth": ["0x28C6c06298d514Db089934071355E5743bf21d60"],      # Binance hot wallet (Ethereum)
               "tron": ["TJDENsfBJs4RFETt1X1W8wMDc8M5XnJhCe"]}              # high-volume exchange-like wallet (TRON)
CONTRACT = DEMO / "contracts" / "01_reentrancy_SimpleDAO.sol"


def analyse(chain, address, analyst=INV):
    """Fetch, score and record one address the way its investigation page does."""
    if chain == "tron":
        tx, acc = tron.fetch_transfers(address, max_transfers=300), tron.fetch_account(address)
        s, cp = flows.summarise(address, tx), flows.counterparties(tx)
        ind = tron.risk_indicators(address, s, cp, acc)
        score = flows.risk_score(ind)
        band = tron.band(score)
        flows.record(analyst, "tron", address, tx, score, band, ind, module="tron", asset="USDT")
    elif chain == "eth":
        tx, acc = ethereum.fetch_transfers(address, max_transfers=300), ethereum.fetch_account(address)
        labels = tx.attrs.get("labels", {})
        s, cp = flows.summarise(address, tx), flows.counterparties(tx)
        ind = ethereum.risk_indicators(address, s, cp, acc, labels)
        score = flows.risk_score(ind)
        band = ethereum.band(score)
        flows.record(analyst, "eth", address, tx, score, band, ind, module="eth", asset="USD",
                     kind="contract" if acc["is_contract"] else "wallet", label=", ".join(acc["labels"][:2]) or None)
    else:
        tx, acc = bitcoin_live.fetch_transfers(address, max_transfers=100), bitcoin_live.fetch_account(address)
        s, cp = flows.summarise(address, tx), flows.counterparties(tx)
        ind = bitcoin_live.risk_indicators(address, s, cp, tx.attrs.get("coinjoins", []))
        score = flows.risk_score(ind)
        band = bitcoin_live.band(score)
        flows.record(analyst, "btc", address, tx, score, band, ind, module="btc", asset="USD")
    store.log(analyst, f"{chain} lookup", module=chain, subject=address, detail=f"{len(tx)} transfers (demo seed)")
    return score, band, ind, s


def trace(chain, address, direction, hops, top_k):
    fn = {"tron": tron.trace, "eth": ethereum.trace, "btc": bitcoin_live.trace}[chain]
    G, errors = fn(address, hops=hops, top_k=top_k, direction=direction)
    graph = {"nodes": dict(G.nodes(data=True)), "edges": list(G.edges(data=True))}
    flows.record_trace(INV, chain, graph, asset="USDT" if chain == "tron" else "USD", module=chain)
    store.log(INV, f"{chain} trace {direction} {hops} hops", module=chain, subject=address)
    return [n for n in graph["nodes"] if store.norm_address(n) != store.norm_address(address)], errors


def rule(ind):
    """The written demo rule for deciding a lead; None leaves it Pending for the tester."""
    names = {n for _, n, _ in ind}
    if names & {"Sanctioned address", "Watchlisted", "Mixer contract", "Frozen by the stablecoin issuer"}:
        return "Confirmed", "Demo rule: the lead is itself sanctioned, watchlisted or frozen."
    if "Likely exchange or large service" in names:
        return "Dismissed", "Demo rule: exchange or large service; request KYC records instead of treating it as a suspect."
    return None


def main():
    if config.PLATFORM_DB.exists():
        config.PLATFORM_DB.unlink()
    OUT.mkdir(exist_ok=True)
    print(f"Seeding {config.PLATFORM_DB.relative_to(ROOT)}")

    store.log(INV, "signed in", detail="role investigator (demo seed)")
    with open(DEMO / "watchlist_ofac_sample.csv") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        store.watch(SUP, r["address"], r["label"], r["source"])
    print(f"  watchlist: {len(rows)} OFAC-listed addresses")

    summary = []
    for chain, address, title, direction, hops, top_k in CASES:
        score, band, ind, s = analyse(chain, address)
        case_id, _ = store.open_case(INV, chain, address, title, score, band, "; ".join(n for _, n, _ in ind),
                                     {"summary": s, "indicators": ind}, entity_id=store.eid(chain, address))
        leads, errors = trace(chain, address, direction, hops, top_k)
        decided = 0
        for lead in leads:
            try:
                lead_ind = analyse(chain, lead)[2]
            except Exception as e:                                   # one failing fetch must not stop the seed
                print(f"    could not score lead {lead}: {e}")
                continue
            store.attach(INV, case_id, [store.eid(chain, lead)])
            d = rule(lead_ind)
            if d:
                store.decide_lead(SUP, case_id, store.eid(chain, lead), *d)
                decided += 1
        summary.append((case_id, chain, address, score, band, len(leads), decided))
        print(f"  case #{case_id} {chain} {address}: {score}/100 {band}, {len(leads)} leads, {decided} decided by rule")

    # contract audit
    r = contracts.scan_source(CONTRACT.read_text(), CONTRACT.name)
    if r.get("error"):
        print(f"  contract scan failed: {r['error']}")
    else:
        cs, cb = contracts.risk(r["findings"])
        ent = store.upsert_entity(INV, "contract", r["sha256"][:16], kind="contract", label=CONTRACT.name,
                                  risk_score=cs, risk_band=cb, module="contract",
                                  reasons=sorted({f["check"] for f in r["findings"] if f["severity"] in ("High", "Medium")}))
        store.log(INV, "contract scan", module="contract", subject=CONTRACT.name,
                  detail=f"sha256 {r['sha256'][:16]}, {len(r['findings'])} findings")
        cid, _ = store.open_case(INV, "contract", r["sha256"][:16], f"Contract {CONTRACT.name}", cs, cb,
                                 "; ".join(sorted({f["check"] for f in r["findings"] if f["severity"] == "High"})),
                                 entity_id=ent)
        print(f"  case #{cid} contract {CONTRACT.name}: {cs}/100 {cb}, {len(r['findings'])} findings")

    # cross-chain run between an Ethereum and a TRON exchange wallet
    twins, hops, errors = crosschain.run(CROSS_CHAIN)
    if len(hops):
        hops = hops[hops["confidence"] == "High"].reset_index(drop=True)     # exchanges produce many weak pairs
    cid, _ = store.open_case(INV, "crosschain", "eth+tron exchange wallets", "Cross-chain: exchange outflows and inflows",
                             summary=f"{len(hops)} High-confidence candidate hops", entity_id=None)
    n, ids = crosschain.record(INV, twins, hops, cid)
    print(f"  case #{cid} cross-chain: {len(hops)} High-confidence hops, {n} links" + (f" ({'; '.join(errors)})" if errors else ""))

    # case states, feedback loop and evidence
    first = summary[0][0]
    store.update_case(SUP, first, status="Escalated", note="Demo: escalated for a request to the exchanges receiving the funds.")
    store.update_case(INV, summary[1][0], note="Demo: identify the funding wallets before the next review.")
    for m in feedback.MODULES:
        p = feedback.recalibrate(SUP, m)
        if p:
            print(f"  feedback: {m} High {p['current_high']:.0f} -> {p['high']:.0f} after {p['decisions']} decisions")
    data, sha, name = evidence.build(SUP, first)
    (OUT / name).write_bytes(data)
    tampered = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(tampered, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            body = src.read(item)
            if item.filename == "report.html":
                body = body.replace(b"</body>", b"<p>Edited after export.</p></body>")
            dst.writestr(item, body)
    (OUT / name.replace(".zip", "_TAMPERED.zip")).write_bytes(tampered.getvalue())
    print(f"  evidence pack for case #{first}: demo/output/{name} (sha256 {sha[:16]}...) and a tampered copy")

    ok, entries, bad, _ = store.verify_audit()
    ents, links = store.graph_stats()
    print(f"Done: {entries} audit entries, chain {'intact' if ok else f'BROKEN at #{bad}'}; "
          f"{sum(ents.values())} entities, {sum(links.values())} links in the graph.")


if __name__ == "__main__":
    main()
