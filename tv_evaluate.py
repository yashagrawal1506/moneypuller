"""Evaluate curated TV recommendations against real price data.

Reads data/tv_recommendations/parsed/<vid>_curated.csv, maps each stock to
its Yahoo symbol (via the MoneyPuller symbols table + a small TV-name
override map), fetches any missing price rows, then runs the SAME verdict
engine used for Trade Spotlight leads:

  entry  = expert's entry level if given, else the open of the show-date
           session
  exit   = highest target hit before SL (Buy; inverted for Sell)
  status = target achieved / SL achieved / NO HIT YET / NOT EVALUABLE ...
  %age and trading days taken, exactly like the leads engine

Commodity (MCX gold/crude), index (Nifty) and non-call rows are skipped.
Unmapped/garbled names are reported for manual review.

Usage:
    python tv_evaluate.py BGGOO3nYMRw [--fetch]
"""

import csv
import json
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from moneypuller.verdicts import evaluate_lead  # same engine as leads

ROOT = Path(__file__).parent
TV_DIR = ROOT / "data" / "tv_recommendations"
DB = ROOT / "data" / "moneypuller.db"

# curated name -> yahoo symbol (checked against Yahoo before trusting)
TV_SYMBOLS = {
    "Maruti Suzuki India": "MARUTI.NS",
    "Torrent Pharmaceuticals": "TORNTPHARM.NS",
    "Himadri Speciality Chemical": "HSCL.NS",
    "Petronet LNG": "PETRONET.NS",
    "Bank of Maharashtra": "MAHABANK.NS",
    "Radiant Cash Management": "RADIANT.NS",
    "South Indian Bank": "SOUTHBANK.NS",
    "Zydus Lifesciences": "ZYDUSLIFE.NS",
    "Dr Reddys Laboratories": "DRREDDY.NS",
    "SBI Cards & Payment Services": "SBICARD.NS",
    "Max Financial Services": "MFSL.NS",
    "Dhampur Sugar (uncertain)": None,
    "IIFL Finance / IIFL?": "IIFL.NS",
    "Yes Bank": "YESBANK.NS",
    "HDFC AMC": "HDFCAMC.NS",
    "NALCO": "NATIONALUM.NS",
    "Balkrishna Industries": "BALKRISIND.NS",
    "Dixon Technologies": "DIXON.NS",
    "LIC Housing Finance": "LICHSGFIN.NS",
    "Larsen & Toubro": "LT.NS",
    "Bank of Baroda": "BANKBARODA.NS",
    "Vodafone Idea": "IDEA.NS",
    "Tata Motors": "TATAMOTORS.NS",
    "IRB Infrastructure": "IRB.NS",
    "MS Bytes / Mrs Bectors Food?": "MRSectors.NS",
    "LG Electronics India": None,          # not listed on Yahoo (India IPO 2025?)
    "Park Mediworld (Hospital)": None,     # unverified listing
    "TVS Motor Company": "TVSMOTOR.NS",
    "Meesho": "MEESHO.NS",
    "Mankind Pharmaceuticals": "MANKIND.NS",
    "ICICI Bank": "ICICIBANK.NS",
    "CG Power (CG P)": "CGPOWER.NS",
    "Vikran Engineering": "VIKRAN.NS",
    "Union Bank of India": "UNIONBANK.NS",
    "Hyundai Motor India": "HYUNDAI.NS",
    "Bharti Airtel": "BHARTIARTL.NS",
    "Ashok Leyland": "ASHOKLEY.NS",
    "Jio Financial Services": "JIOFIN.NS",
    "PB Fintech": "POLICYBZR.NS",
    "GE Shipping (Great Eastern)": "GESHIP.NS",
    "HDFC Bank (June Fut?)": None,      # levels don't match HDFC Bank price
    "Tech Mahindra (probable)": "TECHM.NS",
    "Torrent Pharmaceuticals (2nd)": "TORNTPHARM.NS",
    "Jindal Steel & Power": "JINDALSTEL.NS",
    "MIDHANI (Mishra Dhatu Nigam)": "MIDHANI.NS",
    "Eicher Motors (probable)": "EICHERMOT.NS",
    "Bank of India": "BANKINDIA.NS",
    "GE Shipping": "GESHIP.NS",
    "Aditya Vision?": "ADANIVISION.NS",
    "Mahindra Cognito (Madhani?)": None,
    "Apollo Micro Systems": "APOLLO.NS",
    "HDFC Bank June Fut?": "HDFCBANK.NS",
}

