"""MoneyPuller - dynamic confidence model.

Confidence % for every live lead (NO HIT YET), recomputed daily after
close from four evidence sources, all measured on settled leads:

  1. R:R geometry bucket  (T1 upside / SL risk) - strongest structural signal
  2. Analyst reliability  - the analyst's own hit rate on comparable R:R
     leads, shrunk toward the R:R bucket rate by their sample size, then
     toward the global base rate (two-level shrinkage, so a 5-lead analyst
     barely moves the needle while a 150-lead analyst is trusted)
  3. Entry-day volume confirmation bucket (x2+ / 1.3-2x / normal / low)
  4. Reasoning theme nudge (breakout / pattern / MA-support presence)

Every daily run appends one row per live lead to confidence_history
(rec_id, date, confidence, status, snapshot of the evidence) so the user
can later audit how confident we were the day before a hit/SL landed and
check calibration over time.

Blend (multiplicative on odds, additive fallback): start from the R:R
bucket rate, blend in analyst rate, then volume rate, then apply the theme
nudge. Result is clamped to 5%..95%.
"""

import json
import math
import sqlite3
from collections import defaultdict
from pathlib import Path

DB = Path("data/moneypuller.db")
HIST_TABLE = """
CREATE TABLE IF NOT EXISTS confidence_history (
    rec_id     INTEGER NOT NULL,
    as_of      TEXT NOT NULL,
    confidence REAL,
    status     TEXT,
    rr_bucket  TEXT,
    analyst    TEXT,
    vol_bucket TEXT,
    PRIMARY KEY (rec_id, as_of)
);
"""


def rr_bucket(upside: float | None, risk: float | None,
              is_sell: bool = False) -> str | None:
    if not upside or not risk or risk == 0:
        return None
    rr = upside / abs(risk)
    if rr < 0.75:
        return "RR<0.75"
    if rr < 1.0:
        return "RR 0.75-1"
    if rr < 1.5:
        return "RR 1-1.5"
    return "RR>=1.5"


def vol_bucket_of(d1_vol: int | None, prior: list[int]) -> str | None:
    if d1_vol is None or len(prior) < 5:
        return None
    avg20 = sum(prior[-20:]) / min(len(prior), 20)
    if not avg20:
        return None
    if d1_vol >= 2.0 * avg20:
        return "x2+ volume"
    if d1_vol >= 1.3 * avg20:
        return "1.3-2x volume"
    if d1_vol >= 0.7 * avg20:
        return "normal"
    return "low volume"


def _load_volume_hist(conn: sqlite3.Connection) -> dict[str, list[tuple]]:
    hist: dict[str, list[tuple]] = defaultdict(list)
    for sym, d, v in conn.execute(
            "SELECT symbol, date, volume FROM prices WHERE volume > 0 "
            "ORDER BY symbol, date"):
        hist[sym].append((d, v))
    return hist


