/* Stock Radar PWA — vanilla JS, no dependencies. Data comes from data/*.json written by the daily job:
   {us,il}.json (scan results), status.json, track_record.json and, when present, {us,il}_history.json
   (one year of daily closes for charts). Everything shown is real data; nothing is simulated. */
"use strict";

const SCREENS = ["home", "markets", "watch", "perf", "settings"];
const STATE = {
  us: null, il: null, status: null, track: null, hist: { us: null, il: null }, loaded: false,
  screen: "home", market: "us", hero: { us: null, il: null }, range: "6m", detailRange: "6m",
  movers: "gainers", query: "", filter: "ideas", sort: "score", watchSort: "change", detail: null, sheet: null,
};

const LABEL_HE = { research_buy: "בדיקה לקנייה", watch: "מעקב" };
const CONF_HE = { low: "ביטחון נמוך", medium: "ביטחון בינוני", high: "ביטחון גבוה" };
const MODE_HE = { positive: "שוק חיובי", cautious: "שוק זהיר", negative: "שוק שלילי" };
const MARKET_HE = { us: "ארה״ב", il: "ישראל" };
const STATUS_HE = { pending: "ממתין לכניסה", not_triggered: "לא הופעל", open: "פתוח", target: "הגיע ליעד",
  stopped: "נעצר בסטופ", expired: "פג תוקף" };
/* US "indices" are tracked through their ETFs, so the value shown is the ETF price, not index points. */
const INDEX_META = {
  SPY: { he: "S&P 500", sub: "תעודת סל SPY", unit: "$" },
  QQQ: { he: "Nasdaq-100", sub: "תעודת סל QQQ", unit: "$" },
  DIA: { he: "דאו ג׳ונס", sub: "תעודת סל DIA", unit: "$" },
  IWM: { he: "ראסל 2000", sub: "תעודת סל IWM", unit: "$" },
  "^TA125.TA": { he: "ת״א-125", sub: "נקודות מדד", unit: "" },
  "TA35.TA": { he: "ת״א-35", sub: "נקודות מדד", unit: "" },
};
const RANGES = [["1w", "שבוע", 5], ["1m", "חודש", 21], ["3m", "3 ח׳", 63], ["6m", "6 ח׳", 126], ["1y", "שנה", 252]];
const RANGE_LONG = { "1w": "בשבוע", "1m": "בחודש", "3m": "ב-3 חודשים", "6m": "ב-6 חודשים", "1y": "בשנה" };
const SORTS = { score: "ציון", change: "שינוי יומי", price: "מחיר", turnover: "מחזור כספי", symbol: "סימול" };
/* Regular trading hours (local minutes). Holidays are not known here, so the status says "regular hours". */
const SESSIONS = {
  us: { tz: "America/New_York", open: 570, close: 960, days: { Mon: 1, Tue: 1, Wed: 1, Thu: 1, Fri: 1 } },
  il: { tz: "Asia/Jerusalem", open: 599, close: 1050, closeFri: 830, days: { Mon: 1, Tue: 1, Wed: 1, Thu: 1, Fri: 1 } },
};
const POINTS_HE = {
  close_above_sma50: "מחיר מעל ממוצע 50", sma50_above_sma200: "ממוצע 50 מעל ממוצע 200",
  close_above_sma200: "מחיר מעל ממוצע 200", sma50_rising_10d: "ממוצע 50 עולה",
  rsi_in_range: "RSI בין 45 ל-70", macd_above_signal: "MACD מעל קו האות", macd_hist_rising: "היסטוגרמת MACD עולה",
  volume_strong_up_day: "יום עלייה במחזור גבוה", volume_mild_up_day: "יום עלייה במחזור רגיל",
  relative_strength: "חוזק יחסי מול המדד", near_52w_high: "קרבה לשיא 52 שבועות",
  penalty_rsi_overbought: "קנס: RSI מעל 78", penalty_extended_above_sma50: "קנס: מעל 15% מממוצע 50",
};

/* ---------------------------------------------------------------- helpers */
const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ltr = (s) => `<span class="ltr num">${esc(s)}</span>`;
const isNum = (v) => typeof v === "number" && Number.isFinite(v);

function cur(row) { return row && row.currency === "ILS" ? "₪" : "$"; }
function fmtNum(v, d = 2) {
  if (!isNum(v)) return "—";
  return v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}
