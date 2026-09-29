"""Try the .BO (BSE) Yahoo suffix for lead symbols that 404 on .NS.

For each still-unpriced symbol with leads: attempt capture on the .NS
symbol, then on <base>.BO. If .BO succeeds, the symbols table is updated
to the .BO symbol so verdict joins work.
"""

import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from moneypuller import db
from moneypuller.prices import capture_symbol

conn = db.connect()
rows = conn.execute(
    """SELECT DISTINCT s.stock_name, s.yahoo_symbol FROM symbols s
       JOIN recommendations r ON r.stock_name = s.stock_name
       WHERE s.yahoo_symbol IS NOT NULL
         AND s.yahoo_symbol NOT IN (SELECT DISTINCT symbol FROM prices)
       ORDER BY s.yahoo_symbol""").fetchall()
print(f"{len(rows)} lead symbols still without price rows")

recovered = []
for stock, sym in rows:
    base = sym.rsplit(".", 1)[0]
    n, note, _ = capture_symbol(f"{base}.BO", conn)
    if note == "OK" and n > 0:
        conn.execute("UPDATE symbols SET yahoo_symbol=? WHERE stock_name=?",
                     (f"{base}.BO", stock))
        conn.commit()
        recovered.append((stock, f"{base}.BO", n))
        print(f"  RECOVERED {stock} -> {base}.BO ({n} rows)", flush=True)
    else:
        print(f"  still unpriced: {sym} (.BO 404 too)", flush=True)
    time.sleep(1.5)

print(f"\nrecovered {len(recovered)} of {len(rows)}")
conn.close()