def compute_confidence(as_of: str | None = None,
                       verbose: bool = True) -> dict[str, float]:
    """Compute and store confidence for all live leads. Returns rec_id -> conf."""
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.executescript(HIST_TABLE)
    as_of = as_of or conn.execute(
        "SELECT MAX(record_date) m FROM articles").fetchone()["m"]

    rows = conn.execute("""
        SELECT v.rec_id, v.status, r.stock_name, r.action, r.cmp,
               r.target_1, r.target_2, r.target_3, r.stop_loss,
               r.reasoning, r.analyst, a.record_date
        FROM verdicts v
        JOIN recommendations r ON r.id = v.rec_id
        JOIN articles a ON a.id = r.article_id
        WHERE a.record_date IS NOT NULL""").fetchall()

    sym_of = {r[0]: r[1] for r in conn.execute(
        "SELECT stock_name, yahoo_symbol FROM symbols")}
    vol_hist = _load_volume_hist(conn)
    conn.close()

    import re
    THEME_PATS = {
        "breakout": r"breakout|broke out|break out|break above|cross(ed)? above",
        "pattern": r"head and shoulder|double bottom|flag|triangle|cup and handle|channel|pattern",
        "ma_support": r"moving average|dma|sma|ema|trading above",
    }

    def themes_of(text: str) -> set[str]:
        t = (text or "").lower()
        return {n for n, p in THEME_PATS.items() if re.search(p, t)}

    def vol_bucket(stock: str, record_date: str) -> str | None:
        hist = vol_hist.get(sym_of.get(stock) or "")
        if not hist:
            return None
        prior = [v for d, v in hist if d < record_date]
        d1 = next((v for d, v in hist if d == record_date), None)
        return vol_bucket_of(d1, prior)

    settled, live = [], []
    for r in rows:
        rec = dict(r)
        act = (rec["action"] or "Buy").lower()
        rec["is_sell"] = act.startswith("sell")
        cmp_ = rec["cmp"]
        t1, sl = rec["target_1"], rec["stop_loss"]
        if cmp_ and t1 and sl:
            up = ((t1 - cmp_) if not rec["is_sell"] else (cmp_ - t1)) / cmp_
            risk = ((sl - cmp_) if not rec["is_sell"] else (cmp_ - sl)) / cmp_
            rec["rr"] = rr_bucket(up, risk)
        else:
            rec["rr"] = None
        rec["themes"] = themes_of(rec["reasoning"])
        rec["vol_bucket"] = vol_bucket(rec["stock_name"], rec["record_date"])
        if rec["status"] in ("target achieved", "SL achieved"):
            settled.append(rec)
        elif rec["status"] == "NO HIT YET":
            live.append(rec)

    if not settled:
        return {}

    base_rate = (sum(1 for r in settled if r["status"] == "target achieved")
                 / len(settled))

    # ---- pools ----------------------------------------------------------
    rr_pool: dict[str, list] = defaultdict(list)
    analyst_pool: dict[tuple[str, str], list] = defaultdict(list)
    vol_pool: dict[str, list] = defaultdict(list)
    for r in settled:
        if r["rr"]:
            rr_pool[r["rr"]].append(r)
            analyst_pool[(r["analyst"] or "Unknown", r["rr"])].append(r)
        if r["vol_bucket"]:
            vol_pool[r["vol_bucket"]].append(r)

    def shrunk(sub: list, prior: float, k: float) -> float:
        hits = sum(1 for x in sub if x["status"] == "target achieved")
        return (hits + k * prior) / (len(sub) + k)

    K_RR, K_AN, K_VOL = 30, 25, 20
    conf: dict[int, float] = {}
    for r in live:
        if not r["rr"]:
            continue
        rr_sub = rr_pool[r["rr"]]
        est = shrunk(rr_sub, base_rate, K_RR)
        # analyst evidence on comparable R:R leads, two-level shrinkage
        an_sub = analyst_pool.get((r["analyst"] or "Unknown", r["rr"]), [])
        if an_sub:
            bucket_rate = shrunk(rr_sub, base_rate, K_RR)
            an_rate = shrunk(an_sub, bucket_rate, K_AN)
            est = (est + an_rate) / 2
        # volume confirmation
        if r["vol_bucket"] and r["vol_bucket"] in vol_pool \
                and len(vol_pool[r["vol_bucket"]]) >= 100:
            est_vol = shrunk(vol_pool[r["vol_bucket"]], base_rate, K_VOL)
            est = (est + est_vol) / 2
        # theme nudge (small)
        tset = r["themes"]
        if tset:
            nudge = 0.0
            if "breakout" in tset:
                nudge += 0.01
            if "pattern" in tset:
                nudge += 0.005
            if "ma_support" in tset:
                nudge += 0.005
            est += min(nudge, 0.02)
        conf[r["rec_id"]] = max(0.05, min(0.95, est))

    # ---- persist ---------------------------------------------------------
    conn = sqlite3.connect(DB)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(verdicts)")]
    if "confidence" not in cols:
        conn.execute("ALTER TABLE verdicts ADD COLUMN confidence REAL")
    conn.executemany("UPDATE verdicts SET confidence=? WHERE rec_id=?",
                     [(c, rid) for rid, c in conf.items()])
    conn.executemany(
        """INSERT INTO confidence_history (rec_id, as_of, confidence, status,
               rr_bucket, analyst, vol_bucket)
           VALUES (?, ?, ?, 'NO HIT YET', ?, ?, ?)
           ON CONFLICT(rec_id, as_of) DO UPDATE SET
             confidence=excluded.confidence""",
        [(rid, as_of, c,
          next(r["rr"] for r in live if r["rec_id"] == rid),
          next((r["analyst"] or "Unknown") for r in live
               if r["rec_id"] == rid),
          next((r["vol_bucket"] or "") for r in live
               if r["rec_id"] == rid))
         for rid, c in conf.items()])
    conn.commit()
    conn.close()

    if verbose:
        print(f"confidence computed for {len(conf)} live leads (as of {as_of})")
        if conf:
            vals = sorted(conf.values())
            print(f"  range {vals[0]:.0%} .. {vals[-1]:.0%}, "
                  f"median {vals[len(vals)//2]:.0%}")
    return conf


if __name__ == "__main__":
    compute_confidence()
