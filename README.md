# MoneyPuller

Captures **Moneycontrol "Trade Spotlight"** recommendations into a local SQLite
database — stock, date, CMP, action, targets, stop-loss, reasoning and analyst —
so leads scattered across daily articles become one queryable dataset.

## Status: v0.4 — master database + full price layer complete

**Current contents (2025-04-01 → 2026-09-28):** 368 articles, **3,161 leads**,
802 unique stocks, 125 analysts. Actions: 3,036 Buy / 124 Sell / 1 unstated.

**Price layer (Yahoo Finance, daily):** 665 symbols, ~249,000 sessions of
Open/High/Low/Close/AdjClose/Volume from 2025-03-20 onward, plus 1,331
dividend events, 49 splits and per-symbol metadata — stored in the same
SQLite DB (`prices`, `dividends`, `splits`, `symbol_meta` tables). Lead
date coverage: 99.0% (3,125/3,158 dated leads have same-day prices).
Excel exports split by financial year:
- `data/MoneyPuller_Prices_FY2025-26.xlsx` (Apr 2025 – Mar 2026)
- `data/MoneyPuller_Prices_FY2026-27.xlsx` (Apr 2026 – latest)

Each contains: Prices, Leads (for that FY), Dividends_Splits, Symbol_Meta
and Info sheets.

What it does today:
- Daily scrape: discovers the latest Trade Spotlight articles from the
  [tag page](https://www.moneycontrol.com/news/tags/trade-spotlight.html)
- **Backfill**: `python backfill.py` walks tag-page pagination (pages 1–31,
  ~690 articles) and captures everything from 2025-04-01 onward; checkpointed
  (`data/scraped_ids.txt`), resumable, raw HTML cached in `data/raw/articles/`
  (pass a time budget in seconds: `python backfill.py 240`)

## Usage

```bash
python -m moneypuller -n 2 --show          # scrape 2 latest articles
python -m moneypuller --urls <article-url> # scrape a specific article
python backfill.py                         # full backfill from 2025-04-01
python build_symbol_map.py                 # refresh name->symbol mapping
python fetch_prices.py 540                 # capture prices (time budget s)
python export_prices_excel.py              # FY-split price workbooks
python -m moneypuller --export-only        # leads DB -> Excel, no scraping
python -m unittest discover tests          # run tests (10)
```

Price fetching is checkpointed and cached (`data/raw/prices/*.json`, TTL 20h):
re-runs skip fresh symbols and refetch only stale ones — use the same command
the next trading day to update.

## Excel workbook (`data/moneypuller_leads.xlsx`)

Generated from the SQLite DB (a snapshot — refresh with `--export-only` after
each scrape). Two sheets:

- **Leads** — one row per recommendation: Record Date, Stock, CMP, Action
  (color-coded), Targets 1-3, Stop-Loss, the **verdict columns** (see below),
  plus live-formula columns T1/T2/T3 Upside %, Risk % (SL) and R:R (T1),
  Reasoning, Analyst, article title/URL. Frozen header + filter, so you can
  slice by analyst/date/action/verdict directly.
- **Summary** — KPIs (articles, leads, unique stocks/analysts, date range),
  verdict simulation KPIs (win rate, avg % on targets vs SL, days to exit),
  action breakdown, per-analyst stats (leads, buys, avg T1 upside, avg risk)
  and leads per date.

### Verdict simulation columns

For every dated lead the workbook answers: *"I read the article in the morning
and bought at the OPEN price; did any target or the SL hit first?"*

- **Achieved Target or SL?** — `target achieved` / `SL achieved` / `AMBIGUOUS
  (target & SL same day)` / `NO HIT YET` (live, marked to last close) /
  `NO PRICE DATA`
- **Entry (Open)**, **Exit Price/Level/Date**, **Days Taken** (trading
  sessions, inclusive), **%age** (Buy: exit/entry-1; Sell: (entry-exit)/entry),
  **Verdict Note** (edge cases)
- Exit = the **highest target hit before the SL** (T1→T3 tracked); article
  levels are auto-rescaled when Yahoo restated the price series for splits or
demergers (noted per row); opening through the SL exits at the open.
- Re-evaluate anytime after a price refresh: `python evaluate_verdicts.py --all`
  then `python -m moneypuller --export-only`.

```sql
-- sample query
SELECT a.record_date, r.stock_name, r.cmp, r.action,
       r.target_1, r.target_2, r.target_3, r.stop_loss, r.analyst
FROM recommendations r JOIN articles a ON a.id = r.article_id
ORDER BY a.record_date DESC;
```

## Schema

`articles(url, title, article_date, record_date)` and
`recommendations(article_id, stock_name, cmp, action, target_1..3, stop_loss,
reasoning, analyst)`, plus `verdicts(rec_id, status, entry_price, exit_price,
exit_level, exit_date, days_taken, pct, note)` (one row per recommendation,
rebuilt by `evaluate_verdicts.py`).

- `record_date` = the trading day named in the article title (year inferred
  from the publish date, with a December→January correction)
- `article_date` = the publish timestamp from the page metadata

## Data quality notes

- 5 symbols absent from Yahoo (`LTIM.NS`, `GUJGASLTD.NS`, `SEQUENT.NS`,
  `ICICIPRAMC.NS`, `MANIND.NS`) affect 13 leads (0.4%); 3 niche ETFs left
  unmapped. See `data/price_errors.log`.

- `record_date` comes from the article title (trading day); special editions
  (Budget day, Muhurat Trading) fall back to the publish date
- Field completeness: CMP/reasoning 100%, target_1 99.8%, stop-loss 99.6%,
  analyst 99.8% (a few MC articles omit bylines or numeric targets)
- 3 blocks whose concluding "Strategy:" paragraph was dropped by MC authors
  were recovered from prose; action typos in source articles (`Rs Buy`, `By`)
  were normalized — raw HTML in `data/raw/articles/` remains the source of truth

## Roadmap (next iterations)

1. **Daily automation** — Windows Task Scheduler job each weekday evening
   (scrape, refresh prices, re-evaluate verdicts, re-export).
2. **Analyst scorecard** — hit rate / avg % / time-to-target per analyst
   (data already in the verdicts table; needs an aggregated view).
3. **Backfill** — older articles are reachable by paginating the tag page.
