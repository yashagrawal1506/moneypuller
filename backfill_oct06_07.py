# -*- coding: utf-8 -*-
"""Backfill patch: Oct 6-7, 2026 Trade Spotlight articles.

These two days' articles were never scraped (all scheduled runs failed
on those dates). The pages are Akamai-blocked for datacenter IPs, so the
verbatim content below was captured from a real browser and is written
straight into the DB. Idempotent: safe to re-apply.

Usage: python backfill_oct06_07.py   (cwd must be the repo root)
"""

import sqlite3
import sys

OCT07 = {
    "url": "https://www.moneycontrol.com/news/business/markets/trade-spotlight-how-should-you-trade-laurus-labs-bhel-acme-solar-holdings-indian-hotels-britannia-and-others-on-october-7-14046200.html",
    "title": "Trade Spotlight: How should you trade Laurus Labs, BHEL, ACME Solar Holdings, Indian Hotels, Britannia, and others on October 7?",
    "date": "2026-10-07",
    "blocks": [
        ("Ashish Kyal, CMT, Founder and CEO of Waves Strategy Advisors",
         "Laurus Labs", 2050.0, "Buy", [2160.0, 2270.0], 1950.0,
         "Laurus Labs gained 4 percent and managed to engulf the candles formed over the past six sessions, which is a positive sign. On the daily chart, the stock has been moving higher, forming higher highs and higher lows despite major market indices remaining under pressure, signalling relative outperformance. Prices almost took support at the 25-period EMA near the Rs 1,950 level on October 1. This level also coincides with channel support, and the stock has bounced back from there, indicating its significance. The upmove is now expected to continue in the form of wave 5 of (3). A break above Rs 2,056 could push prices higher towards Rs 2,160, followed by Rs 2,270, with support around the Rs 1,950 level."),
        ("Ashish Kyal, CMT, Founder and CEO of Waves Strategy Advisors",
         "BHEL", 452.0, "Buy", [460.0, 475.0], 425.0,
         "Bharat Heavy Electricals outperformed the broader market by moving higher and breaking above its previous resistance zone of Rs 446 to close at a record high of Rs 454, with a gain of more than 5 percent. Prices have also closed well above the previous session's high for the past three trading sessions, indicating consistent buying interest. The MACD line has also crossed above the signal line, with a green histogram starting to form above the zero line, signalling that the short-term trend is shifting upwards. For now, dips towards Rs 442-447 can be used as a prudent strategy to ride wave (3). On the upside, the stock has the potential to move towards Rs 460, followed by Rs 475, as long as the Rs 425 level remains protected on a closing basis."),
        ("Ashish Kyal, CMT, Founder and CEO of Waves Strategy Advisors",
         "ACME Solar Holdings", 448.2, "Buy", [473.0, 485.0], 435.0,
         "ACME Solar Holdings finally snapped its nine-session losing streak, closing nearly 5 percent higher and signalling a strong recovery in buying momentum. The stock had taken support near the middle Bollinger Band during the previous week, which also coincided with the 16-period time-cycle low, an important polarity area. The confluence of these technical factors provided strong confirmation of the reversal and subsequent upmove. Additionally, volumes have remained higher during up sessions compared with down sessions, indicating stronger participation from buyers and supporting the possibility of further recovery. For now, a move above Rs 454 could open the way towards Rs 473, followed by Rs 485. On the downside, Rs 435 remains the key support level."),
        ("Rajesh Dashrath Bhosale, Fund Manager - Advisory at Renaissance",
         "Indian Hotels Company", 736.0, "Buy", [775.0], 715.0,
         "Indian Hotels has recovered strongly from its April low near Rs 565 and has been consolidating for the past three months, showing resilience amid broader market weakness. On the daily chart, prices appear to be forming the right shoulder of an inverse head-and-shoulders pattern, with Rs 755 acting as the neckline. The Rs 713 zone, which earlier acted as resistance, has turned into strong support and held on repeated retests. The recent sharp rebound from this base, backed by a spike in volumes, indicates accumulation and suggests that the right shoulder is nearing completion. The risk-reward profile looks favourable at current levels, with the stock well placed to move towards the neckline and potentially beyond."),
        ("Amol Athawale, VP Technical Research at Kotak Securities",
         "Infosys", 1013.9, "Buy", [1080.0], 980.0,
         "Infosys has formed a double-bottom chart pattern on the weekly timeframe following a decline from higher levels. The bullish activity near the support zone indicates that the stock has limited downside, making it a good candidate from a risk-reward perspective. The chart structure suggests the possibility of a fresh upward rally. For the next few trading sessions, Rs 980 could act as the trend-deciding level for the bulls. If the stock sustains above this level, further uptrend towards Rs 1,080 can be expected."),
        ("Amol Athawale, VP Technical Research at Kotak Securities",
         "CDSL", 1263.4, "Buy", [1350.0], 1220.0,
         "Central Depository Services (India) has been in a downtrend on the daily timeframe. The stock is currently in oversold territory and trading near its demand zone. The chart structure and RSI indicator suggest that the stock is likely to rebound and begin a new leg of the upmove from its demand zone. For traders, Rs 1,220 would be the key support level to watch. Above this level, the uptrend structure could continue towards Rs 1,350."),
        ("Amol Athawale, VP Technical Research at Kotak Securities",
         "Britannia Industries", 4883.8, "Buy", [5220.0], 4710.0,
         "Britannia Industries has rebounded from a key demand zone on the weekly charts following a prolonged decline, signalling renewed buying interest. The stock has formed a strong bullish candlestick pattern on the daily charts. The RSI indicator also points to strengthening momentum, indicating potential for further upside. In the near term, Rs 4,710 remains a crucial level for the bulls. If the stock holds above this support, the positive trend is likely to persist, with the possibility of the price advancing towards Rs 5,220 in the coming sessions."),
    ],
}

