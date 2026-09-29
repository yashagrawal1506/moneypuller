"""One-shot daily update: everything MoneyPuller needs after market close.

Steps (each idempotent, so re-running is safe):
  1. Scrape latest Trade Spotlight articles into the DB
  2. Map any new stock names -> Yahoo symbols (NSE list + overrides + fuzzy)
  3. Fetch missing/stale prices for all symbols with leads
  4. Re-evaluate verdicts for every lead
  5. Recompute dynamic confidence for live leads (+ append history snapshot)
  6. Regenerate data/moneypuller_leads.xlsx
  7. Rebuild data/dashboard.html

Usage:
    python daily_update.py              # full chain (local default)
    python daily_update.py --no-fetch   # skip price fetch (fast, offline)
    python daily_update.py --cloud      # cloud mode: skip scraping if it
                                        # fails ( Moneycontrol may block
                                        # datacenter IPs); keep last-good DB
"""

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
CLOUD = "--cloud" in sys.argv


def run(label: str, cmd: list[str], budget: int = 600,
        allow_fail: bool = False) -> bool:
    print(f"\n=== {label} ===", flush=True)
    t0 = time.time()
    r = subprocess.run([sys.executable, *cmd], cwd=ROOT,
                       capture_output=True, text=True)
    tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-6:])
    print(tail if tail.strip() else "(no output)")
    dt = time.time() - t0
    if r.returncode != 0:
        if allow_fail:
            print(f"!! '{label}' failed after {dt:.0f}s — continuing (allowed).")
            return False
        print(f"!! '{label}' FAILED after {dt:.0f}s — stopping the chain.")
        raise SystemExit(1)
    print(f"-- ok ({dt:.0f}s)", flush=True)
    return True


def main() -> None:
    t0 = time.time()
    print(f"MoneyPuller daily update — {time.strftime('%Y-%m-%d %H:%M')}")

    # 1. scrape: in cloud mode a scrape failure is tolerated (the article
    #    site sometimes blocks datacenter IPs) — the rest still refreshes
    run("1/6 Scrape latest Trade Spotlight articles",
        ["-m", "moneypuller", "-n", "3"],
        allow_fail=CLOUD)
    run("2/6 Map new symbols", ["build_symbol_map.py"])
    if "--no-fetch" not in sys.argv:
        # budget is per-run seconds; 2 passes cover ~full universe
        run("3/6 Fetch prices (pass 1)", ["fetch_prices.py", "540"])
        run("3/6 Fetch prices (pass 2)", ["fetch_prices.py", "540"])
        run("3/6 Fetch prices for new-only symbols", ["fetch_missing_prices.py", "300"])
    run("4/6 Evaluate verdicts", ["evaluate_verdicts.py", "--all"])
    run("5/6 Recompute confidence", ["-m", "moneypuller.confidence"])
    run("6/6 Export Excel + dashboard", ["-m", "moneypuller", "--export-only", "default"])
    run("6/6 Export Excel + dashboard (2)", ["build_dashboard.py"])

    print(f"\nAll done in {time.time() - t0:.0f}s.")
    print("Open:  data/moneypuller_leads.xlsx   |   data/dashboard.html")


if __name__ == "__main__":
    main()
