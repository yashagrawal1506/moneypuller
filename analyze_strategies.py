"""Strategy / reasoning effectiveness analysis + confidence for live leads.

Part 1: classify each settled lead's reasoning into technical themes
        (breakout, moving averages, RSI, MACD, volume, patterns...) and
        measure target-hit rate and average % per theme, cross-tabbed with
        the lead's own measured risk-reward (T1 upside / SL risk).
Part 2: for live leads (NO HIT YET), compute a confidence % = historical
        base rate of comparable settled leads (same R:R bucket, same theme,
        same action), shrunk toward the global mean by the number of
        comparable observations. Written to verdicts.confidence.

Usage: python analyze_strategies.py
"""

import re
import sqlite3
from collections import defaultdict
from pathlib import Path

DB = Path("data/moneypuller.db")

THEMES = {
    "breakout": r"breakout|broke out|break out|breakabove|break above|"
                r"cleared|resistance.*turn|cross(ed)? above",
    "pattern":  r"head and shoulder|head-and-shoulder|double bottom|"
                r"double top|flag|triangle|cup and handle|channel|"
                r"descending|ascending|pattern",
    "ma_support": r"moving average|dma|sma|ema|200-day|50-day|20-day|"
                  r"trading above its|trading above all",
    "rsi": r"rsi|relative strength",
    "macd": r"macd|moving average convergence",
    "supertrend": r"supertrend",
    "volume": r"volume|volumes",
    "vwap": r"vwap",
    "candlestick": r"candle|hammer|doji|marubozu|engulfing",
    "trendline": r"trendline|trend line",
    "consolidation": r"consolidat|sideways|range-bound|rangebound|"
                     r"coiling|narrow range",
    "fibo": r"fibonacci|fib level|retracement",
    "option": r"call writing|put writing|option (chain|data)|oi|open interest",
    "derivatives": r"futures|long build-?up|short cover",
}


def themes_of(text: str) -> list[str]:
    t = (text or "").lower()
    return [name for name, pat in THEMES.items() if re.search(pat, t)]


def rr_bucket(upside: float | None, risk: float | None) -> str | None:
    """Reward-to-risk bucket from T1 upside and SL risk fractions."""
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