OCT06 = {
    "url": "https://www.moneycontrol.com/news/business/markets/trade-spotlight-how-should-you-trade-zensar-tech-netweb-tech-action-construction-equipment-dr-lal-pathlabs-hero-motocorp-and-others-on-october-6-14045235.html",
    "title": "Trade Spotlight: How should you trade Zensar Tech, Netweb Tech, Action Construction Equipment, Dr Lal PathLabs, Hero MotoCorp, and others on October 6?",
    "date": "2026-10-06",
    "blocks": [
        ("Jigar S Patel, Senior Manager - Equity Research at Anand Rathi",
         "Zensar Technologies", 451.5, "Buy", [510.0], 415.0,
         "Zensar is showing a positive technical setup, supported by improving momentum across multiple time frames. Bullish divergence on both the daily and weekly charts indicates that while prices remained under pressure earlier, downside momentum is weakening, increasing the possibility of a trend reversal. On the hourly chart, the RSI has moved above the 70 level, reflecting strong buying momentum and suggesting that bulls are gaining control in the short term. From a price-action perspective, the stock is sustaining above its 10- and 20-DEMA, keeping the immediate trend positive and providing support on declines. The combination of multi-timeframe bullish divergence, strong hourly RSI momentum and the stock sustaining above key short-term moving averages makes the technical structure constructive. Traders may consider entering long positions in the Rs 450-430 zone, with a target of Rs 510."),
        ("Jigar S Patel, Senior Manager - Equity Research at Anand Rathi",
         "Netweb Technologies India", 4765.1, "Buy", [5300.0], 4370.0,
         "A positive technical setup is emerging in Netweb Technologies, with bullish divergence visible on the daily chart near the previous demand zone. This indicates that although the price had witnessed weakness, selling pressure is gradually losing momentum, increasing the possibility of a recovery. On a broader time frame, the RSI has shown a positive reversal from July to date, suggesting a gradual improvement in underlying momentum and a potential shift in market sentiment. The combination of support from the previous demand zone and an improving RSI structure provides a favourable technical setup. Traders may consider entering long positions in the Rs 4,750-4,700 zone, with a target of Rs 5,300."),
        ("Jigar S Patel, Senior Manager - Equity Research at Anand Rathi",
         "Nippon India ETF Nifty IT", 31.35, "Buy", [39.0], 27.0,
         "IT BEES is showing a positive technical setup, supported by a combination of regular bullish divergence followed by hidden bullish divergence on both the IT Index and IT BEES. During the initial regular bullish divergence, IT BEES formed lower lows in price while the RSI formed higher lows, indicating weakening selling momentum. The stock subsequently crossed its previous peak of Rs 35.50 and moved to a new high of Rs 36.98, while the RSI moved above 70, indicating a positive RSI range shift and strengthening momentum. Following this rally, IT BEES corrected towards the Rs 31 zone. However, this time, the RSI made a lower low while the price did not make a corresponding lower low. This resulted in a hidden bullish divergence, suggesting that the underlying uptrend may still be intact. The combination of these two divergences indicates improving momentum and raises the possibility of a broader recovery in the IT sector. Traders may consider entering long positions in the Rs 31.50-29.50 zone, with a target of Rs 39."),
        ("Vidnyan S Sawant, Head of Research at GEPL Capital",
         "Action Construction Equipment", 1227.5, "Buy", [1375.0], 1159.0,
         "ACE maintains a strong uptrend, forming higher tops and bottoms while breaking above its falling channel. The stock is trading above its 20-, 50-, 100- and 200-DEMA, indicating sustained trend strength. Weekly buying near the 61.8 percent Fibonacci retracement, along with a positive MACD above the equilibrium line, supports the constructive outlook."),
        ("Vidnyan S Sawant, Head of Research at GEPL Capital",
         "Dr Lal PathLabs", 1971.3, "Buy", [2127.0], 1890.0,
         "Dr Lal PathLabs maintains a strong uptrend, forming higher tops and bottoms while sustaining above its 12-month EMA. The stock has shown resilience despite broader market volatility, reflecting relative strength. Weekly consolidation remains positive, while an accelerating MACD supports the constructive outlook."),
        ("Somil Mehta, Head of Retail Research at Mirae Asset ShareKhan",
         "Dixon Technologies (India) Futures", 12758.0, "Sell", [12100.0, 11800.0], 13575.0,
         "Dixon Technologies has broken down from a bearish flag after getting stuck around its daily moving averages. As per the wave count, the wave B pullback appears to be complete, and wave C of the correction should now play out. This could take the stock lower towards the Rs 12,100-11,800 zone. In the near term, any bounce towards Rs 12,850-13,000 would be better used as an opportunity to sell. The bearish setup would come into doubt only if the stock moves above its 40-day EMA, which is currently at Rs 13,575. Sell Dixon October Futures between Rs 12,850 and Rs 13,000, with a stop-loss at Rs 13,575 on a closing basis."),
        ("Somil Mehta, Head of Retail Research at Mirae Asset ShareKhan",
         "Bharat Petroleum Corporation Futures", 298.0, "Sell", [285.0, 277.5], 310.0,
         "The recovery from the March 2026 low could not move past the 40-week EMA and ran into selling pressure there. BPCL has since slipped below its rising trendline, and on Monday, it also fell below the previous weekly low. Momentum indicators on both the daily and weekly charts have turned bearish, while the price is trading below key daily and weekly moving averages. The stock looks set to lag the benchmark and may slide towards the Rs 285-277.50 zone. Until it reclaims the 40-day EMA at Rs 310, the bears are likely to retain the upper hand. Sell BPCL October Futures at CMP, with a stop-loss at Rs 310 on a closing basis."),
        ("Somil Mehta, Head of Retail Research at Mirae Asset ShareKhan",
         "Hero MotoCorp Futures", 5080.5, "Sell", [4860.0, 4742.0], 5335.0,
         "After a sharp fall from the August 2026 highs, Hero MotoCorp moved sideways for a while. On Monday, that range broke on the downside, shortly after the price was turned back near key daily moving averages. The daily momentum indicator has also given a bearish crossover recently. All this points to a resumption of the downtrend, with a drift towards Rs 4,860 likely, followed by Rs 4,742, where wave C would equal wave A. The ongoing trend remains down and is likely to stay that way as long as the stock trades below Rs 5,335, the level of its 40-day EMA. Sell Hero MotoCorp October Futures at CMP, with a stop-loss at Rs 5,335 on a closing basis."),
    ],
}

