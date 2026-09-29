"""TV recommendation extractor (phase 1: rules-based, per video).

Pipeline:
  1. Load timestamped transcript segments (data/tv_recommendations/raw_transcripts/<vid>.json)
  2. Score sliding windows for recommendation density (target / SL / buy / sell
     keywords in Hindi + Latin-script stock names + numeric levels)
  3. Cluster dense windows into "call blocks"
  4. Within each block: detect stock names (Latin-script, fuzzy-matched
     against the MoneyPuller symbols table), associate targets/SL with the
     nearest stock mention, attribute the call to an expert ("X ji" name
     dictionary mined from the video), sanity-check price levels
  5. Write parsed CSV + JSON into data/tv_recommendations/parsed/

Usage:
    python tv_extractor.py BGGOO3nYMRw [--dump-blocks]
"""

import json
import re
import sqlite3
import sys
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).parent
RAW_DIR = ROOT / "data" / "tv_recommendations" / "raw_transcripts"
OUT_DIR = ROOT / "data" / "tv_recommendations" / "parsed"
DB = ROOT / "data" / "moneypuller.db"

# ---------------------------------------------------------------- keywords
TARGET_KW = re.compile(r"टारगेट|टार्गेट|तारगेट|target", re.I)
SL_KW = re.compile(r"स्टॉप\s*लॉस|स्टाप\s*लॉस|stop\s*loss", re.I)
BUY_KW = re.compile(r"खरीद|खरीदारी|बाइंग|buy|एक्यूमुलेट|accumul|सपोर्ट पर", re.I)
SELL_KW = re.compile(r"बेच|बिकवाली|sell|शॉर्ट", re.I)
NUM_RE = re.compile(r"\d{1,3}(?:,\d{2,3})*(?:\.\d+)?")

INDEX_NAMES = {"nifty", "banknifty", "bank nifty", "nifty bank", "sensex",
               "finnifty", "midcpnifty"}

# stocks commonly referred to by their Hindi/Devanagari spelling on TV
DEV_STOCKS = {
    "आईटीसी": "ITC Ltd",
    "मारुति": "Maruti Suzuki India",
    "रिलायंस": "Reliance Industries",
    "एचडीएफसी": "HDFC Bank",
    "आईसीआईसीआई": "ICICI Bank",
    "स्टेट बैंक": "State Bank of India",
    "एसबीआई": "State Bank of India",
    "टाटा मोटर्स": "Tata Motors",
    "टाटा स्टील": "Tata Steel",
    "लार्सन": "Larsen & Toubro",
    "इन्फोसिस": "Infosys",
    "टीसीएस": "Tata Consultancy Services",
    "एचसीएल": "HCL Technologies",
    "विप्रो": "Wipro",
    "भारती एयरटेल": "Bharti Airtel",
    "एयरटेल": "Bharti Airtel",
    "अशोक लेलैंड": "Ashok Leyland",
    "टाटा पावर": "Tata Power",
    "पेट्रोनेट": "Petronet LNG",
    "ओएनजीसी": "Oil & Natural Gas Corporation",
    "एनटीपीसी": "NTPC",
    "पीएफसी": "Power Finance Corporation",
    "आईआरसीटीसी": "Indian Railway Catering & Tourism Corporatio",
    "बेल": "Bharat Electronics",
    "हिंडाल्को": "Hindalco Industries",
    "वेदांता": "Vedanta",
    "जियो": "Jio Financial Services",
}

