// Market Mitra - web page. Talks to Mitra Desk (/api/*).
const $ = id => document.getElementById(id);
const make = (tag, cls, text) => {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (text !== undefined && text !== null) el.textContent = text;
  return el;
};
let markets = [];
let shown = 0;
let timer;
let current = null;

const money = (cur, v, dp = 2) => (v === null || v === undefined || isNaN(v)) ? "–" :
  `${v < 0 ? "-" : ""}${cur}${Math.abs(v).toLocaleString("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp })}`;
const signed = v => (v === null || v === undefined) ? "–" : `${v > 0 ? "+" : ""}${Number(v).toFixed(2)}%`;
const tone = v => v > 0 ? "up" : v < 0 ? "down" : "";
const short = t => t.replace(/\.NS$/, "").replace(/-USD$/, "");
const priceDp = p => p >= 100 ? 2 : p >= 1 ? 3 : 5;

function sparkline(values) {
  const w = 90, h = 26;
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("width", w); svg.setAttribute("height", h); svg.setAttribute("class", "spark");
  if (!values || values.length < 2) return svg;
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * w},${h - 2 - ((v - min) / span) * (h - 4)}`).join(" ");
  const line = document.createElementNS(ns, "polyline");
  line.setAttribute("points", pts);
  line.setAttribute("fill", "none");
  line.setAttribute("stroke", values[values.length - 1] >= values[0] ? "#33c48d" : "#ff6b6b");
  line.setAttribute("stroke-width", "1.8");
  svg.append(line);
  return svg;
}

function selectedMarket() {
  const r = document.querySelector('input[name="market"]:checked');
  return markets.find(m => m.code === (r ? r.value : "IN")) || markets[0];
}

function showTickers() {
  const m = selectedMarket();
  $("tickers").innerHTML = "";
  for (const t of m.watchlist) {
    const lab = make("label", "chip");
    const box = make("input"); box.type = "checkbox"; box.value = t; box.checked = true;
    lab.append(box, document.createTextNode(short(t)));
    $("tickers").append(lab);
  }
  $("toggle-all").textContent = "select none";
  $("capital-note").textContent = `Paper portfolio starts with ${money(m.currency, m.capital, 0)} virtual money. ` +
    `Results are compared with ${m.benchmark}.`;
}

async function loadMarkets() {
  markets = await (await fetch("/api/markets")).json();
  const labels = { IN: "🇮🇳 NSE stocks", US: "🇺🇸 US stocks", CRYPTO: "₿ Crypto" };
  for (const m of markets) {
    const lab = make("label");
    const r = make("input"); r.type = "radio"; r.name = "market"; r.value = m.code; r.checked = m.code === "IN";
    r.addEventListener("change", showTickers);
    lab.append(r, document.createTextNode(labels[m.code] || m.name), make("small", "", `vs ${m.benchmark}`));
    $("markets").append(lab);
  }
  showTickers();
}

$("toggle-all").addEventListener("click", () => {
  const boxes = [...document.querySelectorAll("#tickers input")];
  const anyOn = boxes.some(b => b.checked);
  boxes.forEach(b => { b.checked = !anyOn; });
  $("toggle-all").textContent = anyOn ? "select all" : "select none";
});

$("run-form").addEventListener("submit", async e => {
  e.preventDefault();
  $("form-error").hidden = true;
  const tickers = [...document.querySelectorAll("#tickers input:checked")].map(b => b.value);
  if (!tickers.length) {
    $("form-error").textContent = "Pick at least one asset.";
    $("form-error").hidden = false;
    return;
  }
  $("go").disabled = true;
  $("go").textContent = "Sending to the agents...";
  try {
    const res = await fetch("/api/run", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ market: selectedMarket().code, tickers,
        risk: document.querySelector('input[name="risk"]:checked').value }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Something went wrong");
    startWatching(data.id);
  } catch (err) {
    $("form-error").textContent = err.message;
    $("form-error").hidden = false;
  } finally {
    $("go").disabled = false;
    $("go").textContent = "Run the agents (live)";
  }
});

function startWatching(id) {
  $("form-card").hidden = true;
  $("result").hidden = true;
  $("replay-card").hidden = true;
  $("live-card").hidden = false;
  $("log").innerHTML = ""; shown = 0;
  $("pulse").classList.remove("done");
  history.replaceState(null, "", `?run=${id}`);  // a refresh keeps the result
  poll(id);
}

async function poll(id) {
  clearTimeout(timer);
  let r;
  try {
    const res = await fetch(`/api/run/${id}`, { cache: "no-store" });
    if (!res.ok) throw new Error(res.status);
    r = await res.json();
  } catch (err) {
    // a single failed check (network blip, file being written) must not stop the updates
    timer = setTimeout(() => poll(id), 2000);
    return;
  }
  const events = r.events || [];
  for (; shown < events.length; shown++) {
    const m = events[shown];
    const li = make("li");
    li.append(make("span", "who", `${m.from} → ${m.to}`), make("span", "", m.message));
    $("log").append(li);
  }
  if (r.status === "done" && r.result) {
    $("pulse").classList.add("done");
    current = r;
    render(r);
    return;
  }
  if (r.status === "error") {
    const li = make("li", "error", r.error || "Something went wrong.");
    const again = make("a", "", "Try again");
    again.href = location.pathname;
    li.append(again);
    $("log").append(li);
    $("pulse").classList.add("done");
    return;
  }
  timer = setTimeout(() => poll(id), 2000);
}

function render(run) {
  const res = run.result, ins = res.insights, sc = res.scorecard, cur = ins.currency;
  $("result").hidden = false;
  $("r-market").textContent = `${ins.market_name} · ${run.risk} risk`;
  $("r-equity").textContent = money(cur, sc.equity);
  $("r-meta").textContent = `Paper portfolio value · started with ${money(cur, sc.start_capital, 0)} · cash ${money(cur, sc.cash)}`;
  $("r-return").textContent = signed(sc.return_pct); $("r-return").className = tone(sc.return_pct);
  $("r-bench").textContent = signed(sc.benchmark_return_pct); $("r-bench").className = tone(sc.benchmark_return_pct);
  $("r-bench-name").textContent = `${ins.benchmark.name || "benchmark"} same period`;
  $("r-open").textContent = sc.positions.length;
  $("r-win").textContent = sc.win_rate === null ? "–" : `${sc.win_rate}%`;

  // decisions: approved first, then vetoed, then holds
  $("r-decisions").innerHTML = "";
  const rank = d => d.status === "approved" ? 0 : d.status === "vetoed" ? 1 : 2;
  for (const d of [...res.decisions].sort((a, b) => rank(a) - rank(b))) {
    const box = make("div", `dec ${d.status}`);
    const row = make("div", "row");
    const left = make("div");
    left.append(make("h4", "", short(d.ticker)));
    const right = make("div");
    right.append(make("span", `badge ${d.action}`, d.action));
    if (d.status === "approved" || d.status === "vetoed") right.append(document.createTextNode(" "),
      make("span", `badge ${d.status}`, d.status === "approved" ? "PLACED" : "VETOED"));
    row.append(left, right);
    box.append(row);
    if (d.status === "approved" && d.qty) {
      let line = `${d.qty} @ ${money(cur, d.price, priceDp(d.price))}`;
      if (d.action === "BUY") line += ` · stop ${money(cur, d.stop_loss, priceDp(d.price))} · target ${money(cur, d.target, priceDp(d.price))}`;
      box.append(make("p", "small", line));
    }
    box.append(make("p", "", d.reason || ""));
    if (d.veto) box.append(make("p", "small veto", `Risk rule: ${d.veto}`));
    if (d.confidence !== undefined && !d.auto) box.append(make("p", "small", `Confidence ${Math.round(d.confidence * 100)}%`));
    if (d.lesson) box.append(make("p", "lesson", `📘 ${d.lesson}`));
    if (d.deep_dive) {
      const dd = make("div", "deep");
      dd.append(make("div", "", `Analyst's second look → Bull: ${d.deep_dive.bull || "–"}`),
        make("div", "", `Bear: ${d.deep_dive.bear || "–"}`), make("div", "", `Risk: ${d.deep_dive.risk || "–"}`));
      box.append(dd);
    }
    $("r-decisions").append(box);
  }

  $("r-mood").textContent = ins.market_mood ? `Market mood: ${ins.market_mood}` : "Score combines price action (60%) and news (40%).";
  $("r-insights").innerHTML = "";
  for (const a of ins.assets) {
    const tr = make("tr");
    const name = make("td"); name.append(make("b", "", short(a.ticker)));
    if (a.event) name.append(make("div", "hint small", a.event));
    const spark = make("td"); spark.append(sparkline(a.spark));
    const score = make("td"); score.append(make("span", `score ${a.view}`, a.score > 0 ? `+${a.score}` : a.score));
    tr.append(name, make("td", "", money(cur, a.price, priceDp(a.price))),
      make("td", tone(a.change_1d), signed(a.change_1d)), make("td", tone(a.change_20d), signed(a.change_20d)),
      make("td", "", a.rsi), spark, make("td", "news", `${a.news_sentiment > 0 ? "▲" : a.news_sentiment < 0 ? "▼" : "•"} ${a.news_reason}`), score);
    $("r-insights").append(tr);
  }
  $("r-sources").innerHTML = "";
  (ins.sources || []).slice(0, 8).forEach((s, i) => {
    if (i === 0) $("r-sources").append("News sources: ");
    else $("r-sources").append(" · ");
    const a = make("a", "", s.title || "source");
    a.href = s.url; a.target = "_blank"; a.rel = "noopener";
    $("r-sources").append(a);
  });

  const fin = ins.finch || {};
  const items = [...(fin.agents || []).map(x => ({ ...x, kind: "AGENT" })), ...(fin.skills || []).map(x => ({ ...x, kind: "SKILL" }))];
  $("finch-card").hidden = !items.length;
  $("r-finch").innerHTML = "";
  for (const it of items) {
    const a = make("a"); a.href = it.url; a.target = "_blank"; a.rel = "noopener";
    a.append(make("small", "", `FINCH ${it.kind}`), make("b", "", it.name || "Untitled"), make("span", "", it.summary || ""));
    $("r-finch").append(a);
  }

  $("r-positions").innerHTML = "";
  if (!sc.positions.length) {
    const tr = make("tr"); const td = make("td", "hint", "No open positions yet."); td.colSpan = 7; tr.append(td);
    $("r-positions").append(tr);
  }
  for (const p of sc.positions) {
    const tr = make("tr");
    tr.append(make("td", "", short(p.ticker)), make("td", "", p.qty), make("td", "", money(cur, p.avg_price, priceDp(p.avg_price))),
      make("td", "", money(cur, p.price, priceDp(p.price))), make("td", tone(p.pnl), `${money(cur, p.pnl)} (${signed(p.pnl_pct)})`),
      make("td", "", money(cur, p.stop_loss, priceDp(p.avg_price))), make("td", "", money(cur, p.target, priceDp(p.avg_price))));
    $("r-positions").append(tr);
  }
  $("result").scrollIntoView({ behavior: "smooth" });
}

