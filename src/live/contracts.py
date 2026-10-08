"""Live smart-contract audit: run Slither on Solidity source an investigator uploads or pastes.

Slither lives in its own environment (config.SLITHER_ENV). The compiler version is taken from the
contract's `pragma solidity` line and matched to an installed solc (solc-select).
"""
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

from .. import config
from ..phase3.scan import SOLC_DIR, _lines

SEVERITY_ORDER = {"High": 0, "Medium": 1, "Low": 2, "Informational": 3, "Optimization": 4}
SCAN_DIR = config.ROOT / "data" / "contract_scans"


def installed_solc():
    vs = [p.name.removeprefix("solc-") for p in SOLC_DIR.glob("solc-*") if (p / p.name).exists()]
    return sorted(vs, key=lambda v: tuple(int(x) for x in v.split(".")))


def _v(s):
    return tuple(int(x) for x in s.split("."))


def pick_solc(source):
    """Newest installed solc that satisfies the source's pragma (supports ^, >=, <, =, ranges)."""
    m = re.search(r"pragma\s+solidity\s+([^;]+);", source)
    versions = installed_solc()
    if not versions:
        return None, "No Solidity compiler installed (run solc-select install 0.8.26)."
    if not m:
        return versions[-1], None
    ok = []
    for v in versions:
        good = True
        for op, ver in re.findall(r"(\^|~|>=|<=|>|<|=)?\s*(\d+\.\d+\.\d+)", m.group(1)):
            a, b = _v(v), _v(ver)
            if op == "^":
                good &= a >= b and a[:2] == b[:2] if b[0] == 0 else a >= b and a[0] == b[0]
            elif op == "~":
                good &= a >= b and a[:2] == b[:2]
            elif op == ">=":
                good &= a >= b
            elif op == ">":
                good &= a > b
            elif op == "<=":
                good &= a <= b
            elif op == "<":
                good &= a < b
            else:
                good &= a == b
        if good:
            ok.append(v)
    if not ok:
        return None, f"No installed compiler matches 'pragma solidity {m.group(1).strip()}'. " \
                     f"Installed: {', '.join(versions)}"
    return ok[-1], None


def scan_source(source, filename="Contract.sol", include_low=True):
    """Compile and analyse one Solidity file. Returns a dict with findings, solc version and errors."""
    solc, err = pick_solc(source)
    sha = hashlib.sha256(source.encode()).hexdigest()
    result = {"filename": filename, "sha256": sha, "solc": solc, "lines": source.count("\n") + 1,
              "findings": [], "error": err, "contracts": re.findall(r"^\s*(?:abstract\s+)?contract\s+(\w+)", source, re.M)}
    if err:
        return result
    SCAN_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / Path(filename).name
        path.write_text(source)
        out = Path(d) / "out.json"
        cmd = [str(config.SLITHER_ENV / "bin" / "slither"), str(path), "--solc", str(SOLC_DIR / f"solc-{solc}" / f"solc-{solc}"),
               "--json", str(out), "--exclude-optimization"]
        try:
            run = subprocess.run(cmd, capture_output=True, text=True, timeout=config.CONTRACT_SCAN_TIMEOUT_S, cwd=d)
        except subprocess.TimeoutExpired:
            result["error"] = f"Analysis timed out after {config.CONTRACT_SCAN_TIMEOUT_S}s"
            return result
        if not out.exists():
            tail = [ln for ln in run.stderr.splitlines() if ln.strip()][-3:]
            result["error"] = "Compilation or analysis failed: " + " | ".join(t.strip()[:200] for t in tail)
            return result
        d_json = json.loads(out.read_text())
    if not d_json.get("success"):
        result["error"] = (d_json.get("error") or "Slither failed")[:500]
        return result
    for f in d_json.get("results", {}).get("detectors", []):
        if not include_low and f["impact"] in ("Low", "Informational"):
            continue
        result["findings"].append({"severity": f["impact"], "confidence": f["confidence"], "check": f["check"],
                                   "lines": _lines(f), "description": f["description"].strip()})
    result["findings"].sort(key=lambda x: (SEVERITY_ORDER.get(x["severity"], 9), x["check"]))
    (SCAN_DIR / f"{sha[:16]}.json").write_text(json.dumps(result, indent=1))
    return result


def risk(findings):
    """0-100 contract risk from findings: High 30, Medium 10, Low 2 points each (capped)."""
    pts = {"High": 30, "Medium": 10, "Low": 2}
    score = min(100, sum(pts.get(f["severity"], 0) for f in findings))
    return score, ("High" if score >= 50 else "Medium" if score >= 20 else "Low")
