"""Scan cached article HTML for known Moneycontrol formatting anomalies.

Looks for:
  1. CMP written with a space instead of a comma  ('CMP: Rs 73 0.5')
  2. 'Stop-Loss Rs ...' without the colon
  3. 'Target Rs ...' without the colon
  4. orphan level lines (Target/Stop-Loss appearing before any stock header)

Usage: python scan_anomalies.py
"""

import re
from pathlib import Path

ART_DIR = Path("data/raw/articles")

CMP_LINE = re.compile(r"^.*\|\s*CMP:\s*Rs\.?\s*[\d,]+ [\d,]+(?:\.\d+)?")
SL_NO_COLON = re.compile(r"^Stop-?\s*Loss\s+Rs")
TGT_NO_COLON = re.compile(r"^Target\s+Rs")
LEVEL_LINE = re.compile(r"^(Target|Stop-?\s*Loss)\b", re.I)


def article_lines(path: Path) -> list[str]:
    html = path.read_text(encoding="utf-8", errors="replace")
    i = html.find('id="contentdata"')
    if i == -1:
        return []
    chunk = html[i:]
    j = chunk.lower().find("disclaimer")
    chunk = chunk[:j] if j != -1 else chunk[:200000]
    # split-based extraction: linear even when <p> tags never close
    lines = []
    for part in chunk.split("<p")[1:]:
        end = part.find("</p>")
        if end == -1:
            continue
        s = re.sub(r"<[^>]+>", " ", part[:end])
        s = re.sub(r"\s+", " ", s).strip()
        if s:
            lines.append(s)
    return lines


def main() -> None:
    files = sorted(ART_DIR.glob("*.html"))
    report = {}
    for n, f in enumerate(files, start=1):
        lines = article_lines(f)
        anomalies = []
        seen_header = False
        for ln in lines:
            if "\uFFFD" in ln:
                anomalies.append(("encoding", ln[:90]))
            if CMP_LINE.match(ln):
                anomalies.append(("cmp-space", ln[:90]))
            if SL_NO_COLON.match(ln):
                anomalies.append(("sl-nocolon", ln[:90]))
            if TGT_NO_COLON.match(ln):
                anomalies.append(("tgt-nocolon", ln[:90]))
            if re.match(r"^.+\|\s*CMP:", ln):
                seen_header = True
            elif LEVEL_LINE.match(ln) and not seen_header:
                anomalies.append(("orphan-level", ln[:90]))
        if anomalies:
            report[f.name] = anomalies
        if n % 50 == 0:
            print(f"  ... {n}/{len(files)} scanned", flush=True)

    total = sum(len(v) for v in report.values())
    print(f"{len(files)} articles scanned, {len(report)} with anomalies, "
          f"{total} anomaly lines\n")
    for name, items in report.items():
        print(name)
        for kind, ln in items:
            print(f"   [{kind}] {ln}")
    Path("data/anomaly_scan.txt").write_text(
        "\n".join(f"{n}\n" + "\n".join(f"   [{k}] {l}" for k, l in v)
                  for n, v in report.items()),
        encoding="utf-8")
    print("\nfull report -> data/anomaly_scan.txt")


if __name__ == "__main__":
    main()