function lineChart(series, labels) {
  // series: [{values: [...], color}] - percent returns, drawn on a shared scale with a 0% line
  const ns = "http://www.w3.org/2000/svg", W = 640, H = 220, L = 46, R = 12, T = 12, B = 28;
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const all = series.flatMap(x => x.values).concat([0]);
  let min = Math.min(...all), max = Math.max(...all);
  if (max - min < 1) { max += 0.5; min -= 0.5; }
  const x = i => L + (labels.length > 1 ? (i / (labels.length - 1)) * (W - L - R) : (W - L - R) / 2);
  const y = v => T + (1 - (v - min) / (max - min)) * (H - T - B);
  const add = (tag, attrs, text) => {
    const el = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    if (text !== undefined) el.textContent = text;
    svg.append(el); return el;
  };
  for (const v of [max, (max + min) / 2, min]) {
    add("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), stroke: "#22303d" });
    add("text", { x: L - 6, y: y(v) + 4, "text-anchor": "end", fill: "#93a4b5", "font-size": 11 }, `${v.toFixed(1)}%`);
  }
  add("line", { x1: L, x2: W - R, y1: y(0), y2: y(0), stroke: "#93a4b5", "stroke-dasharray": "4 4" });
  labels.forEach((lab, i) => add("text", { x: x(i), y: H - 8, "text-anchor": "middle", fill: "#93a4b5", "font-size": 11 }, lab));
  for (const sr of series) {
    add("polyline", { points: sr.values.map((v, i) => `${x(i)},${y(v)}`).join(" "), fill: "none", stroke: sr.color, "stroke-width": 2.5 });
    sr.values.forEach((v, i) => add("circle", { cx: x(i), cy: y(v), r: 3, fill: sr.color }));
  }
  return svg;
}

function renderReplay(rp) {
  const cur = rp.currency, sc = rp.scorecard, last = rp.days[rp.days.length - 1] || {};
  $("form-card").hidden = true; $("live-card").hidden = true; $("result").hidden = true;
  $("replay-card").hidden = false;
  $("rp-market").textContent = `Replay · ${rp.market_name} · ${rp.risk} risk · last ${rp.days.length} trading days`;
  $("rp-head").textContent = `${money(cur, rp.capital, 0)} → ${money(cur, last.equity ?? sc.equity)}`;
  const mine = last.return_pct ?? sc.return_pct, bench = last.benchmark_return_pct;
  $("rp-meta").textContent = `Agent portfolio ${signed(mine)} vs ${rp.benchmark_name} ${signed(bench)} · ` +
    `${sc.positions.length} open positions · ${sc.closed_trades} closed trades` +
    (sc.win_rate === null ? "" : ` · win rate ${sc.win_rate}%`) + ". Prices only (no news) in replay.";
  $("rp-bench-name").textContent = rp.benchmark_name;
  $("rp-chart").innerHTML = "";
  $("rp-chart").append(lineChart([
    { values: rp.days.map(d => d.return_pct), color: "#f5b942" },
    { values: rp.days.map(d => d.benchmark_return_pct), color: "#6aa7ff" },
  ], rp.days.map(d => d.date.slice(5))));
  $("rp-days").innerHTML = "";
  for (const d of rp.days) {
    const box = make("div", "day");
    const head = make("div", "day-head");
    const ret = make("span", tone(d.return_pct), `${money(cur, d.equity)} (${signed(d.return_pct)})`);
    head.append(make("span", "", d.date), ret);
    box.append(head);
    const ul = make("ul");
    if (!d.decisions.length) ul.append(make("li", "hint small", `No trades. Best idea was ${short(d.top_idea.ticker)} (score ${d.top_idea.score}) - not strong enough.`));
    for (const x of d.decisions) {
      const li = make("li");
      const label = x.status === "vetoed" ? `VETOED ${x.action} ${short(x.ticker)}` :
        `${x.action} ${x.qty} ${short(x.ticker)} @ ${money(cur, x.price, priceDp(x.price))}`;
      li.append(make("b", x.status === "vetoed" ? "down" : x.action === "BUY" ? "up" : "", label), document.createTextNode(" — "));
      li.append(document.createTextNode(x.veto ? `Risk rule: ${x.veto}` : (x.reason || "")));
      if (x.lesson) li.append(make("div", "lesson", `📘 ${x.lesson}`));
      ul.append(li);
    }
    box.append(ul);
    $("rp-days").append(box);
  }
  window.scrollTo({ top: 0, behavior: "smooth" });
}

$("replay-go").addEventListener("click", async () => {
  $("form-error").hidden = true;
  const tickers = [...document.querySelectorAll("#tickers input:checked")].map(b => b.value);
  if (!tickers.length) { $("form-error").textContent = "Pick at least one asset."; $("form-error").hidden = false; return; }
  $("replay-go").disabled = true; $("replay-go").textContent = "Replaying the last 7 days...";
  try {
    const res = await fetch("/api/replay", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ market: selectedMarket().code, tickers,
        risk: document.querySelector('input[name="risk"]:checked').value }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Replay failed");
    renderReplay(data);
  } catch (err) {
    $("form-error").textContent = err.message; $("form-error").hidden = false;
  } finally {
    $("replay-go").disabled = false; $("replay-go").textContent = "⏪ Replay last 7 days";
  }
});

$("rp-back").addEventListener("click", () => {
  $("replay-card").hidden = true; $("form-card").hidden = false;
});

$("again").addEventListener("click", () => {
  history.replaceState(null, "", location.pathname);
  $("result").hidden = true; $("live-card").hidden = true; $("form-card").hidden = false;
  window.scrollTo({ top: 0, behavior: "smooth" });
});

$("reset").addEventListener("click", async () => {
  if (!current) return;
  const m = current.market;
  $("reset").disabled = true;
  try {
    await fetch(`/api/portfolio/${m}/reset`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    $("reset").textContent = "Portfolio reset ✓";
  } finally {
    $("reset").disabled = false;
  }
});

loadMarkets().then(() => {
  const resumeId = new URLSearchParams(location.search).get("run");
  if (resumeId && /^[A-Za-z0-9-]+$/.test(resumeId)) startWatching(resumeId);
});
