"""Build a self-contained interactive HTML dashboard.

Reads the SQLite DB and writes data/dashboard.html - a single file with
inline CSS/JS and embedded JSON (no server, no CDN, works offline).

Features
--------
- KPI cards: leads, settled, target hit, SL hit, live, avg confidence
- Filter by status (achieved target / SL / live / ambiguous), analyst,
  free-text search over stock / analyst / note
- Sortable leads table with confidence bars and per-lead sparklines
- Flag / follow any lead (persisted in the browser's localStorage)
- Lead detail modal: full reasoning, byline, article link, confidence
  history from confidence_history, price closes since entry
- Analyst scorecard (canonical names) and calibration view (confidence
  bucket vs realised hit rate, built from confidence_history over time)

Usage: python build_dashboard.py
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

DB = Path("data/moneypuller.db")
OUT = Path("data/dashboard.html")


def analyst_name(raw: str | None) -> str:
    if not raw or not raw.strip():
        return "Unknown"
    return raw.split(",")[0].strip() or "Unknown"


def main() -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    leads = []
    for r in conn.execute("""
            SELECT v.rec_id AS id, a.record_date AS date, r.stock_name,
                   r.action, r.cmp, r.target_1, r.target_2, r.target_3,
                   r.stop_loss, v.status, v.entry_price, v.exit_price,
                   v.exit_level, v.exit_date, v.days_taken, v.pct,
                   v.confidence, v.note, r.reasoning, r.analyst,
                   a.title, a.url
            FROM verdicts v
            JOIN recommendations r ON r.id = v.rec_id
            JOIN articles a ON a.id = r.article_id
            WHERE a.record_date IS NOT NULL
            ORDER BY a.record_date DESC, r.stock_name"""):
        leads.append(dict(r))

    # canonical analyst + confidence history + close series
    hist = {}
    for r in conn.execute("""SELECT rec_id, as_of, confidence
            FROM confidence_history ORDER BY as_of"""):
        hist.setdefault(r["rec_id"], []).append(
            [r["as_of"], round(r["confidence"], 4)])

    sym_of = {r[0]: r[1] for r in conn.execute(
        "SELECT stock_name, yahoo_symbol FROM symbols")}
    closes: dict[str, list[tuple[str, float]]] = {}
    for sym, d, c in conn.execute(
            "SELECT symbol, date, close FROM prices WHERE close IS NOT NULL "
            "ORDER BY symbol, date"):
        closes.setdefault(sym, []).append((d, c))

    out = []
    for l in leads:
        series = []
        if l["date"]:
            pts = [(d, c) for d, c in closes.get(sym_of.get(l["stock_name"], ""), [])
                   if d >= l["date"]]
            series = [c for _, c in pts[-45:]]
        out.append({
            "id": l["id"], "d": l["date"], "s": l["stock_name"],
            "a": l["action"], "cmp": l["cmp"],
            "t1": l["target_1"], "t2": l["target_2"], "t3": l["target_3"],
            "sl": l["stop_loss"], "st": l["status"],
            "en": l["entry_price"], "ex": l["exit_price"],
            "xl": l["exit_level"], "xd": l["exit_date"],
            "dy": l["days_taken"], "pct": l["pct"], "cf": l["confidence"],
            "nt": l["note"], "an": analyst_name(l["analyst"]),
            "by": l["analyst"], "rs": (l["reasoning"] or "")[:1800],
            "ti": l["title"], "u": l["url"], "h": hist.get(l["id"], []),
            "sr": series,
        })

    # analyst scorecard
    analysts = {}
    for l in out:
        a = analysts.setdefault(l["an"], {"n": 0, "tgt": 0, "sl": 0,
                                          "live": 0, "pcts": [], "confs": []})
        a["n"] += 1
        if l["st"] == "target achieved":
            a["tgt"] += 1
            if l["pct"] is not None:
                a["pcts"].append(l["pct"])
        elif l["st"] == "SL achieved":
            a["sl"] += 1
            if l["pct"] is not None:
                a["pcts"].append(l["pct"])
        elif l["st"] == "NO HIT YET":
            a["live"] += 1
            if l["cf"] is not None:
                a["confs"].append(l["cf"])

    # calibration: confidence while live vs final outcome
    calib = []
    for r in conn.execute("""
            SELECT h.rec_id, h.confidence, v.status
            FROM confidence_history h
            JOIN verdicts v ON v.rec_id = h.rec_id
            WHERE v.status IN ('target achieved', 'SL achieved')"""):
        calib.append({"c": r["confidence"], "hit":
                      1 if r["status"] == "target achieved" else 0})

    conn.close()

    data = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "leads": out,
        "analysts": analysts,
        "calibration": calib,
    }

    html = TEMPLATE.replace("__DATA__", json.dumps(data, separators=(",", ":")))
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB, "
          f"{len(out)} leads)")


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MoneyPuller - Trade Spotlight Verdicts</title>
<style>
:root{--bg:#0e1420;--panel:#161e2e;--panel2:#1c2740;--line:#263352;--tx:#dbe4f5;
--tx2:#8ea0c0;--green:#22c55e;--red:#ef4444;--amber:#f59e0b;--blue:#3b82f6;--purple:#a78bfa}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--tx);font:14px/1.45 'Segoe UI',system-ui,sans-serif;padding:18px}
h1{font-size:20px;letter-spacing:.3px}
.sub{color:var(--tx2);font-size:12px;margin:2px 0 14px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(128px,1fr));gap:10px;margin-bottom:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.card .v{font-size:22px;font-weight:700}
.card .k{color:var(--tx2);font-size:11px;text-transform:uppercase;letter-spacing:.6px}
.card.g .v{color:var(--green)}.card.r .v{color:var(--red)}.card.b .v{color:var(--blue)}.card.p .v{color:var(--purple)}
.controls{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}
input,select,button{background:var(--panel2);border:1px solid var(--line);color:var(--tx);
border-radius:8px;padding:7px 10px;font:inherit}
input[type=search]{min-width:230px}
button{cursor:pointer}button:hover{border-color:var(--blue)}
.tabs{display:flex;gap:6px;margin-bottom:10px}
.tab{padding:7px 14px;border-radius:8px;background:var(--panel);border:1px solid var(--line);cursor:pointer;color:var(--tx2)}
.tab.on{background:var(--panel2);color:var(--tx);border-color:var(--blue)}
.tblwrap{overflow:auto;max-height:70vh;border:1px solid var(--line);border-radius:10px;background:var(--panel)}
table{border-collapse:collapse;width:100%;font-size:13px}
th{position:sticky;top:0;background:var(--panel2);padding:8px 8px;text-align:left;white-space:nowrap;
cursor:pointer;user-select:none;border-bottom:1px solid var(--line);z-index:2}
td{padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
tr:hover td{background:#1d2947}
tr.flagged td{background:#3a2f14}
.bdg{display:inline-block;padding:2px 8px;border-radius:20px;font-size:11px;font-weight:600}
.bdg.t{background:#0e3b22;color:var(--green)}.bdg.s{background:#43191b;color:var(--red)}
.bdg.l{background:#1e2c4d;color:var(--blue)}.bdg.a{background:#3d3315;color:var(--amber)}
.cbar{width:64px;height:8px;background:#243050;border-radius:4px;display:inline-block;vertical-align:middle;margin-right:6px}
.cfill{height:100%;border-radius:4px;background:linear-gradient(90deg,var(--red),var(--amber),var(--green))}
.star{cursor:pointer;font-size:15px;color:#4b5c82}.star.on{color:var(--amber)}
.pct-pos{color:var(--green)}.pct-neg{color:var(--red)}
.stock{cursor:pointer;color:var(--tx);font-weight:600}.stock:hover{color:var(--blue);text-decoration:underline}
.modal{position:fixed;inset:0;background:rgba(5,8,15,.72);display:none;align-items:flex-start;
justify-content:center;padding:40px 16px;z-index:9}
.modal.open{display:flex}
.mbox{background:var(--panel);border:1px solid var(--line);border-radius:14px;max-width:760px;width:100%;
max-height:84vh;overflow:auto;padding:20px}
.mbox h2{font-size:17px;margin-bottom:4px}
.mrow{display:flex;gap:18px;flex-wrap:wrap;color:var(--tx2);font-size:12px;margin:8px 0 12px}
.mrow b{color:var(--tx)}
.reason{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:12px;
font-size:13px;white-space:pre-wrap;line-height:1.55;margin:10px 0}
.small{color:var(--tx2);font-size:12px}
a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}
.alink{color:var(--tx2);font-weight:600;text-decoration:none;padding:2px 7px;border:1px solid var(--line);border-radius:6px;display:inline-block}.alink:hover{color:var(--blue);border-color:var(--blue)}
.kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin:10px 0}
.kv .card{padding:8px 10px}.kv .card .v{font-size:16px}
.spark{height:36px}.flag-inline{color:var(--amber);font-weight:700}
#calibTab,#anTab{display:none}
.hist{margin:8px 0}
.hbar{display:flex;align-items:center;gap:8px;margin:3px 0;font-size:12px}
.hbar .lab{width:150px;color:var(--tx2)}
.hbar .track{flex:1;background:#243050;border-radius:4px;height:14px;position:relative}
.hbar .fill{height:100%;border-radius:4px;background:var(--blue)}
.hbar .num{width:120px}
</style>
</head>
<body>
<h1>MoneyPuller &mdash; Trade Spotlight Verdicts</h1>
<div class="sub" id="gen"></div>
<div class="cards" id="cards"></div>
<div class="tabs">
  <div class="tab on" data-t="leads">Leads</div>
  <div class="tab" data-t="calib">Confidence calibration</div>
  <div class="tab" data-t="an">Analysts</div>
</div>
<div id="leadsTab">
  <div class="controls">
    <input type="search" id="q" placeholder="Search stock, analyst, note...">
    <select id="fst"><option value="">All statuses</option>
      <option value="target achieved">Target achieved</option>
      <option value="SL achieved">SL achieved</option>
      <option value="NO HIT YET">Live</option>
      <option value="AMBIG">Ambiguous</option></select>
    <select id="fan"><option value="">All analysts</option></select>
    <select id="fflag"><option value="">All leads</option>
      <option value="1">Flagged only</option></select>
    <button id="exp">Export view CSV</button>
  </div>
  <div class="tblwrap"><table id="tbl"></table></div>
  <div class="small" id="count" style="margin-top:8px"></div>
</div>
<div id="calibTab">
  <p class="small" style="margin:6px 0 12px">Each evening the confidence of every live lead is snapshotted.
  When a lead resolves, its last snapshot is compared with the outcome. Buckets fill up over time.</p>
  <div id="calibBody"></div>
</div>
<div id="anTab"><div id="anBody"></div></div>
<div class="modal" id="modal"><div class="mbox" id="mbox"></div></div>
<script>
const DATA = __DATA__;
const L = DATA.leads;
let flags = {};
try { flags = JSON.parse(localStorage.getItem('mp_flags') || '{}'); } catch(e) {}
const $ = s => document.querySelector(s);
const fmtP = v => v == null ? '-' : v.toLocaleString(undefined, {maximumFractionDigits:2});
const fmtPct = v => v == null ? '-' : (v >= 0 ? '+' : '') + (100*v).toFixed(1) + '%';
const stCls = st => st === 'target achieved' ? 't' : st === 'SL achieved' ? 's' :
  st === 'NO HIT YET' ? 'l' : 'a';
const stShort = st => st === 'target achieved' ? 'TARGET' : st === 'SL achieved' ? 'SL HIT' :
  st === 'NO HIT YET' ? 'LIVE' : st.startsWith('AMBIG') ? 'AMBIG' : st;

$('#gen').textContent = 'Generated ' + DATA.generated + ' from data/moneypuller.db — ' +
  L.length + ' dated leads. Click a stock for full detail; star it to follow.';

// KPI cards
const settled = L.filter(l => l.st === 'target achieved' || l.st === 'SL achieved');
const tgt = L.filter(l => l.st === 'target achieved').length;
const sl = L.filter(l => l.st === 'SL achieved').length;
const live = L.filter(l => l.st === 'NO HIT YET');
const pcts = settled.map(l => l.pct).filter(p => p != null);
const avgPct = pcts.length ? pcts.reduce((a,b)=>a+b,0)/pcts.length : 0;
const confs = live.map(l => l.cf).filter(c => c != null);
const avgC = confs.length ? confs.reduce((a,b)=>a+b,0)/confs.length : 0;
$('#cards').innerHTML = [
  ['Leads', L.length, ''],
  ['Settled', settled.length, ''],
  ['Target achieved', tgt, 'g'],
  ['SL hit', sl, 'r'],
  ['Win rate', (100*tgt/Math.max(settled.length,1)).toFixed(0)+'%', 'b'],
  ['Live', live.length, 'p'],
  ['Avg P&L / trade', fmtPct(avgPct), avgPct >= 0 ? 'g' : 'r'],
  ['Avg live confidence', (100*avgC).toFixed(0)+'%', 'p'],
].map(([k,v,c]) => `<div class="card ${c}"><div class="v">${v}</div><div class="k">${k}</div></div>`).join('');

// analyst dropdown
const anSet = [...new Set(L.map(l => l.an))].sort();
$('#fan').innerHTML += anSet.map(a => `<option>${a}</option>`).join('');

// sparkline svg
function spark(vals, color) {
  if (!vals || vals.length < 2) return '';
  const w = 110, h = 30, mn = Math.min(...vals), mx = Math.max(...vals);
  const rng = (mx - mn) || 1;
  const pts = vals.map((v,i) => `${(i*w/(vals.length-1)).toFixed(1)},${(h - 3 - (v-mn)/rng*(h-6)).toFixed(1)}`).join(' ');
  const last = vals[vals.length-1];
  const c = color || (last >= vals[0] ? '#22c55e' : '#ef4444');
  return `<svg class="spark" width="${w}" height="${h}"><polyline fill="none" stroke="${c}" stroke-width="1.6" points="${pts}"/></svg>`;
}

let sortKey = 'd', sortDir = -1;
function view() {
  const q = $('#q').value.toLowerCase(), fs = $('#fst').value, fa = $('#fan').value, ff = $('#fflag').value;
  let rows = L.filter(l => {
    if (fs === 'AMBIG' ? !l.st.startsWith('AMBIG') : fs && l.st !== fs) return false;
    if (fa && l.an !== fa) return false;
    if (ff === '1' && !flags[l.id]) return false;
    if (q && !((l.s||'')+' '+(l.an||'')+' '+(l.nt||'')+' '+(l.xl||'')).toLowerCase().includes(q)) return false;
    return true;
  });
  rows.sort((a,b) => {
    let x = a[sortKey], y = b[sortKey];
    if (x == null) return 1; if (y == null) return -1;
    if (typeof x === 'string') { x = x.toLowerCase(); y = (y||'').toLowerCase(); }
    return (x < y ? -1 : x > y ? 1 : 0) * sortDir;
  });
  return rows;
}

function render() {
  const rows = view();
  const cols = [['','flag'],['Date','d'],['Stock','s'],['Act','a'],['CMP','cmp'],['T1','t1'],['SL','sl'],
    ['Status','st'],['Entry','en'],['Exit','ex'],['Level','xl'],['Days','dy'],['%age','pct'],
    ['Conf','cf'],['Trend','sr'],['Analyst','an'],['Src','u'],['','id']];
  $('#tbl').innerHTML = '<thead><tr>' + cols.map(([h,k]) =>
    `<th data-k="${k}">${h}${sortKey===k?(sortDir<0?' ▾':' ▴'):''}</th>`).join('') + '</tr></thead><tbody>' +
    rows.map(l => `<tr class="${flags[l.id]?'flagged':''}">
      <td><span class="star ${flags[l.id]?'on':''}" data-id="${l.id}">${flags[l.id]?'★':'☆'}</span></td>
      <td>${l.d||''}</td>
      <td><span class="stock" data-id="${l.id}">${l.s}</span>${flags[l.id]?' <span class="flag-inline">⚑</span>':''}</td>
      <td>${l.a||'Buy'}</td><td>${fmtP(l.cmp)}</td><td>${fmtP(l.t1)}</td><td>${fmtP(l.sl)}</td>
      <td><span class="bdg ${stCls(l.st)}">${stShort(l.st)}</span></td>
      <td>${fmtP(l.en)}</td><td>${fmtP(l.ex)}</td><td>${l.xl||'-'}</td><td>${l.dy??'-'}</td>
      <td class="${(l.pct??0)>=0?'pct-pos':'pct-neg'}">${fmtPct(l.pct)}</td>
      <td>${l.cf!=null?`<span class="cbar"><span class="cfill" style="width:${(l.cf*100).toFixed(0)}%"></span></span>${(100*l.cf).toFixed(0)}%`:'-'}</td>
      <td>${spark(l.sr)}</td><td>${l.an}</td>
      <td>${l.u?`<a class="alink" href="${l.u}" target="_blank" rel="noopener" title="Open the Moneycontrol article in a new tab">MC ↗</a>`:'-'}</td>
      <td><span class="stock" data-id="${l.id}" style="color:var(--tx2)">detail</span></td>
    </tr>`).join('') + '</tbody>';
  $('#count').textContent = rows.length + ' of ' + L.length + ' leads shown · ' +
    Object.keys(flags).length + ' flagged';
  document.querySelectorAll('th[data-k]').forEach(th => th.onclick = () => {
    if (sortKey === th.dataset.k) sortDir *= -1; else { sortKey = th.dataset.k; sortDir = -1; }
    render();
  });
  document.querySelectorAll('.star').forEach(el => el.onclick = () => {
    const id = el.dataset.id;
    if (flags[id]) delete flags[id]; else flags[id] = 1;
    localStorage.setItem('mp_flags', JSON.stringify(flags));
    render();
  });
  document.querySelectorAll('.stock[data-id]').forEach(el => el.onclick = () => openModal(+el.dataset.id));
}

// modal
function openModal(id) {
  const l = L.find(x => x.id === id); if (!l) return;
  const hist = (l.h||[]).map(([d,c]) =>
    `<div class="hbar"><span class="lab">${d}</span><span class="track"><span class="fill" style="width:${(c*100).toFixed(0)}%"></span></span><span class="num">${(100*c).toFixed(0)}%</span></div>`).join('')
    || '<span class="small">no snapshots yet</span>';
  $('#mbox').innerHTML = `<h2>${l.s} <span class="bdg ${stCls(l.st)}">${stShort(l.st)}</span>
    ${flags[l.id]?'<span class="flag-inline">⚑ flagged</span>':''}</h2>
    <div class="small">${l.ti||''}</div>
    <div class="mrow">
      <span>Date <b>${l.d||'-'}</b></span><span>Action <b>${l.a||'Buy'}</b></span>
      <span>CMP <b>${fmtP(l.cmp)}</b></span><span>Entry <b>${fmtP(l.en)}</b></span>
      <span>Exit <b>${fmtP(l.ex)} (${l.xl||'-'})</b></span><span>Days <b>${l.dy??'-'}</b></span>
      <span>%age <b>${fmtPct(l.pct)}</b></span>
      <span>Confidence <b>${l.cf!=null?(100*l.cf).toFixed(0)+'%':'-'}</b></span>
    </div>
    <div class="mrow">
      <span>T1 <b>${fmtP(l.t1)}</b></span><span>T2 <b>${fmtP(l.t2||'-')}</b></span>
      <span>T3 <b>${fmtP(l.t3||'-')}</b></span><span>SL <b>${fmtP(l.sl)}</b></span>
      <span>Analyst <b>${l.an}</b></span>
    </div>
    ${l.nt?`<div class="small">Note: ${l.nt}</div>`:''}
    ${l.sr&&l.sr.length>1?`<div style="margin:10px 0">${spark(l.sr.map((c,i)=>c), l.sr[l.sr.length-1]>=l.en?'#22c55e':'#ef4444')}<span class="small"> closes since entry (max 45 sessions, last ${l.sr[l.sr.length-1]})</span></div>`:''}
    <h2 style="font-size:14px;margin-top:12px">Confidence history</h2>${hist}
    <h2 style="font-size:14px;margin-top:12px">Analyst byline</h2><div class="small">${l.by||'-'}</div>
    <h2 style="font-size:14px;margin-top:12px">Reasoning</h2><div class="reason">${l.rs||'-'}</div>
    <p style="margin-top:10px"><a href="${l.u}" target="_blank" rel="noopener">Open the Moneycontrol article ↗</a></p>`;
  $('#modal').classList.add('open');
}
$('#modal').onclick = e => { if (e.target.id === 'modal') $('#modal').classList.remove('open'); };

// tabs
document.querySelectorAll('.tab').forEach(t => t.onclick = () => {
  document.querySelectorAll('.tab').forEach(x => x.classList.remove('on'));
  t.classList.add('on');
  ['leads','calib','an'].forEach(k => $('#' + k + 'Tab').style.display = t.dataset.t === k ? '' : 'none');
  if (t.dataset.t === 'calib') renderCalib();
  if (t.dataset.t === 'an') renderAnalysts();
});

function renderCalib() {
  const buckets = {'<35%':[0,.35],'35-45%':[.35,.45],'45-55%':[.45,.55],'55-65%':[.55,.65],'65%+':[.65,1.01]};
  let html = '';
  for (const [k, [lo,hi]] of Object.entries(buckets)) {
    const sub = DATA.calibration.filter(c => c.c >= lo && c.c < hi);
    const hits = sub.filter(c => c.hit).length;
    const w = sub.length ? (100*hits/sub.length).toFixed(0) : 0;
    html += `<div class="hbar"><span class="lab">${k}</span>
      <span class="track"><span class="fill" style="width:${w}%;background:${w>=50?'var(--green)':w>=35?'var(--amber)':'var(--red)'}"></span></span>
      <span class="num">${hits}/${sub.length} hit (${w}%)</span></div>`;
  }
  $('#calibBody').innerHTML = html + `<p class="small" style="margin-top:10px">
    ${DATA.calibration.length} resolved leads have at least one confidence snapshot. The history grows daily;
    well-calibrated buckets show hit rate close to the bucket range.</p>`;
}

function renderAnalysts() {
  const rows = Object.entries(DATA.analysts).map(([a, v]) => {
    const settled = v.tgt + v.sl;
    const rate = settled ? 100*v.tgt/settled : 0;
    const avg = v.pcts.length ? v.pcts.reduce((x,y)=>x+y,0)/v.pcts.length : 0;
    const conf = v.confs.length ? v.confs.reduce((x,y)=>x+y,0)/v.confs.length : null;
    return {a, n: v.n, settled, rate, avg, live: v.live, conf};
  }).sort((x,y) => y.rate - x.rate);
  $('#anBody').innerHTML = `<div class="tblwrap"><table>
    <thead><tr><th>Analyst</th><th>Leads</th><th>Settled</th><th>Win rate</th>
    <th>Avg P&L</th><th>Live</th><th>Avg live conf</th></tr></thead><tbody>` +
    rows.map(r => `<tr><td>${r.a}</td><td>${r.n}</td><td>${r.settled}</td>
      <td class="${r.rate>=40?'pct-pos':r.rate<33?'pct-neg':''}">${r.rate.toFixed(0)}%</td>
      <td class="${r.avg>=0?'pct-pos':'pct-neg'}">${fmtPct(r.avg)}</td>
      <td>${r.live}</td><td>${r.conf!=null?(100*r.conf).toFixed(0)+'%':'-'}</td></tr>`).join('') +
    '</tbody></table></div>';
}

// csv export of current view
$('#exp').onclick = () => {
  const rows = view();
  const head = 'date,stock,action,cmp,t1,t2,t3,sl,status,entry,exit,exit_level,exit_date,days,pct,confidence,analyst,flagged,article_url';
  const lines = rows.map(l => [l.d,l.s,l.a,l.cmp,l.t1,l.t2,l.t3,l.sl,stShort(l.st),
    l.en,l.ex,l.xl,l.xd,l.dy,l.pct,l.cf,l.an,flags[l.id]?1:0,l.u||''].join(','));
  const blob = new Blob([head + '\\n' + lines.join('\\n')], {type:'text/csv'});
  const aEl = document.createElement('a');
  aEl.href = URL.createObjectURL(blob);
  aEl.download = 'moneypuller_view.csv';
  aEl.click();
};

['q','fst','fan','fflag'].forEach(id => { $('#' + id).oninput = render; $('#' + id).onchange = render; });
render();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
