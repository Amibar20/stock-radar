/* Stock Radar PWA — vanilla JS, no dependencies. Data comes from data/*.json written by the daily job. */
"use strict";

const STATE = { us: null, il: null, status: null, track: null, screen: "today", query: { us: "", il: "" },
  filter: { us: "ideas", il: "ideas" } };

const LABEL_HE = { research_buy: "בדיקה לקנייה", watch: "מעקב" };
const CONF_HE = { low: "ביטחון נמוך", medium: "ביטחון בינוני", high: "ביטחון גבוה" };
const MODE_HE = { positive: "שוק חיובי", cautious: "שוק זהיר", negative: "שוק שלילי" };
const STATUS_HE = { pending: "ממתין לכניסה", not_triggered: "לא הופעל", open: "פתוח", target: "הגיע ליעד",
  stopped: "נעצר בסטופ", expired: "פג תוקף" };
const BENCH_HE = { SPY: "S&P 500 (SPY)", QQQ: "Nasdaq-100 (QQQ)", "^TA125.TA": "ת״א-125" };
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

const store = {
  get(key, fallback) { try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode */ } },
};
const starKey = (market, sym) => `${market}:${sym}`;
function starred() { return new Set(store.get("starred", [])); }
function toggleStar(market, sym) {
  const s = starred(); const k = starKey(market, sym);
  s.has(k) ? s.delete(k) : s.add(k);
  store.set("starred", [...s]);
}

async function loadJSON(name) {
  try {
    const r = await fetch(`data/${name}.json`, { cache: "no-cache" });
    if (!r.ok) return null;
    return await r.json();
  } catch { return null; }
}

