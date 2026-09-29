"""MoneyPuller - OHLC price capture via Yahoo Finance chart API.

Captured per symbol: daily OHLC + volume + adjclose, plus dividend and
split events and symbol metadata. Dates are pinned to Asia/Kolkata so the
conversion never depends on the machine timezone.

Disk cache (data/raw/prices/<symbol>.json) respects Yahoo's rate limits;
a symbol is refetched only after PRICE_TTL_HOURS.
"""

import json
import sqlite3
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
CACHE_DIR = Path("data/raw/prices")
BASE = ("https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        "?period1={p1}&period2={p2}&interval=1d&events=div%2Csplits")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
PRICE_TTL_HOURS = 20  # refetch at most once a day


def _epoch(date_str: str) -> int:
    return int(datetime.strptime(date_str, "%Y-%m-%d")
               .replace(tzinfo=timezone.utc).timestamp())


def _ist_date(ts: float) -> str:
    return datetime.fromtimestamp(ts, IST).date().isoformat()


def _round(x):
    return round(x, 2) if x is not None else None


def fetch_ohlc(symbol: str, start: str = "2025-03-20", end: str = "2026-12-31",
               use_cache: bool = True) -> dict:
    """Fetch one symbol; returns {rows:[...], dividends:[...], splits:[...],
    meta:{...}}. Cached on disk; retries with backoff on failure."""
    cache = CACHE_DIR / f"{symbol.replace('^', '_').replace('&', '_')}.json"
    if use_cache and cache.exists():
        age_h = (time.time() - cache.stat().st_mtime) / 3600
        if age_h < PRICE_TTL_HOURS:
            data = json.loads(cache.read_text())
            rows = data.get("rows") or [{}]
            if rows[0].get("adjclose") is not None or not rows[0]:
                return data
            # pre-adjclose cache format: treat as stale and refetch

    url = BASE.format(symbol=urllib.request.quote(symbol),
                      p1=_epoch(start), p2=_epoch(end))
    last_err = None
    for attempt in range(1, 5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                       "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            res = data["chart"]["result"][0]
            meta = res.get("meta", {})
            q = res["indicators"]["quote"][0]
            adj = None
            if "adjclose" in res["indicators"]:
                adj = res["indicators"]["adjclose"][0]["adjclose"]
            rows = []
            for i, t in enumerate(res["timestamp"]):
                o, h, l, c = (q["open"][i], q["high"][i], q["low"][i],
                              q["close"][i])
                if o is None or h is None or l is None or c is None:
                    continue
                rows.append({
                    "date": _ist_date(t),
                    "open": _round(o), "high": _round(h),
                    "low": _round(l), "close": _round(c),
                    "adjclose": _round(adj[i]) if adj else None,
                    "volume": q["volume"][i] or 0,
                })
            events = res.get("events", {})
            dividends = [{"date": _ist_date(float(v["date"])),
                          "amount": v["amount"]}
                         for v in (events.get("dividends") or {}).values()]
            splits = [{"date": _ist_date(float(v["date"])),
                       "numerator": v.get("numerator"),
                       "denominator": v.get("denominator"),
                       "ratio": v.get("splitRatio")}
                      for v in (events.get("splits") or {}).values()]
            meta_out = {k: meta.get(k) for k in (
                "symbol", "longName", "shortName", "currency",
                "fullExchangeName", "instrumentType", "fiftyTwoWeekHigh",
                "fiftyTwoWeekLow")}
            out = {"symbol": symbol, "fetched_at": time.strftime(
                "%Y-%m-%d %H:%M"), "rows": rows, "dividends": dividends,
                "splits": splits, "meta": meta_out}
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(out), encoding="utf-8")
            return out
        except urllib.error.HTTPError as err:
            if err.code == 404:      # unknown symbol - deterministic, fail fast
                raise RuntimeError(f"fetch_ohlc failed for {symbol}: {err}") from err
            last_err = err
            time.sleep(8 * attempt)
        except Exception as err:  # noqa: BLE001
            last_err = err
            time.sleep(8 * attempt)
    raise RuntimeError(f"fetch_ohlc failed for {symbol}: {last_err}")


PRICES_SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    symbol   TEXT NOT NULL,
    date     TEXT NOT NULL,
    open     REAL, high REAL, low REAL, close REAL,
    adjclose REAL, volume INTEGER,
    PRIMARY KEY (symbol, date)
);
CREATE TABLE IF NOT EXISTS dividends (
    symbol TEXT NOT NULL, date TEXT NOT NULL, amount REAL,
    PRIMARY KEY (symbol, date)
);
CREATE TABLE IF NOT EXISTS splits (
    symbol TEXT NOT NULL, date TEXT NOT NULL, ratio TEXT,
    PRIMARY KEY (symbol, date)
);
CREATE TABLE IF NOT EXISTS symbol_meta (
    symbol TEXT PRIMARY KEY, long_name TEXT, short_name TEXT, currency TEXT,
    exchange TEXT, instrument_type TEXT, week52_high REAL, week52_low REAL,
    sessions INTEGER, first_date TEXT, last_date TEXT, fetched_at TEXT
);
"""


def store_prices(conn: sqlite3.Connection, payload: dict) -> int:
    """Upsert rows/dividends/splits/meta for one symbol payload."""
    symbol = payload["symbol"]
    conn.executescript(PRICES_SCHEMA)
    # migration for DBs created by the pre-adjclose pilot
    cols = [r[1] for r in conn.execute("PRAGMA table_info(prices)")]
    if "adjclose" not in cols:
        conn.execute("ALTER TABLE prices ADD COLUMN adjclose REAL")
    conn.executemany(
        """INSERT INTO prices (symbol, date, open, high, low, close, adjclose,
                               volume)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(symbol, date) DO UPDATE SET
             open=excluded.open, high=excluded.high, low=excluded.low,
             close=excluded.close, adjclose=excluded.adjclose,
             volume=excluded.volume""",
        [(symbol, r["date"], r["open"], r["high"], r["low"], r["close"],
          r.get("adjclose"), r["volume"]) for r in payload["rows"]])
    conn.executemany(
        """INSERT INTO dividends (symbol, date, amount) VALUES (?, ?, ?)
           ON CONFLICT(symbol, date) DO UPDATE SET amount=excluded.amount""",
        [(symbol, d["date"], d["amount"]) for d in payload["dividends"]])
    conn.executemany(
        """INSERT INTO splits (symbol, date, ratio) VALUES (?, ?, ?)
           ON CONFLICT(symbol, date) DO UPDATE SET ratio=excluded.ratio""",
        [(symbol, s["date"], s["ratio"]) for s in payload["splits"]])
    m = payload["meta"]
    rows = payload["rows"]
    conn.execute(
        """INSERT INTO symbol_meta (symbol, long_name, short_name, currency,
             exchange, instrument_type, week52_high, week52_low,
             sessions, first_date, last_date, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(symbol) DO UPDATE SET
             long_name=excluded.long_name, short_name=excluded.short_name,
             currency=excluded.currency, exchange=excluded.exchange,
             instrument_type=excluded.instrument_type,
             week52_high=excluded.week52_high, week52_low=excluded.week52_low,
             sessions=excluded.sessions, first_date=excluded.first_date,
             last_date=excluded.last_date, fetched_at=excluded.fetched_at""",
        (symbol, m.get("longName"), m.get("shortName"), m.get("currency"),
         m.get("fullExchangeName"), m.get("instrumentType"),
         m.get("fiftyTwoWeekHigh"), m.get("fiftyTwoWeekLow"),
         len(rows), rows[0]["date"] if rows else None,
         rows[-1]["date"] if rows else None, payload["fetched_at"]))
    conn.commit()
    return len(rows)


def is_cached_fresh(symbol: str) -> bool:
    """True if a usable, recent cache file exists (no network needed)."""
    cache = CACHE_DIR / f"{symbol.replace('^', '_').replace('&', '_')}.json"
    if not cache.exists():
        return False
    if (time.time() - cache.stat().st_mtime) / 3600 >= PRICE_TTL_HOURS:
        return False
    try:
        rows = json.loads(cache.read_text()).get("rows") or []
    except Exception:  # noqa: BLE001 - corrupt cache -> refetch
        return False
    return not rows or rows[0].get("adjclose") is not None


def capture_symbol(symbol: str, conn: sqlite3.Connection,
                   force: bool = False) -> tuple[int, str, bool]:
    """Fetch (or load from cache) and store one symbol.
    Returns (n_rows, note, from_cache)."""
    try:
        payload = fetch_ohlc(symbol, use_cache=not force)
    except RuntimeError as err:
        return 0, f"FAIL {err}", False
    if not payload["rows"]:
        return 0, "EMPTY", True
    n = store_prices(conn, payload)
    return n, "OK", True


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from moneypuller import db

    sym = sys.argv[1] if len(sys.argv) > 1 else "TITAN.NS"
    conn = db.connect()
    n, note, _ = capture_symbol(sym, conn)
    conn.close()
    print(f"{sym}: {n} sessions ({note})")