# tokens that appear in transcripts but are not stocks
NON_STOCK = {
    "youtube", "whatsapp", "telegram", "google", "ok", "oh", "mm", "hmm",
    "market", "markets", "stock", "stocks", "counter", "counters", "level",
    "levels", "target", "targets", "stop", "loss", "buy", "sell", "trading",
    "trade", "view", "technical", "chart", "charts", "candle", "daily",
    "weekly", "monthly", "futures", "future", "option", "options", "call",
    "calls", "put", "puts", "business", "finance", "live", "update",
    "updates", "breaking", "news", "anchor", "expert", "experts", "guest",
    "closing", "open", "opening", "high", "low", "range", "support",
    "resistance", "trend", "bullish", "bearish", "bounce", "breakout",
    "breakdown", "pattern", "moving", "average", "volume", "rupee", "dollar",
    "crude", "gold", "silver", "commodity", "sector", "sectors", "india",
    " indian", "auto", "bank", "banks", "it", "psu", "fmcg", "pharma",
    "realty", "metal", "metals", "energy", "power", "infra", "railway",
    "defence", "paints", "farma", "pharma", "space", "motors", "motor",
    "industries", "industrial", "finance", "capital", "life", "infra",
    "tech", "technolog", "technologes", "ltd", "limited", "aog", "tmp",
    "tmpv", "tmt", "lts", "lnt", "ds", "ll", "lj", "lg", "lng", "kfs",
}


def looks_like_stock(tok: str) -> bool:
    t = tok.strip(" .,!?|:;()[]{}'\"-—0123456789")
    if len(t) < 2 or len(t) > 25:
        return False
    if not re.fullmatch(r"[A-Za-z][A-Za-z&.\- ]*", t):
        return False
    if t.lower() in NON_STOCK:
        return False
    return t.isupper() or t[0].isupper()


# ---------------------------------------------------------------- blocks
def seg_window_text(segs: list[dict]) -> str:
    return " ".join(s["text"] for s in segs)


def score_window(text: str) -> float:
    score = 0.0
    if TARGET_KW.search(text):
        score += 2.0
    if SL_KW.search(text):
        score += 2.0
    if BUY_KW.search(text):
        score += 1.0
    if SELL_KW.search(text):
        score += 0.5
    if NUM_RE.search(text):
        score += 1.0
    n_stocks = sum(1 for t in re.findall(r"[A-Za-z][A-Za-z&.\- ]+", text)
                   if looks_like_stock(t))
    if n_stocks:
        score += min(n_stocks, 3) * 0.7
    return score


def find_blocks(segs, win=12, stride=3, thresh=3.0, merge_gap_s=55.0,
                min_block_len_s=35.0):
    scored = []
    for i in range(0, max(len(segs) - win, 1), stride):
        chunk = segs[i:i + win]
        s = score_window(seg_window_text(chunk))
        if s >= thresh:
            scored.append((chunk[0]["start"], chunk[-1]["start"] + 4, s))
    if not scored:
        return []
    blocks, cur = [], list(scored[0])
    for st, en, s in scored[1:]:
        if st <= cur[1] + merge_gap_s:
            cur[1] = max(cur[1], en)
            cur[2] = max(cur[2], s)
        else:
            blocks.append({"start": cur[0], "end": cur[1], "score": cur[2]})
            cur = [st, en, s]
    blocks.append({"start": cur[0], "end": cur[1], "score": cur[2]})
    return [b for b in blocks if b["end"] - b["start"] >= min_block_len_s]


