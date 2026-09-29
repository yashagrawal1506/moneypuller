"""Evaluate verdicts for leads and write them to the verdicts table.

Usage:
    python evaluate_verdicts.py                # Titan Company (sample stock)
    python evaluate_verdicts.py "HDFC Bank"    # any stock_name
    python evaluate_verdicts.py --all          # every dated lead in the DB
"""

import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from moneypuller.verdicts import evaluate_lead, write_verdicts

DB = Path("data/moneypuller.db")


def load_leads(conn: sqlite3.Connection, stock_name: str | None) -> list[dict]:
    sql = """SELECT r.id, r.stock_name, a.record_date, r.cmp, r.action,
                    r.target_1, r.target_2, r.target_3, r.stop_loss
             FROM recommendations r JOIN articles a ON a.id = r.article_id
             WHERE a.record_date IS NOT NULL"""
    args: list = []
    if stock_name:
        sql += " AND r.stock_name = ?"
        args.append(stock_name)
    sql += " ORDER BY a.record_date, r.id"
    return [dict(r) for r in conn.execute(sql, args)]


def load_prices(conn: sqlite3.Connection) -> tuple[dict, dict]:
    """symbol -> (all_dates, price_by_date) for every priced symbol."""
    out: dict[str, tuple[list, dict]] = {}
    for sym, d, o, h, l, c, v in conn.execute(
            """SELECT symbol, date, open, high, low, close, volume
               FROM prices ORDER BY symbol, date"""):
        dates, by_date = out.get(sym, ([], {}))
        by_date[d] = {"open": o, "high": h, "low": l, "close": c,
                      "volume": v or 0}
        dates.append(d)
        out[sym] = (dates, by_date)
    return out


def main() -> None:
    stock = None
    if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
        stock = sys.argv[1]
    show_all = "--all" in sys.argv

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    leads = load_leads(conn, stock)
    if not leads:
        raise SystemExit("no dated leads found"
                         + (f" for {stock!r}" if stock else ""))
    stock_of = {l["id"]: l["stock_name"] for l in leads}
    sym_of = {r[0]: r[1] for r in conn.execute(
        "SELECT stock_name, yahoo_symbol FROM symbols")}

    prices = load_prices(conn)
    missing_syms = sorted({sym_of.get(stock_of[l["id"]]) or stock_of[l["id"]]
                           for l in leads
                           if not sym_of.get(stock_of[l["id"]])
                           or sym_of[stock_of[l["id"]]] not in prices})
    conn.close()

    results: dict[int, dict] = {}
    for l in leads:
        symbol = sym_of.get(stock_of[l["id"]])
        bundle = prices.get(symbol)
        if not symbol or not bundle:
            results[l["id"]] = {"status": "NO PRICE DATA", "entry_price": None,
                                "exit_price": None, "exit_level": None,
                                "exit_date": None, "days_taken": None,
                                "pct": None,
                                "note": "no Yahoo symbol / no price rows"}
            continue
        all_dates, by_date = bundle
        results[l["id"]] = evaluate_lead(l, all_dates, by_date)

    conn = sqlite3.connect(DB)
    n = write_verdicts(conn, results)
    conn.close()
    print(f"wrote {n} verdict rows to verdicts table")

    # console report
    rows = [{**l, **results[l["id"]]} for l in leads]
    if not show_all:
        shown = rows
    else:
        shown = rows  # summary only below; full detail lives in Excel
    by_status: dict[str, int] = defaultdict(int)
    for r in rows:
        key = ("AMBIGUOUS" if r["status"].startswith("AMBIGUOUS")
               else r["status"])
        by_status[key] += 1
    print("\nstatus breakdown:")
    for k in ("target achieved", "SL achieved", "AMBIGUOUS", "NO HIT YET",
              "NO PRICE DATA", "NOT EVALUABLE (no targets, no SL)"):
        if by_status.get(k):
            print(f"  {k:38s} {by_status[k]:>5}")
    print(f"  {'TOTAL':38s} {len(rows):>5}")

    if stock:
        print(f"\n{'rec':>5} {'date':11s} {'act':5s} {'entry':>8s} {'T1':>8s} "
              f"{'SL':>8s} {'exit':>8s} {'lvl':>10} {'days':>4} {'pct':>7}  status")
        print("-" * 96)
        for r in shown:
            pct = f"{r['pct']:+.1%}" if r["pct"] is not None else "-"
            print(f"{r['id']:>5} {r['record_date']:11s} "
                  f"{(r['action'] or 'Buy'):5s} {r['entry_price'] or 0:>8} "
                  f"{r['target_1'] or 0:>8} {r['stop_loss'] or 0:>8} "
                  f"{r['exit_price'] or 0:>8} {(r['exit_level'] or '-'):>10} "
                  f"{r['days_taken'] or 0:>4} {pct:>7}  {r['status']}"
                  + (f"  [{r['note']}]" if r["note"] else ""))

    if missing_syms:
        print(f"\nleads in {len(missing_syms)} stock(s) had no price data: "
              + ", ".join(missing_syms[:10])
              + (" ..." if len(missing_syms) > 10 else ""))


if __name__ == "__main__":
    main()