def main() -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT v.rec_id, v.status, v.pct, v.days_taken, v.entry_price,
               r.stock_name, r.action, r.target_1, r.target_2, r.target_3,
               r.stop_loss, r.cmp, r.reasoning, r.analyst,
               a.record_date
        FROM verdicts v
        JOIN recommendations r ON r.id = v.rec_id
        JOIN articles a ON a.id = r.article_id
        WHERE a.record_date IS NOT NULL""").fetchall()
    conn.close()

    settled, live = [], []
    for r in rows:
        rec = dict(r)
        act = (rec["action"] or "Buy").lower()
        is_sell = act.startswith("sell")
        rec["is_sell"] = is_sell
        cmp_ = rec["cmp"]
        t1 = rec["target_1"]
        sl = rec["stop_loss"]
        if cmp_ and t1 and sl:
            up = (t1 - cmp_) / cmp_ if not is_sell else (cmp_ - t1) / cmp_
            risk = (sl - cmp_) / cmp_ if not is_sell else (cmp_ - sl) / cmp_
            rec["upside"], rec["risk"] = up, risk
            rec["rr"] = rr_bucket(up, risk)
        else:
            rec["upside"] = rec["risk"] = None
            rec["rr"] = None
        rec["themes"] = themes_of(rec["reasoning"])
        (live if rec["status"] == "NO HIT YET" else settled).append(rec)

    print(f"settled leads: {len(settled)}   live leads: {len(live)}\n")

    # ---------- theme effectiveness ----------
    print("=" * 78)
    print("WHICH REASONING THEMES ACTUALLY DELIVER? (settled leads)")
    print("=" * 78)
    stats = {}
    for name in THEMES:
        sub = [r for r in settled if name in r["themes"]]
        if len(sub) < 30:
            continue
        hits = sum(1 for r in sub if r["status"] == "target achieved")
        pcts = [r["pct"] for r in sub if r["pct"] is not None]
        stats[name] = (len(sub), hits / len(sub), sum(pcts) / len(pcts))
    for name, (n, rate, avg) in sorted(stats.items(), key=lambda x: -x[1][1]):
        print(f"  {name:14s} n={n:>4}  target-hit {rate:5.1%}  avg {avg:+.2%}")

    base_rate = (sum(1 for r in settled if r["status"] == "target achieved")
                 / len(settled))
    base_pct = sum(r["pct"] for r in settled if r["pct"] is not None) / len(
        [r for r in settled if r["pct"] is not None])
    print(f"\n  {'BASE RATE':14s} n={len(settled):>4}  "
          f"target-hit {base_rate:5.1%}  avg {base_pct:+.2%}")

    # ---------- risk-reward bucket ----------
    print()
    print("=" * 78)
    print("DOES THE LEAD'S OWN R:R (T1 upside / SL risk) PREDICT SUCCESS?")
    print("=" * 78)
    by_rr = defaultdict(list)
    for r in settled:
        if r["rr"]:
            by_rr[r["rr"]].append(r)
    for bucket in ("RR<0.75", "RR 0.75-1", "RR 1-1.5", "RR>=1.5"):
        sub = by_rr.get(bucket, [])
        if not sub:
            continue
        hits = sum(1 for r in sub if r["status"] == "target achieved")
        pcts = [r["pct"] for r in sub if r["pct"] is not None]
        print(f"  {bucket:10s} n={len(sub):>4}  target-hit {hits/len(sub):5.1%}"
              f"  avg {sum(pcts)/len(pcts):+.2%}")

    # ---------- theme x R:R ----------
    print()
    print("=" * 78)
    print("THEME x R:R (top combos, min 40 leads)")
    print("=" * 78)
    combo = defaultdict(list)
    for r in settled:
        if not r["rr"]:
            continue
        for t in r["themes"]:
            combo[(t, r["rr"])].append(r)
    rows_out = []
    for (t, b), sub in combo.items():
        if len(sub) < 40:
            continue
        hits = sum(1 for r in sub if r["status"] == "target achieved")
        rows_out.append((len(sub), hits / len(sub), t, b))
    for n, rate, t, b in sorted(rows_out, reverse=True)[:12]:
        print(f"  {t:14s} {b:10s} n={n:>4}  target-hit {rate:5.1%}")

    # ---------- day-1 volume confirmation (measured, not narrative) ------
    print()
    print("=" * 78)
    print("DAY-1 VOLUME CONFIRMATION (entry-day volume vs 20-day average)")
    print("=" * 78)
    conn = sqlite3.connect(DB)
    vol_hist: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for sym, d, v in conn.execute(
            "SELECT symbol, date, volume FROM prices WHERE volume > 0 "
            "ORDER BY symbol, date"):
        vol_hist[sym].append((d, v))
    sym_of = {r[0]: r[1] for r in conn.execute(
        "SELECT stock_name, yahoo_symbol FROM symbols")}
    conn.close()

    def vol_bucket(stock: str, record_date: str) -> str | None:
        hist = vol_hist.get(sym_of.get(stock) or "")
        if not hist:
            return None
        prior = [v for d, v in hist if d < record_date]
        d1 = next((v for d, v in hist if d == record_date), None)
        if d1 is None or len(prior) < 5:
            return None
        avg20 = sum(prior[-20:]) / min(len(prior), 20)
        if avg20 == 0:
            return None
        if d1 >= 2.0 * avg20:
            return "x2+ volume"
        if d1 >= 1.3 * avg20:
            return "1.3-2x volume"
        if d1 >= 0.7 * avg20:
            return "normal"
        return "low volume"

    vol_stats: dict[str, list] = defaultdict(list)
    for r in settled:
        b = vol_bucket(r["stock_name"], r["record_date"])
        if b:
            r["vol_bucket"] = b
            vol_stats[b].append(r)
    vol_rate = {}
    for b in ("x2+ volume", "1.3-2x volume", "normal", "low volume"):
        sub = vol_stats.get(b, [])
        if sub:
            hits = sum(1 for r in sub if r["status"] == "target achieved")
            vol_rate[b] = (len(sub), hits / len(sub))
            print(f"  {b:14s} n={len(sub):>4}  target-hit {hits/len(sub):5.1%}")

    # ---------- confidence for live leads ----------
    print()
    print("=" * 78)
    print("CONFIDENCE FOR LIVE LEADS (NO HIT YET)")
    print("=" * 78)
    # comparable pools: (rr bucket) x (theme presence x) -> target-hit rate
    pools = defaultdict(list)
    for r in settled:
        if not r["rr"]:
            continue
        tset = set(r["themes"])
        pools[("ALL", r["rr"])].append(r)
        for t in THEMES:
            pools[(t if t in tset else f"no-{t}", r["rr"])].append(r)

    K = 40  # shrinkage strength (pseudo-count)
    conf = {}
    for r in live:
        if not r["rr"]:
            conf[r["rec_id"]] = None
            continue
        pool = pools[("ALL", r["rr"])]
        est = (sum(1 for x in pool if x["status"] == "target achieved")
               + K * base_rate) / (len(pool) + K)
        # small nudge from theme evidence present in the reasoning
        tset = set(r["themes"])
        for t in ("breakout", "pattern", "ma_support"):
            pool_t = pools.get((t if t in tset else f"no-{t}", r["rr"]), [])
            if len(pool_t) >= 30:
                est_t = ((sum(1 for x in pool_t
                              if x["status"] == "target achieved")
                          + K * base_rate) / (len(pool_t) + K))
                est = (est + est_t) / 2
        # strongest measured signal: entry-day volume confirmation
        b = vol_bucket(r["stock_name"], r["record_date"])
        if b and b in vol_rate and vol_rate[b][0] >= 100:
            n_b, rate_b = vol_rate[b]
            est_vol = rate_b  # buckets have n>=100, light shrinkage only
            est_vol = (sum(1 for x in vol_stats[b]
                           if x["status"] == "target achieved")
                       + 20 * base_rate) / (len(vol_stats[b]) + 20)
            est = (est + est_vol) / 2
        conf[r["rec_id"]] = est

    # write back
    conn = sqlite3.connect(DB)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(verdicts)")]
    if "confidence" not in cols:
        conn.executescript("ALTER TABLE verdicts ADD COLUMN confidence REAL")
    conn.executemany("UPDATE verdicts SET confidence=? WHERE rec_id=?",
                     [(c, rid) for rid, c in conf.items() if c is not None])
    conn.commit()
    conn.close()

    print(f"\nlive leads with a confidence estimate: "
          f"{sum(1 for c in conf.values() if c is not None)}/{len(live)}")
    if conf:
        vals = [c for c in conf.values() if c is not None]
        print(f"confidence range: {min(vals):.0%} .. {max(vals):.0%}")

    # persist the analysis tables for the report
    Path("data/strategy_analysis.txt").write_text(
        f"base_rate\t{base_rate:.4f}\nbase_pct\t{base_pct:.4f}\n"
        + "\n".join(f"theme\t{n}\t{rate:.4f}\t{avg:.4f}"
                    for n, (n_, rate, avg) in stats.items()),
        encoding="utf-8")
    print("wrote data/strategy_analysis.txt")


if __name__ == "__main__":
    main()
