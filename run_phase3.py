"""Phase 3, Track B: static analysis of smart contracts with Slither on the SmartBugs benchmark.

    .venv-phase3/bin/python run_phase3.py      # about 5-10 minutes the first time; results are cached

Writes outputs/phase3/: results.json (every contract, label and finding), findings.csv, report.md.
Track B answers a different question from Track A: is this contract code exploitable, before or at
deployment? It is evaluated on its own benchmark, not on transaction data.
"""
import csv
import json
import time
from importlib.metadata import version

from src import config
from src.phase3.evaluate import CATEGORY_LABELS, DETECTORS, evaluate
from src.phase3.scan import contract_id, load_benchmark, scan_all


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def write_findings_csv(contracts, path):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["contract", "folder", "check", "impact", "confidence", "categories", "on_label", "lines", "description"])
        for c in contracts:
            for f in c["findings"]:
                w.writerow([c["path"], c["folder"], f["check"], f["impact"], f["confidence"],
                            ";".join(f["categories"]), f["matched"], " ".join(map(str, f["lines"])), f["description"]])


def pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "-"


def write_report(m, contracts, path):
    lines = [
        "# Phase 3 results: smart-contract static analysis (Track B)", "",
        f"Slither on the SmartBugs curated benchmark: {m['contracts']} Solidity contracts with "
        f"{m['labels']} labelled vulnerabilities. {m['analysed']} contracts analysed, {m['failed']} failed to compile.", "",
        f"**{m['line_hits']} of {m['labels']} labelled vulnerabilities ({pct(m['line_hits'], m['labels'])}) were found on "
        f"the labelled line** (within {m['line_tolerance']} lines) by a detector for the same category. "
        f"Counting only categories Slither has a detector for: {m['covered_line_hits']} of {m['labels_with_detector']} "
        f"({pct(m['covered_line_hits'], m['labels_with_detector'])}).", "",
        "## By category", "",
        "| Category | Labelled | Found on the line | Found in the contract | Slither findings | On a labelled line |",
        "|---|---|---|---|---|---|",
    ]
    for r in m["per_category"]:
        if not r["has_detector"]:
            lines.append(f"| {r['label']} | {r['labelled']} | no detector | no detector | - | - |")
        else:
            lines.append(f"| {r['label']} | {r['labelled']} | {r['line_hits']} ({pct(r['line_hits'], r['labelled'])}) | "
                         f"{r['contract_hits']} ({pct(r['contract_hits'], r['labelled'])}) | {r['findings']} | "
                         f"{r['findings_on_label']} |")
    lines += [
        "", "## Reading the numbers", "",
        "- *Found on the line*: a finding of the right category within "
        f"{m['line_tolerance']} lines of a labelled line. *Found in the contract*: the right category anywhere in the contract.",
        "- *Slither findings* that are not on a labelled line are not necessarily false: the benchmark labels one "
        "intended flaw per spot and leaves other real issues unlabelled. They still cost review time.",
        "- Arithmetic overflow, front running and short addresses have no Slither detector. They need fuzzing, "
        "symbolic execution or off-chain checks, which the full Phase 3 adds (Echidna or Foundry).",
        "- The detector-to-category mapping is in `src/phase3/evaluate.py` and was fixed before the scan ran.", "",
    ]
    failed = [c for c in contracts if c["error"]]
    if failed:
        lines += ["## Contracts that failed", ""] + [f"- `{c['path']}` (solc {c['solc']}): {c['error']}" for c in failed]
    path.write_text("\n".join(lines))


def main():
    out = config.PHASE3_OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    contracts = load_benchmark()
    log(f"{len(contracts)} contracts, {sum(len(c['labels']) for c in contracts)} labelled vulnerabilities")
    t0 = time.time()
    scan_all(contracts, out / "raw")
    log(f"Scanned in {time.time() - t0:.0f}s")
    m = evaluate(contracts)
    for c in contracts:
        c["id"] = contract_id(c)
        c["source"] = (config.PHASE3_BENCHMARK_DIR / c["path"]).read_text(errors="replace")
    json.dump({"tool_version": version("slither-analyzer"), "metrics": m, "detectors": DETECTORS, "category_labels": CATEGORY_LABELS, "contracts": contracts},
              open(out / "results.json", "w"), indent=1)
    write_findings_csv(contracts, out / "findings.csv")
    write_report(m, contracts, out / "report.md")
    log(f"Found on the line: {m['line_hits']}/{m['labels']}; failed contracts: {m['failed']}")
    log(f"Done. Outputs in {out}")


if __name__ == "__main__":
    main()
