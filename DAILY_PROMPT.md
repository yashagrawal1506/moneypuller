# Daily MoneyPuller update

Run the full MoneyPuller daily pipeline end-to-end in `E:\Trade Spotlight`:

1. `python daily_update.py`

That single script chains everything: scrape the latest Trade Spotlight
articles, map any new stock names to Yahoo symbols, fetch missing/stale
prices, re-evaluate verdicts for every lead, recompute dynamic Confidence %
for live leads (appending to confidence_history), and regenerate
`data/moneypuller_leads.xlsx` + `data/dashboard.html`.

2. If any step fails or prints an error, diagnose and fix it before rerunning.
3. When it finishes, report: how many articles/leads were added today, how
   many leads resolved to "target achieved" vs "SL achieved" since yesterday,
   how many leads are still live with their confidence range, and any new
   symbols that could not be mapped or priced.

Notes:
- Python is invoked as `python` (not `python3`).
- If Yahoo rate-limits (HTTP 429), let the script's retries/backoff handle it;
  do not reduce pauses below `MP_PAUSE=1.2`.
- If `data/moneypuller_leads.xlsx` is open in Excel, close it first or the
  export will fail; tell the user to close it if so.