function fmtPrice(v, c) { return isNum(v) ? ltr(`${c}${fmtNum(v, v >= 1000 ? 1 : 2)}`) : "—"; }
function fmtPct(v, d = 1, sign = true) {
  if (!isNum(v)) return "—";
  const p = v * 100;
  return ltr(`${sign && p > 0 ? "+" : ""}${p.toFixed(d)}%`);
}
const compactFmt = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
function fmtCompact(v, prefix = "") { return isNum(v) ? ltr(prefix + compactFmt.format(v)) : "—"; }
function fmtDate(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${Number(d)}/${Number(m)}/${y}`;
}
function fmtDateTime(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("he-IL", { timeZone: "Asia/Jerusalem", day: "numeric", month: "numeric",
      hour: "2-digit", minute: "2-digit" });
  } catch { return iso; }
}
function tone(v) { return isNum(v) ? (v >= 0 ? "up" : "down") : ""; }
function changeHtml(chg, d = 2) { return isNum(chg) ? `<span class="chg ${tone(chg)}">${fmtPct(chg, d)}</span>` : ""; }

const store = {
  get(key, fallback) { try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode */ } },
};
const starKey = (market, sym) => `${market}:${sym}`;
function starred() { return new Set(store.get("starred", [])); }
function isStarred(market, sym) { return starred().has(starKey(market, sym)); }
function toggleStar(market, sym) {
  const s = starred(); const k = starKey(market, sym);
  s.has(k) ? s.delete(k) : s.add(k);
  store.set("starred", [...s]);
}

async function loadJSON(name, tries = 2) {
  try {
    const r = await fetch(`data/${name}.json`, { cache: "no-cache" });
    if (!r.ok) return null;
    return await r.json();
  } catch {
    // A flaky connection (or the service worker starting up) can drop one request; try once more.
    if (tries > 1) { await new Promise((res) => setTimeout(res, 800)); return loadJSON(name, tries - 1); }
    return null;
  }
}

/* ---------------------------------------------------------------- market data access */
function indexEntries(data) {
  if (!data) return [];
  const all = { ...(data.benchmarks || {}), ...(data.indices || {}) };
  return Object.entries(all).filter(([, v]) => v && isNum(v.close));
}
function histSeries(market, key) {
  const h = STATE.hist[market];
  const vals = h?.closes?.[key];
  if (!Array.isArray(vals) || !Array.isArray(h.dates)) return null;
  const out = { values: [], dates: [] };
  vals.forEach((v, i) => { if (isNum(v)) { out.values.push(v); out.dates.push(h.dates[i]); } });
  return out.values.length > 1 ? out : null;
}
function sliceRange(series, key) {
  const n = (RANGES.find((r) => r[0] === key) || RANGES[3])[2] + 1;
  return { values: series.values.slice(-n), dates: series.dates ? series.dates.slice(-n) : null };
}
function sparkValues(row, market) {
  if (Array.isArray(row.sparkline) && row.sparkline.length > 1) return row.sparkline;
  const s = histSeries(market, row.symbol);
  return s ? s.values.slice(-30) : null;
}
function picks(data, n) {
  if (!data) return [];
  return data.stocks.filter((r) => r.selected && r.label && r.levels).slice(0, n);
}
function live(data) { return (data?.stocks || []).filter((r) => r.indicators && !r.stale_since); }

function marketOpen(m) {
  const s = SESSIONS[m];
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-US", { timeZone: s.tz, weekday: "short", hour: "2-digit",
    minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date()).map((p) => [p.type, p.value]));
  if (!s.days[parts.weekday]) return false;
  const min = Number(parts.hour) * 60 + Number(parts.minute);
  const close = parts.weekday === "Fri" && s.closeFri ? s.closeFri : s.close;
  return min >= s.open && min < close;
}

/* ---------------------------------------------------------------- charts */
const CHARTS = new Map(); let chartSeq = 0;

function sparkSvg(values, cls = "spark") {
  if (!Array.isArray(values) || values.length < 2) return "";
  const W = 100, H = 32, pad = 3;
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
  const d = values.map((v, i) => `${i ? "L" : "M"}${((i / (values.length - 1)) * W).toFixed(2)},${(pad + (1 - (v - min) / span) * (H - 2 * pad)).toFixed(2)}`).join("");
  const dir = values[values.length - 1] >= values[0] ? "up" : "down";
  return `<svg class="${cls} ${dir}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true"><path d="${d}" vector-effect="non-scaling-stroke"/></svg>`;
}

function chartHtml(series, unit, h = 180) {
  if (!series || series.values.length < 2) return "";
  const { values, dates } = series; const n = values.length;
  const W = 600, pad = 12;
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
  const X = (i) => (i / (n - 1)) * W;
  const Y = (v) => pad + (1 - (v - min) / span) * (h - 2 * pad);
  const d = values.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(2)},${Y(v).toFixed(2)}`).join("");
  const dir = values[n - 1] >= values[0] ? "up" : "down";
  const id = `c${++chartSeq}`;
  CHARTS.set(id, { values, dates, min, span, pad, h, unit });
  const first = dates?.[0] ? fmtDate(dates[0]) : "", last = dates?.[n - 1] ? fmtDate(dates[n - 1]) : "";
  return `<div class="chart ${dir}" data-chart="${id}" style="height:${h}px" role="img"
      aria-label="גרף מחיר${first ? ` מ-${first} עד ${last}` : ""}">
    <svg viewBox="0 0 ${W} ${h}" preserveAspectRatio="none" aria-hidden="true">
      <defs><linearGradient id="g${id}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="currentColor" stop-opacity=".24"/><stop offset="1" stop-color="currentColor" stop-opacity="0"/>
      </linearGradient></defs>
      <line class="base" x1="0" x2="${W}" y1="${Y(values[0]).toFixed(2)}" y2="${Y(values[0]).toFixed(2)}" vector-effect="non-scaling-stroke"/>
      <path class="area" d="${d}L${W},${h}L0,${h}Z" fill="url(#g${id})"/>
      <path class="line" d="${d}" vector-effect="non-scaling-stroke"/>
    </svg>
    <div class="chart-cursor" hidden></div><div class="chart-dot" hidden></div><div class="chart-tip" hidden></div>
    ${first ? `<div class="chart-axis"><span>${first}</span><span>${last}</span></div>` : ""}
  </div>`;
}

function scrub(el, clientX) {
  const c = CHARTS.get(el.dataset.chart);
  if (!c) return;
  const r = el.getBoundingClientRect(); const n = c.values.length;
  const ratio = Math.min(1, Math.max(0, (clientX - r.left) / r.width));
  const i = Math.round(ratio * (n - 1)); const v = c.values[i];
  const x = (i / (n - 1)) * 100;
  const y = ((c.pad + (1 - (v - c.min) / c.span) * (c.h - 2 * c.pad)) / c.h) * 100;
  const [cursor, dot, tip] = [".chart-cursor", ".chart-dot", ".chart-tip"].map((s) => el.querySelector(s));
  cursor.hidden = dot.hidden = tip.hidden = false;
  cursor.style.left = dot.style.left = `${x}%`;
  dot.style.top = `${y}%`;
  const chg = v / c.values[0] - 1;
  tip.innerHTML = `<b>${ltr(c.unit + fmtNum(v))}</b><span class="chg ${tone(chg)}">${fmtPct(chg, 1)}</span>${c.dates ? `<span>${fmtDate(c.dates[i])}</span>` : ""}`;
  tip.style.left = `${Math.min(80, Math.max(20, x))}%`;
}
function unscrub(el) { el.querySelectorAll(".chart-cursor, .chart-dot, .chart-tip").forEach((x) => { x.hidden = true; }); }

/* ---------------------------------------------------------------- shared pieces */
function segmented(name, options, value, extra = "") {
  return `<div class="seg ${extra}" role="group">${options.map(([k, t]) =>
    `<button class="${k === value ? "on" : ""}" data-action="seg" data-seg="${name}" data-val="${k}" aria-pressed="${k === value}">${t}</button>`).join("")}</div>`;
}

const STAR_PATH = "M12 3.5l2.6 5.3 5.9.9-4.2 4.1 1 5.8L12 16.9l-5.3 2.7 1-5.8-4.2-4.1 5.9-.9z";
function starBtn(market, sym) {
  const on = isStarred(market, sym);
  return `<button class="star ${on ? "on" : ""}" data-action="star" data-market="${market}" data-symbol="${esc(sym)}"
    aria-label="${on ? "הסרה מהרשימה שלי" : "הוספה לרשימה שלי"}" aria-pressed="${on}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="${STAR_PATH}"/></svg></button>`;
}

