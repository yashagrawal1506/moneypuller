"""Titan verdict proof-of-concept.

For each Titan lead: from the record date onward, scan daily sessions and
determine whether T1/T2/T3 or the stop-loss was hit first, how the stock
fared if simply held to today, and an overall verdict.

Demonstrates what the current data supports and surfaces the edge cases
(same-day ambiguity, no-trade placeholders, partial live session).
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

DB = Path("data/moneypuller.db")
OUT = Path("data/titan_verdicts_poc.xlsx")

HEAD_FILL = PatternFill("solid", fgColor="1F4E79")
HEAD_FONT = Font(color="FFFFFF", bold=True)
THIN = Side(style="thin", color="D9D9D9")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
FILL_OK = PatternFill("solid", fgColor="C6EFCE")
FILL_BAD = PatternFill("solid", fgColor="FFC7CE")
FILL_AMB = PatternFill("solid", fgColor="FFEB9C")
FILL_OPEN = PatternFill("solid", fgColor="E7E6E6")
PRICE_FMT = "#,##0.00"
PCT_FMT = "+0.0%;-0.0%"


def is_placeholder(p) -> bool:
    return (p["open"] == p["high"] == p["low"] == p["close"]
            and p["volume"] == 0)


def evaluate(lead, price_by_date: dict, all_dates: list) -> dict:
    rd, action = lead["record_date"], lead["action"] or "Buy"
    entry = lead["cmp"]
    targets = [lead["target_1"], lead["target_2"], lead["target_3"]]
    sl = lead["stop_loss"]

    sessions = [d for d in all_dates
                if d >= rd and not is_placeholder(price_by_date[d])]
    out = {"record_date": rd, "action": action, "entry": entry,
           "t1": targets[0], "t2": targets[1], "t3": targets[2], "sl": sl,
           "t1_day": None, "sl_day": None, "t2_after": False, "t3_after": False,
           "ambiguous": False, "max_reach": None, "worst": None,
           "last_close": None, "hold_pct": None, "verdict": "",
           "n_sessions": len(sessions)}
    if not sessions or not entry:
        out["verdict"] = "NO PRICE DATA"
        return out

    if action.lower().startswith("sell"):
        def hit_target(p, t): return p["low"] <= t
        def hit_sl(p): return p["high"] >= sl if sl else False
        def reach_pct(p): return (p["low"] / entry - 1)     # favorable for Sell
        def adverse_pct(p): return (p["high"] / entry - 1)  # adverse for Sell
    else:  # Buy
        def hit_target(p, t): return p["high"] >= t
        def hit_sl(p): return p["low"] <= sl if sl else False
        def reach_pct(p): return (p["high"] / entry - 1)
        def adverse_pct(p): return (p["low"] / entry - 1)

    t1_first_day = sl_first_day = None
    t1_day_idx = None
    for i, d in enumerate(sessions, start=1):
        p = price_by_date[d]
        t1, t2, t3 = targets
        t1_hit = t1 and hit_target(p, t1)
        sl_hit = hit_sl(p)
        if t1_hit and t1_first_day is None:
            t1_first_day = d
            t1_day_idx = i
        if sl_hit and sl_first_day is None:
            sl_first_day = d
        # same-session T1 and SL -> cannot order intraday with daily bars
        if t1_hit and sl_hit and t1_first_day == sl_first_day == d:
            out["ambiguous"] = True
            break
        if t1_first_day and sl_first_day:
            break
    out["t1_day"] = t1_day_idx
    out["sl_day"] = (sessions.index(sl_first_day) + 1) if sl_first_day else None

    # continuation: after a clean T1 hit, did T2/T3 arrive before SL?
    if t1_first_day and not out["ambiguous"]:
        after = sessions[t1_day_idx:]
        sl_after = None
        for j, d in enumerate(after, start=1):
            p = price_by_date[d]
            if sl and hit_sl(p) and sl_after is None:
                sl_after = j
            for k, key in ((1, "t2_after"), (2, "t3_after")):
                t = targets[k]
                if t and not out[key] and hit_target(p, t):
                    if sl_after is None or j < sl_after:
                        out[key] = True

    highs = [reach_pct(price_by_date[d]) for d in sessions]
    lows = [adverse_pct(price_by_date[d]) for d in sessions]
    out["max_reach"] = max(highs)
    out["worst"] = min(lows)

    last_d = all_dates[-1]
    last = price_by_date.get(last_d)
    out["last_close"] = last["close"] if last else None
    if out["last_close"]:
        move = out["last_close"] / entry - 1
        out["hold_pct"] = move if action.lower().startswith("buy") else -move

    # verdict
    if out["ambiguous"]:
        out["verdict"] = "AMBIGUOUS - T1 & SL hit same session"
    elif t1_first_day and (sl_first_day is None or t1_day_idx <= out["sl_day"]):
        extra = " then SL" if sl_first_day else ""
        cont = []
        if out["t2_after"]:
            cont.append("T2")
        if out["t3_after"]:
            cont.append("T3")
        out["verdict"] = (f"SUCCESS - T1 hit day {t1_day_idx}{extra}"
                          + (f" (+{' & '.join(cont)})" if cont else ""))
    elif sl_first_day:
        out["verdict"] = f"FAILED - SL hit first (day {out['sl_day']})"
    else:
        out["verdict"] = f"NO HIT in {len(sessions)} sessions"
    return out


def main() -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    prices = conn.execute(
        """SELECT date, open, high, low, close, volume FROM prices
           WHERE symbol='TITAN.NS' ORDER BY date""").fetchall()
    leads = conn.execute(
        """SELECT a.record_date, r.cmp, r.action, r.target_1, r.target_2,
                  r.target_3, r.stop_loss
           FROM recommendations r JOIN articles a ON a.id = r.article_id
           WHERE r.stock_name='Titan Company' AND a.record_date IS NOT NULL
           ORDER BY a.record_date""").fetchall()
    conn.close()

    price_by_date = {p["date"]: dict(p) for p in prices}
    all_dates = sorted(price_by_date)
    results = [evaluate(dict(l), price_by_date, all_dates) for l in leads]

    wb = Workbook()
    ws = wb.active
    ws.title = "Titan_Verdicts_PoC"
    headers = ["Record Date", "Action", "Entry CMP", "T1", "T2", "T3", "SL",
               "T1 Hit (day#)", "SL Hit (day#)", "T2 after T1", "T3 after T1",
               "Same-day Ambiguous", "Max Reach %", "Worst Move %",
               "Last Close", "Hold P&L %", "Sessions Scanned", "Verdict"]
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=1, column=i, value=h)
        c.fill, c.font, c.border = HEAD_FILL, HEAD_FONT, BORDER
        c.alignment = Alignment(horizontal="center", vertical="center",
                                wrap_text=True)
    ws.row_dimensions[1].height = 30
    widths = [12, 8, 10, 9, 9, 9, 9, 12, 12, 11, 11, 16, 12, 12, 11, 11, 12, 44]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    for r, v in enumerate(results, start=2):
        vals = [v["record_date"], v["action"], v["entry"], v["t1"], v["t2"],
                v["t3"], v["sl"], v["t1_day"], v["sl_day"],
                "yes" if v["t2_after"] else "", "yes" if v["t3_after"] else "",
                "YES" if v["ambiguous"] else "", v["max_reach"], v["worst"],
                v["last_close"], v["hold_pct"], v["n_sessions"], v["verdict"]]
        for j, val in enumerate(vals, start=1):
            c = ws.cell(row=r, column=j, value=val)
            c.border = BORDER
            if j in (3, 4, 5, 6, 7, 15):
                c.number_format = PRICE_FMT
            if j in (13, 14, 16):
                c.number_format = PCT_FMT
        verdict = v["verdict"]
        fill = (FILL_AMB if verdict.startswith("AMBIGUOUS")
                else FILL_OK if verdict.startswith("SUCCESS")
                else FILL_BAD if verdict.startswith("FAILED") else FILL_OPEN)
        ws.cell(row=r, column=18).fill = fill

    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:R{len(results) + 1}"
    wb.save(OUT)

    # console summary
    print(f"{'date':11s} {'act':5s} {'entry':>8s} {'T1':>8s} {'SL':>8s}  verdict")
    for v in results:
        print(f"{v['record_date']:11s} {v['action']:5s} {v['entry']:>8} "
              f"{v['t1'] or 0:>8} {v['sl'] or 0:>8}  {v['verdict']}")
    n_ok = sum(1 for v in results if v["verdict"].startswith("SUCCESS"))
    n_fail = sum(1 for v in results if v["verdict"].startswith("FAILED"))
    n_amb = sum(1 for v in results if v["verdict"].startswith("AMBIGUOUS"))
    n_open = sum(1 for v in results if v["verdict"].startswith("NO HIT"))
    print(f"\nSUCCESS {n_ok} | FAILED {n_fail} | AMBIGUOUS {n_amb} | "
          f"NO HIT {n_open}  (of {len(results)})")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
