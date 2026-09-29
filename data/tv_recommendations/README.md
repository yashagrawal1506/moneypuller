# TV Recommendations (ET Now Swadesh live shows)

Structured extraction of expert stock recommendations from Indian market TV
shows (YouTube live streams), organised so they can be evaluated with the
same verdict engine as Moneycontrol Trade Spotlight leads.

## Folder layout

```
data/tv_recommendations/
├── README.md                     <- this file
├── raw_transcripts/<video_id>.json   timestamped caption segments (raw)
├── raw_transcripts/<video_id>.txt    human-readable [mm:ss] text dump
├── parsed/<video_id>.json        rules-based extraction (all blocks)
├── parsed/<video_id>.csv         rules-based extraction (flat CSV)
├── parsed/<video_id>_blocks.txt  block texts (for manual curation)
├── parsed/<video_id>_curated.csv THE call sheet (hand-verified calls)
└── evaluated/<video_id>_verdicts.csv  verdicts vs real price data
```

## Pipeline

1. **Transcript** — `youtube-transcript-api` (Hindi auto-captions) →
   `raw_transcripts/`.
2. **Block detection** — `python tv_extractor.py <video_id>` scores sliding
   windows for target/SL/buy/sell keyword density, clusters into blocks,
   fuzzy-matches stock names against the MoneyPuller symbol table, mines
   expert names ("X ji"), and writes the parsed files.
3. **Curation** — auto-generated Hindi captions are noisy (ASR garbles names
   and splits numbers), so the parsed blocks are read and the calls are
   hand-verified into `<video_id>_curated.csv`. Every row keeps the excerpt
   reference so any number can be traced back to the transcript timestamp.
4. **Evaluation** — `python tv_evaluate.py <video_id>` maps curated names to
   Yahoo symbols, fetches missing prices, then runs the SAME verdict engine
   as Trade Spotlight (entry = expert entry level if given, else session
   open; scan forward for targets/SL; sells inverted) → `evaluated/`.

## Semantics in the curated CSV

- `action`: Buy / Sell / Weak (avoid/watch, no trade) / sector (no call)
- `entry`: expert's entry level/zone; empty → use session open
- `horizon`: intraday / positional / investment / year-view
- `confidence`: high (clear levels + clear name) / medium / low
- commodity (gold/crude MCX) and index (Nifty) calls are kept for reference
  but marked excluded from equity evaluation
- garbled ASR names are kept in `stock_variants` and flagged in `notes`

## Source videos processed

| video_id | show | date | outcome |
|---|---|---|---|
| BGGOO3nYMRw | ET Now Swadesh — Stock Market Updates Live | 2026-09-28 | 28 tradeable calls evaluated; 4 names unresolved (manual review); see `evaluated/BGGOO3nYMRw_verdicts.csv` |

## What the first run taught us (ASR reality)

Auto-generated Hindi captions garble stock names and numbers. The
level-signature trick recovers most of it: the prices DB already knows what
every stock trades at, so a call whose levels cluster around 84/88/92 with
SL 81 can only be Bank of Maharashtra; "IC Motor" with top ~8100 → now ~7360
can only be Eicher Motors; "मददानी" with targets 424/440/450 is MIDHANI.
Rows that still cannot be resolved are marked Watch/unmapped with
MANUAL REVIEW in notes — they are never force-evaluated.