function chips(row) {
  const out = [];
  if (isNum(row.score)) out.push(`<span class="chip score">${ltr(Math.round(row.score))}</span>`);
  if (row.label) out.push(`<span class="chip ${esc(row.label.key)}">${esc(LABEL_HE[row.label.key] || row.label.he)}</span>`);
  const ai = row.ai || {};
  if (ai.available && ai.confidence) out.push(`<span class="chip conf-${esc(ai.confidence)}">${CONF_HE[ai.confidence]}</span>`);
  if (row.stale_since) out.push(`<span class="chip stale">לא עודכן מאז ${fmtDate(row.stale_since)}</span>`);
  if (row.watchlist) out.push(`<span class="chip">רשימת מעקב</span>`);
  return out.length ? `<div class="chips">${out.join("")}</div>` : "";
}

function dropHe(reason) {
  if (/52-week high/.test(reason)) return "שיא 52 שבועות קרוב מדי מעל הכניסה";
  if (/too wide/.test(reason)) return "הסטופ רחוק מדי";
  return reason;
}

function levelsBlock(row) {
  const lv = row.levels; const c = cur(row);
  if (!lv) return row.drop_reason ? `<p class="note">ללא רמות: ${esc(dropHe(row.drop_reason))}</p>` : "";
  return `<div class="levels">
    <div class="level"><span class="k">אזור כניסה</span><span class="v">${ltr(`${c}${fmtNum(lv.entry_low)}–${fmtNum(lv.entry_high)}`)}</span></div>
    <div class="level stop"><span class="k">סטופ</span><span class="v">${fmtPrice(lv.stop, c)}</span></div>
    <div class="level target"><span class="k">יעד</span><span class="v">${fmtPrice(lv.target, c)}</span></div>
  </div>`;
}

function ideaCard(row, market) {
  const i = row.indicators || {}; const ai = row.ai || {};
  const summary = ai.available ? `<p class="summary">${esc(ai.summary_he)}</p>`
    : `<p class="summary noai">${esc(ai.note || "ללא ניתוח AI")}</p>`;
  return `<article class="card glass" data-action="detail" data-market="${market}" data-symbol="${esc(row.symbol)}" role="button" tabindex="0">
    <div class="card-top">
      <div class="ident"><div class="ticker ltr">${esc(row.symbol)}</div><div class="name">${esc(row.name_he || row.name || "")}</div></div>
      ${sparkSvg(sparkValues(row, market), "spark card-spark")}
      <div class="price"><div class="last">${fmtPrice(i.close, cur(row))}</div>${changeHtml(i.change_pct)}</div>
    </div>
    ${chips(row)}
    ${levelsBlock(row)}
    ${summary}
  </article>`;
}

function listRow(row, market, { rank = false, star = true } = {}) {
  const i = row.indicators || {};
  const stale = row.stale_since ? ` · <span class="chg down">לא עודכן מאז ${fmtDate(row.stale_since)}</span>` : "";
  return `<div class="row" data-action="detail" data-market="${market}" data-symbol="${esc(row.symbol)}" role="button" tabindex="0">
    ${rank ? `<span class="rank">${row.rank ? ltr(row.rank) : ""}</span>` : ""}
    <div class="ident">
      <div class="ticker"><span class="ltr">${esc(row.symbol)}</span>${row.label ? ` <span class="chip mini ${esc(row.label.key)}">${esc(LABEL_HE[row.label.key])}</span>` : ""}</div>
      <div class="name">${esc(row.name_he || row.name || "")}${stale}</div>
    </div>
    ${sparkSvg(sparkValues(row, market), "spark row-spark")}
    <div class="price"><div class="last">${fmtPrice(i.close, cur(row))}</div>${changeHtml(i.change_pct)}</div>
    ${isNum(row.score) ? `<span class="score-pill">${ltr(Math.round(row.score))}</span>` : `<span class="score-pill empty" title="${esc(row.gate || row.error || "")}">—</span>`}
    ${star ? starBtn(market, row.symbol) : ""}
  </div>`;
}

function banners() {
  const out = [];
  const st = STATE.status || {};
  for (const m of ["us", "il"]) {
    if (st[m] && st[m].ok === false) {
      out.push(`<div class="banner danger"><strong>${MARKET_HE[m]}: העדכון האחרון נכשל</strong>${esc(st[m].message || "")} · ${fmtDateTime(st[m].checked_at)}</div>`);
    }
  }
  const negative = ["us", "il"].filter((m) => STATE[m]?.brief?.caution_banner);
  if (negative.length) {
    const names = negative.map((m) => MARKET_HE[m]).join(" ו");
    out.push(`<div class="banner warn"><strong>זהירות: מצב שוק שלילי ב${names}</strong>המדדים מתחת לממוצעים הנעים 50 ו-200. רמת הביטחון של הרעיונות הורדה אוטומטית.</div>`);
  }
  for (const m of ["us", "il"]) {
    const d = STATE[m];
    if (d?.generated_at && (Date.now() - new Date(d.generated_at)) > 4 * 864e5) {
      out.push(`<div class="banner warn"><strong>הנתונים של ${MARKET_HE[m]} ישנים</strong>עודכנו לאחרונה ב-${fmtDateTime(d.generated_at)}.</div>`);
    }
  }
  return out.join("");
}

function statusStrip() {
  return `<div class="status-strip">${["us", "il"].map((m) => {
    const open = marketOpen(m);
    return `<span class="mstat ${open ? "open" : ""}"><i aria-hidden="true"></i>${MARKET_HE[m]} · ${open ? "המסחר פתוח" : "המסחר סגור"}</span>`;
  }).join("")}</div>`;
}

function modePill(data) {
  const b = data?.brief || {}; const mode = b.risk_mode;
  return mode ? `<span class="mode ${esc(mode)}">${esc(b.risk_mode_he || MODE_HE[mode])}</span>` : "";
}

function briefText(data) {
  const b = data?.brief || {};
  if (!b.text_he) return `<p class="note">ללא ניתוח AI לסיכום השוק היום.</p>`;
  return `<div class="brief"><p class="clamp" data-action="more">${esc(b.text_he)}</p>
    <button class="link" data-action="more">המשך קריאה</button></div>`;
}

