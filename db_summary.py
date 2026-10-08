# -*- coding: utf-8 -*-
"""Print DB counters for the workflow logs (no inline-python pitfalls)."""

import sqlite3

QUERIES = [
    ("articles", "SELECT COUNT(*) FROM articles"),
    ("leads", "SELECT COUNT(*) FROM recommendations"),
    ("leads Oct 6", """SELECT COUNT(*) FROM recommendations r
                        JOIN articles a ON a.id = r.article_id
                        WHERE a.record_date = '2026-10-06'"""),
    ("leads Oct 7", """SELECT COUNT(*) FROM recommendations r
                        JOIN articles a ON a.id = r.article_id
                        WHERE a.record_date = '2026-10-07'"""),
]

if __name__ == "__main__":
    conn = sqlite3.connect("data/moneypuller.db")
    for name, query in QUERIES:
        print(name, conn.execute(query).fetchone()[0])
