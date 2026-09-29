"""Remove orphan recommendation rows left by the reparse accident.

After deleting the fake article rows, recs whose article_id no longer
exists (stale lastrowid artifacts) must go. Then reset the AUTOINCREMENT
counters so subsequent inserts reuse the freed id space.
"""

import sqlite3
from pathlib import Path

DB = Path("data/moneypuller.db")

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

n = conn.execute("""DELETE FROM recommendations
    WHERE article_id NOT IN (SELECT id FROM articles)""").rowcount
print(f"orphan recs deleted: {n}")
conn.commit()

print("articles:", conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0])
print("recs:", conn.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0])
print("max article id:", conn.execute("SELECT MAX(id) FROM articles").fetchone()[0])
print("max rec id:", conn.execute("SELECT MAX(id) FROM recommendations").fetchone()[0])

conn.execute("DELETE FROM sqlite_sequence WHERE name='articles'")
conn.execute("DELETE FROM sqlite_sequence WHERE name='recommendations'")
conn.execute("""INSERT INTO sqlite_sequence(name, seq)
    SELECT 'articles', COALESCE((SELECT MAX(id) FROM articles), 0)""")
conn.execute("""INSERT INTO sqlite_sequence(name, seq)
    SELECT 'recommendations', COALESCE((SELECT MAX(id) FROM recommendations), 0)""")
conn.commit()
print("AUTOINCREMENT counters reset to current maxima")
conn.close()
