"""Assemble the deployable site/ folder for GitHub Pages.

- Copies data/dashboard.html          -> site/index.html
- Copies data/moneypuller_leads.xlsx  -> site/moneypuller_leads.xlsx
- Writes site/updated.txt with the last build time (from the dashboard header)

The dashboard HTML is fully self-contained (data inlined as JSON), so the
site needs no server: GitHub Pages serves the static files.
"""

import shutil
import time
from pathlib import Path

ROOT = Path(__file__).parent
SITE = ROOT / "site"


def main() -> None:
    SITE.mkdir(exist_ok=True)
    dash = ROOT / "data" / "dashboard.html"
    leads = ROOT / "data" / "moneypuller_leads.xlsx"
    if not dash.exists():
        raise SystemExit("data/dashboard.html not found - run the pipeline first")
    shutil.copyfile(dash, SITE / "index.html")
    if leads.exists():
        shutil.copyfile(leads, SITE / "moneypuller_leads.xlsx")
    (SITE / "updated.txt").write_text(time.strftime("%Y-%m-%d %H:%M UTC"))
    # allow cross-origin download of the xlsx from the same site
    (SITE / ".nojekyll").write_text("")
    print(f"site/ ready ({time.strftime('%Y-%m-%d %H:%M')})")


if __name__ == "__main__":
    main()
