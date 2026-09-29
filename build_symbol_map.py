"""Build stock_name -> Yahoo symbol mapping for all leads in the DB.

Resolver chain:
  1. SEED_OVERRIDES + data/symbol_overrides.csv (manual, highest priority)
  2. exact normalized name match vs NSE EQUITY_L.csv "NAME OF COMPANY"
  3. bare acronym == NSE SYMBOL (ABB, TCS, PFC, ...)
  4. futures suffix strip ('ITC June Futures' -> ITC)
  5. fuzzy match (difflib) with conservative cutoff + ambiguity guard

Writes mapping into DB table `symbols` and prints unresolved names.
"""

import csv
import difflib
import re
import sqlite3
from pathlib import Path

NSE_CSV = Path("data/raw/nse_equity.csv")
OVERRIDES = Path("data/symbol_overrides.csv")

STOPWORDS = {w.upper() for w in [
    "ltd", "limited", "the", "co", "company", "corporation", "corp",
    "(india)"]}

MONTHS = ("January|February|March|April|May|June|July|August|September|"
          "October|November|December")
FUTURES_RE = re.compile(rf"\s*(?:(?:{MONTHS})\s+)?Futures$", re.I)

SEED_OVERRIDES = {
    "360 ONE WAM": "360ONE.NS",
    "Eternal": "ETERNAL.NS",
    "Eternal (Zomato)": "ETERNAL.NS",
    "Zomato": "ETERNAL.NS",                       # renamed to Eternal (2025)
    "Indian Hotels Company": "INDHOTEL.NS",
    "Multi Commodity Exchange of India": "MCX.NS",
    "Aditya Birla Capital": "ABCAPITAL.NS",
    "HDFC Asset Management Company": "HDFCAMC.NS",
    "HDFC AMC": "HDFCAMC.NS",
    "ICICI Prudential AMC": "ICICIPRAMC.NS",
    "Power Finance Corporation": "PFC.NS",
    "Hindustan Aeronautics": "HAL.NS",
    "Sun Pharmaceutical Industries": "SUNPHARMA.NS",
    "United Spirits": "UNITDSPR.NS",
    "Vijaya Diagnostic Centre": "VIJAYA.NS",
    "Tamilnad Mercantile Bank": "TMB.NS",
    "Samman Capital": "SAMMAN.NS",
    "Urban Company": "URBANCIE.NS",
    "P B Fintech": "POLICYBZR.NS",
    "Inventurus Knowledge Solutions": "IKS.NS",
    "Aegis Vopak Terminals": "AEGISVOPAK.NS",
    "Allied Blenders and Distillers": "ABLD.NS",
    "Amber Enterprises": "AMBER.NS",
    "Aster DM Healthcare": "ASTERDM.NS",
    "CCL Products": "CCL.NS",
    "Dixon Technologies": "DIXON.NS",
    "Global Health (Medanta)": "MEDANTA.NS",
    "Gujarat Gas": "GUJGASLTD.NS",
    "Gujarat State Petronet": "GPPL.NS",
    "Hind Rectifiers": "HINDRECT.NS",
    "JB Chemicals & Pharmaceuticals": "JBCHEPHARM.NS",
    "JB Chemicals and Pharmaceuticals": "JBCHEPHARM.NS",
    "Jindal Steel & Power": "JINDALSTEL.NS",
    "Jindal Steel and Power": "JINDALSTEL.NS",
    "LTIMindtree": "LTIM.NS",
    "M&M Financial Services": "M&MFIN.NS",
    "Man Industries": "MANIND.NS",
    "National Securities Depository": "NSDL.NS",
    "Paytm": "PAYTM.NS",
    "Poonawalla Fincorp Poonawalla Fincorp": "POONAWALLA.NS",
    "Redington India": "REDINGTON.NS",
    "Sagility India": "SAGILITY.NS",
    "Sequent Scientific": "SEQUENT.NS",
    "Torrent Pharma": "TORNTPHARM.NS",
    "Glenmark Pharma": "GLENMARK.NS",
    "GE Shipping Company": "GESHIP.NS",
    "Central Depository Services May Futures": "CDSL.NS",
    "Valor Estate (DB Realty)": "DBREALTY.NS",
    "APL Apollo Tubes Futures": "APLAPOLLO.NS",
    "Adani Power Futures": "ADANIPOWER.NS",
    "Aurobindo Pharma Futures": "AUROPHARMA.NS",
    "Bank of India Futures": "BANKINDIA.NS",
    "Bharat Electronics Futures": "BEL.NS",
    "Blue Star Futures": "BLUESTARCO.NS",
    "Divis Laboratories Futures": "DIVISLAB.NS",
    "Grasim Industries Futures": "GRASIM.NS",
    "HDFC Bank June Futures": "HDFCBANK.NS",
    "ITC Futures": "ITC.NS",
    "ITC June Futures": "ITC.NS",
    "Lupin Futures": "LUPIN.NS",
    "Muthoot Finance Futures": "MUTHOOTFIN.NS",
    "Power Finance Corporation Futures": "PFC.NS",
    "State Bank of India May Futures": "SBIN.NS",
    "Sun Pharmaceutical Industries September Futures": "SUNPHARMA.NS",
    "Trent Futures": "TRENT.NS",
    "UltraTech Cement Futures": "ULTRACEMCO.NS",
    "Voltas Futures": "VOLTAS.NS",
    "DLF September Futures": "DLF.NS",
    "GMDC": "GMDCLTD.NS",                      # symbol is GMDCLTD on NSE
    "HEG": "HEG.NS",
    "Macrotech Developers": "LODHA.NS",        # renamed Lodha Developers
    "ICICI Prudential Nifty FMCG ETF": "FMCGIETF.NS",
    "ICICI Prudential Nifty India Consumption ETF": "CONSUMIETF.NS",
    "Nippon India ETF Hang Seng Bees": "HNGSNGBEES.NS",
    "Nippon India ETF Nifty Infrastructure BeES": "INFRABEES.NS",
    "Nippon India ETF Nifty PSU Bank BeES": "PSUBNKBEES.NS",
    "Nippon-India-Silver-ETF": "SILVERBEES.NS",
    # NOTE: 3 niche ETFs left unmapped after symbol probing (Yahoo lacks
    # clean .NS listings): Edelweiss BSE Capital Markets & Insurance ETF,
    # Groww Nifty India Railways PSU ETF, Mirae Asset MidSmallcap400
    # Momentum Quality 100 ETF.
}


