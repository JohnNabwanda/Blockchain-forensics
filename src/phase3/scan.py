"""Run Slither on every benchmark contract and collect its findings.

Standard library only, so it runs in the separate Slither environment (.venv-phase3).
Each contract is compiled with the solc version the benchmark lists for it; solc-select
installs those binaries under ~/.solc-select.
"""
import csv
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .. import config

SOLC_DIR = Path.home() / ".solc-select" / "artifacts"


def load_benchmark(root=config.PHASE3_BENCHMARK_DIR):
    """Contracts with their labelled vulnerabilities and the solc version that compiles them."""
    versions = {r["file"]: r["compiled version"].strip()
                for r in csv.DictReader(open(root / "versions.csv"))}
    contracts = []
    for c in json.load(open(root / "vulnerabilities.json")):
        contracts.append({
            "name": c["name"], "path": c["path"], "folder": c["path"].split("/")[1],
            "solc": versions.get(c["path"], c["pragma"]), "source_url": c.get("source", ""),
            "labels": [{"category": v["category"], "lines": v["lines"]} for v in c["vulnerabilities"]],
        })
    return contracts


def contract_id(c):
    return f"{c['folder']}__{Path(c['name']).stem}"


def solc_binary(version):
    return SOLC_DIR / f"solc-{version}" / f"solc-{version}"


def _lines(finding):
    """Source lines a finding points at: its statement nodes if any, else its first element."""
    nodes = [e for e in finding["elements"] if e.get("type") == "node"]
    els = nodes or finding["elements"][:1]
    return sorted({ln for e in els for ln in e.get("source_mapping", {}).get("lines", [])})


def scan_one(c, raw_dir, root=config.PHASE3_BENCHMARK_DIR):
    """Run Slither on one contract (cached as raw JSON). Returns (findings, error)."""
    out = raw_dir / f"{contract_id(c)}.json"
    if not out.exists():
        solc = solc_binary(c["solc"])
        if not solc.exists():
            return [], f"solc {c['solc']} not installed (run solc-select install {c['solc']})"
        slither = Path(sys.executable).parent / "slither"
        cmd = [str(slither), str(root / c["path"]), "--solc", str(solc), "--json", str(out),
               "--exclude-informational", "--exclude-optimization"]
        try:
            run = subprocess.run(cmd, capture_output=True, text=True, timeout=config.PHASE3_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return [], f"timed out after {config.PHASE3_TIMEOUT_S}s"
        if not out.exists():
            last = [ln for ln in run.stderr.strip().splitlines() if ln.strip()][-1:] or ["no output"]
            return [], f"Slither crashed: {last[0].strip()[:200]}"
    d = json.load(open(out))
    if not d.get("success"):
        return [], (d.get("error") or "Slither failed")[:300]
    findings = []
    for f in d.get("results", {}).get("detectors", []):
        findings.append({"check": f["check"], "impact": f["impact"], "confidence": f["confidence"],
                         "lines": _lines(f), "description": f["description"].strip().split("\n")[0][:300]})
    return findings, None


def scan_all(contracts, raw_dir, workers=4):
    raw_dir.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(workers) as ex:
        results = list(ex.map(lambda c: scan_one(c, raw_dir), contracts))
    for c, (findings, err) in zip(contracts, results):
        c["findings"], c["error"] = findings, err
    return contracts