function smaLine(snap) {
  if (!snap) return "";
  const pos = (above, n) => `<span class="pos ${above ? "up" : "down"}">${above ? "מעל" : "מתחת ל"}ממוצע ${n}</span>`;
  return `<div class="sma-line">${pos(snap.above_sma50, 50)}${pos(snap.above_sma200, 200)}</div>`;
}

function sectionTitle(text, extra = "") { return `<div class="section-title"><h3>${text}</h3>${extra}</div>`; }

/* ---------------------------------------------------------------- screens */
function skeleton() {
  return `<div class="skel" style="height:22px;width:55%;margin:6px 0 14px"></div>
    <div class="skel" style="height:330px"></div>
    <div class="skel" style="height:24px;width:40%;margin:22px 0 12px"></div>
    <div class="skel" style="height:150px;margin-bottom:12px"></div><div class="skel" style="height:150px"></div>`;
}

function heroCard() {
  const m = STATE.market; const data = STATE[m];
  const head = `<div class="hero-head">${segmented("market", [["us", "ארה״ב"], ["il", "ישראל"]], m)}${modePill(data)}</div>`;
  const idx = indexEntries(data);
  if (!idx.length) return `<section class="glass hero">${head}<div class="empty">אין עדיין נתונים לשוק הזה.</div></section>`;
  const key = idx.some(([k]) => k === STATE.hero[m]) ? STATE.hero[m] : idx[0][0];
  const snap = Object.fromEntries(idx)[key];
  const meta = INDEX_META[key] || { he: key, sub: "", unit: "" };
  const series = histSeries(m, key);
  const sliced = series && sliceRange(series, STATE.range);
  const rangeChg = sliced ? sliced.values[sliced.values.length - 1] / sliced.values[0] - 1 : null;
  const tabs = idx.length > 1 ? `<div class="index-tabs">${idx.map(([k]) =>
    `<button class="${k === key ? "on" : ""}" data-action="hero" data-key="${esc(k)}">${esc((INDEX_META[k] || { he: k }).he)}</button>`).join("")}</div>` : "";
  return `<section class="glass hero">
    ${head}
    ${tabs}
    <div class="hero-value">
      <div class="hero-name">${esc(meta.he)} <span>${esc(meta.sub)} · נתוני ${fmtDate(snap.date || data.as_of)}</span></div>
      <div class="big">${ltr(meta.unit + fmtNum(snap.close))}</div>
      <div class="hero-sub">${changeHtml(snap.change_pct)} <span class="muted">היום</span>
        ${isNum(rangeChg) ? `<span class="dot-sep"></span>${changeHtml(rangeChg, 1)} <span class="muted">${RANGE_LONG[STATE.range]}</span>` : ""}</div>
    </div>
    ${sliced ? chartHtml(sliced, meta.unit, 190) + segmented("range", RANGES.map((r) => [r[0], r[1]]), STATE.range, "full")
      : `<p class="note">גרף היסטורי של המדד יופיע אחרי העדכון הלילי הבא.</p>`}
    ${smaLine(snap)}
    ${briefText(data)}
  </section>`;
}

function renderHome() {
  const el = $("#screen-home");
  if (!STATE.loaded) { el.innerHTML = skeleton(); return; }
  const us = picks(STATE.us, 5), il = picks(STATE.il, 3);
  const block = (rows, m) => (rows.length ? `<div class="grid">${rows.map((r) => ideaCard(r, m)).join("")}</div>`
    : `<div class="empty glass">אין היום רעיונות ב${MARKET_HE[m]} שעברו את הסינון.</div>`);
  el.innerHTML = `
    ${statusStrip()}
    ${banners()}
    ${heroCard()}
    ${sectionTitle("רעיונות מובילים · ארה״ב", `<button class="link" data-action="tab" data-screen="markets" data-market="us">לכל הדירוג</button>`)}
    ${block(us, "us")}
    ${sectionTitle("רעיונות מובילים · ישראל", `<button class="link" data-action="tab" data-screen="markets" data-market="il">לכל הדירוג</button>`)}
    ${block(il, "il")}`;
}

function breadthBlock(data) {
  const b = data?.brief?.breadth;
  if (!b) return "";
  const meter = (label, v) => `<div class="meter-row"><span>${label}</span><div class="meter"><i style="width:${Math.round((v || 0) * 100)}%"></i></div>${ltr(Math.round((v || 0) * 100) + "%")}</div>`;
  return `<section class="glass pad">
    <div class="panel-head"><h4>רוחב השוק</h4><span class="muted">${ltr(b.count)} מניות</span></div>
    ${meter("עלו היום", b.pct_up_today)}${meter("מעל ממוצע 50", b.pct_above_sma50)}${meter("מעל ממוצע 200", b.pct_above_sma200)}
  </section>`;
}

function indexTiles(m, data) {
  const idx = indexEntries(data);
  if (!idx.length) return "";
  return `<div class="tiles">${idx.map(([k, v]) => {
    const meta = INDEX_META[k] || { he: k, unit: "" };
    const s = histSeries(m, k);
    return `<button class="tile glass" data-action="hero" data-key="${esc(k)}" data-goto="home">
      <div class="tile-name">${esc(meta.he)}</div>
      <div class="tile-val">${ltr(meta.unit + fmtNum(v.close))}</div>
      ${changeHtml(v.change_pct)}
      ${s ? sparkSvg(s.values.slice(-63), "spark tile-spark") : ""}
    </button>`;
  }).join("")}</div>`;
}

function moversBlock(m, data) {
  const rows = live(data).filter((r) => isNum(r.indicators.change_pct));
  if (!rows.length) return "";
  const turnover = (r) => (r.indicators.volume || 0) * (r.indicators.close || 0);
  const sorted = {
    gainers: [...rows].sort((a, b) => b.indicators.change_pct - a.indicators.change_pct),
    losers: [...rows].sort((a, b) => a.indicators.change_pct - b.indicators.change_pct),
    active: [...rows].sort((a, b) => turnover(b) - turnover(a)),
  }[STATE.movers].slice(0, 5);
  return `<section class="glass pad flush">
    <div class="panel-head"><h4>התנועות של היום</h4>${segmented("movers", [["gainers", "עליות"], ["losers", "ירידות"], ["active", "הכי פעילות"]], STATE.movers, "small")}</div>
    <div class="rows">${sorted.map((r) => listRow(r, m, { star: false })).join("")}</div>
  </section>`;
}