SKIP_PREFIXES = ("Gold MCX", "Crude Oil MCX", "Nifty", "(market recap",
                 "(sector recap", "(market close recap", "(HDFC Bank June Fut?",
                 "(medical tourism", "(auto/EV market", "(car buying",
                 "(SIP/car finance", "(closing)", "(unrelated", "BPCL/HPCL")


def show_date_of(vid: str) -> str | None:
    """Extract the show date from the video title via oembed (cached)."""
    cache = TV_DIR / "raw_transcripts" / f"{vid}_meta.json"
    if cache.exists():
        return json.loads(cache.read_text()).get("show_date")
    import urllib.request
    try:
        with urllib.request.urlopen(
                f"https://www.youtube.com/oembed?url="
                f"https://www.youtube.com/watch?v={vid}&format=json",
                timeout=15) as r:
            title = json.loads(r.read()).get("title", "")
    except Exception:
        title = ""
    show_date = None
    m = __import__("re").search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", title)
    if m:
        months = {mn.lower(): i for i, mn in enumerate(
            ["January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"], 1)}
        d, mon, y = int(m.group(1)), m.group(2).lower(), int(m.group(3))
        if mon in months:
            show_date = date(y, months[mon], d).isoformat()
    cache.write_text(json.dumps({"title": title, "show_date": show_date}))
    return show_date


def load_price_data(conn, sym: str):
    rows = conn.execute(
        "SELECT date, open, high, low, close, volume FROM prices "
        "WHERE symbol=? ORDER BY date", (sym,)).fetchall()
    if not rows:
        return [], {}
    dates = [r[0] for r in rows]
    by_date = {r[0]: {"open": r[1], "high": r[2], "low": r[3],
                      "close": r[4], "volume": r[5]} for r in rows}
    return dates, by_date