def norm(s: str) -> str:
    """Uppercase, strip punctuation, drop corporate suffixes.

    Keeps 'INDIA' (part of many official names); only '(India)' is removed.
    """
    s = s.upper().replace("&AMP;", "&").replace("&", " AND ")
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    tokens = [t for t in s.split() if t not in STOPWORDS]
    return " ".join(tokens)


def load_nse() -> list[tuple[str, str]]:
    rows = []
    with open(NSE_CSV, encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            r = {k.strip(): (v or "").strip() for k, v in raw.items()}
            if r.get("SERIES") in ("EQ", "BE", "BZ"):
                rows.append((r["SYMBOL"].strip(), r["NAME OF COMPANY"].strip()))
    return rows


def load_overrides() -> dict[str, str]:
    if not OVERRIDES.exists():
        return {}
    out = {}
    with open(OVERRIDES, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if (r.get("stock_name") or "").strip() and \
               (r.get("yahoo_symbol") or "").strip():
                out[r["stock_name"].strip()] = r["yahoo_symbol"].strip()
    return out


def main() -> None:
    nse = load_nse()
    nse_by_norm: dict[str, tuple[str, str]] = {}
    for sym, name in nse:
        nse_by_norm.setdefault(norm(name), (sym, name))
    symbols_by_key = {sym.replace("&", "").replace("-", ""): (sym, name)
                      for sym, name in nse}

    # merge seeds into the manual overrides file (manual edits preserved)
    overrides = load_overrides()
    merged = dict(overrides)
    merged.update(SEED_OVERRIDES)
    if merged != overrides:
        with open(OVERRIDES, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(("stock_name", "yahoo_symbol"))
            for k in sorted(merged):
                w.writerow((k, merged[k]))
        overrides = merged
        print(f"seeded {OVERRIDES} with {len(overrides)} mappings")

    conn = sqlite3.connect("data/moneypuller.db")
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS symbols (
        stock_name   TEXT PRIMARY KEY,
        yahoo_symbol TEXT,
        nse_symbol   TEXT,
        nse_name     TEXT,
        method       TEXT,
        score        REAL
    );
    """)
    conn.execute("DELETE FROM symbols")

    names = [r[0] for r in conn.execute(
        "SELECT DISTINCT stock_name FROM recommendations ORDER BY 1")]

    def resolve_one(name: str):
        key = norm(name)
        hit = nse_by_norm.get(key)
        if hit:
            return hit[0] + ".NS", hit[0], hit[1], "exact", 1.0
        compact = key.replace(" ", "")
        if compact in symbols_by_key:
            sym, comp = symbols_by_key[compact]
            return sym + ".NS", sym, comp, "symbol", 0.95
        return None

    counts = {"override": 0, "exact": 0, "symbol": 0, "fuzzy": 0}
    unresolved = []
    for name in names:
        if name in overrides:
            ysym = overrides[name]
            conn.execute("INSERT INTO symbols VALUES (?,?,?,?,?,?)",
                         (name, ysym, ysym.replace(".NS", ""), "",
                          "override", 1.0))
            counts["override"] += 1
            continue
        hit = resolve_one(name)
        if hit is None and FUTURES_RE.search(name):
            hit = resolve_one(FUTURES_RE.sub("", name).strip())
        if hit:
            ysym, sym, comp, method, score = hit
            conn.execute("INSERT INTO symbols VALUES (?,?,?,?,?,?)",
                         (name, ysym, sym, comp, method, score))
            counts[method] += 1
            continue
        # fuzzy fallback
        key = norm(name)
        scored = []
        for norm_name, (sym, comp) in nse_by_norm.items():
            if abs(len(norm_name) - len(key)) > max(6, len(key) // 2):
                continue
            r = difflib.SequenceMatcher(None, key, norm_name).ratio()
            if r >= 0.82:
                scored.append((r, sym, comp))
        if scored:
            scored.sort(reverse=True)
            r, sym, comp = scored[0]
            if len(scored) > 1 and scored[1][0] > r - 0.03:
                unresolved.append((name, f"ambiguous: {comp} vs {scored[1][2]}"))
                continue
            conn.execute("INSERT INTO symbols VALUES (?,?,?,?,?,?)",
                         (name, sym + ".NS", sym, comp, "fuzzy", round(r, 3)))
            counts["fuzzy"] += 1
            continue
        unresolved.append((name, ""))

    conn.commit()
    total = sum(counts.values())
    print(f"\nmapped: {total}/{len(names)} "
          f"(override {counts['override']}, exact {counts['exact']}, "
          f"symbol {counts['symbol']}, fuzzy {counts['fuzzy']})")
    if unresolved:
        print(f"\nUNRESOLVED ({len(unresolved)}) - add to symbol_overrides.csv:")
        for name, note in unresolved:
            print(f"  {name:50s} {note}")
    conn.close()


if __name__ == "__main__":
    main()