function rankRows(m) {
  const data = STATE[m];
  const q = STATE.query.trim().toLowerCase();
  let rows = data.stocks;
  if (STATE.filter === "ideas") rows = rows.filter((r) => r.label);
  if (STATE.filter === "scored") rows = rows.filter((r) => isNum(r.score));
  if (q) rows = rows.filter((r) => [r.symbol, r.name, r.name_he].some((x) => (x || "").toLowerCase().includes(q)));
  const val = {
    score: (r) => (isNum(r.score) ? r.score : -1e9),
    change: (r) => (isNum(r.indicators?.change_pct) ? r.indicators.change_pct : -1e9),
    price: (r) => (isNum(r.indicators?.close) ? r.indicators.close : -1e9),
    turnover: (r) => (r.indicators?.volume || 0) * (r.indicators?.close || 0),
  }[STATE.sort];
  rows = STATE.sort === "symbol" ? [...rows].sort((a, b) => a.symbol.localeCompare(b.symbol))
    : [...rows].sort((a, b) => val(b) - val(a));
  return rows;
}

function renderRankList() {
  const m = STATE.market; const el = $("#rank-list");
  if (!el || !STATE[m]) return;
  const rows = rankRows(m); const st = STATE[m].stats;
  $("#rank-count").innerHTML = `${ltr(rows.length)} מניות · נסרקו ${ltr(st.fetched)}/${ltr(st.universe)}${st.failed.length ? ` · נכשלו ${ltr(st.failed.length)}` : ""}`;
  el.innerHTML = rows.length ? rows.map((r) => listRow(r, m, { rank: true })).join("") : `<div class="empty">לא נמצאו מניות.</div>`;
}

function sortSelect(name, value, keys) {
  return `<label class="select-wrap"><span class="sr">מיון</span><select class="select" data-select="${name}">
    ${keys.map((k) => `<option value="${k}" ${k === value ? "selected" : ""}>מיון: ${SORTS[k]}</option>`).join("")}</select></label>`;
}

function renderMarkets() {
  const el = $("#screen-markets");
  if (!STATE.loaded) { el.innerHTML = skeleton(); return; }
  const m = STATE.market; const data = STATE[m];
  const head = `<div class="screen-head"><h2 class="large-title">שווקים</h2>${segmented("market", [["us", "ארה״ב"], ["il", "ישראל"]], m)}</div>`;
  if (!data) { el.innerHTML = `${head}<div class="empty glass">אין עדיין נתונים לשוק הזה.</div>`; return; }
  const top = picks(data, m === "us" ? 12 : 6);
  el.innerHTML = `
    ${head}
    <div class="market-meta">${modePill(data)}<span class="muted">נתוני ${fmtDate(data.as_of)}</span></div>
    ${indexTiles(m, data)}
    <div class="cols">${breadthBlock(data)}${moversBlock(m, data)}</div>
    ${top.length ? `${sectionTitle("הנבחרות להיום")}<div class="grid">${top.map((r) => ideaCard(r, m)).join("")}</div>` : ""}
    ${sectionTitle("דירוג מלא", sortSelect("sort", STATE.sort, ["score", "change", "price", "turnover", "symbol"]))}
    <input class="search" type="search" inputmode="search" placeholder="חיפוש לפי סימול או שם" value="${esc(STATE.query)}" data-input="rank" aria-label="חיפוש בדירוג">
    ${segmented("filter", [["ideas", "רעיונות"], ["scored", "כל המדורגות"], ["all", "הכול"]], STATE.filter)}
    <div class="count" id="rank-count"></div>
    <div class="glass flush rows" id="rank-list"></div>`;
  renderRankList();
}

function renderWatch() {
  const el = $("#screen-watch");
  const s = starred();
  const mine = [];
  for (const m of ["us", "il"]) for (const r of STATE[m]?.stocks || []) if (s.has(starKey(m, r.symbol))) mine.push([r, m]);
  const key = {
    change: ([r]) => (isNum(r.indicators?.change_pct) ? r.indicators.change_pct : -1e9),
    score: ([r]) => (isNum(r.score) ? r.score : -1e9),
    price: ([r]) => (isNum(r.indicators?.close) ? r.indicators.close : -1e9),
  }[STATE.watchSort];
  if (STATE.watchSort === "symbol") mine.sort((a, b) => a[0].symbol.localeCompare(b[0].symbol));
  else mine.sort((a, b) => key(b) - key(a));
  el.innerHTML = `
    <div class="screen-head"><h2 class="large-title">הרשימה שלי</h2>
      <button class="btn" data-action="search"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>הוספת מניה</button></div>
    ${mine.length ? `<div class="list-tools"><span class="count">${ltr(mine.length)} מניות</span>${sortSelect("watchSort", STATE.watchSort, ["change", "score", "price", "symbol"])}</div>
      <div class="glass flush rows">${mine.map(([r, m]) => listRow(r, m)).join("")}</div>`
    : `<div class="empty glass empty-big">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="${STAR_PATH}"/></svg>
        <strong>הרשימה ריקה</strong>
        <span>חפשו מניה והקישו על הכוכב כדי לעקוב אחריה כאן. הרשימה נשמרת במכשיר הזה בלבד.</span>
        <button class="btn" data-action="search">חיפוש מניה</button></div>`}`;
}

