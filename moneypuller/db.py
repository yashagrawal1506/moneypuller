"""MoneyPuller - SQLite storage layer."""

import sqlite3
from pathlib import Path

DB_PATH = Path("data/moneypuller.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    url           TEXT UNIQUE NOT NULL,
    title         TEXT,
    article_date  TEXT,
    record_date   TEXT,
    fetched_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS recommendations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id    INTEGER NOT NULL REFERENCES articles(id),
    stock_name    TEXT NOT NULL,
    cmp           REAL,
    action        TEXT,
    target_1      REAL,
    target_2      REAL,
    target_3      REAL,
    stop_loss     REAL,
    reasoning     TEXT,
    analyst       TEXT,
    UNIQUE (article_id, stock_name)
);

CREATE INDEX IF NOT EXISTS idx_recs_stock ON recommendations(stock_name);
CREATE INDEX IF NOT EXISTS idx_recs_date ON recommendations(article_id);
"""


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert_article(conn: sqlite3.Connection, art) -> int:
    conn.execute(
        """INSERT INTO articles (url, title, article_date, record_date)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(url) DO UPDATE SET
             title=excluded.title, article_date=excluded.article_date,
             record_date=excluded.record_date""",
        (art.url, art.title, art.article_date, art.record_date),
    )
    # lastrowid is stale when the upsert took the UPDATE path - always
    # re-select the id by the (unique) url instead.
    row = conn.execute("SELECT id FROM articles WHERE url = ?",
                       (art.url,)).fetchone()
    return row[0]


def upsert_recommendation(conn: sqlite3.Connection, article_id: int, rec) -> None:
    conn.execute(
        """INSERT INTO recommendations
             (article_id, stock_name, cmp, action, target_1, target_2, target_3,
              stop_loss, reasoning, analyst)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(article_id, stock_name) DO UPDATE SET
             cmp=excluded.cmp, action=excluded.action,
             target_1=excluded.target_1, target_2=excluded.target_2,
             target_3=excluded.target_3, stop_loss=excluded.stop_loss,
             reasoning=excluded.reasoning, analyst=excluded.analyst""",
        (article_id, rec.stock_name, rec.cmp, rec.action,
         rec.targets[0] if len(rec.targets) > 0 else None,
         rec.targets[1] if len(rec.targets) > 1 else None,
         rec.targets[2] if len(rec.targets) > 2 else None,
         rec.stop_loss, rec.reasoning, rec.analyst),
    )


def save_article(conn: sqlite3.Connection, art) -> int:
    """Save an Article and its recommendations; returns the article id."""
    article_id = upsert_article(conn, art)
    for rec in art.recommendations:
        upsert_recommendation(conn, article_id, rec)
    conn.commit()
    return article_id
