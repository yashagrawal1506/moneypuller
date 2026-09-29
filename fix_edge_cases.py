"""One-off cleanup of known edge cases in the master DB.

- Normalize author typos in actions: 'Rs Buy'/'By' -> 'Buy',
  'Sell Futures of May 29' -> 'Sell' (verbatim detail kept in article)
- Recover action/targets/stop-loss/analyst for blocks whose concluding
  'Strategy:' paragraph was omitted by the authors (recovered from prose)
- Fill record_date for special editions (Budget day / Muhurat Trading)
  from the article publish date
"""

import sqlite3

FIXES = {
    # rec id: (action, target_1, target_2, target_3, stop_loss, analyst, trim_reasoning_suffix)
    141: ("Buy", 2300.0, 2350.0, None, 1769.0,
          "Jatin Gedia, VP - Technical Research at Teji Mandi Investment Technologies", None),
    142: ("Buy", 175.0, 180.0, None, 144.0,
          "Jatin Gedia, VP - Technical Research at Teji Mandi Investment Technologies",
          " Jatin Gedia, VP - Technical Research at Teji Mandi Investment Technologies"),
    1614: ("Buy", 4200.0, None, None, 3900.0,
           "Anshul Jain, Head of Research at Lakshmishree Investments",
           " Anshul Jain, Head of Research at Lakshmishree Investments"),
    # 1991 Voltas: bullish but no explicit strategy sentence - left for review
}

conn = sqlite3.connect("data/moneypuller.db")

# 1. action normalization (author typos / futures-qualified sells)
for old, new in [("Rs Buy", "Buy"), ("By", "Buy"), ("Sell Futures of May 29", "Sell")]:
    cur = conn.execute("UPDATE recommendations SET action=? WHERE action=?", (new, old))
    print(f"action {old!r} -> {new!r}: {cur.rowcount} rows")

# 2. recovered fields
for rec_id, (action, t1, t2, t3, sl, analyst, trim) in FIXES.items():
    row = conn.execute("SELECT reasoning FROM recommendations WHERE id=?", (rec_id,)).fetchone()
    reasoning = row[0]
    if trim and reasoning.endswith(trim):
        reasoning = reasoning[: -len(trim)].rstrip()
    conn.execute(
        """UPDATE recommendations SET action=?, target_1=?, target_2=?, target_3=?,
           stop_loss=?, analyst=?, reasoning=? WHERE id=?""",
        (action, t1, t2, t3, sl, analyst, reasoning, rec_id))
    print(f"recovered fields for rec id {rec_id}")

# 3. special-edition record dates
conn.execute("""UPDATE articles SET record_date=article_date
                WHERE record_date IS NULL AND article_date IS NOT NULL""")
print("filled special-edition record dates:",
      conn.execute("SELECT url, record_date FROM articles WHERE record_date IS NULL").fetchall())

conn.commit()

print("\nPost-fix action distribution:")
for r in conn.execute("SELECT action, COUNT(*) FROM recommendations GROUP BY action ORDER BY 2 DESC"):
    print(" ", r[0], "->", r[1])
print("\nRemaining nulls:")
for col in ["cmp", "action", "target_1", "stop_loss", "reasoning", "analyst"]:
    n = conn.execute(f"SELECT COUNT(*) FROM recommendations WHERE {col} IS NULL OR {col}=''").fetchone()[0]
    print(f"  {col:12s} {n}")
print("Articles missing record_date:",
      conn.execute("SELECT COUNT(*) FROM articles WHERE record_date IS NULL").fetchone()[0])
conn.close()
