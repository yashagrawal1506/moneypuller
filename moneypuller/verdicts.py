"""MoneyPuller - verdict evaluation.

Evaluates each lead under the "normal person" simulation:

  I read the Trade Spotlight article in the morning of the record date and
  bought (or shorted) the stock at the OPEN of that session. Then I wait
  until either ANY of the targets or the stop-loss trades.

Rules
-----
entry         : OPEN price of the record-date session. If the record date is
                itself a no-trade placeholder (O=H=L=C, volume=0) the entry
                is taken at the next real session's OPEN (a fill there is
                impossible, so the next real open is used and noted).
targets       : T1..T3 sorted nearest-first. Buy  -> hit when session HIGH
                >= target; Sell (short) -> hit when session LOW <= target.
                If several targets are hit before the SL, the exit is the
                FURTHEST (highest for a Buy, lowest price for a Sell) target
                hit while the trade was still live.
stop loss     : Buy  -> session LOW  <= SL;  Sell -> session HIGH >= SL.
hit day       : day 1 = the record-date session itself, counting real
                trading sessions (placeholders are not counted).
same-day tie  : if the first target and the SL are hit on the same session,
                daily bars cannot order the intraday moves -> verdict
                "AMBIGUOUS (target & SL same day)", no exit recorded. A
                further target touched on the SL day is also not credited
                (only targets hit on sessions without an SL hit count).
opened through stop: if the stock opens beyond the SL level (gap down
                through a Buy stop or up through a Sell stop), the exit is
                the open itself (pessimistic, ~0%).
%age          : Buy -> exit/entry - 1;  Sell -> (entry - exit)/entry.
time taken    : trading sessions from the record date to the exit session,
                inclusive.

Open-gaps: if the entry open already trades beyond the nearest target, the
target is credited on day 1 with the open as exit price (a real fill would
be at least as good).

Unit alignment: Yahoo restates historical OHLC after corporate actions
(splits, demergers), so old bars can be in post-action units while the
article's targets/SL are in the units of its day. The engine compares the
previous session's close with thearticle CMP (which is exactly that close - validated); when the ratio is
far from 1 (beyond +/-5%), all article levels are rescaled by it before
the scan, keeping the %age computation in consistent (post-action) units.
"""

import sqlite3

# ---------------------------------------------------------------- schema

VERDICTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS verdicts (
    rec_id        INTEGER PRIMARY KEY REFERENCES recommendations(id),
    status        TEXT,    -- target achieved / SL achieved / AMBIGUOUS
                           -- (target & SL same day) / NO HIT YET / NO PRICE DATA
    entry_price   REAL,    -- open of the record-date (or next real) session
    exit_price    REAL,    -- furthest target hit, SL, or last close if open
    exit_level    TEXT,    -- T1 / T2 / T3 / SL / last close
    exit_date     TEXT,    -- session date of the exit
    days_taken    INTEGER, -- trading sessions record-date -> exit, inclusive
    pct           REAL,    -- fractional return (positive = profit)
    note          TEXT
);
"""


def ensure_verdicts_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(VERDICTS_SCHEMA)


def write_verdicts(conn: sqlite3.Connection,
                   results: dict[int, dict]) -> int:
    """Upsert evaluation results keyed by recommendation id."""
    ensure_verdicts_schema(conn)
    conn.executemany(
        """INSERT INTO verdicts (rec_id, status, entry_price, exit_price,
               exit_level, exit_date, days_taken, pct, note)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(rec_id) DO UPDATE SET
             status=excluded.status, entry_price=excluded.entry_price,
             exit_price=excluded.exit_price, exit_level=excluded.exit_level,
             exit_date=excluded.exit_date, days_taken=excluded.days_taken,
             pct=excluded.pct, note=excluded.note""",
        [(rid, r["status"], r["entry_price"], r["exit_price"],
          r["exit_level"], r["exit_date"], r["days_taken"], r["pct"],
          r["note"]) for rid, r in results.items()])
    conn.commit()
    return len(results)


# ---------------------------------------------------------------- helpers

def is_placeholder(p: dict) -> bool:
    """No-trade session (holiday/illiquid): O=H=L=C and volume 0."""
    return (p["open"] == p["high"] == p["low"] == p["close"]
            and p["volume"] == 0)


def _pct(entry: float, exit_price: float, is_sell: bool) -> float | None:
    if not entry or exit_price is None:
        return None
    if is_sell:
        return (entry - exit_price) / entry
    return exit_price / entry - 1


def _prev_close_before(rd: str, all_dates: list[str],
                       price_by_date: dict) -> float | None:
    """Last real close strictly before the record date (units anchor)."""
    for d in reversed([d for d in all_dates if d < rd]):
        p = price_by_date[d]
        if not is_placeholder(p) and p["close"]:
            return p["close"]
    return None


def evaluate_lead(lead: dict, all_dates: list[str],
                  price_by_date: dict) -> dict:
    """Evaluate one lead against daily bars.

    `price_by_date` maps ISO date -> {open, high, low, close, volume};
    `all_dates` is the sorted list of all session dates for the symbol.
    Returns a dict matching the `verdicts` table columns.
    """
    action = (lead.get("action") or "Buy").strip().lower()
    is_sell = action.startswith("sell")

    raw_targets = [t for t in (lead.get("target_1"), lead.get("target_2"),
                               lead.get("target_3")) if t]
    targets = sorted(raw_targets, reverse=is_sell)  # nearest first
    levels = [f"T{i + 1}" for i in range(len(targets))]
    sl = lead.get("stop_loss")

    rd = lead["record_date"]
    sessions = [d for d in all_dates
                if d >= rd and not is_placeholder(price_by_date[d])]

    out = {"status": None, "entry_price": None, "exit_price": None,
           "exit_level": None, "exit_date": None, "days_taken": None,
           "pct": None, "note": None}

    if not sessions:
        # Distinguish "no price rows at all" from "rows exist but no real
        # session at/after the record date" (e.g. lead published this
        # morning, market still open — tonight's fetch supplies the bar).
        out["status"] = ("PENDING (awaiting today's price)"
                         if all_dates else "NO PRICE DATA")
        return out
    if not targets and sl is None:
        out["status"] = "NOT EVALUABLE (no targets, no SL)"
        return out

    # --- entry ------------------------------------------------------------
    entry_date = sessions[0]
    entry = price_by_date[entry_date]["open"]
    out["entry_price"] = entry
    if entry_date != rd:
        out["note"] = f"entry at next session {entry_date} (record date no-trade)"

    # --- unit alignment (splits / demergers restate Yahoo history) --------
    cmp_ = lead.get("cmp")
    prev_close = _prev_close_before(rd, all_dates, price_by_date)
    if cmp_ and prev_close and (targets or sl is not None):
        ratio = prev_close / cmp_
        if ratio < 0.95 or ratio > 1.05:
            targets = [round(t * ratio, 2) for t in targets]
            if sl is not None:
                sl = round(sl * ratio, 2)
            out["note"] = (out["note"] + "; " if out["note"] else "") + \
                f"article levels rescaled x{ratio:.4g} " \
                "(price series restated by corporate action)"

    # --- open already beyond the nearest target ---------------------------
    if targets:
        nearest = targets[0]
        if (not is_sell and entry >= nearest) or (is_sell and entry <= nearest):
            out["status"] = "target achieved"
            out["exit_price"] = entry
            out["exit_level"] = f"{levels[0]} (gap at open)"
            out["exit_date"] = entry_date
            out["days_taken"] = 1
            out["pct"] = 0.0
            out["note"] = (out["note"] + "; " if out["note"] else "") + \
                "open already beyond nearest target; exit at open"
            return out

    # --- stock opened through the stop-loss --------------------------------
    if sl is not None and ((not is_sell and entry <= sl)
                           or (is_sell and entry >= sl)):
        # A fill at the stop level above/below the open is impossible in
        # reality; the realistic (and pessimistic) reading is an immediate
        # exit at the open, i.e. roughly break-even.
        out["status"] = "SL achieved"
        out["exit_price"] = entry
        out["exit_level"] = "SL (opened through stop)"
        out["exit_date"] = entry_date
        out["days_taken"] = 1
        out["pct"] = 0.0
        out["note"] = (out["note"] + "; " if out["note"] else "") + \
            "opened beyond the stop-loss; exited at open (no trade profit)"
        return out

    # --- scan sessions ------------------------------------------------------
    def hit_target(p: dict, t: float) -> bool:
        return p["low"] <= t if is_sell else p["high"] >= t

    def hit_sl(p: dict) -> bool:
        if sl is None:
            return False
        return p["high"] >= sl if is_sell else p["low"] <= sl

    def is_further(t: float, best_t: float) -> bool:
        return targets.index(t) > targets.index(best_t)

    first_target_day = None     # day index of the nearest target's first hit
    first_target_level = None
    best = None                 # (day, level, price) furthest clean hit
    sl_day = None
    ambiguous = False
    stop_day_hits = []          # targets touched on the SL day (informational)

    for i, d in enumerate(sessions, start=1):
        p = price_by_date[d]
        hits = [(lvl, t) for lvl, t in zip(levels, targets)
                if hit_target(p, t)]
        sl_hit = hit_sl(p)

        if hits and first_target_day is None:
            first_target_day = i
            first_target_level = hits[0][0]
        if sl_hit and sl_day is None:
            sl_day = i
        if hits and not sl_hit:
            # clean session: any target hit here happened before the SL
            for lvl, t in hits:
                if best is None or is_further(t, best[2]):
                    best = (i, lvl, t)
        elif hits and sl_hit:
            stop_day_hits.extend(lvl for lvl, _ in hits)

        if hits and sl_hit and first_target_day == sl_day == i:
            ambiguous = True
            break
        if first_target_day is not None and sl_day is not None:
            break

    if ambiguous:
        out["status"] = "AMBIGUOUS (target & SL same day)"
        return out

    # --- target(s) hit before the SL ---------------------------------------
    if first_target_day is not None and (sl_day is None
                                         or first_target_day < sl_day):
        day, lvl, price = best if best is not None else \
            (first_target_day, first_target_level, targets[0])
        out["status"] = "target achieved"
        out["exit_price"] = price
        out["exit_level"] = lvl
        out["exit_date"] = sessions[day - 1]
        out["days_taken"] = day
        out["pct"] = _pct(entry, price, is_sell)
        if stop_day_hits:
            out["note"] = (out["note"] + "; " if out["note"] else "") + \
                f"{'+'.join(stop_day_hits)} also touched on SL day"
        return out

    # --- stopped out --------------------------------------------------------
    if sl_day is not None:
        out["status"] = "SL achieved"
        out["exit_price"] = sl
        out["exit_level"] = "SL"
        out["exit_date"] = sessions[sl_day - 1]
        out["days_taken"] = sl_day
        out["pct"] = _pct(entry, sl, is_sell)
        return out

    # --- still live: mark to last close -------------------------------------
    last_d = all_dates[-1]
    last = price_by_date.get(last_d)
    out["status"] = "NO HIT YET"
    n = len(sessions)
    out["days_taken"] = n
    if last and not is_placeholder(last):
        out["exit_price"] = last["close"]
        out["exit_level"] = "last close"
        out["exit_date"] = last_d
        out["pct"] = _pct(entry, last["close"], is_sell)
        out["note"] = (out["note"] + "; " if out["note"] else "") + \
            f"no target/SL hit in {n} sessions; marked to last close"
    return out