ARTICLES = [OCT06, OCT07]


def apply(conn: sqlite3.Connection) -> dict:
    now = "00:00:00"  # placeholder replaced per-article below
    art_added = rec_added = 0
    for art in ARTICLES:
        # fetched_at must be the article's own date, NOT today: the morning
        # freshness guard skips a run when articles were fetched "today",
        # and this patch runs BEFORE that guard inside the workflow.
        fetched = f"{art['date']} 12:00:00"
        row = conn.execute("SELECT id FROM articles WHERE url = ?",
                           (art["url"],)).fetchone()
        if row:
            art_id = row[0]
        else:
            cur = conn.execute(
                """INSERT INTO articles (url, title, article_date, record_date,
                                         fetched_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (art["url"], art["title"], art["date"], art["date"], fetched))
            art_id = cur.lastrowid
            art_added += 1
        for analyst, stock, cmp_, action, targets, sl, reasoning in art["blocks"]:
            exists = conn.execute(
                "SELECT 1 FROM recommendations WHERE article_id = ? AND stock_name = ?",
                (art_id, stock)).fetchone()
            if exists:
                continue
            conn.execute(
                """INSERT INTO recommendations
                     (article_id, stock_name, cmp, action, target_1, target_2,
                      target_3, stop_loss, reasoning, analyst)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (art_id, stock, cmp_, action,
                 targets[0] if len(targets) > 0 else None,
                 targets[1] if len(targets) > 1 else None,
                 targets[2] if len(targets) > 2 else None,
                 sl, reasoning, analyst or ""))
            rec_added += 1
    conn.commit()
    return {"articles_added": art_added, "recommendations_added": rec_added}


def main() -> None:
    conn = sqlite3.connect("data/moneypuller.db")
    try:
        stats = apply(conn)
        n = conn.execute("SELECT COUNT(*) FROM recommendations r "
                         "JOIN articles a ON a.id = r.article_id "
                         "WHERE a.record_date >= '2026-10-06'").fetchone()[0]
        print(f"backfill: {stats} | recommendations with record_date >= "
              f"2026-10-06: {n}")
        if n == 0:
            sys.exit("nothing applied - verify the DB path/content")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