def fetch_missing(symbols: list[str]) -> None:
    from moneypuller import db
    from moneypuller.prices import capture_symbol
    conn = db.connect()
    for sym in symbols:
        if not sym:
            continue
        n, note, _ = capture_symbol(sym, conn)
        print(f"  {sym}: {n} rows {note}")
    conn.close()


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python tv_evaluate.py <video_id> [--fetch]")
        return
    vid = sys.argv[1]
    curated = TV_DIR / "parsed" / f"{vid}_curated.csv"
    if not curated.exists():
        print(f"no curated file: {curated}")
        return

    show_date = show_date_of(vid)
    print(f"show date: {show_date}")
    if not show_date:
        print("!! could not parse show date from title; "
              "rows needing session-open entry are NOT EVALUABLE")
        show_date = None

    rows = list(csv.DictReader(curated.open(encoding="utf-8-sig")))
    # rows with extra columns get a None key from DictReader - drop it
    rows = [{k: v for k, v in r.items() if k is not None} for r in rows]
    out_rows, skipped, unmapped = [], [], []
    conn = sqlite3.connect(DB)

    for r in rows:
        stock = (r.get("stock") or "").strip()
        action = (r.get("action") or "").strip()
        # Watch/Weak/sector rows carry no tradable call - keep out of P&L
        if action in ("Watch", "Weak", "sector", "unknown") or \
                (not stock or stock.startswith(SKIP_PREFIXES)
                 or not any([r.get("target_1"), r.get("stop_loss")])):
            if stock and not stock.startswith("("):
                skipped.append((stock, "no levels / sector / commodity"))
            continue
        sym = TV_SYMBOLS.get(stock)
        if sym is None and stock in TV_SYMBOLS:
            unmapped.append((stock, r.get("stock_variants", "")))
            continue                      # explicitly unmapped (garbled name)
        if sym is None:
            # fall back to leads symbol table (exact or fuzzy on words)
            hit = conn.execute(
                "SELECT yahoo_symbol FROM symbols WHERE stock_name=?",
                (stock,)).fetchone()
            sym = hit[0] if hit else None
        if sym is None:
            unmapped.append((stock, r.get("stock_variants", "")))
            continue
        if "--fetch" in sys.argv:
            fetch_missing([sym])

        dates, by_date = load_price_data(conn, sym)
        if not dates:
            out_rows.append({**r, "yahoo_symbol": sym, "status":
                             "NO PRICE DATA", "entry_price": "", "exit_price":
                             "", "exit_level": "", "exit_date": "",
                             "days_taken": "", "pct": ""})
            continue

        # ---- sanity guards: ASR curation errors produce levels that cannot
        # belong to this stock - flag for review instead of nonsense verdicts
        lv = []
        for k in ("target_1", "target_2", "target_3", "stop_loss", "entry"):
            try:
                lv.append(float(r[k])) if r.get(k) else None
            except (TypeError, ValueError):
                pass
        closes = sorted(by_date[d]["close"] for d in dates[-20:]
                        if by_date[d]["close"])
        med = closes[len(closes) // 2] if closes else None
        if med and lv:
            if max(lv) < med * 0.33 or min(lv) > med * 3:
                out_rows.append({**r, "yahoo_symbol": sym,
                                 "status": "REVIEW (levels vs price mismatch)",
                                 "entry_price": med, "exit_price": "",
                                 "exit_level": "", "exit_date": "",
                                 "days_taken": "", "pct": "",
                                 "note": f"stock trades ~{med:.0f}"})
                continue

        lead = {
            "action": action or "Buy",
            "cmp": None,
            "target_1": r.get("target_1") or None,
            "target_2": r.get("target_2") or None,
            "target_3": r.get("target_3") or None,
            "stop_loss": r.get("stop_loss") or None,
            "record_date": show_date,
        }
        # parse numbers
        for k in ("target_1", "target_2", "target_3", "stop_loss"):
            try:
                lead[k] = float(lead[k]) if lead[k] else None
            except (TypeError, ValueError):
                lead[k] = None
        entry_level = r.get("entry")
        try:
            entry_level = float(entry_level) if entry_level else None
        except (TypeError, ValueError):
            entry_level = None

        v = evaluate_lead(lead, dates, by_date)
        # target-below-entry (Buy) / above-entry (Sell) = misattributed levels
        entry_open = by_date.get(show_date, {}).get("open") if show_date else None
        if lead["target_1"] and entry_open:
            if (not lead["action"].lower().startswith("sell")
                    and lead["target_1"] < entry_open * 0.97) or \
                    (lead["action"].lower().startswith("sell")
                     and lead["target_1"] > entry_open * 1.03):
                out_rows.append({**r, "yahoo_symbol": sym,
                                 "status": "REVIEW (target on wrong side of entry)",
                                 "entry_price": entry_open,
                                 "exit_price": "", "exit_level": "",
                                 "exit_date": "", "days_taken": "", "pct": "",
                                 "note": f"open {entry_open:.2f} vs T1 "
                                         f"{lead['target_1']:.2f}"})
                continue
        if v["status"] and v["status"].startswith("NO PRICE DATA") \
                and show_date and show_date in by_date:
            v["status"] = "PENDING (awaiting today's price)"
        # expert-given entry overrides session open
        entry_used = entry_level or v.get("entry_price")
        pct = v.get("pct")
        if entry_level and pct is not None and v.get("exit_price") is not None:
            is_sell = (lead["action"] or "Buy").lower().startswith("sell")
            base = entry_level
            pct = ((base - v["exit_price"]) / base if is_sell
                   else v["exit_price"] / base - 1)
        out_rows.append({
            **r, "yahoo_symbol": sym,
            "status": v["status"],
            "entry_price": entry_used or "",
            "exit_price": v.get("exit_price") or "",
            "exit_level": v.get("exit_level") or "",
            "exit_date": v.get("exit_date") or "",
            "days_taken": v.get("days_taken") or "",
            "pct": (f"{pct:.2%}" if pct is not None else ""),
            "note": v.get("note") or "",
        })

    conn.close()
    out_dir = TV_DIR / "evaluated"
    out_dir.mkdir(exist_ok=True)
    out_csv = out_dir / f"{vid}_verdicts.csv"
    if out_rows:
        cols = list(out_rows[0].keys())
        with out_csv.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(out_rows)

    print(f"\nevaluated: {len(out_rows)} calls -> {out_csv}")
    if skipped:
        print(f"skipped (no trade): {len(skipped)}")
        for s, why in skipped[:6]:
            print(f"  - {s}: {why}")
    if unmapped:
        print(f"UNMAPPED (need manual symbol): {len(unmapped)}")
        for s, v_ in unmapped:
            print(f"  - {s}  [{v_}]")
    for r in out_rows:
        line = (f"{str(r['stock'])[:28]:28} {r['action'][:5]:5} "
                f"status={str(r['status'])[:24]:24} "
                f"entry={str(r['entry_price'])[:8]:8} "
                f"exit={str(r['exit_price'])[:8]:8} "
                f"days={str(r['days_taken'])[:4]:4} pct={r['pct']}")
        try:
            print(line)
        except UnicodeEncodeError:
            print(line.encode("ascii", "replace").decode())


if __name__ == "__main__":
    main()
