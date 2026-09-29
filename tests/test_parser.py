"""Regression tests for the Trade Spotlight parser (no network needed)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from moneypuller.parser import (extract_article, _extract_record_date)  # noqa: E402

SAMPLE = """
<html><head><title>x</title></head><body>
<h1>Trade Spotlight: How should you trade Alpha Ltd, Beta Industries, and others on September 25?</h1>
<div class="content_wrapper arti-flow" id="contentdata">
<p>The market ended flat. Here are some ideas.</p>
<p><strong>Meera Nair, Head of Research at Example Securities</strong></p>
<p><strong>Alpha Ltd | CMP: Rs 1,234.50</strong></p>
<p>Alpha broke out of a two-month consolidation with strong volume.</p>
<p>RSI remains above 50, supporting upside momentum.</p>
<p><strong>Strategy: Buy</strong></p>
<p><strong>Target: Rs 1,300, Rs 1,400</strong></p>
<p><strong>Stop-Loss: Rs 1,150</strong></p>
<p><strong>Rahul Verma, Technical Analyst at Demo Capital</strong></p>
<p><strong>Beta Industries | CMP: Rs 87.90</strong></p>
<p>Beta reclaimed its 20-day SMA; candle structure is positive.</p>
<p><strong>Strategy: Avoid</strong></p>
<p><strong>Target: Rs 96</strong></p>
<p><strong>Stop-Loss: 84.8</strong></p>
</div>
</body></html>
"""


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.art = extract_article(SAMPLE, url="https://example.com/ts")

    def test_two_recommendations(self):
        self.assertEqual(len(self.art.recommendations), 2)

    def test_stock_fields(self):
        a, b = self.art.recommendations
        self.assertEqual(a.stock_name, "Alpha Ltd")
        self.assertEqual(a.cmp, 1234.5)
        self.assertEqual(a.targets, [1300.0, 1400.0])
        self.assertEqual(a.stop_loss, 1150.0)
        self.assertEqual(a.action, "Buy")
        self.assertIn("broke out", a.reasoning)
        self.assertEqual(a.analyst, "Meera Nair, Head of Research at Example Securities")

    def test_second_block(self):
        b = self.art.recommendations[1]
        self.assertEqual(b.stock_name, "Beta Industries")
        self.assertEqual(b.cmp, 87.9)
        self.assertEqual(b.targets, [96.0])
        self.assertEqual(b.stop_loss, 84.8)
        self.assertEqual(b.action, "Avoid")
        self.assertEqual(b.analyst, "Rahul Verma, Technical Analyst at Demo Capital")

    def test_record_date_year_inference(self):
        self.assertEqual(
            _extract_record_date("... on September 25?", "2026-09-25T07:00:00+05:30"),
            "2026-09-25")
        self.assertEqual(
            _extract_record_date("... on January 2?", "2026-01-02T07:00:00+05:30"),
            "2026-01-02")
        self.assertEqual(
            _extract_record_date("... on December 30?", "2026-01-02T07:00:00+05:30"),
            "2025-12-30")

    def test_article_date(self):
        html = SAMPLE.replace("<title>x</title>",
                              '<title>x</title><script type="application/ld+json">'
                              '{"@type":"NewsArticle","datePublished":'
                              '"2026-09-25T07:36:50+05:30"}</script>')
        art = extract_article(html, url="u")
        self.assertEqual(art.article_date, "2026-09-25")


SELL_SAMPLE = """
<html><body>
<h1>Trade Spotlight: How should you trade Gamma Ltd, Delta Ltd, and others on October 1?</h1>
<div id="contentdata">
<p>Market recap paragraph.</p>
<p><strong>First Analyst, Head of Research at Firm One</strong></p>
<p><strong>Gamma Ltd | CMP: Rs 500</strong></p>
<p>Gamma is facing resistance near its recent high.</p>
<p><strong>Strategy: Sell</strong></p>
<p><strong>Target: Rs 470, Rs 450</strong></p>
<p><strong>Stop-Loss: Rs 520</strong></p>
<p><strong>Second Analyst, Technical Analyst at Firm Two</strong></p>
<p><strong>Delta Ltd | CMP: Rs 1,200</strong></p>
<p>Delta shows exhaustion after a long rally.</p>
<p><strong>Strategy: SELL</strong></p>
<p><strong>Target: Rs 1,100, Rs 1,050, Rs 1,000</strong></p>
<p><strong>Stop-Loss: 1,250</strong></p>
<p><strong>Third Analyst, Analyst at Firm Three</strong></p>
<p><strong>Epsilon Ltd | CMP: Rs 90.5</strong></p>
<p>Epsilon has support around Rs 85; limited downside risk.</p>
<p><strong>Strategy: Sell on rise</strong></p>
<p><strong>Target: Rs 80</strong></p>
<p><strong>Stop-Loss: Rs 95</strong></p>
</div>
</body></html>
"""


class SellLeadTests(unittest.TestCase):
    """Moneycontrol articles sometimes tag blocks BUY/SELL/AVOID in caps or
    with mixed-case phrasing; ensure all variants parse as Sell leads."""

    def setUp(self):
        self.art = extract_article(SELL_SAMPLE, url="https://example.com/sell")
        self.by_stock = {r.stock_name: r for r in self.art.recommendations}

    def test_all_three_sell_blocks_parsed(self):
        self.assertEqual(len(self.art.recommendations), 3)

    def test_plain_sell(self):
        r = self.by_stock["Gamma Ltd"]
        self.assertEqual(r.action, "Sell")
        self.assertEqual(r.targets, [470.0, 450.0])
        self.assertEqual(r.stop_loss, 520.0)

    def test_allcaps_sell(self):
        r = self.by_stock["Delta Ltd"]
        self.assertEqual(r.action, "Sell")
        self.assertEqual(r.targets, [1100.0, 1050.0, 1000.0])  # fills T1..T3
        self.assertEqual(r.stop_loss, 1250.0)

    def test_mixed_case_sell_on_rise_kept_verbatim(self):
        r = self.by_stock["Epsilon Ltd"]
        self.assertEqual(r.action, "Sell on rise")
        self.assertEqual(r.targets, [80.0])

    def test_long_byline_over_100_chars(self):
        """Regression: a byline longer than 100 chars must still attach."""
        long_byline = ("Chandan Taparia, Head Derivatives & Technicals, "
                       "Wealth Management at Motilal Oswal Financial Services")
        self.assertGreater(len(long_byline), 100)
        html = SAMPLE.replace(
            "Meera Nair, Head of Research at Example Securities", long_byline)
        art = extract_article(html, url="u")
        self.assertEqual(art.recommendations[0].analyst, long_byline)
    def test_space_in_cmp_and_missing_colon_sl(self):
        """MC typos: 'CMP: Rs 73 0.5' (space for comma) and
        'Stop-Loss Rs 1,834' (no colon) must parse, and following blocks
        must not inherit the previous block's levels as a byline."""
        html = """<h1>Trade Spotlight</h1>
        <div id="contentdata">
        <p>Guru, Analyst at Firm</p>
        <p><strong>Container Corporation of India | CMP: Rs 73 0.5</strong></p>
        <p>Container Corp rallied.</p>
        <p><strong>Strategy: Buy</strong></p>
        <p><strong>Target: Rs 800, Rs 820</strong></p>
        <p><strong>Stop-Loss: Rs 668</strong></p>
        <p><strong>Adani Green Energy | CMP: Rs 1,020.10</strong></p>
        <p>Adani Green surged.</p>
        <p><strong>Strategy: Buy</strong></p>
        <p><strong>Target: Rs 1,120, Rs 1,140</strong></p>
        <p><strong>Stop-Loss: Rs 920</strong></p>
        </div>"""
        art = extract_article(html, url="u")
        self.assertEqual(len(art.recommendations), 2)
        cc, ag = art.recommendations
        self.assertEqual(cc.stock_name, "Container Corporation of India")
        self.assertEqual(cc.cmp, 730.5)
        self.assertEqual(cc.targets, [800.0, 820.0])
        self.assertEqual(cc.stop_loss, 668.0)
        self.assertEqual(cc.analyst, "Guru, Analyst at Firm")
        self.assertEqual(ag.cmp, 1020.1)
        self.assertEqual(ag.targets, [1120.0, 1140.0])
        self.assertEqual(ag.stop_loss, 920.0)
        self.assertEqual(ag.analyst, "Guru, Analyst at Firm")

    def test_stoploss_without_colon_not_byline(self):
        html = """<h1>T</h1>
        <div id="contentdata">
        <p>First Analyst, Research at Firm A</p>
        <p><strong>Lloyds Metals | CMP: Rs 1,930.6</strong></p>
        <p>Lloyds is in an uptrend.</p>
        <p><strong>Strategy: Buy</strong></p>
        <p><strong>Target: Rs 2,122</strong></p>
        <p><strong>Stop-Loss Rs 1,834</strong></p>
        <p><strong>Global Health | CMP: Rs 1,378.2</strong></p>
        <p>Medanta is bullish.</p>
        <p><strong>Strategy: Buy</strong></p>
        <p><strong>Target: Rs 1,498</strong></p>
        <p><strong>Stop-Loss: Rs 1,318</strong></p>
        </div>"""
        art = extract_article(html, url="u")
        lm, gh = art.recommendations
        self.assertEqual(lm.stop_loss, 1834.0)
        self.assertEqual(lm.analyst, "First Analyst, Research at Firm A")
        self.assertEqual(gh.stop_loss, 1318.0)
        self.assertEqual(gh.analyst, "First Analyst, Research at Firm A")


if __name__ == "__main__":
    unittest.main()
