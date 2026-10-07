# -*- coding: utf-8 -*-
"""Freshness guard used by the GitHub Actions workflows.

Prints "already-done" if today's (IST) data already exists in the local
DB, otherwise "run-needed". Any DB error defaults to "run-needed" so a
corrupt/missing DB never silences the pipeline.

Usage: python freshness_guard.py [morning|daily]
"""
import datetime
import sqlite3
import sys

MODE = sys.argv[1] if len(sys.argv) > 1 else "daily"
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
TODAY = datetime.datetime.now(IST).strftime("%Y-%m-%d")

try:
    conn = sqlite3.connect("data/moneypuller.db")
    if MODE == "morning":
        n = conn.execute(
            "SELECT COUNT(*) FROM articles WHERE substr(fetched_at,1,10) >= ?",
            (TODAY,),
        ).fetchone()[0]
    else:
        n = conn.execute(
            "SELECT COUNT(*) FROM prices WHERE date = ?",
            (TODAY,),
        ).fetchone()[0]
    print("already-done" if n else "run-needed")
except Exception as exc:  # noqa: BLE001 - never block the pipeline on guard errors
    print(f"guard error ({exc!r}); defaulting to run-needed", file=sys.stderr)
    print("run-needed")
