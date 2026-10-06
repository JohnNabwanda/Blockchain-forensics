"""Build the Phase 3 dashboard (smart-contract static analysis on the SmartBugs benchmark).

    python build_phase3_dashboard.py     # writes outputs/phase3/dashboard_phase3.html

Run it after run_phase3.py. It reuses the visual style of the Phase 1 dashboard.
"""
import json
import re

from src import config

TEMPLATE = config.ROOT / "src" / "phase3_template.html"
STYLE_FROM = config.ROOT / "src" / "dashboard_template.html"


def main():
    out = config.PHASE3_OUTPUT_DIR
    data = json.load(open(out / "results.json"))
    style = re.search(r"<link rel=\"stylesheet\".*?</style>", STYLE_FROM.read_text(), re.S).group(0)
    html = TEMPLATE.read_text().replace("<!--__STYLE__-->", style) \
        .replace("/*__DATA__*/null", json.dumps(data, separators=(",", ":")).replace("</", "<\\/")) \
        .replace("/*__LINKS__*/null", json.dumps(config.switcher_links("phase3")))
    (out / "dashboard_phase3.html").write_text(html)
    print(f"Dashboard written to {out / 'dashboard_phase3.html'} ({len(html) // 1024} KB)")


if __name__ == "__main__":
    main()