/* ---------------------------------------------------------------- pieces */
function sparkline(values) {
  if (!Array.isArray(values) || values.length < 2) return "";
  const w = 88, h = 34, pad = 2;
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
  const pts = values.map((v, i) => {
    const x = pad + (i / (values.length - 1)) * (w - 2 * pad); // time runs left→right, like any chart
    const y = h - pad - ((v - min) / span) * (h - 2 * pad);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const dir = values[values.length - 1] >= values[0] ? "up" : "down";
  return `<svg class="spark ${dir}" viewBox="0 0 ${w} ${h}" aria-hidden="true"><polyline points="${pts}"/></svg>`;
}

function chips(row) {
  const out = [];
  if (isNum(row.score)) out.push(`<span class="chip score">${ltr(Math.round(row.score))}</span>`);
  if (row.label) out.push(`<span class="chip ${esc(row.label.key)}">${esc(LABEL_HE[row.label.key] || row.label.he)}</span>`);
  const ai = row.ai || {};
  if (ai.available && ai.confidence) out.push(`<span class="chip conf-${esc(ai.confidence)}">${CONF_HE[ai.confidence]}</span>`);
  if (row.stale_since) out.push(`<span class="chip stale">לא עודכן מאז ${fmtDate(row.stale_since)}</span>`);
  if (row.watchlist) out.push(`<span class="chip">רשימת מעקב</span>`);
  return `<div class="chips">${out.join("")}</div>`;
}

function levelsBlock(row) {
  const lv = row.levels; const c = cur(row);
  if (!lv) return row.drop_reason ? `<p class="count">ללא רמות: ${esc(dropHe(row.drop_reason))}</p>` : "";
  return `<div class="levels">
    <div class="level"><span class="k">אזור כניסה</span><span class="v">${ltr(`${c}${fmtNum(lv.entry_low)}–${fmtNum(lv.entry_high)}`)}</span></div>
    <div class="level stop"><span class="k">סטופ</span><span class="v">${fmtPrice(lv.stop, c)}</span></div>
    <div class="level target"><span class="k">יעד</span><span class="v">${fmtPrice(lv.target, c)}</span></div>
  </div>`;
}

function dropHe(reason) {
  if (/52-week high/.test(reason)) return "שיא 52 שבועות קרוב מדי מעל הכניסה";
  if (/too wide/.test(reason)) return "הסטופ רחוק מדי";
  return reason;
}

function changeHtml(chg) {
  if (!isNum(chg)) return "";
  return `<div class="chg ${chg >= 0 ? "up" : "down"}">${fmtPct(chg, 2)}</div>`;
}

function card(row, market) {
  const i = row.indicators || {};
  const ai = row.ai || {};
  const summary = ai.available ? `<p class="summary">${esc(ai.summary_he)}</p>`
    : `<p class="summary noai">${esc(ai.note || "ללא ניתוח AI")}</p>`;
  const name = row.name_he || row.name || "";
  return `<button class="card" data-market="${market}" data-symbol="${esc(row.symbol)}">
    <div class="card-top">
      <div class="ident"><div class="ticker ltr">${esc(row.symbol)}</div><div class="name">${esc(name)}</div></div>
      <div class="price"><div class="last">${fmtPrice(i.close, cur(row))}</div>${changeHtml(i.change_pct)}</div>
    </div>
    ${chips(row)}
    ${levelsBlock(row)}
    <div class="card-body">${summary}${sparkline(row.sparkline)}</div>
  </button>`;
}

function listRow(row, market) {
  const i = row.indicators || {};
  const s = starred().has(starKey(market, row.symbol));
  return `<div class="row" data-market="${market}" data-symbol="${esc(row.symbol)}" role="button" tabindex="0">
    <span class="rank">${row.rank ? ltr(row.rank) : ""}</span>
    <div class="ident"><div class="ticker"><span class="ltr">${esc(row.symbol)}</span>${row.label ? ` <span class="chip mini ${esc(row.label.key)}">${esc(LABEL_HE[row.label.key])}</span>` : ""}</div>
      <div class="name">${esc(row.name_he || row.name || "")}${row.stale_since ? ` · <span class="chg down">לא עודכן מאז ${fmtDate(row.stale_since)}</span>` : ""}</div></div>
    <div class="price"><div class="last">${fmtPrice(i.close, cur(row))}</div>${changeHtml(i.change_pct)}</div>
    ${isNum(row.score) ? `<span class="chip score">${ltr(Math.round(row.score))}</span>` : `<span class="chip" title="${esc(row.gate || row.error || "")}">—</span>`}
    <button class="star ${s ? "on" : ""}" data-star="${market}:${esc(row.symbol)}" aria-label="${s ? "הסרה מהמעקב" : "הוספה למעקב"}" aria-pressed="${s}">${s ? "★" : "☆"}</button>
  </div>`;
}

function briefBlock(data, market) {
  if (!data) return `<div class="brief"><div class="brief-head"><h3>${market === "us" ? "ארה״ב" : "ישראל"}</h3></div><p class="count">אין עדיין נתונים.</p></div>`;
  const b = data.brief || {};
  const mode = b.risk_mode || "cautious";
  const bench = Object.entries(data.benchmarks || {}).map(([k, v]) =>
    `<span>${esc(BENCH_HE[k] || k)} ${ltr(fmtNum(v.close))} ${changeHtml(v.change_pct).replace("<div", "<span").replace("</div>", "</span>")}
     · ${v.above_sma50 ? "מעל " : "מתחת ל"}ממוצע 50 ו${v.above_sma200 ? "מעל " : "מתחת ל"}ממוצע 200</span>`).join("");
  const text = b.text_he ? `<p class="clamp">${esc(b.text_he)}</p><button class="more" data-more>המשך קריאה</button>`
    : `<p class="count">ללא ניתוח AI לסיכום השוק היום.</p>`;
  return `<div class="brief">
    <div class="brief-head"><h3>${market === "us" ? "ארה״ב" : "ישראל"} <span class="count">· נתוני ${fmtDate(data.as_of)}</span></h3>
      <span class="mode ${esc(mode)}">${esc(b.risk_mode_he || MODE_HE[mode])}</span></div>
    ${text}
    <div class="bench-row">${bench}</div>
  </div>`;
}

function banners() {
  const out = [];
  const st = STATE.status || {};
  for (const m of ["us", "il"]) {
    if (st[m] && st[m].ok === false) {
      out.push(`<div class="banner danger"><strong>${m === "us" ? "ארה״ב" : "ישראל"}: העדכון האחרון נכשל</strong>${esc(st[m].message || "")} · ${fmtDateTime(st[m].checked_at)}</div>`);
    }
  }
  const negative = ["us", "il"].filter((m) => STATE[m]?.brief?.caution_banner);
  if (negative.length) {
    const names = negative.map((m) => (m === "us" ? "ארה״ב" : "ישראל")).join(" ו");
    out.push(`<div class="banner warn"><strong>⚠️ זהירות: מצב שוק שלילי ב${names}</strong>המדדים מתחת לממוצעים הנעים 50 ו-200. רמת הביטחון של הרעיונות הורדה אוטומטית.</div>`);
  }
  for (const m of ["us", "il"]) {
    const d = STATE[m];
    if (d?.generated_at && (Date.now() - new Date(d.generated_at)) > 4 * 864e5) {
      out.push(`<div class="banner warn"><strong>הנתונים של ${m === "us" ? "ארה״ב" : "ישראל"} ישנים</strong>עודכנו לאחרונה ב-${fmtDateTime(d.generated_at)}.</div>`);
    }
  }
  return out.join("");
}

function picks(data, n) {
  if (!data) return [];
  return data.stocks.filter((r) => r.selected && r.label && r.levels).slice(0, n);
}

/* ---------------------------------------------------------------- screens */
function renderToday() {
  const us = picks(STATE.us, 5), il = picks(STATE.il, 3);
  const html = [
    banners(),
    `<div class="section-title">סיכום שוק</div>`,
    briefBlock(STATE.us, "us"), briefBlock(STATE.il, "il"),
    `<div class="section-title">רעיונות מובילים · ארה״ב</div>`,
    us.length ? `<div class="grid2">${us.map((r) => card(r, "us")).join("")}</div>` : `<div class="empty">אין היום רעיונות שעברו את הסינון.</div>`,
    `<div class="section-title">רעיונות מובילים · ישראל</div>`,
    il.length ? `<div class="grid2">${il.map((r) => card(r, "il")).join("")}</div>` : `<div class="empty">אין היום רעיונות שעברו את הסינון.</div>`,
  ];
  $("#screen-today").innerHTML = html.join("");
}

function renderMarket(market) {
  const el = $(`#screen-${market}`);
  const data = STATE[market];
  if (!data) { el.innerHTML = `<div class="empty">אין עדיין נתונים לשוק הזה.</div>`; return; }
  const q = STATE.query[market].trim().toLowerCase();
  const f = STATE.filter[market];
  let rows = data.stocks;
  if (f === "ideas") rows = rows.filter((r) => r.label);
  if (f === "scored") rows = rows.filter((r) => isNum(r.score));
  if (q) rows = rows.filter((r) => [r.symbol, r.name, r.name_he].some((x) => (x || "").toLowerCase().includes(q)));
  const top = picks(data, market === "us" ? 12 : 6);
  const filters = [["ideas", "רעיונות"], ["scored", "כל המדורגות"], ["all", "הכול"]]
    .map(([k, t]) => `<button class="filter ${f === k ? "on" : ""}" data-filter="${k}" data-market="${market}">${t}</button>`).join("");
  el.innerHTML = `
    ${briefBlock(data, market)}
    ${top.length && !q && f === "ideas" ? `<div class="section-title">הנבחרות להיום</div><div class="grid2">${top.map((r) => card(r, market)).join("")}</div>` : ""}
    <div class="section-title">דירוג מלא</div>
    <input class="search" type="search" inputmode="search" placeholder="חיפוש לפי סימול או שם" value="${esc(STATE.query[market])}" data-search="${market}" aria-label="חיפוש">
    <div class="filters">${filters}</div>
    <div class="count">${ltr(rows.length)} מניות · נסרקו ${ltr(data.stats.fetched)}/${ltr(data.stats.universe)}${data.stats.failed.length ? ` · נכשלו ${ltr(data.stats.failed.length)}` : ""}</div>
    ${rows.length ? `<div class="list">${rows.map((r) => listRow(r, market)).join("")}</div>` : `<div class="empty">לא נמצאו מניות.</div>`}`;
}

function renderWatch() {
  const s = starred();
  const mine = [];
  for (const m of ["us", "il"]) {
    for (const r of STATE[m]?.stocks || []) if (s.has(starKey(m, r.symbol))) mine.push([r, m]);
  }
  const t = STATE.track;
  const sum = t?.summary?.all;
  let trackHtml = `<div class="empty">התיעוד יתחיל להצטבר אחרי ההרצה הראשונה.</div>`;
  if (sum) {
    const pct = (v) => (isNum(v) ? fmtPct(v, 1) : "—");
    trackHtml = `
      ${sum.too_few_to_conclude ? `<div class="banner warn"><strong>מעט מדי רעיונות כדי להסיק מסקנות</strong>הסתיימו ${ltr(sum.completed)} רעיונות מתוך ${ltr(sum.min_completed_for_conclusion)} הדרושים לפחות. התוצאות עד כה הן אקראיות במידה רבה.</div>` : ""}
      <div class="stats">
        <div class="stat"><span class="v">${ltr(sum.completed)}</span><span class="k">רעיונות שהסתיימו</span></div>
        <div class="stat"><span class="v">${isNum(sum.hit_rate) ? ltr(Math.round(sum.hit_rate * 100) + "%") : "—"}</span><span class="k">הגיעו ליעד</span></div>
        <div class="stat"><span class="v">${isNum(sum.avg_r) ? ltr((sum.avg_r > 0 ? "+" : "") + sum.avg_r.toFixed(2) + "R") : "—"}</span><span class="k">ממוצע R</span></div>
        <div class="stat"><span class="v">${pct(sum.avg_pct)}</span><span class="k">תשואה ממוצעת</span></div>
        <div class="stat"><span class="v">${pct(sum.avg_bench_pct_same_period)}</span><span class="k">המדד באותן תקופות</span></div>
        <div class="stat"><span class="v">${ltr(sum.open)}</span><span class="k">פתוחים כעת</span></div>
      </div>
      <div class="count">ממתינים לכניסה: ${ltr(sum.pending)} · לא הופעלו (לא נספרים): ${ltr(sum.not_triggered)} · הסתיימו בארה״ב: ${ltr(t.summary.us.completed)} · בישראל: ${ltr(t.summary.il.completed)}</div>
      <div class="section-title">רעיונות אחרונים</div>
      <div class="list evals">${(t.evaluations || []).slice(0, 40).map(evalRow).join("") || `<div class="empty">אין עדיין רעיונות.</div>`}</div>`;
  }
  $("#screen-watch").innerHTML = `
    <div class="section-title">המניות שסימנתי</div>
    ${mine.length ? `<div class="list">${mine.map(([r, m]) => listRow(r, m)).join("")}</div>`
      : `<div class="empty">סמנו ☆ ליד מניה ברשימות ארה״ב או ישראל כדי לעקוב אחריה כאן. הסימונים נשמרים במכשיר הזה בלבד.</div>`}
    <div class="section-title">תיעוד ביצועים</div>
    ${trackHtml}`;
}

function evalRow(e) {
  const c = e.currency === "ILS" ? "₪" : "$";
  const r = isNum(e.r) ? ltr((e.r > 0 ? "+" : "") + e.r.toFixed(2) + "R") : "";
  return `<div class="row">
    <div class="ident"><div class="ticker ltr">${esc(e.symbol)}</div>
      <div class="name">${fmtDate(e.date)} · ${e.market === "us" ? "ארה״ב" : "ישראל"} · כניסה ${fmtPrice(e.entry, c)}</div></div>
    <span class="status ${esc(e.status)}">${STATUS_HE[e.status] || esc(e.status)}</span>
    <div class="price"><div class="last">${r}</div>${isNum(e.pct) ? `<div class="chg ${e.pct >= 0 ? "up" : "down"}">${fmtPct(e.pct, 1)}</div>` : ""}</div>
  </div>`;
}

/* ---------------------------------------------------------------- detail sheet */
function openDetail(market, symbol) {
  const row = STATE[market]?.stocks.find((r) => r.symbol === symbol);
  if (!row) return;
  const i = row.indicators || {}; const c = cur(row); const ai = row.ai || {};
  const s = starred().has(starKey(market, symbol));
  const cls = (v) => (isNum(v) ? (v >= 0 ? "pos" : "neg") : "");
  const tr = (k, v, extra = "") => `<tr><td>${k}</td><td class="${extra}">${v}</td></tr>`;
  const points = Object.entries(row.points || {}).map(([k, v]) =>
    tr(esc(POINTS_HE[k] || k), ltr((v > 0 ? "+" : "") + v), v < 0 ? "neg" : "")).join("");
  $("#sheet-body").innerHTML = `
    <h2 id="sheet-title"><span class="ltr">${esc(row.symbol)}</span> · ${esc(row.name_he || row.name || "")}</h2>
    <div class="count">${market === "us" ? "ארה״ב" : "ישראל"} · נתוני ${fmtDate(row.date)}${row.rank ? ` · מקום ${ltr(row.rank)} בדירוג` : ""}</div>
    ${chips(row)}
    <button class="filter ${s ? "on" : ""}" data-star="${market}:${esc(row.symbol)}" aria-pressed="${s}">${s ? "★ במעקב" : "☆ הוספה למעקב"}</button>
    ${levelsBlock(row)}
    ${row.levels ? `<div class="count">סיכון עד הסטופ ${fmtPct(row.levels.risk_pct, 1, false)} · יחס סיכוי/סיכון ${ltr("1:" + row.levels.reward_risk)}</div>` : ""}
    ${ai.available ? `
      <h4>${esc(ai.verdict_he)}</h4><p>${esc(ai.summary_he)}</p>
      <h4>ניתוח טכני</h4><p>${esc(ai.technical_he)}</p>
      <h4>הצד השלילי</h4><p>${esc(ai.bear_case_he)}</p>
      <h4>סיכונים עיקריים</h4><ul>${(ai.key_risks_he || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`
      : `<h4>ניתוח</h4><p class="count">${esc(ai.note || "ללא ניתוח AI")}</p>`}
    ${row.gate ? `<p class="count">לא דורגה: ${esc(row.gate)}</p>` : ""}
    <h4>אינדיקטורים</h4>
    <table class="kv"><tbody>
      ${tr("מחיר סגירה", fmtPrice(i.close, c))}
      ${tr("שינוי יומי", fmtPct(i.change_pct, 2), cls(i.change_pct))}
      ${tr("ממוצע נע 20 / 50 / 200", ltr(`${fmtNum(i.sma20)} / ${fmtNum(i.sma50)} / ${fmtNum(i.sma200)}`))}
      ${tr("RSI 14", ltr(fmtNum(i.rsi14, 0)))}
      ${tr("MACD / קו אות", ltr(`${fmtNum(i.macd)} / ${fmtNum(i.macd_signal)}`))}
      ${tr("ATR 14", fmtPrice(i.atr14, c))}
      ${tr("מחזור מול ממוצע 20 יום", ltr(`${fmtNum(i.volume_ratio)}x`))}
      ${tr("תשואה 63 ימים", fmtPct(i.ret_63d), cls(i.ret_63d))}
      ${tr(`חוזק יחסי מול ${market === "us" ? "SPY" : "ת״א-125"}`, fmtPct(i.rs_63d), cls(i.rs_63d))}
      ${tr("מרחק משיא 52 שבועות", fmtPct(i.dist_52w_high), cls(i.dist_52w_high))}
      ${tr("מחזור כספי ממוצע ליום", ltr(`${c}${fmtNum((i.avg_dollar_volume20 || 0) / 1e6, 1)}M`))}
    </tbody></table>
    ${points ? `<h4>פירוט הציון (${ltr(Math.round(row.score) + "/100")})</h4><table class="kv"><tbody>${points}</tbody></table>` : ""}
    <footer class="disclaimer">כלי מחקר אישי, אינו ייעוץ השקעות. הנתונים מתעכבים ועלולים להיות שגויים.</footer>`;
  $("#sheet").hidden = false; $("#sheet-backdrop").hidden = false;
  $("#sheet").scrollTop = 0;
  document.body.style.overflow = "hidden";
  $("#sheet-close").focus();
}
function closeDetail() {
  $("#sheet").hidden = true; $("#sheet-backdrop").hidden = true;
  document.body.style.overflow = "";
}

/* ---------------------------------------------------------------- app shell */
function renderAll() {
  renderToday(); renderMarket("us"); renderMarket("il"); renderWatch();
  const times = [STATE.us?.generated_at, STATE.il?.generated_at].filter(Boolean).sort();
  $("#updated").textContent = times.length ? `עודכן לאחרונה ${fmtDateTime(times[times.length - 1])}` : "";
}

function show(screen) {
  STATE.screen = screen;
  for (const s of document.querySelectorAll(".screen")) s.hidden = s.id !== `screen-${screen}`;
  for (const t of document.querySelectorAll(".tab")) {
    const on = t.dataset.screen === screen;
    t.classList.toggle("active", on);
    on ? t.setAttribute("aria-current", "page") : t.removeAttribute("aria-current");
  }
  $("#screen-title").textContent = $(`#screen-${screen}`).dataset.title;
  store.set("screen", screen);
  window.scrollTo(0, 0);
}

document.addEventListener("click", (ev) => {
  const star = ev.target.closest("[data-star]");
  if (star) {
    ev.stopPropagation();
    const [m, ...rest] = star.dataset.star.split(":");
    toggleStar(m, rest.join(":"));
    const sheetOpen = !$("#sheet").hidden;
    renderMarket("us"); renderMarket("il"); renderWatch();
    if (sheetOpen) openDetail(m, rest.join(":"));
    return;
  }
  const more = ev.target.closest("[data-more], .brief p.clamp, .brief p.open");
  if (more) {
    const p = more.closest(".brief").querySelector("p.clamp, p.open");
    const open = p.classList.toggle("open"); p.classList.toggle("clamp", !open);
    const btn = more.closest(".brief").querySelector("[data-more]");
    if (btn) btn.textContent = open ? "הצג פחות" : "המשך קריאה";
    return;
  }
  const tab = ev.target.closest(".tab");
  if (tab) return show(tab.dataset.screen);
  const filter = ev.target.closest("[data-filter]");
  if (filter) { STATE.filter[filter.dataset.market] = filter.dataset.filter; return renderMarket(filter.dataset.market); }
  const item = ev.target.closest(".card, .row[data-symbol]");
  if (item) return openDetail(item.dataset.market, item.dataset.symbol);
  if (ev.target.id === "sheet-backdrop" || ev.target.closest("#sheet-close")) closeDetail();
});
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") closeDetail();
  if (ev.key === "Enter" && ev.target.matches(".row[data-symbol]")) openDetail(ev.target.dataset.market, ev.target.dataset.symbol);
});
document.addEventListener("input", (ev) => {
  const m = ev.target.dataset.search;
  if (!m) return;
  STATE.query[m] = ev.target.value;
  const pos = ev.target.selectionStart;
  renderMarket(m);
  const input = $(`[data-search="${m}"]`);
  input.focus(); input.setSelectionRange(pos, pos);
});

async function init() {
  show(store.get("screen", "today"));
  const [us, il, status, track] = await Promise.all(["us", "il", "status", "track_record"].map(loadJSON));
  Object.assign(STATE, { us, il, status, track });
  renderAll();
}

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("service-worker.js").catch(() => {}));
}
init();