function renderPerf() {
  const el = $("#screen-perf");
  const t = STATE.track; const sum = t?.summary?.all;
  let body = `<div class="empty glass">התיעוד יתחיל להצטבר אחרי ההרצה הראשונה.</div>`;
  if (sum) {
    const pct = (v) => (isNum(v) ? fmtPct(v, 1) : "—");
    const stat = (v, k, cls = "") => `<div class="stat glass"><span class="v ${cls}">${v}</span><span class="k">${k}</span></div>`;
    body = `
      ${sum.too_few_to_conclude ? `<div class="banner warn"><strong>מעט מדי רעיונות כדי להסיק מסקנות</strong>הסתיימו ${ltr(sum.completed)} רעיונות מתוך ${ltr(sum.min_completed_for_conclusion)} הדרושים לפחות. התוצאות עד כה הן אקראיות במידה רבה.</div>` : ""}
      <div class="stats">
        ${stat(ltr(sum.completed), "רעיונות שהסתיימו")}
        ${stat(isNum(sum.hit_rate) ? ltr(Math.round(sum.hit_rate * 100) + "%") : "—", "הגיעו ליעד")}
        ${stat(isNum(sum.avg_r) ? ltr((sum.avg_r > 0 ? "+" : "") + sum.avg_r.toFixed(2) + "R") : "—", "ממוצע R", tone(sum.avg_r))}
        ${stat(pct(sum.avg_pct), "תשואה ממוצעת", tone(sum.avg_pct))}
        ${stat(pct(sum.avg_bench_pct_same_period), "המדד באותן תקופות", tone(sum.avg_bench_pct_same_period))}
        ${stat(ltr(sum.open), "פתוחים כעת")}
      </div>
      <div class="count">ממתינים לכניסה: ${ltr(sum.pending)} · לא הופעלו (לא נספרים): ${ltr(sum.not_triggered)} · הסתיימו בארה״ב: ${ltr(t.summary.us.completed)} · בישראל: ${ltr(t.summary.il.completed)}</div>
      ${sectionTitle("רעיונות אחרונים")}
      ${(t.evaluations || []).length ? `<div class="glass flush rows">${t.evaluations.slice(0, 40).map(evalRow).join("")}</div>`
        : `<div class="empty glass">אין עדיין רעיונות שנבדקו. הבדיקה מתחילה ביום המסחר שאחרי כל רעיון.</div>`}`;
  }
  el.innerHTML = `<div class="screen-head"><h2 class="large-title">ביצועים</h2></div>
    <p class="lead">כל רעיון נבדק אוטומטית מול המחירים בפועל: כניסה עד 5 ימי מסחר, ואז יעד, סטופ או תום 20 ימים.</p>
    ${body}`;
}

function evalRow(e) {
  const c = e.currency === "ILS" ? "₪" : "$";
  const r = isNum(e.r) ? ltr((e.r > 0 ? "+" : "") + e.r.toFixed(2) + "R") : "";
  return `<div class="row static">
    <div class="ident"><div class="ticker ltr">${esc(e.symbol)}</div>
      <div class="name">${fmtDate(e.date)} · ${MARKET_HE[e.market] || ""} · כניסה ${fmtPrice(e.entry, c)}</div></div>
    <span class="status ${esc(e.status)}">${STATUS_HE[e.status] || esc(e.status)}</span>
    <div class="price"><div class="last">${r}</div>${isNum(e.pct) ? changeHtml(e.pct, 1) : ""}</div>
  </div>`;
}

function renderSettings() {
  const el = $("#screen-settings");
  const theme = store.get("theme", "dark");
  const n = starred().size;
  const row = (k, v) => `<div class="set-row"><span>${k}</span><span class="muted">${v}</span></div>`;
  el.innerHTML = `
    <div class="screen-head"><h2 class="large-title">הגדרות</h2></div>
    <div class="set-title">מראה</div>
    <div class="glass set-group"><div class="set-row"><span>ערכת צבעים</span>${segmented("theme", [["dark", "כהה"], ["light", "בהירה"], ["system", "לפי המכשיר"]], theme, "small")}</div></div>
    <div class="set-title">נתונים</div>
    <div class="glass set-group">
      ${row("ארה״ב", "Twelve Data · מחירי סגירה יומיים")}
      ${row("ישראל", "Yahoo Finance · מחירי סגירה יומיים")}
      ${row("ניתוח AI", "Gemini · לרעיונות הנבחרים בלבד")}
      ${row("עדכון ארה״ב", STATE.us ? fmtDateTime(STATE.us.generated_at) : "—")}
      ${row("עדכון ישראל", STATE.il ? fmtDateTime(STATE.il.generated_at) : "—")}
      ${row("שעות העדכון", "ישראל בערב, ארה״ב אחרי חצות (שעון ישראל)")}
    </div>
    <p class="set-foot">מצב "המסחר פתוח/סגור" מחושב לפי שעות המסחר הרגילות ואינו מכיר חגים. שווי שוק, מכפיל רווח וחדשות עדיין לא נכללים בגרסה הזו.</p>
    <div class="set-title">הרשימה שלי</div>
    <div class="glass set-group"><div class="set-row"><span>${ltr(n)} מניות מסומנות · נשמרות במכשיר הזה בלבד</span>
      ${n ? `<button class="btn danger small" data-action="clear-stars">ניקוי</button>` : ""}</div></div>
    <div class="set-title">אודות</div>
    <div class="glass set-group">${row("גרסה", ltr("3.0"))}${row("קוד", ltr("github.com/Amibar20/stock-radar"))}</div>`;
}

/* ---------------------------------------------------------------- sheet: stock detail and search */
function openSheet(kind, html) {
  STATE.sheet = kind;
  $("#sheet-body").innerHTML = html;
  const wasHidden = $("#sheet").hidden;
  $("#sheet").hidden = false; $("#sheet-backdrop").hidden = false;
  if (wasHidden) { $("#sheet").scrollTop = 0; document.body.classList.add("locked"); }
}
function closeSheet() {
  $("#sheet").hidden = true; $("#sheet-backdrop").hidden = true;
  STATE.sheet = null; STATE.detail = null;
  document.body.classList.remove("locked");
}

