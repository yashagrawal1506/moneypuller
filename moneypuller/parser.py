"""
MoneyPuller - parser for Moneycontrol "Trade Spotlight" articles.

Article body lives in <div id="contentdata"> as a sequence of <p> blocks:

    <p><strong>Analyst Name, Title at Firm</strong></p>        <- optional byline
    <p><strong>Stock Name | CMP: Rs 1,234.50</strong></p>      <- block header
    <p>reasoning paragraph 1 ...</p>
    <p>reasoning paragraph 2 ...</p>
    <p><strong>Strategy: Buy</strong></p>                      <- action
    <p><strong>Target: Rs 1,300, Rs 1,400</strong></p>         <- 1..3 targets
    <p><strong>Stop-Loss: Rs 1,150</strong></p>

Everything between a block header and the next header/byline belongs to the
previous stock. Images and ad markup are ignored.
"""

import html as html_mod
import re
from dataclasses import dataclass, field

RECORD_DATE_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+(\d{1,2})(?:,\s*(20\d\d))?"
)
MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}

NUM = r"([\d,]+(?:\.\d+)?)"

BLOCK_HEADER_RE = re.compile(
    rf"^(?P<stock>.+?)\s*\|\s*CMP:\s*(?:Rs\.?\s*)?"
    rf"(?P<price>[\d,]+(?:\s?[\d,]+)*(?:\.\d+)?)\.?$")
TARGETS_RE = re.compile(rf"^Target(?:\s*s)?\s*:\s*(?P<vals>.*?)(?:\.\s*)?$", re.I)
ACTION_RE = re.compile(r"^Strategy:\s*(?P<action>.+?)\s*$", re.I)
STOPLOSS_RE = re.compile(rf"^Stop-?\s*Loss\s*:?\s*(?:Rs\.?\s*)?{NUM}\.?$", re.I)


@dataclass
class Recommendation:
    stock_name: str
    cmp: float
    reasoning: str = ""
    action: str = ""
    targets: list = field(default_factory=list)
    stop_loss: float | None = None
    analyst: str = ""


@dataclass
class Article:
    url: str
    title: str
    article_date: str | None          # "2026-09-25"
    record_date: str | None           # trading day from the title, "2026-09-25"
    recommendations: list = field(default_factory=list)


def _strip_tags(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = html_mod.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _num(raw: str) -> float:
    # commas and the rare space-instead-of-comma typo ('Rs 73 0.5' -> 730.5)
    return float(re.sub(r"[\s,]", "", raw))


def _extract_article_date(text: str) -> str | None:
    m = re.search(r'"datePublished"\s*:\s*"(\d{4}-\d{2}-\d{2})', text)
    if m:
        return m.group(1)
    m = re.search(r'published_time" content="(\d{4}-\d{2}-\d{2})', text)
    return m.group(1) if m else None


def _looks_like_byline(line: str) -> bool:
    """Bylines like 'Chandan Taparia, Head Derivatives at Motilal Oswal' can
    exceed 100 chars; prose sentences usually end with a period."""
    if line.endswith("."):
        return False
    if line.startswith(("The ", "Top ", "Market ", "Here ", "Benchmark ")):
        return False
    # level/strategy lines must never be mistaken for a byline even when
    # malformed ('Stop-Loss Rs 1,834' contains a comma inside the number)
    if line.lower().startswith(
            ("target", "stop-loss", "stop loss", "strategy", "cmp")):
        return False
    if "," not in line:
        return False
    if len(line) < 100:
        return True
    return " at " in line and len(line) < 160


def _extract_record_date(title: str, article_date: str | None) -> str | None:
    """Trading day from the title, e.g. '... on September 25?'.

    Titles omit the year, so take it from the article publish date; adjust
    for the December/January boundary.
    """
    m = RECORD_DATE_RE.search(title)
    if not m:
        return None
    month_name, day = m.group(1), int(m.group(2))
    if m.group(3):
        return f"{int(m.group(3)):04d}-{MONTHS[month_name]:02d}-{day:02d}"
    if not article_date:
        return None
    year = int(article_date[:4])
    if MONTHS[month_name] == 12 and article_date[5:7] == "01":
        year -= 1
    return f"{year:04d}-{MONTHS[month_name]:02d}-{day:02d}"


def extract_article(html: str, url: str = "") -> Article:
    """Parse one Trade Spotlight article into an Article with recommendations."""
    title = ""
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    if m:
        title = _strip_tags(m.group(1))

    article_date = _extract_article_date(html)

    # Slice out the body container.
    start = html.find('id="contentdata"')
    if start == -1:
        return Article(url=url, title=title, article_date=article_date,
                       record_date=_extract_record_date(title, article_date))
    chunk = html[start:]
    end = chunk.lower().find("disclaimer")
    chunk = chunk[:end] if end != -1 else chunk[:150000]

    recs: list[Recommendation] = []
    current: Recommendation | None = None
    analyst = ""
    seen_strategy = False

    for raw_p in re.findall(r"<p[^>]*>(.*?)</p>", chunk, re.S):
        line = _strip_tags(raw_p)
        if not line or line.startswith("-->") or line.startswith(".snap"):
            continue

        header = BLOCK_HEADER_RE.match(line)
        if header:
            current = Recommendation(stock_name=header.group("stock").strip(),
                                     cmp=_num(header.group("price")),
                                     analyst=analyst)
            recs.append(current)
            seen_strategy = False
            continue

        if current is None:
            if _looks_like_byline(line):
                analyst = line
            continue

        action = ACTION_RE.match(line)
        if action:
            raw_action = action.group("action").strip()
            # Normalize plain BUY/SELL/buy/sell to title case; keep mixed-case
            # phrasing like "Sell on rise" exactly as written.
            if raw_action.isupper() or raw_action.islower():
                raw_action = raw_action.title()
            current.action = raw_action
            seen_strategy = True
            continue

        targets = TARGETS_RE.match(line)
        if targets:
            vals = re.findall(NUM + r"\s*(?=,|$)", targets.group("vals"))
            current.targets = [_num(v) for v in vals if v]
            continue

        sl = STOPLOSS_RE.match(line)
        if sl:
            current.stop_loss = _num(sl.group(1))
            continue

        # A byline after a completed block signals the next expert.
        if seen_strategy and current.targets and _looks_like_byline(line):
            current = None
            analyst = line
            continue

        if current and current.cmp:
            current.reasoning = (current.reasoning + " " + line).strip()

    return Article(url=url, title=title, article_date=article_date,
                   record_date=_extract_record_date(title, article_date),
                   recommendations=recs)
