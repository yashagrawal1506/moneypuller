# Hosting MoneyPuller online — free, no credit card

## Architecture

```
GitHub Actions (free 2,000 min/mo; this job uses ~35)
  └─ cron 10:45 UTC (16:15 IST) Mon–Fri  +  manual "Run workflow" button
       ├─ python daily_update.py --cloud  (scrape → prices → verdicts → confidence → exports)
       ├─ DB state kept in GitHub's actions-cache (rotating key)
       ├─ day-1 fallback: data/db_seed.gz (committed, 11.4MB)
       └─ python make_site.py  →  GitHub Pages deployment
            ├─ index.html               (the dashboard, self-contained)
            └─ moneypuller_leads.xlsx   (download link stays on the page)
```

Zero cost, zero credit card. Public repo + public dashboard URL (you approved).

## One-time setup (10 minutes, all free)

### 1. Create the GitHub repo
- Go to <https://github.com/new>
- Repository name: `moneypuller` (anything works)
- Visibility: **Public**
- **Do NOT** tick "Add a README" (we already have everything committed)
- Click **Create repository**

### 2. Push the local repo
Run these in `E:\Trade Spotlight` (replace `YOURUSERNAME`):

```bash
git remote add origin https://github.com/YOURUSERNAME/moneypuller.git
git push -u origin main
```

GitHub will open a browser login (or a device code) — approve it once.

### 3. Enable GitHub Pages (one toggle)
- Repo page → **Settings** → **Pages** (left sidebar)
- Under **Build and deployment → Source** choose **GitHub Actions**
- Done. (The workflow already has the `pages: write` permission.)

### 4. First run
- Repo page → **Actions** tab → **daily-update** → **Run workflow** → **Run**
- Takes ~20–35 min (first run backfills prices)
- Your dashboard then lives at:
  `https://YOURUSERNAME.github.io/moneypuller/`

From then on it runs automatically every trading day at 16:15 IST.
If the repo is private instead, Actions Minutes are still free at this scale
but Pages needs GitHub Pro — keep it public for the free tier.

## What the daily run does (automatically)

| Step | What | Failure mode |
|---|---|---|
| Scrape | Latest Trade Spotlight articles | Tolerated (site sometimes blocks datacenter IPs) — the rest still runs, dashboard shows last-good data |
| Prices | Yahoo OHLC for all mapped symbols | Retries + backoff; `MP_PAUSE=1.2` pacing |
| Verdicts | All 3,705+ leads re-evaluated | Hard dependency |
| Confidence | Live leads re-scored, history appended | Hard dependency |
| Excel + site | Workbook + dashboard rebuilt, deployed to Pages | Hard dependency |

The DB lives in GitHub's cache between runs, so the lead history keeps
growing — the committed `data/db_seed.gz` is only the day-1 bootstrap.

## Watching it / fixing it

- **Run status**: Actions tab → latest run. If a step goes red, the log says
  which stage and why.
- **Moneycontrol blocking cloud IPs**: if scraping keeps failing, the
  dashboard still updates (verdicts/prices move daily); we can route the
  scrape through your PC later with a tiny scheduled script that pushes
  article HTML to the repo.
- **Manual refresh any time**: Actions → daily-update → Run workflow.

## Security notes

- Nothing secret is in the repo (no keys, no login). Yahoo endpoints are
  public; the scraper uses browser-like headers.
- If you later add anything secret, use repo **Settings → Secrets and
  variables → Actions**, never commit it.