function openDetail(market, symbol) {
  const row = STATE[market]?.stocks.find((r) => r.symbol === symbol);
  if (!row) return;
  const same = STATE.detail && STATE.detail.market === market && STATE.detail.symbol === symbol;
  const scroll = $("#sheet").scrollTop;
  STATE.detail = { market, symbol };
  const i = row.indicators || {}; const c = cur(row); const ai = row.ai || {};
  const tr = (k, v, cls = "") => `<div class="kv-row"><span>${k}</span><span class="${cls}">${v}</span></div>`;
  const series = histSeries(market, symbol);
  let chart = "";
  if (series) {
    chart = chartHtml(sliceRange(series, STATE.detailRange), c, 200) + segmented("drange", RANGES.map((r) => [r[0], r[1]]), STATE.detailRange, "full");
  } else if (Array.isArray(row.sparkline) && row.sparkline.length > 1) {
    chart = chartHtml({ values: row.sparkline, dates: null }, c, 170) + `<p class="note">30 ימי המסחר האחרונים</p>`;
  }
  const range = series ? sliceRange(series, STATE.detailRange) : null;
  const rangeChg = range ? range.values[range.values.length - 1] / range.values[0] - 1 : null;
  const sector = market === "us" ? (row.sector || "—") : (row.index === "TA35" ? "מדד ת״א-35" : row.index === "TA90" ? "מדד ת״א-90" : "—");
  const points = Object.entries(row.points || {}).map(([k, v]) =>
    tr(esc(POINTS_HE[k] || k), ltr((v > 0 ? "+" : "") + v), v < 0 ? "down" : "")).join("");
  const stat = (k, v, cls = "") => `<div class="mini-stat"><span class="k">${k}</span><span class="v ${cls}">${v}</span></div>`;
  openSheet("detail", `
    <div class="detail-head">
      <div class="ident">
        <h2 id="sheet-title"><span class="ltr">${esc(row.symbol)}</span></h2>
        <div class="name">${esc(row.name_he || row.name || "")}</div>
        <div class="muted small">${MARKET_HE[market]} · נתוני ${fmtDate(row.date)}${row.rank ? ` · מקום ${ltr(row.rank)} בדירוג` : ""}</div>
      </div>
      ${starBtn(market, row.symbol)}
    </div>
    <div class="detail-price">
      <div class="big">${fmtPrice(i.close, c)}</div>
      <div class="hero-sub">${changeHtml(i.change_pct)} <span class="muted">היום</span>
        ${isNum(rangeChg) ? `<span class="dot-sep"></span>${changeHtml(rangeChg, 1)} <span class="muted">${RANGE_LONG[STATE.detailRange]}</span>` : ""}</div>
    </div>
    ${chart}
    ${chips(row)}
    <div class="mini-stats">
      ${stat("שיא 52 שבועות", fmtPrice(i.high_52w, c))}
      ${stat("שפל 52 שבועות", fmtPrice(i.low_52w, c))}
      ${stat("מחזור היום", fmtCompact(i.volume))}
      ${stat("מחזור ממוצע 20 יום", fmtCompact(i.avg_volume20))}
      ${stat("מחזור כספי יומי", fmtCompact(i.avg_dollar_volume20, c))}
      ${stat("RSI 14", ltr(fmtNum(i.rsi14, 0)))}
      ${stat("תשואה 3 חודשים", fmtPct(i.ret_63d), tone(i.ret_63d))}
      ${stat(market === "us" ? "ענף" : "מדד", `<span class="${market === "us" ? "ltr" : ""}">${esc(sector)}</span>`)}
    </div>
    ${row.levels ? `<div class="sub-title">רמות לרעיון</div>${levelsBlock(row)}
      <p class="note">סיכון עד הסטופ ${fmtPct(row.levels.risk_pct, 1, false)} · יחס סיכוי/סיכון ${ltr("1:" + row.levels.reward_risk)}</p>` : levelsBlock(row)}
    ${ai.available ? `
      <div class="ai glass">
        <div class="ai-head"><span class="ai-badge">AI</span><h4>${esc(ai.verdict_he)}</h4></div>
        <p>${esc(ai.summary_he)}</p>
        <div class="sub-title">ניתוח טכני</div><p>${esc(ai.technical_he)}</p>
        <div class="sub-title">הצד השלילי</div><p>${esc(ai.bear_case_he)}</p>
        <div class="sub-title">סיכונים עיקריים</div><ul>${(ai.key_risks_he || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
      </div>` : `<p class="note">${esc(ai.note || "ללא ניתוח AI למניה הזו (הניתוח נעשה רק לרעיונות הנבחרים).")}</p>`}
    ${row.gate ? `<p class="note">לא דורגה: ${esc(row.gate)}</p>` : ""}
    <div class="sub-title">אינדיקטורים</div>
    <div class="kv glass">
      ${tr("ממוצע נע 20 / 50 / 200", ltr(`${fmtNum(i.sma20)} / ${fmtNum(i.sma50)} / ${fmtNum(i.sma200)}`))}
      ${tr("MACD / קו אות", ltr(`${fmtNum(i.macd)} / ${fmtNum(i.macd_signal)}`))}
      ${tr("ATR 14", fmtPrice(i.atr14, c))}
      ${tr("מחזור מול ממוצע 20 יום", ltr(`${fmtNum(i.volume_ratio)}x`))}
      ${tr(`חוזק יחסי מול ${market === "us" ? "SPY" : "ת״א-125"} (3 ח׳)`, fmtPct(i.rs_63d), tone(i.rs_63d))}
      ${tr("מרחק משיא 52 שבועות", fmtPct(i.dist_52w_high), tone(i.dist_52w_high))}
    </div>
    ${points ? `<div class="sub-title">פירוט הציון (${ltr(Math.round(row.score) + "/100")})</div><div class="kv glass">${points}</div>` : ""}
    <footer class="disclaimer">כלי מחקר אישי, אינו ייעוץ השקעות. הנתונים מתעכבים ועלולים להיות שגויים.</footer>`);
  if (same) $("#sheet").scrollTop = scroll;
}

function openSearch() {
  STATE.detail = null;
  openSheet("search", `
    <h2 id="sheet-title" class="sheet-title">חיפוש מניה</h2>
    <input class="search" id="search-input" type="search" inputmode="search" autocomplete="off" placeholder="סימול או שם, בארה״ב או בישראל" data-input="search" aria-label="חיפוש מניה">
    <div class="count" id="search-hint">הקישו על הכוכב כדי להוסיף לרשימה שלי.</div>
    <div class="glass flush rows" id="search-results"></div>`);
  renderSearch();
  setTimeout(() => $("#search-input")?.focus(), 60);
}
function renderSearch() {
  const el = $("#search-results");
  if (!el) return;
  const q = ($("#search-input")?.value || "").trim().toLowerCase();
  const out = [];
  for (const m of ["us", "il"]) {
    for (const r of STATE[m]?.stocks || []) {
      if (!q) { if (r.selected) out.push([r, m]); continue; }
      const sym = r.symbol.toLowerCase();
      const hit = sym.startsWith(q) ? 0 : [r.name, r.name_he, sym].some((x) => (x || "").toLowerCase().includes(q)) ? 1 : -1;
      if (hit >= 0) out.push([r, m, hit]);
    }
  }
  out.sort((a, b) => (a[2] ?? 0) - (b[2] ?? 0));
  $("#search-hint").textContent = q ? `${out.length} תוצאות` : "הנבחרות של היום. הקלידו כדי לחפש בכל המניות.";
  el.innerHTML = out.length ? out.slice(0, 50).map(([r, m]) => listRow(r, m)).join("") : `<div class="empty">לא נמצאו מניות.</div>`;
  el.hidden = false;
}

/* ---------------------------------------------------------------- app shell */
function applyTheme(pref) {
  const resolved = pref === "system" ? (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark") : pref;
  document.documentElement.dataset.theme = resolved === "light" ? "light" : "dark";
  $('meta[name="theme-color"]').setAttribute("content", resolved === "light" ? "#f2f2f5" : "#08090c");
}

function renderUpdated() {
  const times = [STATE.us?.generated_at, STATE.il?.generated_at].filter(Boolean).sort();
  $("#updated").textContent = times.length ? `עודכן ${fmtDateTime(times[times.length - 1])}` : "";
}

function renderAll() {
  CHARTS.clear();
  renderHome(); renderMarkets(); renderWatch(); renderPerf(); renderSettings(); renderUpdated();
}

function show(screen) {
  if (!SCREENS.includes(screen)) screen = "home";
  STATE.screen = screen;
  for (const s of document.querySelectorAll(".screen")) s.hidden = s.id !== `screen-${screen}`;
  for (const t of document.querySelectorAll(".tab")) {
    const on = t.dataset.screen === screen;
    t.classList.toggle("active", on);
    on ? t.setAttribute("aria-current", "page") : t.removeAttribute("aria-current");
  }
  document.title = `${$(`#screen-${screen}`).dataset.title} · Stock Radar`;
  store.set("screen", screen);
  window.scrollTo(0, 0);
}

function refreshAfterStar() {
  renderMarkets(); renderWatch(); renderSettings();
  if (STATE.sheet === "detail" && STATE.detail) openDetail(STATE.detail.market, STATE.detail.symbol);
  if (STATE.sheet === "search") renderSearch();
}

function onSeg(name, val) {
  if (name === "market") { STATE.market = val; store.set("market", val); renderHome(); renderMarkets(); }
  else if (name === "range") { STATE.range = val; store.set("range", val); renderHome(); }
  else if (name === "drange") { STATE.detailRange = val; store.set("range", val); if (STATE.detail) openDetail(STATE.detail.market, STATE.detail.symbol); }
  else if (name === "movers") { STATE.movers = val; renderMarkets(); }
  else if (name === "filter") { STATE.filter = val; renderMarkets(); }
  else if (name === "theme") { store.set("theme", val); applyTheme(val); renderSettings(); }
}

document.addEventListener("click", (ev) => {
  const a = ev.target.closest("[data-action]");
  if (!a) return;
  const act = a.dataset.action;
  if (act === "star") {
    ev.stopPropagation();
    toggleStar(a.dataset.market, a.dataset.symbol);
    return refreshAfterStar();
  }
  if (act === "seg") return onSeg(a.dataset.seg, a.dataset.val);
  if (act === "detail") return openDetail(a.dataset.market, a.dataset.symbol);
  if (act === "tab") {
    if (a.dataset.market) { STATE.market = a.dataset.market; store.set("market", a.dataset.market); renderHome(); renderMarkets(); }
    closeSheet();
    return show(a.dataset.screen);
  }
  if (act === "hero") {
    STATE.hero[STATE.market] = a.dataset.key; renderHome();
    if (a.dataset.goto) show("home");
    return;
  }
  if (act === "more") {
    const box = a.closest(".brief"); const p = box.querySelector("p");
    const open = p.classList.toggle("open"); p.classList.toggle("clamp", !open);
    box.querySelector("button.link").textContent = open ? "הצג פחות" : "המשך קריאה";
    return;
  }
  if (act === "search") return openSearch();
  if (act === "close") return closeSheet();
  if (act === "clear-stars") {
    if (confirm("לנקות את כל המניות מהרשימה שלי?")) { store.set("starred", []); refreshAfterStar(); }
  }
});
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && STATE.sheet) closeSheet();
  if ((ev.key === "Enter" || ev.key === " ") && ev.target.matches('[data-action="detail"]')) {
    ev.preventDefault(); openDetail(ev.target.dataset.market, ev.target.dataset.symbol);
  }
});
document.addEventListener("input", (ev) => {
  const kind = ev.target.dataset.input;
  if (kind === "rank") { STATE.query = ev.target.value; renderRankList(); }
  if (kind === "search") renderSearch();
});
document.addEventListener("change", (ev) => {
  const s = ev.target.dataset.select;
  if (s === "sort") { STATE.sort = ev.target.value; renderRankList(); }
  if (s === "watchSort") { STATE.watchSort = ev.target.value; renderWatch(); }
});
document.addEventListener("pointermove", (ev) => { const el = ev.target.closest?.(".chart"); if (el) scrub(el, ev.clientX); });
document.addEventListener("pointerdown", (ev) => { const el = ev.target.closest?.(".chart"); if (el) scrub(el, ev.clientX); });
document.addEventListener("pointerout", (ev) => {
  const el = ev.target.closest?.(".chart");
  if (el && !el.contains(ev.relatedTarget) && ev.pointerType === "mouse") unscrub(el);
});
for (const t of ["pointerup", "pointercancel"]) {
  document.addEventListener(t, (ev) => {
    if (ev.pointerType === "mouse") return;
    const el = ev.target.closest?.(".chart"); if (el) setTimeout(() => unscrub(el), 900);
  });
}
matchMedia("(prefers-color-scheme: light)").addEventListener?.("change", () => {
  if (store.get("theme", "dark") === "system") applyTheme("system");
});

async function init() {
  applyTheme(store.get("theme", "dark"));
  STATE.market = store.get("market", "us") === "il" ? "il" : "us";
  STATE.range = RANGES.some((r) => r[0] === store.get("range")) ? store.get("range") : "6m";
  STATE.detailRange = STATE.range;
  show(store.get("screen", "home"));
  renderAll();
  const [us, il, status, track] = await Promise.all(["us", "il", "status", "track_record"].map(loadJSON));
  Object.assign(STATE, { us, il, status, track, loaded: true });
  renderAll();
  // One year of daily closes for the charts: larger files, loaded after the first paint.
  const [hu, hi] = await Promise.all([loadJSON("us_history"), loadJSON("il_history")]);
  if (hu || hi) {
    STATE.hist = { us: hu, il: hi };
    renderAll();
    if (STATE.sheet === "detail" && STATE.detail) openDetail(STATE.detail.market, STATE.detail.symbol);
  }
}

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("service-worker.js").catch(() => {}));
}
init();
