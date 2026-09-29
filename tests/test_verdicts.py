"""Tests for moneypuller.verdicts - the any-target vs SL simulation."""

import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from moneypuller.verdicts import evaluate_lead, is_placeholder, write_verdicts


def bars(*rows) -> tuple[list, dict]:
    """rows of (date, open, high, low, close, volume) -> (all_dates, by_date)."""
    by_date = {d: {"open": o, "high": h, "low": l, "close": c, "volume": v}
               for d, o, h, l, c, v in rows}
    return sorted(by_date), by_date


def lead(**kw) -> dict:
    base = {"record_date": "2026-01-01", "action": "Buy",
            "target_1": None, "target_2": None, "target_3": None,
            "stop_loss": None}
    base.update(kw)
    return base


class TestVerdicts(unittest.TestCase):

    def test_buy_target_hit(self):
        dates, px = bars(
            ("2026-01-01", 100, 103, 99, 101, 1000),
            ("2026-01-02", 101, 110, 100, 109, 2000),
        )
        r = evaluate_lead(lead(target_1=110, stop_loss=95), dates, px)
        self.assertEqual(r["status"], "target achieved")
        self.assertEqual(r["entry_price"], 100)
        self.assertEqual(r["exit_price"], 110)
        self.assertEqual(r["exit_level"], "T1")
        self.assertEqual(r["days_taken"], 2)
        self.assertAlmostEqual(r["pct"], 0.10, places=6)

    def test_buy_sl_first(self):
        dates, px = bars(
            ("2026-01-01", 100, 102, 99, 101, 1000),
            ("2026-01-02", 101, 103, 94, 95, 2000),
        )
        r = evaluate_lead(lead(target_1=110, stop_loss=95), dates, px)
        self.assertEqual(r["status"], "SL achieved")
        self.assertEqual(r["exit_price"], 95)
        self.assertEqual(r["days_taken"], 2)
        self.assertAlmostEqual(r["pct"], -0.05, places=6)

    def test_highest_target_taken_as_exit(self):
        dates, px = bars(
            ("2026-01-01", 100, 104, 99, 102, 1000),
            ("2026-01-02", 102, 106, 101, 105, 1000),   # T1
            ("2026-01-03", 105, 121, 104, 118, 1000),   # T2 and T3
        )
        r = evaluate_lead(lead(target_1=105, target_2=110, target_3=120,
                               stop_loss=95), dates, px)
        self.assertEqual(r["status"], "target achieved")
        self.assertEqual(r["exit_level"], "T3")
        self.assertEqual(r["exit_price"], 120)
        self.assertEqual(r["exit_date"], "2026-01-03")
        self.assertEqual(r["days_taken"], 3)
        self.assertAlmostEqual(r["pct"], 0.20, places=6)

    def test_same_day_target_and_sl_is_ambiguous(self):
        dates, px = bars(
            ("2026-01-01", 100, 111, 94, 102, 1000),
        )
        r = evaluate_lead(lead(target_1=110, stop_loss=95), dates, px)
        self.assertEqual(r["status"], "AMBIGUOUS (target & SL same day)")
        self.assertIsNone(r["exit_price"])

    def test_target_first_then_sl_touch_later_still_target(self):
        dates, px = bars(
            ("2026-01-01", 100, 104, 99, 102, 1000),
            ("2026-01-02", 102, 106, 101, 105, 1000),   # T1 clean
            ("2026-01-03", 105, 112, 94, 104, 1000),    # T2 + SL same day
        )
        r = evaluate_lead(lead(target_1=105, target_2=110, stop_loss=95),
                          dates, px)
        self.assertEqual(r["status"], "target achieved")
        self.assertEqual(r["exit_level"], "T1")
        self.assertIn("T2", r["note"])

    def test_placeholder_record_date_enters_next_session(self):
        dates, px = bars(
            ("2026-01-01", 100, 100, 100, 100, 0),      # placeholder
            ("2026-01-02", 101, 104, 100, 103, 1000),
            ("2026-01-03", 104, 111, 103, 110, 1000),   # T1
        )
        r = evaluate_lead(lead(target_1=110, stop_loss=95), dates, px)
        self.assertEqual(r["status"], "target achieved")
        self.assertEqual(r["entry_price"], 101)
        self.assertEqual(r["days_taken"], 2)            # placeholder not counted
        self.assertIn("next session", r["note"])

    def test_placeholder_between_days_not_counted(self):
        dates, px = bars(
            ("2026-01-01", 100, 104, 99, 102, 1000),
            ("2026-01-02", 100, 100, 100, 100, 0),      # placeholder
            ("2026-01-03", 102, 110, 101, 109, 1000),   # T1
        )
        r = evaluate_lead(lead(target_1=110, stop_loss=95), dates, px)
        self.assertEqual(r["days_taken"], 2)

    def test_open_already_beyond_target(self):
        dates, px = bars(
            ("2026-01-01", 112, 115, 110, 113, 1000),
        )
        r = evaluate_lead(lead(target_1=110, stop_loss=95), dates, px)
        self.assertEqual(r["status"], "target achieved")
        self.assertEqual(r["exit_price"], 112)          # exit at the open
        self.assertEqual(r["days_taken"], 1)
        self.assertEqual(r["pct"], 0.0)
        self.assertIn("gap at open", r["exit_level"])

    def test_sell_target_hit(self):
        dates, px = bars(
            ("2026-01-01", 100, 102, 99, 101, 1000),
            ("2026-01-02", 101, 104, 93, 94, 2000),     # low <= T1
        )
        r = evaluate_lead(lead(action="Sell", target_1=95, stop_loss=105),
                          dates, px)
        self.assertEqual(r["status"], "target achieved")
        self.assertEqual(r["exit_price"], 95)
        self.assertAlmostEqual(r["pct"], 0.05, places=6)

    def test_sell_sl_hit(self):
        dates, px = bars(
            ("2026-01-01", 100, 102, 99, 101, 1000),
            ("2026-01-02", 101, 106, 100, 104, 2000),   # high >= SL
        )
        r = evaluate_lead(lead(action="Sell", target_1=95, stop_loss=105),
                          dates, px)
        self.assertEqual(r["status"], "SL achieved")
        self.assertEqual(r["exit_price"], 105)
        self.assertAlmostEqual(r["pct"], -0.05, places=6)

    def test_sell_lowest_target_is_highest_reward(self):
        dates, px = bars(
            ("2026-01-01", 100, 102, 99, 101, 1000),
            ("2026-01-02", 101, 102, 94, 95, 1000),     # T1 95
            ("2026-01-03", 95, 96, 88, 90, 1000),       # T2 90
        )
        r = evaluate_lead(lead(action="Sell", target_1=95, target_2=90,
                               stop_loss=105), dates, px)
        self.assertEqual(r["exit_level"], "T2")
        self.assertEqual(r["exit_price"], 90)

    def test_no_hit_yet_marks_to_last_close(self):
        dates, px = bars(
            ("2026-01-01", 100, 104, 99, 102, 1000),
        )
        r = evaluate_lead(lead(target_1=200, stop_loss=50), dates, px)
        self.assertEqual(r["status"], "NO HIT YET")
        self.assertEqual(r["exit_price"], 102)
        self.assertEqual(r["exit_level"], "last close")

    def test_no_targets_no_sl_not_evaluable(self):
        dates, px = bars(("2026-01-01", 100, 103, 99, 101, 1000))
        r = evaluate_lead(lead(action=None, target_1=None, stop_loss=None),
                          dates, px)
        self.assertEqual(r["status"], "NOT EVALUABLE (no targets, no SL)")

    def test_no_price_data(self):
        r = evaluate_lead(lead(), [], {})
        self.assertEqual(r["status"], "NO PRICE DATA")

    def test_unit_rescale_for_restated_series(self):
        # Yahoo restated the series x0.1 after a split; article quotes old units
        dates, px = bars(
            ("2026-01-01", 100, 102, 99, 100, 1000),    # prev close 100
            ("2026-01-02", 101, 105, 100, 104, 1000),   # record date
            ("2026-01-03", 104, 112, 103, 110, 1000),   # rescaled T1=110
        )
        r = evaluate_lead(lead(record_date="2026-01-02", cmp=1000.0,
                               target_1=1100, stop_loss=950), dates, px)
        self.assertEqual(r["status"], "target achieved")
        self.assertEqual(r["exit_level"], "T1")
        self.assertEqual(r["days_taken"], 2)
        self.assertIn("rescaled", r["note"])
        self.assertAlmostEqual(r["pct"], 110.0 / 101 - 1, places=6)

    def test_no_rescale_when_units_match(self):
        dates, px = bars(
            ("2026-01-01", 100, 102, 99, 100, 1000),
            ("2026-01-02", 101, 111, 100, 109, 1000),
        )
        r = evaluate_lead(lead(record_date="2026-01-02", cmp=100.0,
                               target_1=110, stop_loss=95), dates, px)
        self.assertIsNone(r["note"])
        self.assertEqual(r["days_taken"], 1)

    def test_opened_through_stop_exits_at_open(self):
        # stock gaps below the SL on day 1: realistic exit is the open (~0%)
        dates, px = bars(
            ("2026-01-01", 100, 102, 99, 100, 1000),
            ("2026-01-02", 92, 96, 90, 94, 1000),      # opens below SL 95
        )
        r = evaluate_lead(lead(record_date="2026-01-02", cmp=100.0,
                               target_1=110, stop_loss=95), dates, px)
        self.assertEqual(r["status"], "SL achieved")
        self.assertEqual(r["exit_price"], 92)
        self.assertEqual(r["pct"], 0.0)
        self.assertEqual(r["days_taken"], 1)
        self.assertIn("opened beyond the stop-loss", r["note"])

    def test_placeholder_detector(self):
        self.assertTrue(is_placeholder({"open": 5, "high": 5, "low": 5,
                                        "close": 5, "volume": 0}))
        self.assertFalse(is_placeholder({"open": 5, "high": 5, "low": 5,
                                         "close": 5, "volume": 10}))
        self.assertFalse(is_placeholder({"open": 5, "high": 6, "low": 5,
                                         "close": 5, "volume": 0}))


class TestWriteVerdicts(unittest.TestCase):

    def test_upsert_roundtrip(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE recommendations (id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO recommendations (id) VALUES (1)")
        n = write_verdicts(conn, {1: {
            "status": "target achieved", "entry_price": 100.0,
            "exit_price": 110.0, "exit_level": "T1",
            "exit_date": "2026-01-02", "days_taken": 2, "pct": 0.1,
            "note": None}})
        self.assertEqual(n, 1)
        row = conn.execute("SELECT * FROM verdicts WHERE rec_id=1").fetchone()
        self.assertEqual(row[1], "target achieved")
        # upsert again with new values
        write_verdicts(conn, {1: {
            "status": "SL achieved", "entry_price": 100.0,
            "exit_price": 95.0, "exit_level": "SL",
            "exit_date": "2026-01-03", "days_taken": 3, "pct": -0.05,
            "note": None}})
        row = conn.execute("SELECT status FROM verdicts WHERE rec_id=1").fetchone()
        self.assertEqual(row[0], "SL achieved")
        conn.close()


if __name__ == "__main__":
    unittest.main()