def ts_fmt(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# ---------------------------------------------------------------- symbols
class StockIndex:
    """Fuzzy-matcher against MoneyPuller's known stock names + NSE names."""

    def __init__(self):
        names = set()
        try:
            conn = sqlite3.connect(DB)
            for (n,) in conn.execute(
                    "SELECT DISTINCT stock_name FROM recommendations"):
                names.add(n)
            for (n,) in conn.execute("SELECT nse_name FROM symbols WHERE nse_name"):
                names.add(n)
            conn.close()
        except Exception as e:
            print(f"(no symbol db: {e})")
        self.canon = {n.lower(): n for n in names if 3 <= len(n) <= 30}
        self.cache: dict[str, str | None] = {}

    def match(self, tok: str) -> str | None:
        t = tok.strip(" .,!?|:;()[]{}'\"-—")
        if t.lower() in self.cache:
            return self.cache[t.lower()]
        best, best_score = None, 0.0
        tl = t.lower()
        for low, canon in self.canon.items():
            # exact single-word match against any word of the canonical name
            # (ITC -> "ITC Ltd", Maruti -> "Maruti Suzuki India")
            words = low.replace("(", " ").replace(")", " ").split()
            if tl in words or (tl.isdigit() is False and words
                               and words[0] == tl):
                sc = 1.0
            elif low.startswith(tl) and len(t) >= 4:
                sc = len(t) / len(low) * 0.97
            else:
                sc = SequenceMatcher(None, tl, low).ratio()
            if sc > best_score:
                best, best_score = canon, sc
        out = best if best_score >= 0.80 else None
        self.cache[tl] = out
        return out


# ---------------------------------------------------------------- experts
def mine_experts(segs) -> dict[str, str]:
    """Find person names via '<X> ji' patterns; return dict lower->display."""
    # curated common Hindi first names (whitelist — ASR fragments otherwise
    # slip through: युद्ध 'war', स्ट्रेट 'strategy', एफएमसी 'FMCG', ...)
    KNOWN = {
        "अजय", "रवि", "विकास", "विनीत", "सौरभ", "दीपक", "दिनेश", "मोहन",
        "अक्षय", "अनुज", "महेश", "अमित", "विवेक", "श्रीकांत", "कुणाल",
        "गौरव", "तरुण", "पंकज", "अंकित", "नितेश", "नीलेश", "निमेश",
        "हितेश", "प्रदीप", "गुरप्रीत", "शिवांगी", "मानसी", "स्वाति",
        "दिव्या", "पूनम", "कविता", "सुनील", "राकेश", "लक्ष्मीकांत",
        "गौरांग", "संगीता", "रमनदीप", "बलदेव", "अनुराग", "निथिलेश",
        "निथलेश", "विक्रम", "राहुल", "संदीप", "जय", "जयेश", "हेमंत",
        "आलोक", "मुकेश", "रतन", "सुरेश", "जगदीश", "प्रकाश",
    }
    text = seg_window_text(segs)
    cands = re.findall(r"([\u0900-\u097F]{3,14})\s*जी", text)
    freq: dict[str, int] = {}
    for c in cands:
        c = c.rstrip("।.,?!")
        freq[c] = freq.get(c, 0) + 1
    return {c.lower(): c for c in freq if c in KNOWN and freq[c] >= 2}


# ---------------------------------------------------------------- fields
def nums_within(nums: list, pos: int, reach: int) -> list[float]:
    return [float(v.replace(",", "")) for p, v in nums if abs(p - pos) <= reach]


def plausible(targets: list[float], sl: float | None,
              entry: float | None, action: str) -> bool:
    """Levels must hang together as prices and be consistent with action."""
    vals = [v for v in targets if 5 <= v <= 200000]
    if sl is not None and not (5 <= sl <= 200000):
        sl = None
    if entry is not None and not (5 <= entry <= 200000):
        entry = None
    if not vals and sl is None and entry is None:
        return False
    pool = [v for v in vals + [entry, sl] if v]
    if len(pool) >= 2 and min(pool) > 0 and max(pool) / min(pool) > 6:
        return False                      # mixed units (264 vs 24600)
    if action == "Buy" and sl is not None and vals:
        if max(vals) <= sl:               # targets must sit above SL
            return False
    if action == "Buy" and entry is not None and sl is not None \
            and entry <= sl:
        return False
    return True


def merge_split_numbers(text: str) -> str:
    """ASR writes '12 450' for 12,450 — merge space-separated numeral pairs
    when the result lands in a plausible price range."""
    def join(m: re.Match) -> str:
        merged = m.group(1) + m.group(2)
        try:
            v = float(merged)
        except ValueError:
            return m.group(0)
        return merged if 20 <= v <= 200000 else m.group(0)
    # repeat twice: '11 11 900' cases collapse progressively
    for _ in range(2):
        text = re.sub(r"\b(\d{1,2})\s(\d{2,3})\b", join, text)
    return text


def parse_block(segs: list[dict], meta: dict, sidx: StockIndex,
                experts: dict) -> dict:
    text = merge_split_numbers(seg_window_text(segs))

    # ---- sentence segmentation (ASR punctuation is sparse; split on
    # danda, 'तो ', long gaps are already merged by seg_window_text)
    sentences = re.split(r"(?<=[।?!.])\s+", text)
    # further split very long sentences on common discourse markers
    expanded = []
    for s in sentences:
        if len(s) > 260:
            expanded += re.split(r"(?=तो |और |वहां|इसमें|अगर)", s)
        else:
            expanded.append(s)
    sentences = [s for s in expanded if s.strip()]

    # ---- stock mentions with positions
    mentions: list[tuple[int, str]] = []
    for m in re.finditer(r"[A-Za-z][A-Za-z&.\- ]{1,24}|[\u0900-\u097F]{4,}",
                         text):
        tok = m.group().strip()
        canon = None
        if re.match(r"[A-Za-z]", tok):
            if not looks_like_stock(tok):
                continue
            canon = sidx.match(tok)
            if canon is None:
                if len(tok) >= 4 and tok[0].isupper() \
                        and tok.lower() not in INDEX_NAMES:
                    canon = f"{tok}?"
                else:
                    continue
        else:
            # Devanagari token: only map when in the hardcoded dictionary
            canon = DEV_STOCKS.get(tok)
            if canon is None:
                continue
        if canon.lower() not in {c.lower() for _, c in mentions}:
            mentions.append((m.start(), canon))

    # ---- per-stock spans (mention until next mention)
    stocks_out: list[dict] = []
    if not mentions:
        stocks_out.append({"stock": None, "action": "", "targets": [],
                           "stop_loss": None, "entry": None})
    for i, (pos, name) in enumerate(mentions):
        span_end = mentions[i + 1][0] if i + 1 < len(mentions) else len(text)
        span = text[pos:span_end]
        nums = [(m.start(), m.group()) for m in NUM_RE.finditer(span)]
        targets, sl, entry = [], None, None
        for m in TARGET_KW.finditer(span):
            near = nums_within(nums, m.start(), reach=80)
            if near:
                targets += near[:2]          # max 2 numbers per mention
        for m in SL_KW.finditer(span):
            near = nums_within(nums, m.start(), reach=80)
            if near and sl is None:
                sl = near[0]
        for m in BUY_KW.finditer(span):
            after = nums_within(nums, m.end(), reach=50)
            if after and entry is None:
                entry = after[0]
                break
        action = "Buy" if BUY_KW.search(span) and not SELL_KW.search(span) \
            else "Sell" if SELL_KW.search(span) and not BUY_KW.search(span) \
            else "Mixed" if BUY_KW.search(span) or SELL_KW.search(span) else ""
        targets = sorted({t for t in targets if 5 <= t <= 200000},
                         reverse=(action == "Sell"))
        if entry is not None and entry in targets:
            targets.remove(entry)
        if not plausible(targets, sl, entry, action):
            targets, sl, entry = [], None, None
        if targets or sl is not None or entry or action:
            stocks_out.append({"stock": name, "action": action,
                               "targets": targets[:3], "stop_loss": sl,
                               "entry": entry})
    if not stocks_out:
        stocks_out.append({"stock": mentions[0][1] if mentions else None,
                           "action": "", "targets": [], "stop_loss": None,
                           "entry": None})

    # attribution: prefer anchor-style "X ki taraf se" near the end
    expert = None
    for m in re.finditer(
            r"([A-Z\u0900-\u097F][\w\u0900-\u097F]{2,14})\s*जी[^(।)]{0,120}"
            r"(की तरफ से|के तरफ से|ने)", text):
        nm = m.group(1)
        if nm.lower() in experts:
            expert = experts[nm.lower()]
            break
    if expert is None:
        for m in re.finditer(r"([A-Z\u0900-\u097F][\w\u0900-\u097F]{2,14})\s*जी",
                             text):
            if m.group(1).lower() in experts:
                expert = experts[m.group(1).lower()]
                break

    # if a single stock dominates, promote to flat columns
    main = max(stocks_out, key=lambda s: bool(s["stock"]) and
               (len(s["targets"]) + (s["stop_loss"] is not None)
                + (s.get("entry") is not None)))
    has_call = bool(main["targets"] or main["stop_loss"] is not None)
    rec = {
        "video_id": meta["video_id"],
        "video_title": meta.get("video_title", ""),
        "start_s": meta["start"],
        "end_s": meta["end"],
        "start_ts": ts_fmt(meta["start"]),
        "end_ts": ts_fmt(meta["end"]),
        "stock": main["stock"],
        "all_stocks": "; ".join(dict.fromkeys(
            s["stock"] for s in stocks_out if s["stock"])),
        "action": main["action"],
        "entry": main.get("entry"),
        "target_1": main["targets"][0] if main["targets"] else None,
        "target_2": main["targets"][1] if len(main["targets"]) > 1 else None,
        "target_3": main["targets"][2] if len(main["targets"]) > 2 else None,
        "stop_loss": main["stop_loss"],
        "expert": expert,
        "excerpt": text[:500],
        "has_call": has_call,
        "confidence": ("high" if has_call and main["stock"]
                       and not main["stock"].endswith("?")
                       else "medium" if main["stock"] or has_call else "low"),
    }
    return rec


def fmt_num(v) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v)


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python tv_extractor.py <video_id> [--dump-blocks]")
        return
    vid = sys.argv[1]
    jpath = RAW_DIR / f"{vid}.json"
    if not jpath.exists():
        print(f"transcript not found: {jpath}")
        return

    meta = {"video_id": vid, "video_title": vid}
    try:
        import urllib.request
        with urllib.request.urlopen(
                f"https://www.youtube.com/oembed?url="
                f"https://www.youtube.com/watch?v={vid}&format=json",
                timeout=15) as r:
            meta["video_title"] = json.loads(r.read()).get("title", "")
    except Exception:
        pass

    segs = json.loads(jpath.read_text(encoding="utf-8"))
    print(f"{vid}: {len(segs)} segments, {segs[-1]['start']/3600:.1f}h — "
          f"'{meta['video_title'][:60]}'")

    sidx = StockIndex()
    experts = mine_experts(segs)
    print(f"expert dictionary: {list(experts.values())}")

    blocks = find_blocks(segs)
    print(f"candidate blocks: {len(blocks)}")
    recs = []
    for b in blocks:
        bsegs = [s for s in segs if b["start"] <= s["start"] <= b["end"]]
        recs.append(parse_block(bsegs, dict(meta, start=b["start"],
                                            end=b["end"]), sidx, experts))

    calls = [r for r in recs if r["has_call"]]
    print(f"records: {len(recs)} blocks, {len(calls)} with extractable calls")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{vid}.json").write_text(
        json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")

    cols = ["start_ts", "end_ts", "stock", "action", "entry", "target_1",
            "target_2", "target_3", "stop_loss", "expert", "confidence"]
    csv_path = OUT_DIR / f"{vid}.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        f.write(",".join(cols) + "\n")
        for r in recs:
            row = [fmt_num(r[c]) or "" for c in cols]
            row = [f'"{v}"' if ("," in v or '"' in v) else v for v in row]
            f.write(",".join(row) + "\n")
    print(f"wrote -> {csv_path}")

    for r in recs:
        line = (f"[{r['start_ts']:>7}-{r['end_ts']:>7}] "
                f"{str(r['stock'])[:24]:24} {r['action'][:5]:5} "
                f"E:{fmt_num(r.get('entry'))[:7]:7} "
                f"T:{fmt_num(r['target_1'])[:7]:7}/{fmt_num(r['target_2'])[:7]:7} "
                f"SL:{fmt_num(r['stop_loss'])[:7]:7} "
                f"exp:{str(r['expert'])[:12]:12} {r['confidence']}")
        try:
            print(line)
        except UnicodeEncodeError:
            print(line.encode("ascii", "replace").decode())


if __name__ == "__main__":
    main()
