/* EpochLab web client. Works against the live API or a static export with the same URL layout. */
"use strict";
const $ = (s) => document.querySelector(s);
const API = "api";
const TARGETS = [
  ["Barnard's Star", "Barnard's Star", "high PM"], ["eps Ind B", "ε Indi B", "brown dwarf"],
  ["WISE J085510.83-071442.5", "WISE 0855", "Y dwarf"], ["RW Aur", "RW Aurigae", "T Tauri"], ["R Dra", "R Draconis", "Mira"],
];
const STEP_OF = [[/resolv/i, "resolve"], [/sia|irsa|query/i, "irsa"], [/download/i, "download"], [/measur/i, "measure"],
  [/wavelength|fitting|control|done/i, "analysis"]];
const STEPS = ["resolve", "irsa", "download", "measure", "analysis"];
const S = { mode: "live", job: null, d: null, idx: 0, view: "raw", timer: null, aladin: null, frames: [] };

const fmt = (v, n = 2) => (v === null || v === undefined || Number.isNaN(v) ? "—" : Number(v).toFixed(n));
const mjdToIso = (m) => new Date((m - 40587) * 86400000).toISOString().replace(".000Z", "Z").replace("T", " ");
const mjdToDate = (m) => new Date((m - 40587) * 86400000).toISOString().slice(0, 10);
const mjdToYear = (m) => 1858.877 + m / 365.25;
const lamBin = (l, w) => (l > 0 ? Math.floor(Math.log(l) / Math.log1p(w)) : -1);
const lamFrac = (l) => Math.min(1, Math.max(0, (Math.log(l) - Math.log(0.75)) / (Math.log(5) - Math.log(0.75))));
function lamColor(l) { // wavelength → colour, log scale 0.75–5 µm (same stops as the legend bar)
  if (!(l > 0)) return "#666";
  const stops = [[75, 108, 255], [54, 201, 198], [155, 225, 93], [255, 193, 69], [255, 94, 94]];
  const p = lamFrac(l) * (stops.length - 1), i = Math.min(stops.length - 2, Math.floor(p)), f = p - i;
  return `rgb(${stops[i].map((a, k) => Math.round(a + f * (stops[i + 1][k] - a)))})`;
}
const NS = { svg: "http://www.w3.org/2000/svg", html: "http://www.w3.org/1999/xhtml" };
const el = (tag, attrs = {}, text) => {
  const e = document.createElementNS(attrs.svg ? NS.svg : NS.html, tag);
  for (const [k, v] of Object.entries(attrs)) if (k !== "svg") e.setAttribute(k, v);
  if (text !== undefined) e.textContent = text;
  return e;
};
const svgEl = (tag, attrs, text) => el(tag, { ...attrs, svg: 1 }, text);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function getJSON(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json();
}

/* ---------- opening animation (Narvalis mark), only when the page opens ---------- */
const Splash = (() => {
  const box = document.getElementById("splash");
  const t0 = performance.now();
  let finished = false;
  // light collected by the aperture: faint points converge from all around onto the outer ring, then the target star flares
  // dot-matrix rings: a radar hand sweeps once and lights the two rings dot by dot (outer clockwise, inner counter-clockwise)
  const conv = box && box.querySelector(".s-conv");
  if (conv) for (const [R, n, dir, r0] of [[46, 56, 1, 1.25], [29, 34, -1, 1.1]]) for (let k = 0; k < n; k++) {
    const t = k / n, a = -Math.PI / 2 + dir * t * Math.PI * 2;
    const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    c.setAttribute("cx", (50 + Math.cos(a) * R).toFixed(2)); c.setAttribute("cy", (50 + Math.sin(a) * R).toFixed(2)); c.setAttribute("r", r0);
    c.style.setProperty("--d", `${(0.15 + t * 0.85 + (R < 40 ? 0.12 : 0)).toFixed(3)}s`); conv.append(c);
  }
  // NARVALIS letters light up one by one at random, like stars appearing in a long exposure
  const word = box && box.querySelector(".splash-word");
  if (word) { const txt = word.textContent; word.setAttribute("aria-label", txt);
    word.replaceChildren(...[...txt].map((c, i) => { const sp = document.createElement("span"); sp.textContent = c; sp.setAttribute("aria-hidden", "true"); sp.style.setProperty("--r", (0.25 + Math.random() * 0.3).toFixed(2) + "s"); sp.style.setProperty("--i", i); return sp; })); }
  async function finish(markSel) {
    if (finished || !box) return; finished = true;
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    await sleep(Math.max(0, (reduce ? 300 : 2300) - (performance.now() - t0)));   // let the drawing complete
    const arc = box.querySelector(".s-arc");
    box.classList.add("settle");
    const wordsGone = sleep(reduce ? 0 : 750);
    if (!reduce && arc) {                       // stop the red arc exactly at its resting angle
      await new Promise((res) => { const done = () => { arc.style.animation = "fade 0s forwards"; res(); };
        arc.addEventListener("animationiteration", done, { once: true }); setTimeout(done, 1300); });
    }
    await wordsGone;   // NARVALIS and the subtitle fade to black before the mark moves
    // FLIP: fly the mark onto the header logo while the page fades in underneath
    const logo = box.querySelector(".splash-logo"), mark = document.querySelector(markSel || ".top .brand-mark");
    document.body.classList.remove("booting"); document.body.classList.add("booted");
    if (mark && !reduce) {
      const a = logo.getBoundingClientRect(), b = mark.getBoundingClientRect();
      const sc = b.width / a.width;
      logo.style.transform = `translate(${b.left + b.width / 2 - (a.left + a.width / 2)}px, ${b.top + b.height / 2 - (a.top + a.height / 2)}px) scale(${sc})`;
      box.classList.add("fly");
      await sleep(720);
    }
    box.classList.add("gone");
    if (!markSel && window.brandPlay) setTimeout(window.brandPlay, 250);
    await sleep(460);
    box.remove();
  }
  setTimeout(finish, 8000);   // fail-safe: never block the page
  return { finish };
})();

/* ---------- brand: click folds the Narvalis mark into the wordmark (an eclipse), click again unfolds it ---------- */
(function brandToggle() {
  const b = $("#brand"), tag = b.querySelector(".tag");
  tag.setAttribute("aria-label", tag.textContent);
  tag.replaceChildren(...[...tag.textContent].map((c, i) => { const sp = el("span", { "aria-hidden": "true" }, c === " " ? "\u00a0" : c); sp.style.setProperty("--i", i); return sp; }));
  const toggle = () => {
    const on = !b.classList.contains("compact");
    b.classList.toggle("compact", on); b.setAttribute("aria-pressed", String(on));
    b.title = on ? "Narvalis · click to show the mark" : "Narvalis · click to fold the logo";
  };
  b.addEventListener("click", toggle);
  // after the opening animation lands on the logo: fold to the name alone, then unfold back to the full logo
  window.brandPlay = () => { if (!b.classList.contains("compact")) toggle(); };
  b.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); toggle(); } });
})();

/* ---------- clock: UTC → MJD (the time unit of every SPHEREx frame) → local; click to cycle ---------- */
const CLOCKS = ["utc", "mjd", "local"];
let clockMode = 0;
try { clockMode = Math.max(0, CLOCKS.indexOf(localStorage.getItem("epochlab_clock_v1"))); } catch { }
const p2 = (n) => String(n).padStart(2, "0");
function tick() {
  const d = new Date(), m = CLOCKS[clockMode];
  const txt = m === "utc" ? `${p2(d.getUTCHours())}:${p2(d.getUTCMinutes())}`
    : m === "mjd" ? (d.getTime() / 86400000 + 40587).toFixed(innerWidth <= 380 ? 2 : isPhone() ? 3 : 4)
    : `${p2(d.getHours())}:${p2(d.getMinutes())}`;
  if ($("#clock").textContent !== txt) $("#clock").textContent = txt;
}
function setClockMode(k, animate) {
  clockMode = k; const m = CLOCKS[k], box = $("#clockbox");
  $("#clockLbl").textContent = { utc: "UTC", mjd: "MJD", local: "LOCAL" }[m];
  box.title = { utc: "Coordinated Universal Time · click: Modified Julian Date",
    mjd: "Modified Julian Date (UTC days since 1858-11-17), the time stamp SPHEREx frames carry · click: local time",
    local: "Your local time · click: UTC" }[m];
  box.dataset.clock = m;
  try { localStorage.setItem("epochlab_clock_v1", m); } catch { }
  if (animate) { box.classList.remove("flip"); void box.offsetWidth; box.classList.add("flip"); }
  tick();
}
$("#clockbox").addEventListener("click", () => setClockMode((clockMode + 1) % CLOCKS.length, true));
$("#clockbox").addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); $("#clockbox").click(); } });
setInterval(tick, 1000);

async function detectMode() {
  try { const h = await getJSON(`${API}/health`); S.mode = h.mode || "live"; }
  catch { try { await getJSON(`${API}/health.json`); S.mode = "static"; } catch { S.mode = "offline"; } }
  const narrow = matchMedia("(max-width:400px)").matches;
  $("#mode").textContent = { live: "IRSA · CHECKING", static: narrow ? "DEMO" : "STATIC DEMO", offline: narrow ? "OFFLINE" : "SERVER OFFLINE" }[S.mode];
  $("#signal").className = `signal ${S.mode === "live" ? "checking" : S.mode}`;
  if (S.mode !== "live") {
    $("#q").placeholder = S.mode === "static" ? "Static demo · open a saved analysis below" : "Live analysis unavailable in this mode";
    document.body.classList.add("not-live");   // the search button stays clickable: it explains why nothing new can run
    $("#connBtn").dataset.state = S.mode; $("#connBtn").title = S.mode === "static"
      ? "Static demo: analyses computed beforehand from real SPHEREx data; no live archive access" : "The Narvalis server is not answering";
  }
}

/* ---------- archive status: is IRSA answering *now*? (checked by the server; see /api/status) ---------- */
async function checkServices(force) {
  if (S.mode !== "live") return;
  const m = $("#mode"); m.classList.add("checking");
  try {
    const st = await getJSON(`${API}/status${force ? "?refresh=true" : ""}`);
    S.svc = st;
    const i = st.irsa || {}, t = (st.checked_utc || "").slice(11, 16);
    const [label, cls] = i.state === "online" ? ["LIVE · IRSA", "live"]
      : i.state === "offline" ? ["IRSA · NO LINK", "nolink"]
      : ["IRSA · BUSY", "degraded"];
    m.textContent = label; m.className = `mode ${cls}`;
    $("#connBtn").dataset.state = cls; $("#connBtn").title = `Connections · ${label}`;
    $("#signal").className = `signal ${cls}`;
    const cds = st.cds || {};
    const why = { online: "answering", degraded: `answering with server errors (HTTP ${i.http})`, error: `answering HTTP ${i.http}`, offline: "not reachable from this computer" }[i.state] || i.state;
    m.title = `IRSA SPHEREx archive: ${why}${i.ms != null ? `, ${i.ms} ms` : ""} · CDS sky images: ${cds.state === "online" ? "answering" : cds.http ? `HTTP ${cds.http}` : "not reachable"} · checked ${t} UTC · click to test every connection`;
    $("#signal").setAttribute("aria-label", `IRSA ${why}`);
    S.svcNote = i.state === "online" ? "IRSA, the NASA archive that serves SPHEREx images, is answering normally."
      : i.state === "offline" ? "IRSA cannot be reached from this computer (no network route). Saved analyses still open; new searches need the connection."
      : `IRSA, the NASA archive that serves SPHEREx images, is answering with a server error (HTTP ${i.http}). This is on IRSA’s side, not on this computer. Saved analyses still open normally; new searches may fail until IRSA recovers — it usually does within minutes to hours.`;
  } catch {
    m.textContent = "SERVER OFFLINE"; m.className = "mode nolink"; $("#signal").className = "signal offline"; $("#connBtn").dataset.state = "nolink";
    m.title = "The Narvalis server is not answering · click to check again";
  } finally { m.classList.remove("checking"); }
}
$("#mode").addEventListener("click", () => Conn.open());
$("#connBtn").addEventListener("click", () => Conn.open());
/* ---------- connections: test, from the server, every service the analysis depends on ---------- */
const Conn = (() => {
  const WORD = {
    online: (s) => [`Answering · ${s.ms} ms`, "ok"], slow: (s) => [`Answering slowly · ${(s.ms / 1000).toFixed(1)} s`, "warn"],
    server_error: (s) => [`Server error (HTTP ${s.http}) — a problem on their side`, "warn"],
    error: (s) => [s.http === 404 ? "Service unavailable (HTTP 404) — down or in maintenance on their side" : `Refused the request (HTTP ${s.http})`, "bad"],
    unreachable: (s, netOk) => [/timeout|timed out/i.test(s.detail || "")
      ? (netOk ? "No answer within 15 s — the service is down or overloaded (your connection works: other services answer)" : "No answer within 15 s")
      : (netOk ? "Could not connect — the service is down (your connection works: other services answer)" : "No answer from this computer — check the network connection"), "bad"],
    untested: (s) => [s.detail || "Not tested", "off"],
  };
  let box = null;
  function build() {
    box = el("div", { class: "conn", role: "dialog", "aria-modal": "true", "aria-label": "Connections", hidden: "" });
    box.innerHTML = `<div class="conn-card"><div class="conn-head"><div><h2>Connections</h2><p class="conn-sub">Tested from the Narvalis server, where the analysis runs.</p></div>
      <button type="button" class="round conn-x" aria-label="Close">×</button></div>
      <p class="conn-sum" aria-live="polite"></p><ul class="conn-list"></ul>
      <div class="conn-foot"><span class="conn-time"></span><button type="button" class="conn-run">Test again</button></div></div>`;
    document.body.append(box);
    box.querySelector(".conn-x").onclick = close; box.onclick = (e) => { if (e.target === box) close(); };
    box.querySelector(".conn-run").onclick = () => run(true);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && box && !box.hidden) { e.stopPropagation(); close(); } }, true);
  }
  function rowsTesting() {
    const ul = box.querySelector(".conn-list");
    if (!ul.children.length) ["IRSA image search", "IRSA collection list", "IRSA image download", "ESA Gaia DR3", "CDS Sesame", "CDS SIMBAD", "Sky context images (2MASS)"]
      .forEach((n) => { const li = el("li", { class: "testing" }); li.append(el("i"), el("b", {}, n), el("span", { class: "conn-st" }, "testing…")); ul.append(li); });
    else ul.querySelectorAll("li").forEach((li) => { li.className = "testing"; li.querySelector(".conn-st").textContent = "testing…"; });
    box.querySelector(".conn-sum").textContent = "Contacting each service…"; box.querySelector(".conn-sum").className = "conn-sum";
  }
  async function run(force) {
    rowsTesting(); box.querySelector(".conn-run").disabled = true;
    try {
      const rr = await fetch(`${API}/connections${force ? "?refresh=true" : ""}`, { cache: "no-store" });
      if (rr.status === 404 && S.mode === "live") { const e = new Error("old"); e.old = true; throw e; }
      if (!rr.ok) throw new Error(`HTTP ${rr.status}`);
      const d = await rr.json();
      const ul = box.querySelector(".conn-list"); ul.replaceChildren();
      const netOk = d.services.some((x) => x.state === "online" || x.state === "slow");
      d.services.forEach((s, k) => {
        const [txt, cls] = (WORD[s.state] || WORD.untested)(s, netOk);
        const li = el("li", { class: cls }); li.style.setProperty("--k", k);
        const info = el("div", { class: "conn-info" }); info.append(el("b", {}, s.name), el("small", {}, `${s.role}${s.host ? ` · ${s.host}` : ""}`));
        li.append(el("i"), info, el("span", { class: "conn-st", title: s.detail || "" }, txt)); ul.append(li);
      });
      const core = d.services.filter((s) => s.id.startsWith("irsa") || s.id === "gaia" || s.id === "sesame");
      const badCore = core.filter((s) => !["online", "slow", "untested"].includes(s.state));
      const sum = box.querySelector(".conn-sum");
      if (!badCore.length) { sum.textContent = "Everything a new analysis needs is answering."; sum.className = "conn-sum ok"; }
      else { sum.textContent = `${badCore.map((s) => s.name).join(", ")} ${badCore.length > 1 ? "are" : "is"} not answering normally. New analyses may fail until ${badCore.length > 1 ? "they recover" : "it recovers"}; saved analyses open as usual.`; sum.className = "conn-sum warn"; }
      box.querySelector(".conn-time").textContent = `Checked ${d.checked_utc.slice(11, 16)} UTC`;
    } catch (e) {
      box.querySelector(".conn-sum").textContent = e.old ? "The Narvalis server is running an older version that cannot test connections yet. Restart it (Ctrl+C, then start it again) and press Test again."
        : S.mode === "live" ? "The Narvalis server did not answer." : "This is the static demo: there is no server to test from; the analyses shown were computed beforehand from real SPHEREx data.";
      box.querySelector(".conn-sum").className = "conn-sum warn"; box.querySelector(".conn-list").replaceChildren();
    } finally { box.querySelector(".conn-run").disabled = false; checkServices(true); }
  }
  function open() { if (!box) build(); box.hidden = false; document.body.classList.add("conn-open"); run(false); box.querySelector(".conn-run").focus({ preventScroll: true }); }
  function close() { if (box) { box.hidden = true; document.body.classList.remove("conn-open"); } }
  return { open, close };
})();
/* small notice at the bottom of the screen (status explanations, deletions) */
function toast(msg, ms = 4000, action) {
  let t = $("#toast");
  if (!t) { t = el("div", { id: "toast", class: "toast", role: "status", "aria-live": "polite" }); document.body.append(t); }
  t.replaceChildren(el("span", {}, msg));
  if (action) { const b = el("button", { type: "button", class: "toast-act" }, action.label); b.onclick = () => { t.classList.remove("on"); action.fn(); }; t.append(b); }
  t.classList.toggle("act", !!action); t.classList.add("on"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("on"), ms);
}
setInterval(() => { if (!document.hidden) checkServices(false); }, 150000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) checkServices(false); });

/* ---------- loader (dynamic loading) ---------- */
/* Instrument-style acquisition screen behind the progress readout (Canvas 2D, no dependencies): a faint graticule,
   the target reticle and a slow scan line. Everything numeric on it (percentage, stage, elapsed time) is the job's
   REAL progress reported by the server; the canvas itself is decoration and draws no data.
   prefers-reduced-motion → one static frame, no scan line. Same interface as before (start/stop/set/reset/finale). */
const Warp = (() => {
  const cv = $("#warp"), ctx = cv.getContext("2d");
  const reduce = matchMedia("(prefers-reduced-motion: reduce)");
  let W = 0, H = 0, dpr = 1, raf = 0, last = 0, target = 0, q = 0, running = false, t = 0, t0 = 0, fin = null;
  const clamp01 = (x) => Math.max(0, Math.min(1, x));
  function resize() {
    const r = cv.getBoundingClientRect();
    dpr = Math.min(2, window.devicePixelRatio || 1);
    W = Math.max(1, Math.round(r.width * dpr)); H = Math.max(1, Math.round(r.height * dpr));
    cv.width = W; cv.height = H;
    if (!running || reduce.matches) draw();
  }
  function draw() {
    ctx.clearRect(0, 0, W, H);   // the readout is plain HTML on a dark field; nothing is drawn here any more
  }
  function drawGrid() {
    const cx = W / 2, cy = H / 2, step = Math.min(W, H) / 8, fade = fin ? clamp01(1 - fin.t / 0.45) : 1;
    ctx.clearRect(0, 0, W, H);
    ctx.lineWidth = dpr;
    // graticule, centred on the target
    for (let k = -Math.ceil(cx / step); k <= Math.ceil(cx / step); k++) {
      const x = Math.round(cx + k * step) + 0.5;
      ctx.strokeStyle = `rgba(255,255,255,${(k % 2 ? 0.035 : 0.07) * fade})`; ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
    }
    for (let k = -Math.ceil(cy / step); k <= Math.ceil(cy / step); k++) {
      const y = Math.round(cy + k * step) + 0.5;
      ctx.strokeStyle = `rgba(255,255,255,${(k % 2 ? 0.035 : 0.07) * fade})`; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
    }
    // tick marks along the edges
    ctx.strokeStyle = `rgba(255,255,255,${0.22 * fade})`;
    for (let x = cx % (step / 4); x < W; x += step / 4) { const l = (Math.round((x - cx) / (step / 4)) % 4 ? 4 : 9) * dpr; ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, l); ctx.moveTo(x, H); ctx.lineTo(x, H - l); ctx.stroke(); }
    for (let y = cy % (step / 4); y < H; y += step / 4) { const l = (Math.round((y - cy) / (step / 4)) % 4 ? 4 : 9) * dpr; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(l, y); ctx.moveTo(W, y); ctx.lineTo(W - l, y); ctx.stroke(); }
    // scan line (time base only, not a measurement)
    if (!reduce.matches && running) {
      const y = ((t * 0.18) % 1) * H, g = ctx.createLinearGradient(0, y - 60 * dpr, 0, y);
      g.addColorStop(0, "rgba(255,255,255,0)"); g.addColorStop(1, `rgba(255,255,255,${0.06 * fade})`);
      ctx.fillStyle = g; ctx.fillRect(0, y - 60 * dpr, W, 60 * dpr);
      ctx.fillStyle = `rgba(255,255,255,${0.18 * fade})`; ctx.fillRect(0, y, W, dpr);
    }
    // dark field behind the readout so it stays legible
    const rt = Math.min(W, H) * 0.3, gw = ctx.createRadialGradient(cx, cy, rt * 0.3, cx, cy, rt * 1.6);
    gw.addColorStop(0, "rgba(0,0,0,0.9)"); gw.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = gw; ctx.fillRect(0, 0, W, H);
  }
  function frame(now) {
    if (!running) return;
    const dt = Math.min(0.05, (now - (last || now)) / 1000); last = now; t += dt;
    q += (target - q) * Math.min(1, dt * 3);
    if (fin) { fin.t += dt; if (fin.t >= 0.45 && !fin.done) { fin.done = true; fin.res(); } }
    const el_ = $("#lel"); if (el_) { const s = Math.floor((performance.now() - t0) / 1000); el_.textContent = `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`; }
    draw(); cv.dataset.level = q.toFixed(3);
    raf = requestAnimationFrame(frame);
  }
  new ResizeObserver(() => resize()).observe(cv);
  reduce.addEventListener?.("change", () => { if (running) { stop(); start(); } });
  function start() {
    if (running) return;
    if (!t0) t0 = performance.now();
    resize(); running = true;
    if (reduce.matches) { q = target; draw(); running = false; return; }
    last = 0; raf = requestAnimationFrame(frame);
  }
  function stop() { running = false; cancelAnimationFrame(raf); if (fin && !fin.done) { fin.done = true; fin.res(); } fin = null; }
  function set(p) { target = clamp01(p); if (reduce.matches) { q = target; draw(); } }
  function reset() { q = 0; target = 0; fin = null; t0 = performance.now(); }
  function finale() {
    if (reduce.matches || !running) return Promise.resolve();
    if (!fin) { let res; const promise = new Promise((r) => (res = r)); fin = { t: 0, res, promise, done: false }; target = 1; }
    return fin.promise;
  }
  return { start, stop, set, reset, finale, get finaling() { return fin && fin.promise; }, get level() { return q; } };
})();

/* the dot sphere of the first version: 23 × 23 dots inside a circle, pulsing outward from the centre */
(function buildDots() {
  const box = $("#dots"); if (!box) return;
  const n = 23, c = (n - 1) / 2;
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
    const i = document.createElement("i"), r = Math.hypot(x - c, y - c);
    if (r > c + 0.5) i.style.visibility = "hidden";
    i.style.animationDelay = `${(r * 0.11).toFixed(2)}s`;
    box.append(i);
  }
})();
let loaderFade = 0;
function showLoader(f, msg) {
  const L = $("#loader");
  clearTimeout(loaderFade); L.classList.remove("leaving");
  if (L.hidden) { Warp.reset(); L.classList.remove("jump"); }
  L.hidden = false; $("#empty").hidden = true; document.body.classList.add("busy");
  const p = Math.max(0, Math.min(1, f || 0));
  $("#pct").textContent = `${Math.round(p * 100)}%`;
  $("#lmsg").textContent = msg || "";
  $("#ringFg").style.strokeDashoffset = String(276.5 * (1 - p));
  const fill = $("#lbarFill"); if (fill) fill.style.transform = `scaleX(${p})`;
  Warp.set(p); Warp.start();
  setSteps(msg);
}
/* completed → fade the warp out over the real result; failure (instant) → stop at once and show the error state */
function hideLoader(instant) {
  const L = $("#loader");
  document.body.classList.remove("busy");
  if (L.hidden) { Warp.stop(); return; }
  clearTimeout(loaderFade);
  if (instant === true || matchMedia("(prefers-reduced-motion: reduce)").matches) { Warp.stop(); L.classList.remove("leaving", "jump"); L.hidden = true; return; }
  const fin = Warp.finaling;
  if (fin) {
    // completed job: let the jump peak, make sure the first real frame is decoded, then drop out of hyperspace into it
    const img = $("#frame");
    Promise.all([fin, Promise.race([img.decode ? img.decode().catch(() => { }) : null, sleep(900)])]).then(() => {
      const st = $("#stage"); st.classList.remove("arrive"); void st.offsetWidth; st.classList.add("arrive");
      setTimeout(() => st.classList.remove("arrive"), 1400);
      L.classList.add("leaving");
      loaderFade = setTimeout(() => { Warp.stop(); L.hidden = true; L.classList.remove("leaving", "jump"); }, 400);
    });
    return;
  }
  L.classList.add("leaving");
  loaderFade = setTimeout(() => { Warp.stop(); L.hidden = true; L.classList.remove("leaving"); }, 650);
}
function setSteps(msg, state) {
  let k = 0;
  for (const [re, key] of STEP_OF) if (re.test(msg || "")) { k = STEPS.indexOf(key); }
  for (const sel of ["#steps li", "#lsteps li"]) document.querySelectorAll(sel).forEach((li, i) => {
    li.className = state === "done" ? "done" : i < k ? "done" : i === k ? (state === "fail" ? "fail" : "active") : "";
  });
}
function clearSteps() { document.querySelectorAll("#steps li").forEach((li) => (li.className = "")); }

/* ---------- jobs ---------- */
async function loadJobs() {
  let list = [];
  try { list = (await getJSON(S.mode === "static" ? `${API}/jobs/index.json` : `${API}/jobs`)).jobs; } catch { }
  const ul = $("#jobs"); ul.replaceChildren();
  if (!list.length) ul.append(el("li", { class: "dim" }, "No analyses yet"));
  for (const j of list) {
    const r = j.request || {};
    const name = r.target_name || (r.ra_deg !== undefined && r.ra_deg !== null ? `${fmt(r.ra_deg, 3)}, ${fmt(r.dec_deg, 3)}` : j.job_id);
    const li = el("li", { "data-id": j.job_id, tabindex: 0 });
    li.append(el("span", {}, name), el("span", { class: `st ${j.state}` }, j.state));
    if (S.mode === "live" && j.state !== "running" && j.state !== "queued") {
      const del = el("button", { type: "button", class: "jdel", "aria-label": `Delete analysis ${name}`, title: "Delete this analysis" });
      del.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>';
      del.onclick = (e) => { e.stopPropagation(); askDelete(li, j.job_id, name); };
      li.append(del);
    }
    li.dataset.state = j.state; li.dataset.name = name;
    li.onclick = (e) => {
      if (li.classList.contains("asking")) return;
      if (Sel.on) { if (Sel.justPressed) { Sel.justPressed = false; return; } Sel.toggle(li); return; }
      if (isPhone()) setSection("sky"); return j.state === "done" ? loadJob(j.job_id) : j.state !== "failed" && poll(j.job_id);
    };
    Sel.press(li);
    if (Sel.ids.has(j.job_id)) li.classList.add("sel");
    li.onkeydown = (e) => e.key === "Enter" && li.onclick();
    if (j.job_id === S.job) li.classList.add("on");
    ul.append(li);
  }
  renderTrash();
  return list;
}

/* haptic feedback: Vibration API where it exists (Android); on iPhone (no Vibration API in Safari) the system tick of a
   native switch control is used (iOS 18+). Both only fire inside a user gesture; elsewhere this does nothing. */
const haptic = (() => {
  let lab = null;
  return (kind = "light") => {
    try {
      if (navigator.vibrate) { navigator.vibrate({ light: 8, medium: 16, heavy: 28, success: [10, 50, 14], warn: [20, 60, 20] }[kind] || 8); return; }
      if (!/iP(hone|ad|od)/.test(navigator.userAgent) && !(navigator.maxTouchPoints > 1 && /Mac/.test(navigator.platform))) return;
      if (!lab) {
        lab = document.createElement("label"); lab.setAttribute("aria-hidden", "true");
        lab.style.cssText = "position:fixed;left:-9999px;top:0;width:1px;height:1px;overflow:hidden;opacity:0;pointer-events:none";
        const inp = document.createElement("input"); inp.type = "checkbox"; inp.setAttribute("switch", ""); inp.tabIndex = -1;
        lab.append(inp); document.body.append(lab);
      }
      lab.click(); if (kind === "success" || kind === "heavy") setTimeout(() => lab.click(), 90);
    } catch { }
  };
})();

/* select several analyses (long-press on a phone, or the Select button) and move them to Recently deleted at once */
const Sel = {
  on: false, ids: new Set(), justPressed: false,
  enter() { if (S.mode !== "live") return; haptic("medium"); this.on = true; document.body.classList.add("jobs-selecting"); $("#jobsBar").hidden = false; $("#jobsSelect").textContent = "Done"; this.sync(); },
  exit() { this.on = false; this.ids.clear(); document.body.classList.remove("jobs-selecting"); $("#jobsBar").hidden = true; $("#jobsSelect").textContent = "Select";
    document.querySelectorAll("#jobs li.sel").forEach((x) => x.classList.remove("sel")); },
  toggle(li) {
    const id = li.dataset.id; if (!id || li.dataset.state === "running" || li.dataset.state === "queued") return;
    const on = !this.ids.has(id);
    on ? this.ids.add(id) : this.ids.delete(id); li.classList.toggle("sel", on);
    li.classList.remove("pop", "unpop"); void li.offsetWidth; li.classList.add(on ? "pop" : "unpop");
    haptic(on ? "light" : "light"); this.sync();
  },
  sync() { const n = this.ids.size, c = $("#jobsCount"); if (c.dataset.n !== String(n)) { c.dataset.n = n; c.classList.remove("bump"); void c.offsetWidth; c.classList.add("bump"); } c.textContent = `${n} selected`; $("#jobsDelete").disabled = !n; $("#jobsDelete").textContent = n ? `Delete ${n}` : "Delete"; },
  press(li) {   // long-press (touch or mouse) enters selection with this item selected
    let t = 0, x0 = 0, y0 = 0;
    const cancel = () => { clearTimeout(t); li.classList.remove("pressing"); };
    li.addEventListener("pointerdown", (e) => {
      if (e.target.closest("button")) return; x0 = e.clientX; y0 = e.clientY;
      if (!Sel.on) li.classList.add("pressing");      // a fill grows under the finger while it is held
      t = setTimeout(() => { li.classList.remove("pressing"); if (!Sel.on) Sel.enter(); if (!Sel.ids.has(li.dataset.id)) Sel.toggle(li); Sel.justPressed = true; }, 480);
    });
    li.addEventListener("pointermove", (e) => { if (Math.hypot(e.clientX - x0, e.clientY - y0) > 10) cancel(); });
    ["pointerup", "pointercancel", "pointerleave"].forEach((ev) => li.addEventListener(ev, cancel));
    li.addEventListener("contextmenu", (e) => { if (isPhone() || Sel.on) e.preventDefault(); });
  },
  async remove() {
    const ids = [...this.ids]; if (!ids.length) return;
    $("#jobsDelete").disabled = true; haptic("heavy");
    ids.forEach((id, k) => { const li = document.querySelector(`#jobs li[data-id="${id}"]`); if (li) { li.style.setProperty("--k", k); li.classList.add("collapsing"); } });
    await sleep(320 + Math.min(ids.length, 8) * 40);
    const done = [], fails = [];
    for (const id of ids) {
      try { const r = await fetch(`${API}/jobs/${id}`, { method: "DELETE", headers: Owner.hdr(id) }); if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.detail || `HTTP ${r.status}`); } done.push(id); }
      catch (err) { fails.push(err.message); }
    }
    const was = done.includes(S.job);
    this.exit();
    const list = await loadJobs(); targetResults(list);
    document.querySelectorAll("#chips li[data-q]").forEach((c) => { if (done.includes(c.dataset.job)) { delete c.dataset.job; const t = c.querySelector(".tres"); t.textContent = "not analysed yet"; t.className = "tres none"; } });
    if (was) { const next = list.find((x) => x.state === "done"); if (next) loadJob(next.job_id); }
    if (fails.length && !done.length) toast(`Could not delete: ${fails[0]}`, 6000);
    else toast(`${done.length} ${done.length === 1 ? "analysis" : "analyses"} moved to Recently deleted${fails.length ? ` (${fails.length} could not be deleted)` : ""}.`, 9000,
      { label: "Undo", fn: async () => { haptic("success"); for (const id of done) await fetch(`${API}/trash/${id}/restore`, { method: "POST", headers: Owner.hdr(id) }).catch(() => {}); const l = await loadJobs(); targetResults(l); toast("Restored."); } });
  },
};
$("#jobsSelect").onclick = () => (Sel.on ? (haptic("light"), Sel.exit()) : Sel.enter());
$("#jobsCancel").onclick = () => { haptic("light"); Sel.exit(); };
$("#jobsDelete").onclick = () => Sel.remove();
$("#jobsFailed").onclick = () => { haptic("medium"); document.querySelectorAll("#jobs li[data-state=failed]").forEach((li) => { if (!Sel.ids.has(li.dataset.id)) Sel.toggle(li); }); };

/* delete one analysis after an inline confirmation (no browser dialog) */
function askDelete(li, id, name) {
  if (li.classList.contains("asking")) return;
  li.classList.add("asking");
  const box = el("span", { class: "jask" });
  const yes = el("button", { type: "button", class: "jyes" }, "Delete"), no = el("button", { type: "button", class: "jno" }, "Cancel");
  box.append(el("span", {}, `Delete “${name}”?`), yes, no); li.append(box); yes.focus();
  no.onclick = (e) => { e.stopPropagation(); box.remove(); li.classList.remove("asking"); };
  yes.onclick = async (e) => {
    e.stopPropagation(); yes.disabled = true;
    try {
      const r = await fetch(`${API}/jobs/${id}`, { method: "DELETE", headers: Owner.hdr(id) });
      if (r.status === 405) throw new Error("the server is running an older version — restart it (Ctrl+C, then start it again) and try once more");
      if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.detail || `HTTP ${r.status}`); }
      li.classList.add("gone");
      const was = S.job === id;
      await sleep(250);
      const list = await loadJobs(); targetResults(list);
      document.querySelectorAll("#chips li[data-q]").forEach((c) => { if (c.dataset.job === id) { delete c.dataset.job; const t = c.querySelector(".tres"); t.textContent = "not analysed yet"; t.className = "tres none"; } });
      if (was) { const next = list.find((x) => x.state === "done"); if (next) loadJob(next.job_id); else location.hash = ""; }
      toast(`“${name}” moved to Recently deleted.`, 9000, { label: "Undo", fn: () => restoreJob(id, name) });
    } catch (err) { box.remove(); li.classList.remove("asking"); toast(`Could not delete: ${err.message}`, 6000); }
  };
}

/* deleted analyses wait in the server's trash: restore from the toast or from "Recently deleted" under the list */
async function restoreJob(id, name) {
  try {
    const r = await fetch(`${API}/trash/${id}/restore`, { method: "POST", headers: Owner.hdr(id) });
    if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.detail || `HTTP ${r.status}`); }
    const list = await loadJobs(); targetResults(list);
    toast(`“${name || id}” restored.`);
  } catch (err) { toast(`Could not restore: ${err.message}`, 6000); }
}
async function renderTrash() {
  const ul = $("#jobs"); if (S.mode !== "live" || !ul) return;
  let items = [];
  try { items = (await getJSON(`${API}/trash`)).jobs || []; } catch { return; }
  ul.querySelector(".trashrow")?.remove();
  if (!items.length) return;
  const li = el("li", { class: "trashrow" });
  const head = el("button", { type: "button", class: "trash-toggle", "aria-expanded": "false" }, `Recently deleted · ${items.length}`);
  const box = el("div", { class: "trash-list", hidden: "" });
  items.forEach((j) => {
    const r = j.request || {}, nm = r.target_name || (r.ra_deg != null ? `${fmt(r.ra_deg, 3)}, ${fmt(r.dec_deg, 3)}` : j.job_id);
    const row = el("div", { class: "trash-item" }), rb = el("button", { type: "button" }, "Restore");
    rb.onclick = (e) => { e.stopPropagation(); restoreJob(j.job_id, nm); };
    row.append(el("span", {}, nm), el("small", {}, (j.deleted_utc || "").slice(0, 16).replace("T", " ")), rb); box.append(row);
  });
  head.onclick = (e) => { e.stopPropagation(); box.hidden = !box.hidden; head.setAttribute("aria-expanded", String(!box.hidden)); };
  li.append(head, box); ul.append(li);
}

/* challenge-target cards show the verdict of the latest finished analysis of that target; nothing is shown if none exists */
async function targetResults(list) {
  for (const li of document.querySelectorAll("#chips li[data-q]")) {
    const q = li.dataset.q.toLowerCase();
    const j = (list || []).find((x) => x.state === "done" && ((x.request || {}).target_name || "").toLowerCase() === q);
    if (!j) continue;
    try {
      const d = await getJSON(`${API}/jobs/${j.job_id}/dossier.json`);
      const vr = (k) => ((d.verdicts || []).find((x) => x.check === k) || {}).result || "";
      const pm = vr("proper_motion_vs_catalogue"), va = vr("variability_matched_wavelength");
      if (S.aladin) skyMarkers();
      const kind = /^REAL/.test(d.data_kind || "") ? "" : " · simulated";
      // brightness targets (T Tauri, Mira) answer the brightness question; the others the motion question
      const bins = ((d.results || {}).variability || {}).bins || [], worst = bins.length ? Math.max(...bins.map((x) => x.max_over_min || 1)) : null;
      const brightFirst = /tauri|mira/i.test(li.querySelector("small").textContent);
      const bright = va === "VARIABLE" ? [`variable${worst ? ` ×${fmt(worst, 1)}` : ""}`, "warn"]
        : /saturated/i.test(va) || (va === "INCONCLUSIVE" && /saturat/i.test(JSON.stringify(d.verdicts || []))) ? ["saturated · inconclusive", "dim"]
        : /INCONCLUSIVE|POSSIBLE/.test(va) ? ["brightness inconclusive", "dim"] : va === "NO EVIDENCE" ? ["brightness steady", "ok"] : null;
      const motion = pm === "CONSISTENT" ? ["matches Gaia", "ok"] : pm === "INCONSISTENT" ? ["differs from Gaia", "warn"] : null;
      const [txt, cls] = (brightFirst ? bright || motion : motion || bright) || ["analysed", "ok"];
      const em = li.querySelector(".tres"); em.textContent = txt + kind; em.className = `tres ${cls}`;
      li.dataset.job = j.job_id; li.title = `Latest analysis ${j.job_id} · tap to open`;
      const qp = (d.target || {}).query_position_deg; if (qp) { li.dataset.ra = qp[0]; li.dataset.dec = qp[1]; }
    } catch { }
  }
}

/* ---------- submit & poll ---------- */
// Owner tokens: the browser that started an analysis can remove it again on a public server (see api._may_remove).
const Owner = {
  KEY: "narvalis_owner_v1",
  all() { try { return JSON.parse(localStorage.getItem(this.KEY) || "{}"); } catch { return {}; } },
  save(id, tok) { if (!tok) return; const a = this.all(); a[id] = tok; try { localStorage.setItem(this.KEY, JSON.stringify(a)); } catch { } },
  hdr(id) { const t = this.all()[id]; return t ? { "X-Narvalis-Owner": t } : {}; },
};
function parseQuery(q) {
  const m = q.trim().match(/^([+-]?\d+(?:\.\d+)?)[\s,]+([+-]?\d+(?:\.\d+)?)$/);
  return m ? { ra_deg: Number(m[1]), dec_deg: Number(m[2]) } : { target_name: q.trim() };
}
$("#advBtn").onclick = () => { const a = $("#adv"); a.hidden = !a.hidden; $("#advBtn").setAttribute("aria-expanded", String(!a.hidden)); };
$("#form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (S.mode !== "live") { toast(S.mode === "static" ? "This is the static demo: it shows analyses computed beforehand from real SPHEREx data. Running a new analysis needs the Narvalis server (see the README)." : "The Narvalis server is not answering, so no new analysis can start.", 7000); return; }
  const q = $("#q").value;
  if (!q.trim()) { $("#q").focus(); return; }
  const num = (id) => { const v = $(id).value.trim(); return v === "" ? null : Number(v); };
  const body = { ...parseQuery(q), max_frames: num("#maxFrames"), cutout_size_arcsec: num("#size"),
    n_controls: num("#controls") ?? 2, use_gaia: $("#useGaia").checked };
  $("#adv").hidden = true; $("#run").disabled = true; stop();
  if (isPhone()) setSection("sky");
  $("#lTarget").textContent = q.trim();
  showLoader(0, "Submitting");
  try {
    const r = await fetch(`${API}/jobs`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const j = await r.json();
    if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail));
    Owner.save(j.job_id, j.owner_token);
    poll(j.job_id);
  } catch (err) { fail(err.message); }
});

function fail(msg) {
  hideLoader(true); $("#run").disabled = false; setSteps($("#lmsg").textContent, "fail");
  const e = $("#empty"); e.hidden = false;
  const full = String(msg || "failed"), head = full.split(/\.\s|\s\|\s/)[0].replace(/^\w+(Error|Exception):\s*/, "");
  const short = head.length > 150 ? `${head.slice(0, 147)}…` : head;
  e.replaceChildren(el("div", { class: "dot big", style: "color:var(--red)" }, "FAILED"), el("p", {}, short));
  if (short.length < full.length - 2) { const det = el("details", { class: "errdetail" }); det.append(el("summary", {}, "Technical detail"), el("pre", {}, full.replace(/\. Tried: /, ".\n\nTried:\n").replaceAll(" | ", "\n"))); e.append(det); }
  // the stage no longer shows the previous analysis: clear its frame labels so nothing looks like current data
  $("#stamp").textContent = ""; $("#overlay").replaceChildren(); $("#crumb1").textContent = "SKY / SPHEREx"; $("#coordTxt").textContent = "RA —  DEC —";
  // network-type failures: say so plainly and point to the built-in reachability check (no data was shown or invented)
  $("#storyMini").hidden = true;
  const hint = failHint(full);
  if (hint) e.append(el("p", { class: "hint" }, hint));
  setProv(null);
}

/* plain-language reason for a failed job, read from the server's own error text (nothing is guessed beyond it) */
function failHint(m) {
  const code = m.match(/\b(50[0-4])\b\s*(?:Server Error|Proxy Error|Bad Gateway|Service Unavailable|Gateway Time)/i);
  const host = (m.match(/https?:\/\/([^/\s:]+)/) || [])[1] || "archive";
  if (code) return `The archive server ${host} answered with HTTP ${code[1]} (server-side error), also after automatic retries. Your internet connection works; the archive is down or overloaded. No data is shown. Try again in a few minutes.`;
  if (/returned no SPHEREx images/i.test(m) && !/failed/i.test(m)) return "IRSA answered correctly but has no SPHEREx exposure covering this position yet. No data is shown.";
  if (/could not resolve/i.test(m)) return "The name could not be resolved (SIMBAD / Sesame). Check the spelling, enter RA Dec in degrees instead, or run  python -m epochlab.cli diagnose";
  if (/connect|timeout|unreachable|network|SSL|proxy|getaddrinfo/i.test(m)) return "An archive could not be reached from this computer, so no data is available. Check the internet connection, then run  python -m epochlab.cli diagnose";
  return "";
}

/* ---------- data provenance: real archive data, simulated test data, or nothing ---------- */
function setProv(kind) {
  const k = kind || "";
  const [cls, short, long] =
    /^REAL/.test(k) ? ["real", "REAL · IRSA", "Real SPHEREx data from NASA/IPAC IRSA"]
    : /^INJECTED/.test(k) ? ["inj", "REAL + INJECTED", "Real cutouts with an injected synthetic source"]
    : /SYNTHETIC/i.test(k) ? ["syn", "SIMULATED", "Simulated test data, not astronomical data"]
    : ["none", "NO DATA", "No data loaded"];
  for (const [id, txt] of [["#prov", short], ["#provCard", long], ["#provHead", short]]) {
    const b = $(id); if (!b) continue;
    b.className = `prov${id === "#provCard" ? " inline" : id === "#provHead" ? " head" : ""} ${cls}`;
    b.title = k || long; b.querySelector("span").textContent = txt;
  }
}

async function poll(id) {
  $("#run").disabled = true; showLoader(0, "Queued");
  await pollLoop(id);
}
async function pollLoop(id) {
  for (;;) {
    let st;
    try { st = await getJSON(`${API}/jobs/${id}/status.json`); } catch { await sleep(1500); continue; }
    if (st.state === "done") {
      showLoader(1, "Done"); setSteps("", "done");
      $("#loader").classList.add("jump"); Warp.finale();       // the result loads while the jump plays
      $("#run").disabled = false; await loadJobs(); return loadJob(id);
    }
    if (st.state === "failed") { $("#lmsg").textContent = st.message; fail(st.message || "failed"); loadJobs(); return; }
    showLoader(st.progress || 0, st.message || st.state);
    await sleep(800);
  }
}

/* ---------- load a dossier ---------- */
async function loadJob(id) {
  stop();
  const d = await getJSON(`${API}/jobs/${id}/dossier.json`);
  if (S.job !== id) Zoom.reset();
  S.job = id; S.d = d; location.hash = `job=${id}`;
  S.frames = d.frames.map((f, i) => ({ ...f, i })).filter((f) => f.status === "ok" && f.display && f.display.png);
  S.idx = 0;
  hideLoader(); setSteps("", "done");
  document.querySelectorAll("#jobs li").forEach((li) => li.classList.toggle("on", li.dataset.id === id));
  const t = d.target, ref = t.reference;
  $("#crumb1").textContent = `SKY / SPHEREx ${d.archive.collections.join(" + ").toUpperCase()}`;
  $("#tname").textContent = t.name || "Custom position";
  { // phone header: target name + what the time series is
    const ok = d.frames.filter((f) => f.status === "ok"), mj = ok.map((f) => f.time_mjd);
    const span = mj.length > 1 ? (Math.max(...mj) - Math.min(...mj)) / 365.25 : 0;
    $("#ptName").textContent = t.name || "Custom position";
    const kind = /^REAL/.test(d.data_kind) ? (/INJECT/.test(d.data_kind) ? "REAL + INJECTED" : "REAL") : /SYNTH/i.test(d.data_kind) ? "SIMULATED" : "DATA ?";
    $("#ptSky").textContent = `${kind} · SPHEREx ${d.archive.collections.join(" + ").replace(/spherex_/ig, "").toUpperCase()} · ${d.frames.length} exp · ${fmt(span, 1)} yr`;
    $("#ptRes").textContent = `${kind} · ${(d.verdicts || []).some((x) => x.check === "distance_from_parallax") ? "four" : "three"} answers`;
    document.body.classList.add("has-d");
  }
  $("#tsub").textContent = `SPHEREx · ${d.archive.collections.join(" + ")}`;
  $("#sRa").textContent = `${fmt(t.query_position_deg[0], 4)}°`;
  $("#sDec").textContent = `${t.query_position_deg[1] >= 0 ? "+" : ""}${fmt(t.query_position_deg[1], 4)}°`;
  $("#sDist").textContent = ref && ref.parallax_mas > 0 ? `${fmt(3.26156 / (ref.parallax_mas / 1000), 2)} ly` : "—";
  $("#sDist").title = ref && ref.parallax_mas > 0 ? `1/parallax, ${ref.source}` : "no parallax in reference";
  const k = $("#kind"); k.textContent = d.data_kind; k.className = `kind ${d.data_kind.startsWith("REAL") ? "" : "syn"}`;
  setProv(d.data_kind);
  renderVerdicts(); renderKV(); renderStrip(); renderFilm(); renderTimeline(); renderCaveats(); exportsOn(); renderStory();
  const e = $("#empty");
  e.hidden = S.frames.length > 0;
  if (!S.frames.length) e.replaceChildren(el("div", { class: "dot big" }, "NO FRAMES"), el("p", {}, "No measurable frames for this target. The dossier lists the reason for each exposure."));
  showFrame(0);
  aladinGoto(t.query_position_deg[0], t.query_position_deg[1]);
}

function renderVerdicts() {
  const ul = $("#verdicts"); ul.replaceChildren();
  for (const v of S.d.verdicts) {
    const li = el("li", { title: v.rule });
    li.append(el("span", { class: "c" }, v.check.replaceAll("_", " ")), el("span", { class: `r ${v.result.split(" ")[0]}` }, v.result), el("span", { class: "d" }, v.detail));
    ul.append(li);
  }
}

/* ---------- story: the three answers in plain words (Focus view on desktop, first screen of RESULTS on phones) ----------
   Every number here is read from the dossier; nothing is computed that the panels do not already show. */
const GOOD = /^(PASS|CONSISTENT|YES|NO EVIDENCE|MEASURED)$/, BAD = /FAIL|INCONSISTENT/;
function verdictOf(k) { return ((S.d.verdicts || []).find((x) => x.check === k) || {}).result || ""; }
function renderStory() {
  const d = S.d, box = $("#story"), mini = $("#storyMini");
  if (!d) { box.hidden = mini.hidden = true; return; }
  const m = d.results.motion || {}, r = d.target.reference, v = d.results.variability || { bins: [] };
  const okFrames = d.frames.filter((f) => f.status === "ok");
  const tmin = Math.min(...okFrames.map((f) => f.time_mjd)), tmax = Math.max(...okFrames.map((f) => f.time_mjd));
  const flagsOff = d.frames.some((f) => (f.warnings || []).some((w) => /flags not interpreted/.test(w)));
  const node = (tag, cls, text) => el(tag, cls ? { class: cls } : {}, text);
  const card = (k, title, big, sub, chip, chipCls) => {
    const c = node("article", `sc sc-${k}`); c.style.setProperty("--d", `${["motion", "bright", "dist", "trust"].indexOf(k) * 90}ms`);
    const h = node("div", "sc-h"); h.append(node("span", "label", title));
    if (chip) h.append(node("span", `chip ${chipCls || ""}`, chip));
    const b = node("div", "sc-big dot", big); b.dataset.final = big;
    c.append(h, b, node("p", "sc-sub", sub)); return c;
  };
  // 1 · motion
  const tot = m.ok ? Math.hypot(m.pmra_masyr, m.pmdec_masyr) / 1000 : null;
  const cat = r && r.pm_known !== false && r.pmra_masyr != null ? Math.hypot(r.pmra_masyr, r.pmdec_masyr) / 1000 : null;
  const pv = verdictOf("proper_motion_vs_catalogue"), md = verdictOf("motion_detected");
  const mChip = pv === "CONSISTENT" ? ["matches Gaia", "ok"] : pv === "INCONSISTENT" ? ["differs from Gaia", "bad"] : md === "YES" ? ["moving", ""] : md ? ["no motion detected", ""] : ["not measured", "off"];
  const c1 = card("motion", "Does it move?", tot != null ? `${fmt(tot, 2)}″/yr` : "—",
    tot != null ? `measured over ${m.n_epochs} exposures in ${fmt(m.time_span_yr, 2)} yr${cat != null ? ` · Gaia DR3 says ${fmt(cat, 2)}″/yr` : ""}${m.z_pmra != null ? ` · difference ${fmt(Math.hypot(m.z_pmra, m.z_pmdec), 1)}σ` : ""}` : (m.reason || "not enough measured exposures"), ...mChip);
  // direction compass: N up, E left (as in the viewer); white dashed = Gaia, red = measured with its 1σ circle
  if (tot != null) {
    const sv = svgEl("svg", { viewBox: "-1.2 -1.2 2.4 2.4", class: "sc-vis", "aria-hidden": "true" });
    const L = Math.max(tot, cat || 0) * 1000, sc = (x) => x / L;
    sv.append(svgEl("circle", { cx: 0, cy: 0, r: 1, fill: "none", stroke: "#ffffff22", "stroke-width": 0.02, "stroke-dasharray": "0.03 0.06" }));
    sv.append(svgEl("text", { x: 0, y: -1.06, "text-anchor": "middle", "font-size": 0.18, fill: "#8b8b8b" }, "N"), svgEl("text", { x: -1.1, y: 0.06, "text-anchor": "middle", "font-size": 0.18, fill: "#8b8b8b" }, "E"));
    if (cat != null) sv.append(svgEl("line", { x1: 0, y1: 0, x2: -sc(r.pmra_masyr), y2: -sc(r.pmdec_masyr), stroke: "#fff", "stroke-width": 0.05, "stroke-dasharray": "0.08 0.07", "stroke-linecap": "round", class: "draw" }));
    const ex = -sc(m.pmra_masyr), ey = -sc(m.pmdec_masyr);
    sv.append(svgEl("circle", { cx: ex, cy: ey, r: Math.max(0.03, sc(Math.hypot(m.pmra_err, m.pmdec_err) / Math.SQRT2)), fill: "#d7192133", stroke: "#d71921", "stroke-width": 0.02 }));
    sv.append(svgEl("line", { x1: 0, y1: 0, x2: ex, y2: ey, stroke: "#d71921", "stroke-width": 0.07, "stroke-linecap": "round", class: "draw" }));
    sv.append(svgEl("circle", { cx: 0, cy: 0, r: 0.05, fill: "#fff" }));
    c1.append(sv);
  }
  // 2 · brightness
  const vv = verdictOf("variability_matched_wavelength");
  const worst = v.bins.length ? Math.max(...v.bins.map((b) => b.max_over_min || 1)) : null;
  const poss = vv.startsWith("POSSIBLE"), possWhy = poss ? vv.replace(/^POSSIBLE \(|\)$/g, "") : "";
  const c2 = card("bright", "Does its brightness change?", vv === "VARIABLE" ? "varies" : vv === "NO EVIDENCE" ? "steady" : poss ? "maybe" : "—",
    v.bins.length ? `compared only between exposures at the same wavelength · ${v.bins.length} λ bins${worst ? ` · largest spread ×${fmt(worst, 2)}` : ""}` : "no wavelength bin has two or more exposures",
    ...(vv === "VARIABLE" ? ["variable", "warn"] : vv === "NO EVIDENCE" ? ["no evidence", "ok"] : poss ? [`possible · ${possWhy}`, ""] : ["not tested", "off"]));
  if (v.bins.length) {   // one bar per λ bin: height = max/min flux ratio inside the bin (1 = constant), colour = λ
    const sv = svgEl("svg", { viewBox: "0 0 100 40", preserveAspectRatio: "none", class: "sc-vis bars", "aria-hidden": "true" });
    const top = Math.max(2, ...v.bins.map((b) => b.max_over_min || 1)), n = v.bins.length, w = 100 / n;
    sv.append(svgEl("line", { x1: 0, y1: 39.5, x2: 100, y2: 39.5, stroke: "#ffffff33", "stroke-width": 1, "vector-effect": "non-scaling-stroke" }));
    v.bins.forEach((b, i) => {
      const hgt = 4 + 34 * ((b.max_over_min || 1) - 1) / (top - 1), lam = (b.lambda_um_min + b.lambda_um_max) / 2;
      const rect = svgEl("rect", { x: i * w + w * 0.2, y: 40 - hgt, width: w * 0.6, height: hgt, fill: lamColor(lam), rx: 0.6, class: "grow" });
      rect.style.setProperty("--i", i); sv.append(rect);
    });
    c2.append(sv);
  }
  // 3 · distance, from SPHEREx alone (5-parameter fit). Shown only for dossiers that carry the check.
  const dv = (d.verdicts || []).find((x) => x.check === "distance_from_parallax");
  let c4 = null;
  if (dv) {
    const pf = (m.parallax_fit) || {}, gp = pf.catalogue_parallax_mas;
    const gaiaTxt = gp ? ` · Gaia DR3 says ${fmt(1000 / gp, gp > 100 ? 2 : 0)} pc` : "";
    if (dv.result === "MEASURED" || dv.result === "INCONSISTENT") {
      const dist = 1000 / pf.parallax_mas;
      c4 = card("dist", "How far is it?", `${fmt(dist, dist < 10 ? 1 : 0)} pc`,
        `parallax ${fmt(pf.parallax_mas, 0)} ± ${fmt(pf.parallax_err_mas, 0)} mas from SPHEREx alone, ${fmt(pf.significance, 1)}σ${gaiaTxt}`,
        ...(dv.result === "MEASURED" ? (gp ? ["matches Gaia", "ok"] : ["measured", "ok"]) : ["differs from Gaia", "bad"]));
      // the annual parallax ellipse: red = fitted from SPHEREx, white dashed = Gaia; dots = visits (offset and
      // proper motion removed) with 1-sigma bars. North up, east left, as in the viewer.
      const pl = pf.plot;
      if (pl && pl.unit_ellipse && pl.visits && pl.visits.length) {
        const ue = pl.unit_ellipse, P = pf.parallax_mas;
        const ext = Math.max(...ue.map(([x, y]) => Math.hypot(x, y))) * Math.max(P, gp || 0);
        // scale set by the ellipse and the dots; long error bars may run off the edge
        const L = Math.max(1.35 * ext, 1.1 * Math.max(...pl.visits.map((v) => Math.hypot(v[1], v[2]))));
        const sc = (x) => x / L;
        const sv = svgEl("svg", { viewBox: "-1.2 -1.2 2.4 2.4", class: "sc-vis", "aria-hidden": "true" });
        sv.append(svgEl("text", { x: 0, y: -1.06, "text-anchor": "middle", "font-size": 0.18, fill: "#8b8b8b" }, "N"),
          svgEl("text", { x: -1.1, y: 0.06, "text-anchor": "middle", "font-size": 0.18, fill: "#8b8b8b" }, "E"));
        const path = (k) => "M" + ue.map(([x, y]) => `${(-sc(x * k)).toFixed(4)},${(-sc(y * k)).toFixed(4)}`).join("L") + "Z";
        if (gp) sv.append(svgEl("path", { d: path(gp), fill: "none", stroke: "#fff", "stroke-width": 0.035, "stroke-dasharray": "0.08 0.07", class: "draw" }));
        sv.append(svgEl("path", { d: path(P), fill: "none", stroke: "#d71921", "stroke-width": 0.05, class: "draw" }));
        for (const [, dx, dy, ex, ey] of pl.visits) {
          const cx = -sc(dx), cy = -sc(dy);
          sv.append(svgEl("line", { x1: cx - sc(ex), y1: cy, x2: cx + sc(ex), y2: cy, stroke: "#ffffff88", "stroke-width": 0.02 }),
            svgEl("line", { x1: cx, y1: cy - sc(ey), x2: cx, y2: cy + sc(ey), stroke: "#ffffff88", "stroke-width": 0.02 }),
            svgEl("circle", { cx, cy, r: 0.045, fill: "#fff" }));
        }
        sv.append(svgEl("circle", { cx: 0, cy: 0, r: 0.03, fill: "#8b8b8b" }));
        c4.append(sv);
      }
    } else if (dv.result === "NOT DETECTED") {
      c4 = card("dist", "How far is it?", `> ${fmt(pf.distance_lower_limit_pc_3sigma, 0)} pc`,
        `no parallax detected in SPHEREx alone (3σ limit)${gaiaTxt}`, "too far to measure", "");
    } else {
      const why = (dv.detail.split("; ").slice(1).join(" · ")) || dv.detail;
      c4 = card("dist", "How far is it?", "—", `${dv.result === "NOT RELIABLE" ? "not trusted: " : ""}${why}${gaiaTxt}`,
        dv.result === "NOT RELIABLE" ? "not reliable" : "not measured", "off");
    }
  }
  // 4 · trust
  const vs = d.verdicts || [], pass = vs.filter((x) => GOOD.test(x.result)).length, bad = vs.filter((x) => BAD.test(x.result)).length;
  const c3 = card("trust", "Can I trust it?", `${pass}/${vs.length}`,
    `${d.data_kind.startsWith("REAL") ? "real SPHEREx exposures from NASA/IPAC IRSA" : d.data_kind} · ${okFrames.length} measured · ${mjdToDate(tmin)} → ${mjdToDate(tmax)}`,
    ...(bad ? [`${bad} need${bad > 1 ? "" : "s"} attention`, "bad"] : ["all checks pass", "ok"]));
  const dots = node("div", "sc-dots");
  vs.forEach((x, i) => { const dd = el("button", { type: "button", class: `vd ${BAD.test(x.result) ? "bad" : GOOD.test(x.result) ? "good" : ""}`, title: `${x.check.replaceAll("_", " ")}: ${x.result} — ${x.detail}` }); dd.style.setProperty("--i", i); dd.onclick = () => openDetails("checks"); dots.append(dd); });
  c3.append(dots);
  if (flagsOff) c3.append(node("p", "sc-warn", "Measured before pixel flags were read (saturated pixels were used). Run this target again for final numbers."));
  const more = el("button", { type: "button", class: "sc-more", id: "detailsBtn" }, document.body.classList.contains("details") && isPhone() ? "Hide full analysis" : "Full analysis →");
  more.onclick = () => {
    if (isPhone() && document.body.classList.contains("details")) { document.body.classList.remove("details"); more.textContent = "Full analysis →"; return; }
    openDetails("motion");
  };
  box.replaceChildren(...[c1, c2, c4, c3].filter(Boolean), more); box.hidden = false;
  // count-up of the big numbers (decoration; the final text is set immediately for screen readers and copy)
  if (!matchMedia("(prefers-reduced-motion: reduce)").matches) box.querySelectorAll(".sc-big").forEach((b) => {
    const t = b.dataset.final, mm = t.match(/^([\d.]+)(.*)$/); if (!mm) return;
    const target = parseFloat(mm[1]), dec = (mm[1].split(".")[1] || "").length, t0 = performance.now();
    const step = (now) => { const k = Math.min(1, (now - t0) / 900), e = 1 - (1 - k) ** 3; b.textContent = (target * e).toFixed(dec) + mm[2]; if (k < 1) requestAnimationFrame(step); else b.textContent = t; };
    requestAnimationFrame(step);
  });
  // phones: three tappable chips under the viewer
  mini.replaceChildren();
  for (const [lab, val, cls, tab] of [["MOTION", mChip[0], mChip[1], "motion"], ["BRIGHTNESS", vv ? (poss ? "possible" : vv.toLowerCase()) : "—", vv === "VARIABLE" ? "warn" : "", "bright"], ["CHECKS", `${pass}/${vs.length}`, bad ? "bad" : "ok", "checks"]]) {
    const c = el("button", { type: "button", class: `smc ${cls}` }); c.append(el("span", { class: "label" }, lab), el("b", {}, val));
    c.onclick = () => { setSection("results"); if (tab !== "motion") openDetails(tab); }; mini.append(c);
  }
  mini.hidden = false;
}
/* from the summary to the detailed panels: on phones the details unfold under the story, on desktop Focus closes */
function openDetails(tab) {
  if (isPhone()) { document.body.classList.add("details"); $("#detailsBtn") && ($("#detailsBtn").textContent = "Hide full analysis"); }
  else if (document.body.classList.contains("focus")) setFocus(false);
  const t = document.querySelector(`.tabs button[data-tab="${tab}"]`); if (t) t.click();
  const card = document.querySelector(".right .card");
  if (card && isPhone()) setTimeout(() => card.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
}

/* ---------- Focus view (desktop): the viewer and the three answers; everything else one click away ---------- */
function setFocus(on) {
  if (isPhone()) return;
  on = on === undefined ? !document.body.classList.contains("focus") : on;
  let restore = null;
  try { restore = localStorage.getItem("epochlab_focus_restore"); } catch { }
  if (on) {
    if (window.EpochCockpit && EpochCockpit.active) { restore = "cockpit"; EpochCockpit.setMode("classic"); }
    document.body.classList.add("focus");
  } else {
    document.body.classList.remove("focus");
    if (restore === "cockpit" && window.EpochCockpit) EpochCockpit.setMode("cockpit");
    restore = null;
  }
  try { localStorage.setItem("epochlab_focus_v1", on ? "1" : "0"); restore ? localStorage.setItem("epochlab_focus_restore", restore) : localStorage.removeItem("epochlab_focus_restore"); } catch { }
  const b = $("#focusBtn"); b.setAttribute("aria-pressed", String(on)); b.classList.toggle("on", on);
  b.title = on ? "Leave Focus view (V)" : "Focus view: the image and the key answers, nothing else (V)";
  setTimeout(() => { fitLayout(); if (S.d) reflow(); }, 80);
}
$("#focusBtn").onclick = () => setFocus();
$("#dispBtn").onclick = () => { const on = document.body.classList.toggle("disp-open"); $("#dispBtn").setAttribute("aria-expanded", String(on)); $("#dispBtn").textContent = on ? "Hide display options" : "Display options"; };

function renderKV() {
  const m = S.d.results.motion, r = S.d.target.reference, v = S.d.results.variability;
  const fill = (dl, rows) => { dl.replaceChildren(); for (const [a, b] of rows) { const d = el("div"); d.append(el("dt", {}, a), el("dd", {}, b)); dl.append(d); } };
  const tot = m.ok ? Math.hypot(m.pmra_masyr, m.pmdec_masyr) / 1000 : null;
  fill($("#kvMotion"), [
    ["µ MEASURED", tot !== null ? `${fmt(tot, 2)}″/yr` : "—"],
    ["µ CATALOGUE", r ? `${fmt(Math.hypot(r.pmra_masyr, r.pmdec_masyr) / 1000, 2)}″/yr` : "—"],
    ["DIFFERENCE", m.z_pmra !== null && m.z_pmra !== undefined ? `${fmt(m.z_pmra, 1)}σ · ${fmt(m.z_pmdec, 1)}σ` : "—"],
    ["EPOCHS · SPAN", m.ok ? `${m.n_epochs} · ${fmt(m.time_span_yr, 2)} yr` : (m.reason || "—")],
    ["FIELD-STAR CAL.", (() => { const c = S.d.results.calibration || {}; return c.enabled ? `${c.frames_calibrated}/${c.frames_usable} exp · ${fmt(c.median_stars_per_frame, 0)}★` : "off"; })()],
    ["CONTROL STARS", (() => { const c = S.d.results.controls || {}; return c.n_stars ? `${c.n_stars} · ${fmt(100 * c.frac_abs_z_gt_3, 0)}% |z|>3` : "—"; })()],
  ]);
  const verdict = (S.d.verdicts.find((x) => x.check === "variability_matched_wavelength") || {}).result || "—";
  fill($("#kvBright"), [
    ["VARIABILITY", verdict.toLowerCase()],
    ["p (CONSTANT)", v.combined_p_value !== null && v.combined_p_value !== undefined ? v.combined_p_value.toExponential(1) : "—"],
    ["λ BINS USED", `${v.bins.length}`],
    ["χ² / DOF", v.combined_dof ? `${fmt(v.combined_chi2, 1)} / ${v.combined_dof}` : "—"],
  ]);
  const bad = S.d.verdicts.filter((x) => /FAIL|INCONSISTENT/.test(x.result)).length;
  const b = $("#checkBadge"); b.textContent = bad ? `${bad}/${S.d.verdicts.length}` : `${S.d.verdicts.length}`;
  b.title = bad ? `${bad} of ${S.d.verdicts.length} checks need attention (FAIL or INCONSISTENT)` : `${S.d.verdicts.length} checks, none failing`; b.className = `badge ${bad ? "bad" : ""}`;
  const mb = $("#mBadge"); mb.hidden = !bad; mb.textContent = String(bad);
}

/* filmstrip under the viewer: every exposure as a real thumbnail, λ colour bar and date; replaces the tiny ticks
   as the main way to pick a frame (the tick timeline stays for the true time spacing) */
const MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
function shortDate(m) { const d = new Date((m - 40587) * 86400000); return `${String(d.getUTCDate()).padStart(2, "0")} ${MON[d.getUTCMonth()]} ${String(d.getUTCFullYear()).slice(2)}`; }
function renderFilm() {
  const film = $("#film"); film.replaceChildren();
  S.frames.forEach((f, k) => {
    const b = el("button", { type: "button", role: "option", "aria-selected": "false",
      title: `${k + 1}/${S.frames.length} · ${mjdToIso(f.time_mjd)} · λ ${fmt(f.wavelength_um, 3)} µm${f.centroid && f.centroid.ok ? "" : " · not measured"}` });
    const im = el("span", { class: "fi" }); im.style.background = tintFor(f);
    im.append(el("img", { alt: "", loading: "lazy", decoding: "async", src: `${API}/jobs/${S.job}/${f.display.png}` }));
    const bar = el("span", { class: "fb" }); bar.style.background = lamColor(f.wavelength_um);
    b.append(im, bar, el("span", { class: "fd" }, shortDate(f.time_mjd)));
    if (!(f.centroid && f.centroid.ok)) b.classList.add("nm");
    b.onclick = () => { stop(); showFrame(k); };
    film.append(b);
  });
}
function markFilm() {
  const film = $("#film"), list = film.children;
  const lock = $("#lockBin").checked;
  for (let i = 0; i < list.length; i++) {
    const on = i === S.idx; list[i].classList.toggle("on", on); list[i].setAttribute("aria-selected", String(on));
    list[i].classList.toggle("off", lock && !inSameBin(i));          // "same λ": other wavelength bins fade
  }
  $("#filmCount").textContent = S.frames.length ? `${S.idx + 1} / ${S.frames.length}` : "";
  const cur = list[S.idx];
  if (cur && film.clientWidth) {
    const left = cur.offsetLeft - film.clientWidth / 2 + cur.clientWidth / 2;
    film.scrollTo({ left, behavior: S.timer || matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }
}

function renderStrip() {
  const s = $("#strip"); s.replaceChildren();
  $("#seqCount").textContent = S.frames.length ? `${S.frames.length} epochs` : "";
  S.frames.forEach((f, k) => {
    const b = el("button", { type: "button", title: `${mjdToIso(f.time_mjd)} · λ ${fmt(f.wavelength_um, 3)} µm` });
    const sw = el("span", { class: "sw" });
    sw.style.background = tintFor(f);
    sw.append(el("img", { alt: "", loading: "lazy", src: `${API}/jobs/${S.job}/${f.display.png}` }));
    b.append(sw, document.createTextNode(mjdToDate(f.time_mjd)));
    b.onclick = () => { stop(); showFrame(k); };
    s.append(b);
  });
}

/* angular scale bar, bottom right; drawn outside the zoomed layer so it stays put and shows the true scale at any zoom */
function drawScaleBar() {
  const svg = $("#scalebar"); svg.replaceChildren();
  if (!S.d || !S.frames.length) return;
  const g = S.d.display_grid, fov = g.n * g.pix_arcsec, z = Zoom.level;
  const ns = { "vector-effect": "non-scaling-stroke" };
  const arcsec = [60, 30, 20, 10, 5, 2, 1].find((a) => (a / fov) * z <= 0.24) || 1;
  const L = (arcsec / fov) * z, y = 0.93, x1 = 0.96 - L;
  svg.append(svgEl("line", { x1, y1: y, x2: 0.96, y2: y, stroke: "#fff", "stroke-width": 2, ...ns }));
  for (const xx of [x1, 0.96]) svg.append(svgEl("line", { x1: xx, y1: y - 0.012, x2: xx, y2: y + 0.012, stroke: "#fff", "stroke-width": 1.5, ...ns }));
  svg.append(svgEl("text", { x: 0.96 - L / 2, y: y - 0.02, "text-anchor": "middle", fill: "#fff", "font-size": 0.03, stroke: "#000", "stroke-width": 3, "paint-order": "stroke", style: "font-family:var(--mono)", ...ns }, `${arcsec}″`));
}

/* ---------- zoom & pan of the frame (display only: the same real pixels, enlarged; nothing is re-measured) ---------- */
const Zoom = (() => {
  const port = $("#zoomport"), zm = $("#zoomer"), MAX = 16;
  let s = 1, tx = 0, ty = 0;
  const pts = new Map(); let pinch = null, pan = null, lastTap = 0, lastTapXY = [0, 0], moved = false;
  function apply(anim) {
    zm.style.transition = anim ? "transform .28s cubic-bezier(.2,.9,.3,1)" : "none";
    zm.style.transform = `translate(${tx}px, ${ty}px) scale(${s})`;
    $("#zLvl").textContent = s < 1.02 ? "1×" : `${s < 9.95 ? s.toFixed(1) : Math.round(s)}×`;
    port.classList.toggle("zoomed", s > 1.02); $("#zoomctl").classList.toggle("zoomed", s > 1.02);
    port.style.touchAction = s > 1.02 ? "none" : "pan-y";
    drawScaleBar();
    if (S.d && S.frames[S.idx]) drawOverlay(S.frames[S.idx]);
  }
  function clamp() { const w = port.clientWidth, h = port.clientHeight; tx = Math.min(0, Math.max(w - w * s, tx)); ty = Math.min(0, Math.max(h - h * s, ty)); }
  function at(ns, px, py, anim) {
    ns = Math.max(1, Math.min(MAX, ns));
    tx = px - (px - tx) * (ns / s); ty = py - (py - ty) * (ns / s); s = ns; clamp(); apply(anim);
  }
  const centre = () => [port.clientWidth / 2, port.clientHeight / 2];
  const local = (e) => { const r = port.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  port.addEventListener("wheel", (e) => {
    if (!S.frames.length) return;
    e.preventDefault();
    const [x, y] = local(e); at(s * Math.exp(-Math.max(-60, Math.min(60, e.deltaY)) * 0.004), x, y, false);
  }, { passive: false });
  let touchZoomAt = 0;
  port.addEventListener("dblclick", (e) => {
    if (performance.now() - touchZoomAt < 600) return;          // already handled as a touch double-tap
    const [x, y] = local(e); s > 1.5 ? at(1, x, y, true) : at(4, x, y, true);
  });
  port.addEventListener("pointerdown", (e) => {
    if (!S.frames.length) return;
    port.setPointerCapture(e.pointerId); pts.set(e.pointerId, local(e)); moved = false;
    if (pts.size === 2) { const [a, b] = [...pts.values()]; pinch = { d: Math.hypot(a[0] - b[0], a[1] - b[1]), s }; pan = null; }
    else if (pts.size === 1 && s > 1.02) pan = { x: e.clientX, y: e.clientY, tx, ty };
  });
  port.addEventListener("pointermove", (e) => {
    if (!pts.has(e.pointerId)) return;
    pts.set(e.pointerId, local(e));
    if (pinch && pts.size === 2) {
      const [a, b] = [...pts.values()], d = Math.hypot(a[0] - b[0], a[1] - b[1]);
      at(pinch.s * d / Math.max(1, pinch.d), (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, false); moved = true;
    } else if (pan) {
      tx = pan.tx + e.clientX - pan.x; ty = pan.ty + e.clientY - pan.y;
      if (Math.hypot(e.clientX - pan.x, e.clientY - pan.y) > 3) moved = true;
      clamp(); apply(false); port.classList.add("panning");
    }
  });
  const up = (e) => {
    const was = pts.get(e.pointerId); pts.delete(e.pointerId);
    if (pts.size < 2) pinch = null;
    if (!pts.size) { pan = null; port.classList.remove("panning"); }
    // double-tap on touch screens (dblclick is not reliable there)
    if (e.pointerType === "touch" && was && !moved && e.type === "pointerup") {
      const now = performance.now();
      if (now - lastTap < 320 && Math.hypot(was[0] - lastTapXY[0], was[1] - lastTapXY[1]) < 30) { s > 1.5 ? at(1, ...was, true) : at(4, ...was, true); lastTap = 0; touchZoomAt = now; }
      else { lastTap = now; lastTapXY = was; }
    }
  };
  port.addEventListener("pointerup", up); port.addEventListener("pointercancel", up);
  $("#zIn").onclick = () => at(s * 1.6, ...centre(), true);
  $("#zOut").onclick = () => at(s / 1.6, ...centre(), true);
  $("#zLvl").onclick = () => at(1, ...centre(), true);
  addEventListener("resize", () => { clamp(); apply(false); });
  return { get level() { return s; }, get state() { const w = port.clientWidth || 1, h = port.clientHeight || 1; return { s, fx: tx / w, fy: ty / h }; }, reset: () => { s = 1; tx = 0; ty = 0; apply(false); }, in: () => at(s * 1.6, ...centre(), true), out: () => at(s / 1.6, ...centre(), true), one: () => at(1, ...centre(), true) };
})();

/* ---------- research mode: sky coordinates under the cursor, and pins fixed on the sky ----------
   The viewer images are resampled onto one gnomonic (TAN) grid centred on the target's query position
   (pipeline: render.common_wcs); these two functions are its exact inverse/forward (checked against astropy). */
const D2R = Math.PI / 180;
function gridGeom() {
  if (!S.d || !S.d.display_grid) return null;
  const g = S.d.display_grid, q = S.d.target.query_position_deg;
  return { n: g.n, s: g.pix_arcsec / 3600, ra0: q[0] * D2R, de0: q[1] * D2R, c: (g.n - 1) / 2 };
}
function fracToSky(fx, fy) {
  const w = gridGeom(); if (!w) return null;
  const xi = -((fx * w.n - 0.5) - w.c) * w.s * D2R, eta = (((1 - fy) * w.n - 0.5) - w.c) * w.s * D2R;
  const den = Math.cos(w.de0) - eta * Math.sin(w.de0);
  const ra = w.ra0 + Math.atan2(xi, den), dec = Math.atan2(eta * Math.cos(w.de0) + Math.sin(w.de0), Math.hypot(xi, den));
  return [((ra / D2R) % 360 + 360) % 360, dec / D2R];
}
function skyToFrac(ra, dec) {
  const w = gridGeom(); if (!w) return null;
  ra *= D2R; dec *= D2R;
  const cc = Math.sin(w.de0) * Math.sin(dec) + Math.cos(w.de0) * Math.cos(dec) * Math.cos(ra - w.ra0); if (cc <= 0) return null;
  const xi = Math.cos(dec) * Math.sin(ra - w.ra0) / cc, eta = (Math.cos(w.de0) * Math.sin(dec) - Math.sin(w.de0) * Math.cos(dec) * Math.cos(ra - w.ra0)) / cc;
  return [((w.c - xi / D2R / w.s) + 0.5) / w.n, 1 - ((w.c + eta / D2R / w.s) + 0.5) / w.n];
}
const hms = (ra) => { const h = ra / 15, H = Math.floor(h), m = (h - H) * 60, M = Math.floor(m), sec = (m - M) * 60; return `${String(H).padStart(2, "0")}h${String(M).padStart(2, "0")}m${sec.toFixed(2).padStart(5, "0")}s`; };
const dms = (dec) => { const sg = dec < 0 ? "−" : "+", a = Math.abs(dec), D = Math.floor(a), m = (a - D) * 60, M = Math.floor(m), sec = (m - M) * 60; return `${sg}${String(D).padStart(2, "0")}°${String(M).padStart(2, "0")}′${sec.toFixed(1).padStart(4, "0")}″`; };
const fmtSky = (ra, dec) => `RA ${ra.toFixed(5)}°  Dec ${dec >= 0 ? "+" : ""}${dec.toFixed(5)}°`;

const Pins = (() => {
  const KEY = "narvalis_pins_v1";
  let list = [], mode = false, cat = null;
  try { list = JSON.parse(localStorage.getItem(KEY) || "[]").filter((p) => isFinite(p.ra) && isFinite(p.dec)); } catch { }
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(list.slice(-200))); } catch { } };
  function add(ra, dec, src, label) {
    const n = list.reduce((m, p) => Math.max(m, +String(p.label).replace(/\D/g, "") || 0), 0) + 1;
    const p = { id: `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 5)}`, ra, dec, label: label || `P${n}`, src, near: S.d ? (S.d.target.name || "") : "", t: new Date().toISOString().slice(0, 16).replace("T", " ") };
    list.push(p); save(); changed(); haptic("light");
    toast(`${p.label} pinned · ${fmtSky(ra, dec)}`, 4000, { label: "Copy", fn: () => copy(p) });
    return p;
  }
  function remove(id) { list = list.filter((p) => p.id !== id); save(); changed(); }
  function copy(p) { const t = `${p.ra.toFixed(6)} ${p.dec.toFixed(6)}`; try { navigator.clipboard.writeText(t); toast(`Copied: ${t}`); } catch { toast(t, 6000); } }
  function changed() {
    $("#pinCount").hidden = !list.length; $("#pinCount").textContent = list.length;
    renderList(); if (S.d && S.frames[S.idx]) drawOverlay(S.frames[S.idx]); mapLayer();
  }
  function renderList() {
    const ul = $("#pinsList"); $("#pinsBox").hidden = !list.length; ul.replaceChildren();
    [...list].reverse().forEach((p) => {
      const li = el("li", { class: "pin" }), info = el("div", { class: "pin-info" });
      info.append(el("b", {}, p.label), el("span", { class: "mono" }, `${p.ra.toFixed(5)}  ${p.dec >= 0 ? "+" : ""}${p.dec.toFixed(5)}`), el("small", {}, `${hms(p.ra)} ${dms(p.dec)}${p.near ? ` · near ${p.near}` : ""}`));
      const acts = el("div", { class: "pin-acts" });
      const b = (txt, title, fn) => { const x = el("button", { type: "button", title }, txt); x.onclick = (e) => { e.stopPropagation(); fn(); }; acts.append(x); };
      b("Copy", "Copy RA Dec in degrees", () => copy(p));
      b("Map", "Show on the sky map", () => { if (!SkyBig.layer) skyBig(true); setTimeout(() => { try { S.aladin.gotoRaDec(p.ra, p.dec); S.aladin.setFoV(0.1); } catch { } }, 250); });
      b("Analyse", "Run a SPHEREx analysis at this position", () => { $("#q").value = `${p.ra.toFixed(5)} ${p.dec.toFixed(5)}`; if (SkyBig.layer) skyBig(false); if (isPhone()) setSection("targets"); $("#q").focus(); toast("Coordinates in the search box — press the arrow to analyse this position."); });
      b("×", "Remove this pin", () => remove(p.id));
      li.append(info, acts); ul.append(li);
    });
  }
  function draw(svg, Z) {
    const box = $("#pinLabels"); box.replaceChildren();
    if (!list.length || !gridGeom()) return;
    const ns = { "vector-effect": "non-scaling-stroke" };
    for (const p of list) {
      const f = skyToFrac(p.ra, p.dec); if (!f) continue;
      const q = Z(f); if (q[0] < -0.02 || q[0] > 1.02 || q[1] < -0.02 || q[1] > 1.02) continue;
      const r = 0.022;
      svg.append(svgEl("path", { d: `M${q[0]} ${q[1] - r}L${q[0] + r} ${q[1]}L${q[0]} ${q[1] + r}L${q[0] - r} ${q[1]}Z`, fill: "none", stroke: "#000", "stroke-width": 4, "stroke-opacity": 0.7, ...ns }));
      svg.append(svgEl("path", { d: `M${q[0]} ${q[1] - r}L${q[0] + r} ${q[1]}L${q[0]} ${q[1] + r}L${q[0] - r} ${q[1]}Z`, fill: "none", stroke: "#e3c27f", "stroke-width": 1.8, ...ns }));
      const lab = el("span", { class: "pinlab" }, p.label); lab.style.left = `${q[0] * 100}%`; lab.style.top = `${q[1] * 100}%`; box.append(lab);
    }
  }
  function mapLayer() {
    try {
      const A = aladinLib; if (!S.aladin || !A) return;
      if (!cat) { cat = A.catalog({ name: "Pins", sourceSize: 14, color: "#e3c27f", shape: "rhomb", displayLabel: true, labelColumn: "name", labelColor: "#e3c27f", labelFont: "12px Space Mono" }); S.aladin.addCatalog(cat); }
      cat.removeAll && cat.removeAll();
      if (list.length) cat.addSources(list.map((p) => A.source(p.ra, p.dec, { name: p.label })));
    } catch { }
  }
  // viewer: readout under the pointer; in pin mode a click/tap (not a drag) drops a pin
  const port = $("#zoomport"), rd = $("#cursorRd");
  const at = (e) => { const r = port.getBoundingClientRect(), z = Zoom.state; const u = (e.clientX - r.left) / r.width, v = (e.clientY - r.top) / r.height; return fracToSky((u - z.fx) / z.s, (v - z.fy) / z.s); };
  port.addEventListener("pointermove", (e) => { if (e.pointerType !== "mouse" || !S.d) return; const sk = at(e); if (!sk) return; rd.hidden = false; rd.textContent = `${fmtSky(...sk)}  ·  ${hms(sk[0])} ${dms(sk[1])}`; });
  port.addEventListener("pointerleave", () => { rd.hidden = true; });
  let down = null;
  port.addEventListener("pointerdown", (e) => { down = mode ? [e.clientX, e.clientY] : null; });
  port.addEventListener("pointerup", (e) => {
    if (!mode || !down || !S.d) return; const moved = Math.hypot(e.clientX - down[0], e.clientY - down[1]); down = null;
    if (moved > 6) return; const sk = at(e); if (sk) add(sk[0], sk[1], "viewer");
  });
  function setMode(on) { mode = on === undefined ? !mode : on; $("#zPin").setAttribute("aria-pressed", String(mode)); $("#zPin").classList.toggle("on", mode); port.classList.toggle("pinning", mode); if (mode) toast("Pin mode: click or tap the image to mark a sky position. Press the pin again to stop.", 4500); }
  $("#zPin").onclick = () => setMode();
  addEventListener("keydown", (e) => { if ((e.key === "p" || e.key === "P") && !e.target.closest("input,textarea") && S.d) setMode(); });
  $("#pinsClear").onclick = () => { const old = list; list = []; save(); changed(); toast(`${old.length} pins cleared.`, 7000, { label: "Undo", fn: () => { list = old; save(); changed(); } }); };
  setTimeout(changed, 0);
  return { add, remove, draw, mapLayer, get list() { return list; }, setMode };
})();

/* full screen: the whole viewer column (image, transport, timeline). Falls back to a fixed overlay where the
   Fullscreen API is missing (iPhone Safari). */
function viewerFull(on) {
  const col = $("#stage").closest(".col.center") || $("#stage").closest(".stage-wrap");
  const native = document.fullscreenElement !== undefined && col.requestFullscreen;
  const isOn = document.fullscreenElement === col || col.classList.contains("pseudo-full");
  on = on === undefined ? !isOn : on;
  if (native) { if (on && !isOn) col.requestFullscreen().catch(() => col.classList.add("pseudo-full")); else if (!on && document.fullscreenElement) document.exitFullscreen(); }
  if (!native || !on) col.classList.toggle("pseudo-full", on && !native);
  setTimeout(() => { if (S.d) reflow?.(); }, 120);
}
$("#zFull").onclick = () => viewerFull();
document.addEventListener("fullscreenchange", () => { $("#zFull").classList.toggle("on", !!document.fullscreenElement); setTimeout(() => S.d && typeof reflow === "function" && reflow(), 120); });

/* small charts */
function chart(svg, series, { W, H, ylab = "", zero = false, logy = false, xfmt = (v) => v.toFixed(2) }) {
  svg.replaceChildren();
  // draw in real screen pixels when the chart is visible, so it fills its box without distorting text
  const r = svg.getBoundingClientRect();
  if (r.width > 40 && r.height > 40 && !isPhone()) { W = r.width; H = r.height; }
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  if (logy) { // plot log10(y); error bars become asymmetric in log space
    series = series.map((s) => ({ ...s, points: s.points.filter((p) => p.y > 0).map((p) => {
      const lo = Math.log10(Math.max(p.y - (p.e || 0), p.y * 0.05)), hi = Math.log10(p.y + (p.e || 0));
      return { ...p, y: Math.log10(p.y), e: (hi - lo) / 2, _log: true };
    }) }));
  }
  const L = 30, R = 6, T = 10, B = 16;
  const pts = series.flatMap((s) => s.points);
  if (!pts.length) { svg.append(svgEl("text", { x: W / 2, y: H / 2, "text-anchor": "middle" }, "no data")); return; }
  const xs = pts.map((p) => p.x), ys = pts.flatMap((p) => [p.y - (p.e || 0), p.y + (p.e || 0)]);
  let x0 = Math.min(...xs), x1 = Math.max(...xs); if (x1 === x0) { x0 -= 0.1; x1 += 0.1; }
  let y0 = Math.min(...ys, zero ? 0 : Infinity), y1 = Math.max(...ys, zero ? 0 : -Infinity); if (y1 === y0) { y0 -= 1; y1 += 1; }
  const pad = (y1 - y0) * 0.08; y0 -= pad; y1 += pad;
  const X = (x) => L + (x - x0) / (x1 - x0) * (W - L - R), Y = (y) => T + (1 - (y - y0) / (y1 - y0)) * (H - T - B);
  for (let gx = L; gx <= W - R; gx += 8) for (let gy = T; gy <= H - B; gy += 8) svg.append(svgEl("circle", { cx: gx, cy: gy, r: 0.35, fill: "#333" }));
  if (zero && y0 < 0 && y1 > 0) svg.append(svgEl("line", { x1: L, x2: W - R, y1: Y(0), y2: Y(0), stroke: "#555", "stroke-dasharray": "1 2" }));
  const short = (v) => (Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(0)}k` : Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(1));
  for (const v of [y0 + pad, y1 - pad]) svg.append(svgEl("text", { x: L - 4, y: Y(v) + 3, "text-anchor": "end" }, logy ? short(10 ** v) : short(v)));
  for (const v of [x0, x1]) svg.append(svgEl("text", { x: X(v), y: H - 3, "text-anchor": v === x0 ? "start" : "end" }, xfmt(v)));
  if (ylab) svg.append(svgEl("text", { x: L, y: 7 }, ylab));
  for (const s of series) {
    if (s.line && s.points.length > 1) {
      const sorted = [...s.points].sort((a, b) => a.x - b.x);
      svg.append(svgEl("polyline", { points: sorted.map((p) => `${X(p.x)},${Y(p.y)}`).join(" "), fill: "none", stroke: s.color, "stroke-opacity": 0.5, "stroke-width": 1 }));
    }
    for (const p of s.points) {
      const c = p.color || s.color;
      if (p.e) svg.append(svgEl("line", { x1: X(p.x), x2: X(p.x), y1: Y(p.y - p.e), y2: Y(p.y + p.e), stroke: c, "stroke-opacity": 0.55 }));
      const dot = svgEl("circle", { cx: X(p.x), cy: Y(p.y), r: p.cur ? 3.6 : 2, fill: c, stroke: p.cur ? "#d71921" : "none", "stroke-width": 1.6, style: "cursor:pointer" });
      if (p.frame !== undefined) dot.onclick = () => { stop(); showFrame(p.frame); };
      svg.append(dot);
    }
  }
}

function renderResiduals() {
  const a = [], b = [];
  S.frames.forEach((f, k) => {
    const c = f.centroid; if (!c || !c.ok || !c.offset_from_prediction_arcsec) return;
    const x = mjdToYear(f.time_mjd), cur = k === S.idx;
    a.push({ x, y: c.offset_from_prediction_arcsec[0], e: c.sigma_ra_arcsec, frame: k, cur });
    b.push({ x, y: c.offset_from_prediction_arcsec[1], e: c.sigma_dec_arcsec, frame: k, cur });
  });
  chart($("#resid"), [{ points: a, color: "#5cc8e6" }, { points: b, color: "#f2b84b" }], { W: 400, H: 130, ylab: "Δα* cyan · Δδ amber", zero: true });
}

function renderLC() {
  const w = S.d.settings.wavelength_bin_rel, groups = {};
  S.frames.forEach((f, k) => {
    const p = f.photometry; if (!p || !p.ok) return;
    const b = lamBin(f.wavelength_um, w);
    (groups[b] ||= []).push({ x: mjdToYear(f.time_mjd), y: p.flux_ujy, e: p.flux_err_ujy, color: lamColor(f.wavelength_um), frame: k, cur: k === S.idx });
  });
  chart($("#lc"), Object.values(groups).map((pts) => ({ points: pts, color: pts[0].color, line: true })), { W: 400, H: 150, ylab: "" });
}

const timeColor = (f) => { // cyan (first epoch) → amber (last epoch)
  const a = [92, 200, 230], b = [242, 184, 75];
  return `rgb(${a.map((v, k) => Math.round(v + f * (b[k] - v)))})`;
};
function renderSED() {
  const sed = S.d.results.sed, dl = $("#kvSed");
  const fill = (rows) => { dl.replaceChildren(); for (const [a, b] of rows) { const d = el("div"); d.append(el("dt", {}, a), el("dd", {}, b)); dl.append(d); } };
  if (!sed || !sed.n) {
    fill([["POINTS", "0"], ["λ RANGE", "—"]]); $("#sedChart").replaceChildren(); $("#sedNote").textContent = "No photometry available for this target."; return;
  }
  const ts = sed.points.map((p) => p.time_mjd), t0 = Math.min(...ts), t1 = Math.max(...ts), span = Math.max(t1 - t0, 1e-6);
  const cur = S.frames[S.idx] ? S.frames[S.idx].i : -1;
  const frameOf = new Map(S.frames.map((f, k) => [f.i, k]));
  const pts = sed.points.map((p) => ({ x: p.lambda_um, y: p.flux_ujy, e: p.flux_err_ujy, color: timeColor((p.time_mjd - t0) / span),
    frame: frameOf.get(p.index), cur: p.index === cur }));
  const ys = pts.map((p) => p.y).filter((v) => v > 0);
  const logy = ys.length > 1 && Math.max(...ys) / Math.min(...ys) > 20;
  chart($("#sedChart"), [{ points: pts, color: "#ccc" }], { W: 400, H: 170, ylab: logy ? "log scale" : "", logy, xfmt: (v) => `${v.toFixed(2)} µm` });
  fill([
    ["POINTS", `${sed.n} epochs`],
    ["λ RANGE", `${sed.lambda_range_um[0].toFixed(2)}–${sed.lambda_range_um[1].toFixed(2)} µm`],
    ["NEGATIVE / ≤0", `${sed.points.filter((p) => p.flux_ujy <= 0).length}`],
    ["SCALE", logy ? "log" : "linear"],
  ]);
  $("#sedT0").textContent = mjdToDate(t0); $("#sedT1").textContent = mjdToDate(t1);
  $("#sedNote").textContent = sed.caveat;
}

function renderTimeline() {
  const tl = $("#timeline"); tl.replaceChildren();
  if (!S.frames.length) return;
  const t0 = S.frames[0].time_mjd, t1 = S.frames[S.frames.length - 1].time_mjd || t0 + 1, span = Math.max(t1 - t0, 1);
  const pos = (t) => 1 + 98 * (t - t0) / span;
  S.frames.forEach((f, k) => {
    const d = el("div", { class: "tick", title: `${mjdToIso(f.time_mjd)} · λ=${fmt(f.wavelength_um, 3)} µm` });
    d.style.left = `${pos(f.time_mjd)}%`; d.style.background = lamColor(f.wavelength_um);
    d.onclick = () => { stop(); showFrame(k); }; tl.append(d);
  });
  for (let y = Math.ceil(mjdToYear(t0) * 2) / 2; y <= mjdToYear(t1); y += 0.5) {
    const l = el("div", { class: "lab" }, y.toFixed(1)); l.style.left = `${pos((y - 1858.877) * 365.25)}%`; tl.append(l);
  }
}

/* ---------- timeline lens: ticks swell under the pointer (dock-style) and a preview card shows the frame ----------
   Mouse: hover to preview, click to open. Touch: press and slide to scrub, lift to open. */
const Lens = (() => {
  const tl = $("#timeline");
  const card = el("div", { class: "tl-card", role: "tooltip" }); card.hidden = true; document.body.append(card);
  let near = -1, touching = false;
  function ticks() { return [...tl.querySelectorAll(".tick")]; }
  function update(clientX) {
    const r = tl.getBoundingClientRect(), list = ticks();
    if (!list.length) return;
    let best = -1, bd = 1e9;
    list.forEach((t, i) => {
      const tr = t.getBoundingClientRect(), cx = tr.left + tr.width / 2, d = Math.abs(cx - clientX);
      const k = Math.exp(-((d / 26) ** 2));                     // gaussian swell, ~26 px wide
      t.style.setProperty("--sw", (1 + 2.4 * k).toFixed(3)); t.style.setProperty("--sh", (1 + 0.9 * k).toFixed(3));
      if (d < bd) { bd = d; best = i; }
    });
    tl.classList.add("lens");
    if (bd > 140) { hideCard(); return; }        // snaps to the nearest exposure, even across gaps
    list.forEach((t, i) => t.classList.toggle("hot", i === best));
    if (best !== near) { near = best; fill(best); }
    const tr = list[best].getBoundingClientRect(), cw = card.offsetWidth || 180, ch = card.offsetHeight || 210;
    card.style.left = `${Math.max(8, Math.min(innerWidth - cw - 8, tr.left + tr.width / 2 - cw / 2))}px`;
    card.style.top = `${Math.max(8, r.top - ch - 12)}px`;
  }
  function fill(k) {
    const f = S.frames[k]; if (!f) return;
    const src = `${API}/jobs/${S.job}/${f.display.png}`;
    const box = el("div", { class: "tl-img" }); box.style.background = tintFor(f); box.append(el("img", { alt: "", src }));
    const m1 = el("div", { class: "tl-meta" }); m1.append(el("b", {}, `${k + 1}/${S.frames.length}`), el("span", {}, mjdToIso(f.time_mjd).slice(0, 16)));
    const sw = el("span", { class: "sw" }); sw.style.background = lamColor(f.wavelength_um);
    const m2 = el("div", { class: "tl-meta" }); m2.append(sw, el("span", {}, `λ ${fmt(f.wavelength_um, 3)} µm`), el("span", { class: "dim" }, f.centroid && f.centroid.ok ? "measured" : "not measured"));
    card.replaceChildren(box, m1, m2);
    card.hidden = false; requestAnimationFrame(() => card.classList.add("on"));
  }
  function hideCard() { card.classList.remove("on"); card.hidden = true; near = -1; ticks().forEach((t) => t.classList.remove("hot")); }
  function reset() { hideCard(); tl.classList.remove("lens"); ticks().forEach((t) => { t.style.removeProperty("--sw"); t.style.removeProperty("--sh"); }); }
  tl.addEventListener("pointermove", (e) => { if (e.pointerType === "mouse" || touching) update(e.clientX); });
  tl.addEventListener("pointerleave", (e) => { if (e.pointerType === "mouse") reset(); });
  tl.addEventListener("pointerdown", (e) => {
    if (e.pointerType === "mouse") return;
    touching = true; tl.setPointerCapture(e.pointerId); update(e.clientX); e.preventDefault();
  });
  const end = (e) => {
    if (!touching) return;
    touching = false; const k = near; reset();
    if (k >= 0 && e.type === "pointerup") { stop(); showFrame(k); }
  };
  tl.addEventListener("pointerup", end); tl.addEventListener("pointercancel", end);
  return { reset };
})();

const tintFor = (f) => ($("#tintOn").checked ? lamColor(f.wavelength_um) : "#fff");
const inSameBin = (k) => { const w = S.d.settings.wavelength_bin_rel; return lamBin(S.frames[k].wavelength_um, w) === lamBin(S.frames[S.idx].wavelength_um, w); };

function showFrame(k) {
  if (!S.frames.length) return;
  S.idx = (k + S.frames.length) % S.frames.length;
  const f = S.frames[S.idx], disp = f.display, diff = S.view === "diff";
  if (S.d) { setProv(S.d.data_kind); $("#empty").hidden = true; }   // frames on screen always carry the label of the analysis they belong to
  const src = diff ? disp.diff_png : disp.png;
  const img = $("#frame"); img.hidden = !src;
  if (src) img.src = `${API}/jobs/${S.job}/${src}`;
  const th = $("#thumb"); th.hidden = false; th.src = `${API}/jobs/${S.job}/${disp.png}`;
  $("#thumbbox").style.background = tintFor(f);
  // difference images are signed (grey = no change): never tint them
  $("#imgbox").style.background = diff ? "#fff" : tintFor(f);
  $("#fcBadge").hidden = !($("#tintOn").checked && !diff);
  const st = diff ? disp.diff_stretch : disp.stretch;
  const sig = (v) => (Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 1 ? v.toFixed(2) : v.toPrecision(2));
  $("#cbGrad").className = diff ? "signed" : "";
  $("#cbLo").textContent = st ? sig(st.vmin) : "—";
  $("#cbHi").textContent = st ? sig(st.vmax) : "—";
  $("#cbUnit").textContent = st ? `MJy/sr · ${st.type}${diff ? " · Δ between epochs" : ""}` : "";
  $("#cbScope").textContent = st && st.scope ? `intensity scale ${st.scope}` : "";
  $("#specmark").style.left = f.wavelength_um > 0 ? `${(lamFrac(f.wavelength_um) * 100).toFixed(1)}%` : "-10px";
  if (!src) {
    const e = $("#empty"); e.hidden = false;
    const kids = [el("div", { class: "dot big" }, "NO PAIR"), el("p", {}, disp.diff_note || "No image")];
    if (diff) {   // jump to the nearest later exposure that does have a same-wavelength partner
      const n = S.frames.length, nxt = [...Array(n - 1)].map((_, k) => (S.idx + 1 + k) % n).find((k) => S.frames[k].display && S.frames[k].display.diff_png);
      if (nxt !== undefined) {
        const b = el("button", { type: "button", class: "nopair-next" }, `Next exposure with a pair → ${shortDate(S.frames[nxt].time_mjd)} · ${fmt(S.frames[nxt].wavelength_um, 2)} µm`);
        b.onclick = () => { stop(); showFrame(nxt); }; kids.push(b);
      }
      kids.push(el("p", { class: "nopair-why" }, "Matched-λ diff subtracts another exposure taken at the same wavelength. SPHEREx sees each star at a different wavelength on every visit, so some exposures have no partner."));
    }
    e.replaceChildren(...kids);
  }
  else $("#empty").hidden = true;
  drawOverlay(f);
  const lock = $("#lockBin").checked;
  document.querySelectorAll("#timeline .tick").forEach((t, i) => { t.classList.toggle("cur", i === S.idx); t.classList.toggle("off", lock && !inSameBin(i)); });
  document.querySelectorAll("#strip button").forEach((b, i) => b.classList.toggle("on", i === S.idx));
  const cur = document.querySelectorAll("#strip button")[S.idx], strip = $("#strip");
  if (cur) strip.scrollTo({ left: cur.offsetLeft - strip.offsetLeft - strip.clientWidth / 2 + cur.clientWidth / 2, behavior: "smooth" });
  markFilm();
  const p = f.predicted;
  $("#coordTxt").textContent = `RA ${fmt(p.ra_deg, 4)}°   DEC ${p.dec_deg >= 0 ? "+" : ""}${fmt(p.dec_deg, 4)}°`;
  $("#stamp").innerHTML = "";
  const lamDiv = el("div", { class: "st-lam" }), sw = el("i", { class: "lsw", "aria-hidden": "true" });
  sw.style.background = lamColor(f.wavelength_um);
  lamDiv.append(sw, `λ ${fmt(f.wavelength_um, 3)} µm` + (diff && disp.diff_ref_index !== undefined ? ` · − frame ${disp.diff_ref_index} (Δt ${fmt(disp.diff_dt_days, 0)} d)` : ""));
  const dt = el("div", { class: "st-date", title: mjdToIso(f.time_mjd) });
  dt.append(el("span", { class: "lg-only" }, mjdToIso(f.time_mjd)), el("span", { class: "ph-only" }, mjdToIso(f.time_mjd).slice(0, 16)));
  $("#stamp").append(dt, lamDiv);
  renderMeta(f); renderResiduals(); renderLC(); renderSED();
}

function drawOverlay(f) {
  const svg = $("#overlay"); svg.replaceChildren();
  const g = S.d.display_grid, fov = g.n * g.pix_arcsec;
  // the overlay is not scaled with the image: positions follow the zoom, marker sizes stay constant on screen,
  // and the uncertainty ellipse (a physical size) grows with it
  const z = Zoom.state, Z = (q) => q && [q[0] * z.s + z.fx, q[1] * z.s + z.fy];
  const ns = { "vector-effect": "non-scaling-stroke" };
  if ($("#showTrack").checked) {
    const pts = S.frames.map((x) => Z(x.display.pred_frac)).filter(Boolean);
    svg.append(svgEl("polyline", { points: pts.map((p) => p.join(",")).join(" "), fill: "none", stroke: "#fff", "stroke-opacity": 0.6, "stroke-width": 1.2, "stroke-dasharray": "1 4", "stroke-linecap": "round", ...ns }));
    for (const p of [pts[0], pts[pts.length - 1]]) if (p) svg.append(svgEl("circle", { cx: p[0], cy: p[1], r: 0.008, fill: "#fff", "fill-opacity": 0.8 }));
  }
  const p = Z(f.display.pred_frac);
  if (p) {
    const r = 0.06, gap = 0.016;
    for (const [x1, y1, x2, y2] of [[p[0] - r, p[1], p[0] - gap, p[1]], [p[0] + gap, p[1], p[0] + r, p[1]], [p[0], p[1] - r, p[0], p[1] - gap], [p[0], p[1] + gap, p[0], p[1] + r]])
      svg.append(svgEl("line", { x1, y1, x2, y2, stroke: "#fff", "stroke-width": 1.4, ...ns }));
    svg.append(svgEl("circle", { cx: p[0], cy: p[1], r: 0.1, fill: "none", stroke: "#fff", "stroke-opacity": 0.5, "stroke-width": 1, "stroke-dasharray": "1 3", ...ns }));
  }
  drawScaleBar();
  Pins.draw(svg, Z);
  const m = Z(f.display.meas_frac), c = f.centroid;
  if (m && c && c.ok) {
    const rx = Math.max(c.sigma_ra_arcsec / fov * z.s, 0.008), ry = Math.max(c.sigma_dec_arcsec / fov * z.s, 0.008);
    // dark halo under the red marker keeps it legible on red-tinted (long-λ) frames
    svg.append(svgEl("circle", { cx: m[0], cy: m[1], r: 0.045, fill: "none", stroke: "#000", "stroke-opacity": 0.8, "stroke-width": 4.5, ...ns }));
    svg.append(svgEl("circle", { cx: m[0], cy: m[1], r: 0.045, fill: "none", stroke: "#fff", "stroke-width": 2.6, ...ns }));
    svg.append(svgEl("circle", { cx: m[0], cy: m[1], r: 0.045, fill: "none", stroke: "#d71921", "stroke-width": 1.6, ...ns }));
    svg.append(svgEl("ellipse", { cx: m[0], cy: m[1], rx, ry, fill: "#fff", "fill-opacity": 0.35, stroke: "#d71921", "stroke-width": 1.2, ...ns }));
  }
}

function renderMeta(f) {
  const dl = $("#meta"); dl.replaceChildren();
  const c = f.centroid || {}, o = f.observation, dlx = f.download || {};
  const rows = [
    ["frame", `${S.idx + 1}/${S.frames.length} (index ${f.i})`], ["obs_id", o.obs_id], ["collection", o.collection],
    ["time (UTC)", `${mjdToIso(f.time_mjd)} [${f.time_source}]`], ["λ / Δλ", `${fmt(f.wavelength_um, 4)} / ${fmt(f.bandwidth_um, 4)} µm`],
    ["detector", f.detector ?? "—"],
    ["centroid", c.ok ? `S/N ${fmt(c.snr, 1)} · σ ${fmt(c.sigma_ra_arcsec)}″, ${fmt(c.sigma_dec_arcsec)}″` : `not used: ${c.reason}`],
    ["offset vs catalogue", c.offset_from_prediction_arcsec ? `${fmt(c.offset_from_prediction_arcsec[0])}″, ${fmt(c.offset_from_prediction_arcsec[1])}″${c.calibrated ? " (calibrated)" : ""}` : "—"],
    ["exposure offset", f.astrometric_calibration && f.astrometric_calibration.ok ? `${fmt(f.astrometric_calibration.offset_arcsec[0])}″, ${fmt(f.astrometric_calibration.offset_arcsec[1])}″ from ${f.astrometric_calibration.n_stars} Gaia stars` : "not calibrated"],
    ["flags rejected", (f.flags_rejected || []).join(", ") || "none defined"], ["flagged px in stamp", f.n_flagged_in_stamp],
    ["photometry", f.photometry && f.photometry.ok ? `${fmt(f.photometry.flux_ujy, 1)} ± ${fmt(f.photometry.flux_err_ujy, 1)} µJy (${f.photometry.method || "aperture"})` : (f.photometry || {}).reason],
    ["sha256", (dlx.sha256 || "").slice(0, 16) + "…"],
  ];
  for (const [k, v] of rows) dl.append(el("dt", {}, k), el("dd", {}, String(v ?? "—")));
  dl.append(el("dt", {}, "source file"));
  const dd = el("dd"); dd.append(el("a", { href: o.access_url, target: "_blank", rel: "noopener" }, "IRSA original ↗")); dl.append(dd);
  if (f.warnings && f.warnings.length) dl.append(el("dt", {}, "warnings"), el("dd", {}, f.warnings.join(" · ")));
}

function renderCaveats() { const ul = $("#caveats"); ul.replaceChildren(); S.d.caveats.forEach((c) => ul.append(el("li", {}, c))); }

function exportsOn() {
  const a = $("#dlDossier"); a.href = `${API}/jobs/${S.job}/dossier.json`; a.download = `narvalis_${S.job}.json`; a.removeAttribute("aria-disabled");
  $("#dlCsv").removeAttribute("aria-disabled");
  const z = $("#dlBundle");
  if (S.mode === "live") { z.href = `${API}/jobs/${S.job}/bundle.zip`; z.removeAttribute("aria-disabled"); }
  else { z.removeAttribute("href"); z.setAttribute("aria-disabled", "true"); }
}
$("#dlCsv").onclick = () => {
  if (!S.d) return;
  const hdr = ["index", "obs_id", "mjd", "lambda_um", "pred_ra", "pred_dec", "meas_ra", "meas_dec", "sig_ra_arcsec", "sig_dec_arcsec", "snr", "flux_ujy", "flux_err_ujy", "sha256", "url"];
  const lines = [hdr.join(",")];
  for (const f of S.d.frames.filter((f) => f.status === "ok")) {
    const c = f.centroid, p = f.photometry;
    lines.push([f.index, f.observation.obs_id, f.time_mjd, f.wavelength_um, f.predicted.ra_deg, f.predicted.dec_deg,
      c.ok ? c.ra_deg : "", c.ok ? c.dec_deg : "", c.ok ? c.sigma_ra_arcsec : "", c.ok ? c.sigma_dec_arcsec : "", c.snr ?? "",
      p.ok ? p.flux_ujy : "", p.ok ? p.flux_err_ujy : "", f.download.sha256, `"${f.download.url}"`].join(","));
  }
  const a = el("a", { href: URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" })), download: `narvalis_${S.job}_epochs.csv` }); a.click();
};

/* ---------- playback ---------- */
function step(dir) {
  if (!S.frames.length) return;
  let k = S.idx;
  for (let n = 0; n < S.frames.length; n++) { k = (k + dir + S.frames.length) % S.frames.length; if (!$("#lockBin").checked || inSameBin(k)) break; }
  showFrame(k);
}
function play() { stop(); $("#play").classList.add("playing"); $("#play").setAttribute("aria-label", "Pause"); S.timer = setInterval(() => step(1), 1000 / Number($("#fps").value)); }
function stop() { clearInterval(S.timer); S.timer = null; const b = $("#play"); if (b) { b.classList.remove("playing"); b.setAttribute("aria-label", "Play"); } }
$("#play").onclick = () => (S.timer ? stop() : play());
$("#prev").onclick = () => { stop(); step(-1); };
$("#next").onclick = () => { stop(); step(1); };
$("#fps").oninput = () => { $("#fpsVal").textContent = $("#fps").value; if (S.timer) play(); };
$("#lockBin").onchange = () => showFrame(S.idx);
$("#showTrack").onchange = () => showFrame(S.idx);
$("#tintOn").onchange = () => { document.querySelectorAll("#strip .sw").forEach((sw, i) => (sw.style.background = tintFor(S.frames[i]))); document.querySelectorAll("#film .fi").forEach((sw, i) => (sw.style.background = tintFor(S.frames[i]))); showFrame(S.idx); };
document.querySelectorAll(".seg button").forEach((b) => (b.onclick = () => {
  document.querySelectorAll(".seg button").forEach((x) => x.classList.toggle("on", x === b));
  S.view = b.dataset.view; showFrame(S.idx);
}));
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT") return;
  if (e.key === " ") { e.preventDefault(); S.timer ? stop() : play(); }
  if (e.key === "ArrowRight") { stop(); step(1); }
  if (e.key === "ArrowLeft") { stop(); step(-1); }
  if (e.key === "d") document.querySelector(`.seg button[data-view=${S.view === "raw" ? "diff" : "raw"}]`).click();
  if (e.key === "+" || e.key === "=") Zoom.in();
  if (e.key === "-" || e.key === "_") Zoom.out();
  if (e.key === "0") Zoom.one();
  if (e.key === "f" || e.key === "F") viewerFull();
  if (e.key === "v" || e.key === "V") setFocus();
  if (e.key === "Escape") viewerFull(false);
});
$("#helpBtn").onclick = () => window.EpochTour && EpochTour.start();

/* ---------- fit the layout to the screen ---------- */
// The viewer is square: the centre column is exactly as wide as the viewer can be tall (within limits),
// and the evidence panel takes all remaining width.
function fitLayout() {
  const lay = document.querySelector(".layout");
  if (!lay) return;
  if (isPhone() || document.body.classList.contains("ck")) { lay.style.removeProperty("--centerw"); return; }
  const u = parseFloat(getComputedStyle(document.querySelector(".shell")).getPropertyValue("--gap")) / 16 || 1;
  const wrap = document.querySelector(".stage-wrap");
  const h = wrap.getBoundingClientRect().height;
  const left = document.querySelector(".left");
  const leftW = getComputedStyle(left).display === "none" ? 0 : left.getBoundingClientRect().width;
  const total = lay.getBoundingClientRect().width;
  const gaps = 2 * 16 * u;
  const minRight = 400 * u, minCenter = 640 * u;
  const w = Math.max(minCenter, Math.min(h, total - leftW - gaps - minRight));
  lay.style.setProperty("--centerw", `${Math.floor(w)}px`);
}
const reflow = () => { fitLayout(); if (S.d) { renderResiduals(); renderLC(); renderSED(); } };
let rT = null;
// the cockpit layout moved or resized modules: redraw charts at their new size and keep the sky view centred
addEventListener("epochlab:layout", () => { reflow(); try { if (S.aladin && S.d) S.aladin.gotoRaDec(...S.d.target.query_position_deg); } catch { } });
addEventListener("resize", () => { clearTimeout(rT); rT = setTimeout(reflow, 80); });
document.addEventListener("click", (e) => { if (e.target.closest(".tabs button")) setTimeout(reflow, 0); });

/* ---------- phone sections (bottom navigation) ---------- */
const PHONE_MQ = "(max-width:760px), (max-width:1100px) and (orientation:portrait)";
const isPhone = () => matchMedia(PHONE_MQ).matches;
function setSection(m) {
  document.body.dataset.m = m;
  document.querySelectorAll(".mnav button").forEach((b) => b.classList.toggle("on", b.dataset.m === m));
  if (isPhone()) window.scrollTo({ top: 0, behavior: "instant" });
  // the sky widget cannot measure itself while hidden: re-fit it once its section is visible
  if (m === "targets" && S.d) setTimeout(() => { window.dispatchEvent(new Event("resize")); aladinGoto(...S.d.target.query_position_deg); }, 60);
}
function placeSearch() {
  const f = $("#form"), slot = $("#heroSlot");
  if (isPhone()) { if (f.parentElement !== slot) slot.append(f); $("#q").placeholder = "Barnard's Star · 269.45 4.69"; }
  else if (f.parentElement === slot) { $("#ptitle").after(f); $("#q").placeholder = "Barnard's Star  ·  or  269.4521 4.6934"; }
}
placeSearch(); matchMedia(PHONE_MQ).addEventListener("change", placeSearch);
window.setSection = setSection;
document.querySelectorAll(".mnav button").forEach((b) => (b.onclick = () => setSection(b.dataset.m)));
// the tour asks us to reveal whichever section holds the element it wants to show
window.revealForTour = (el) => {
  if (!isPhone() || !el) return;
  if (el.closest(".left")) setSection("targets");
  else if (el.closest(".right")) setSection("results");
  else if (el.closest(".center")) setSection("sky");
};

/* ---------- evidence tabs ---------- */
function selectTab(name) {
  if (document.body.classList.contains("ck")) { document.querySelectorAll(".panel").forEach((p) => p.classList.add("on")); return; }
  document.querySelectorAll(".tabs button").forEach((b) => { const on = b.dataset.tab === name; b.classList.toggle("on", on); b.setAttribute("aria-selected", String(on)); });
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("on", p.dataset.panel === name));
}
window.selectTab = selectTab;
document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => selectTab(b.dataset.tab)));

/* ---------- Sky context: Aladin Lite + 2MASS (orientation only; not SPHEREx data) ---------- */
// Aladin Lite is bundled in web/vendor (LGPL-3.0) so it does not depend on a CDN; only the 2MASS
// image tiles are fetched from CDS by the browser. 2MASS observed 1997-2001, so for high proper-motion
// stars we mark both the catalogue position at 2MASS epoch (≈2000.0) and the position now.
const TWO_MASS_EPOCH = 2000.0;
let aladinLib = null;
async function loadAladin() {
  if (aladinLib) return aladinLib;
  try { aladinLib = (await import("./vendor/aladin-lite/aladin.js")).default; }
  catch (e) {
    console.warn("local Aladin Lite failed, trying CDS", e);
    await new Promise((res, rej) => { const s = document.createElement("script"); s.src = "https://aladin.cds.unistra.fr/AladinLite/api/v3/latest/aladin.js"; s.onload = res; s.onerror = () => rej(new Error("Aladin Lite could not be downloaded")); document.head.append(s); });
    aladinLib = window.A;
  }
  await aladinLib.init;   // throws "WebGL2 not supported by your browser" where applicable
  return aladinLib;
}
function propagateLinear(ref, yr) { // display-only linear propagation (no parallax)
  const dt = yr - ref.epoch_jyear, dec = ref.dec_deg + (ref.pmdec_masyr * dt) / 3.6e6;
  return [ref.ra_deg + (ref.pmra_masyr * dt) / 3.6e6 / Math.cos((ref.dec_deg * Math.PI) / 180), dec];
}
// 2MASS colour first; if CDS tiles cannot be fetched, fall back to DSS2 colour, then report clearly.
// Order: via our own server (works behind ad-blockers/DNS filters) → directly from CDS → DSS2 fallbacks.
const relay = (p) => new URL(`api/sky/${p}`, location.href).href;
const SKY_SURVEYS = [
  ...(location.protocol.startsWith("http") ? [[() => relay("2MASS/Color"), "2MASS 1997–2001", "live"]] : []),
  [() => "CDS/P/2MASS/color", "2MASS 1997–2001"],
  ...(location.protocol.startsWith("http") ? [[() => relay("DSS/DSSColor"), "DSS2 (photographic, 1980s–90s)", "live"]] : []),
  [() => "CDS/P/DSS2/color", "DSS2 (photographic, 1980s–90s)"],
];
function setSkySurvey(A, k) {
  const lab = $("#skySurvey");
  if (k >= SKY_SURVEYS.length) {
    lab.textContent = "sky images could not be downloaded from CDS (network or firewall) — analysis is unaffected";
    return;
  }
  const [idf, name, needsLive] = SKY_SURVEYS[k];
  if (needsLive && S.mode !== "live") return setSkySurvey(A, k + 1);
  const id = idf();
  try {
    const layer = A.imageHiPS(id, {
      successCallback: () => { lab.textContent = `${name} · not SPHEREx data`; },
      errorCallback: (e) => { console.warn("HiPS failed", id, e); setSkySurvey(A, k + 1); },
    });
    S.aladin.setImageLayer(layer);
    lab.textContent = `${name} · loading…`;
  } catch (e) { console.warn(e); setSkySurvey(A, k + 1); }
}
/* Is any sky survey reachable? Checked once, before Aladin starts: if none is, Aladin is never created,
   because a failing Aladin retries its surveys several times a second for as long as the page is open. */
let skyProbe = null, skyWhy = "";
function skyReachable() {
  const opt = () => ({ signal: AbortSignal.timeout ? AbortSignal.timeout(8000) : undefined });
  skyProbe ??= (async () => {
    if (location.protocol.startsWith("http")) {
      try {
        const r = await fetch(relay("2MASS/Color") + "/properties", opt());
        if (r.ok) return true;
        const j = await r.json().catch(() => ({}));
        skyWhy = typeof j.detail === "string" ? j.detail.replace(/^CDS unreachable from server: /, "CDS not reachable from this computer — ") : `relay HTTP ${r.status}`;
      } catch (e) { skyWhy = "relay did not answer"; }
    }
    try { if ((await fetch("https://irsa.ipac.caltech.edu/data/hips/CDS/2MASS/Color/properties", opt())).ok) return true; } catch { }
    return false;
  })();
  return skyProbe;
}
/* sky context, enlarged: the Aladin box moves into a full-window layer and back (the widget keeps its state) */
const SkyBig = { home: null, layer: null };
function skyBig(on) {
  const box = $("#aladin"), btn = $("#skyFull");
  on = on === undefined ? !SkyBig.layer : on;
  if (on && !SkyBig.layer) {
    SkyBig.home = [box.parentElement, box.nextSibling];
    const layer = el("div", { class: "skybig", role: "dialog", "aria-modal": "true", "aria-label": "Sky context, enlarged" });
    const head = el("div", { class: "skybig-head" });
    head.append(el("span", { class: "label" }, $("#skySurvey").textContent), el("span", { class: "label dim" }, "drag to pan · scroll or pinch to zoom · Esc to close"));
    const nav = el("div", { class: "skybig-nav" }), chipsRow = el("div", { class: "skychips" });
    if (S.d) { const cur = el("button", { type: "button", class: "skychip on" }, `${S.d.target.name || "Current target"}`); cur.onclick = () => aladinGoto(...S.d.target.query_position_deg); chipsRow.append(cur); }
    document.querySelectorAll("#chips li[data-q]").forEach((li) => {
      const nm = li.querySelector("span").textContent; if (S.d && nm === S.d.target.name) return;
      const b = el("button", { type: "button", class: "skychip" }, nm); b.onclick = () => { chipsRow.querySelectorAll(".skychip").forEach((x) => x.classList.toggle("on", x === b)); skyGoto(li.dataset.ra ? nm : li.dataset.q); }; chipsRow.append(b);
    });
    const f = el("form", { class: "skysearch", role: "search" }); const inp = el("input", { type: "text", enterkeyhint: "go", autocomplete: "off", autocapitalize: "off", autocorrect: "off", spellcheck: "false", placeholder: "Go to: name or RA Dec", "aria-label": "Go to a name or RA Dec in degrees" });
    const go = el("button", { type: "submit", class: "skychip" }, "Go"); f.append(inp, go);
    f.onsubmit = (e) => { e.preventDefault(); skyGoto(inp.value); };
    const pinT = el("button", { type: "button", class: "skychip pintoggle", "aria-pressed": String(!!S.mapPin) }, "Pin on click");
    pinT.onclick = () => { S.mapPin = !S.mapPin; pinT.setAttribute("aria-pressed", String(S.mapPin)); pinT.classList.toggle("on", S.mapPin); if (S.mapPin) toast("Click the map to drop a pin; pins also show in the viewer when they fall inside it.", 4500); };
    pinT.classList.toggle("on", !!S.mapPin);
    nav.append(chipsRow, f, pinT);
    const close = el("button", { type: "button", class: "round skybig-x", "aria-label": "Close enlarged sky" }, "×");
    close.onclick = () => skyBig(false); head.append(close);
    layer.append(head, nav, box); layer.onclick = (e) => { if (e.target === layer) skyBig(false); };
    document.body.append(layer); SkyBig.layer = layer; document.body.classList.add("sky-open");
  } else if (!on && SkyBig.layer) {
    const [par, nxt] = SkyBig.home; par.insertBefore(box, nxt && nxt.parentElement === par ? nxt : null);
    SkyBig.layer.remove(); SkyBig.layer = null; document.body.classList.remove("sky-open");
  }
  btn.setAttribute("aria-pressed", String(!!SkyBig.layer));
  setTimeout(() => { window.dispatchEvent(new Event("resize")); if (S.d) aladinGoto(...S.d.target.query_position_deg); }, 60);
}
$("#skyFull").onclick = () => skyBig();
/* challenge targets on the sky map (positions from the user's own finished analyses) */
function skyMarkers() {
  try {
    const A = aladinLib; if (!S.aladin || !A) return;
    if (!S.tgtCat) { S.tgtCat = A.catalog({ name: "Challenge targets", sourceSize: 14, color: "#f2f2f2", shape: "square", displayLabel: true, labelColumn: "name", labelColor: "#f2f2f2", labelFont: "12px Space Grotesk" }); S.aladin.addCatalog(S.tgtCat); }
    S.tgtCat.removeAll && S.tgtCat.removeAll();
    const src = [...document.querySelectorAll("#chips li[data-ra]")].map((li) => A.source(+li.dataset.ra, +li.dataset.dec, { name: li.querySelector("span").textContent }));
    if (src.length) S.tgtCat.addSources(src);
  } catch { }
}
function skyGoto(q) {
  q = (q || "").trim(); if (!q || !S.aladin) return;
  const m = q.match(/^([+-]?\d+(?:\.\d+)?)[\s,]+([+-]?\d+(?:\.\d+)?)$/);
  try {
    if (m) { S.aladin.gotoRaDec(+m[1], +m[2]); Pins.add(+m[1], +m[2], "map search"); return; }
    const li = [...document.querySelectorAll("#chips li[data-q]")].find((x) => x.dataset.q.toLowerCase() === q.toLowerCase() || x.querySelector("span").textContent.toLowerCase() === q.toLowerCase());
    if (li && li.dataset.ra) { S.aladin.gotoRaDec(+li.dataset.ra, +li.dataset.dec); S.aladin.setFoV(0.15); return; }
    S.aladin.gotoObject(q, { success: () => { S.aladin.setFoV(0.15); try { const c = S.aladin.getRaDec(); Pins.add(c[0], c[1], "map search", q); } catch { } }, error: () => toast(`“${q}” was not found by the CDS name resolver. Try RA Dec in degrees.`, 5000) });
  } catch (e) { toast(`Could not move the map: ${e.message || e}`, 5000); }
}
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && SkyBig.layer) { e.stopPropagation(); skyBig(false); } }, true);

async function aladinGoto(ra, dec) {
  const box = $("#aladin"), note = $("#skyNote");
  try {
    if (!S.aladin && !(await skyReachable())) {
      const short = skyWhy.replace(/\.cds\.unistra\.fr|\.ipac\.caltech\.edu|\.esac\.esa\.int/g, "").replace(/^CDS answered /, "");
      $("#skySurvey").textContent = `sky images unavailable${short ? ` (${short.slice(0, 110)})` : ""} — orientation only, analysis is unaffected`;
      $("#skySurvey").title = skyWhy;
      box.textContent = "Sky imagery unavailable"; note.textContent = "";
      return;
    }
    const A = await loadAladin();
    if (!S.aladin) {
      box.textContent = "";
      S.aladin = A.aladin("#aladin", { fov: 0.1, showReticle: false, showLayersControl: false,
        showGotoControl: false, showFrame: false, showZoomControl: false, showFullscreenControl: false, showCooGridControl: false,
        showSimbadPointerControl: false, showProjectionControl: false, showStatusBar: false, showCooLocation: false, showSettingsControl: false, showShareControl: false });
      setSkySurvey(A, 0);
      skyMarkers(); Pins.mapLayer();
      try { S.aladin.on("click", (e) => { if (!S.mapPin || !e || e.isDragging || e.ra == null) return; Pins.add(e.ra, e.dec, "sky map"); }); } catch { }
    }
    const A_ = A, al = S.aladin, ref = S.d && S.d.target.reference;
    try { (S.skyLayers || []).forEach((l) => l.hide && l.hide()); } catch { }
    S.skyLayers = [];
    let fov = 0.08, centre = [ra, dec];
    if (ref) {
      const now = new Date().getUTCFullYear() + new Date().getUTCMonth() / 12;
      const then = propagateLinear(ref, TWO_MASS_EPOCH), cur = propagateLinear(ref, now);
      const sepDeg = Math.hypot((cur[0] - then[0]) * Math.cos((dec * Math.PI) / 180), cur[1] - then[1]);
      fov = Math.max(0.06, sepDeg * 2.6);
      centre = [(then[0] + cur[0]) / 2, (then[1] + cur[1]) / 2];
      try {
        const ov = A_.graphicOverlay({ color: "#d71921", lineWidth: 2 });
        al.addOverlay(ov); S.skyLayers.push(ov);
        if (sepDeg * 3600 > 3) ov.add(A_.polyline([then, cur]));
        const cat = A_.catalog({ name: "Narvalis", sourceSize: 16, color: "#d71921", shape: "circle" });
        al.addCatalog(cat); S.skyLayers.push(cat);
        cat.addSources([A_.source(cur[0], cur[1], { name: "now" })]);
        const cat2 = A_.catalog({ name: "2MASS epoch", sourceSize: 12, color: "#ffffff", shape: "plus" });
        al.addCatalog(cat2); S.skyLayers.push(cat2);
        cat2.addSources([A_.source(then[0], then[1], { name: "c. 2000" })]);
      } catch (e) { console.warn("sky overlays", e); }
      note.textContent = sepDeg * 3600 > 3
        ? `+ catalogue position at 2MASS epoch (≈2000) → ○ now · moved ${(sepDeg * 3600).toFixed(0)}″`
        : "○ target · moves < 3″ since 2000";
    } else if (S.d && S.d.target.name) note.textContent = "○ resolver position · no catalogue proper motion available";
    else note.textContent = "○ query position";
    al.gotoRaDec(centre[0], centre[1]); al.setFoV(fov);
    // re-apply once the survey metadata has loaded (Aladin may reset the view when the HiPS initialises)
    setTimeout(() => { try { al.gotoRaDec(centre[0], centre[1]); al.setFoV(fov); } catch { } }, 1500);
  } catch (e) {
    const msg = String((e && e.message) || e);
    box.textContent = /webgl/i.test(msg) ? "Sky context needs WebGL2, which this browser/GPU does not provide — analysis is unaffected"
      : `Sky context unavailable (${msg}) — analysis is unaffected`;
    note.textContent = "";
  }
}


/* ---------- intro presentation: what Narvalis is and why it exists (first visit, and from the About button) ----------
   Images are frames of the analysis on screen (real SPHEREx exposures); the target results are read from the
   challenge-target cards, i.e. from the user's own finished analyses. Nothing in it is invented. */
const Intro = (() => {
  const KEY = "narvalis_intro_v1";
  const SL = [
    { k: "NASA Space Apps 2026 · SPHEREx", t: "Did it move? Ask every SPHEREx epoch.",
      b: "Narvalis checks, exposure by exposure, whether a star really moves across the sky or really changes brightness — in real images from NASA’s SPHEREx mission.",
      n: "Every image is a real SPHEREx exposure downloaded from NASA/IPAC IRSA. Anything simulated is labelled as such.", fig: "hero" },
    { k: "The sky, again and again", t: "SPHEREx maps the whole sky in 102 colours, and keeps coming back.",
      b: "It covers every part of the sky about every six months. Each return is a new epoch, so the same star appears in many separate exposures taken months apart.",
      n: "The change over time is in the data, but spread over single exposures that are rarely looked at side by side.", fig: "film" },
    { k: "Why it is hard", t: "No two exposures see the star in the same colour.",
      b: "Each exposure records a slightly different wavelength. Compare the wrong pair and a colour difference looks like a brightness change. Bright stars saturate; neighbours get confused with the target.",
      n: "Narvalis compares brightness only within matched wavelength bins, reads the pixel flags and tests every result against the field stars.", fig: "lambda" },
    { k: "How it works", t: "From a name to an answer you can check.",
      b: "Type a star’s name or coordinates. Narvalis finds every SPHEREx exposure that covers it, measures it, and answers three questions: does it move, does its brightness change, and can I trust it?",
      n: "Every number links back to the exposure it came from, and the whole run can be exported and reproduced.", fig: "steps" },
    { k: "Tested on real data", t: "The challenge targets, checked against Gaia.",
      b: "Proper motions are compared with the Gaia DR3 catalogue; brightness only at matched wavelengths. Saturated or too-sparse data is reported as inconclusive, not forced into an answer.",
      n: "Results below are read from the analyses stored in this copy of Narvalis.", fig: "targets" },
  ];
  let i = 0, onClose = null, timer = 0, paused = false;
  const AUTO = 9000, reduce = matchMedia("(prefers-reduced-motion: reduce)");
  // slides advance on their own (paused while the pointer is over the intro or after any manual step); never past the last
  function arm() { clearTimeout(timer); L.classList.toggle("auto", !paused && !reduce.matches && i < SL.length - 1); if (paused || reduce.matches || i >= SL.length - 1) return; timer = setTimeout(() => { i++; render(); }, AUTO); }
  function manual() { paused = true; }
  const L = $("#intro");
  const node = (tag, cls, text) => el(tag, cls ? { class: cls } : {}, text);
  function frameUrl(f) { return f && f.display && f.display.png ? `${API}/jobs/${S.job}/${f.display.png}` : ""; }
  function fig(kind) {
    const box = $("#inFig"); box.replaceChildren(); box.className = `in-fig fig-${kind}`;
    if (kind === "hero") {
      const f = S.frames[Math.min(S.frames.length - 1, Math.floor(S.frames.length / 3))];
      if (f) {
        box.append(el("img", { src: frameUrl(f), alt: `Real SPHEREx exposure of ${S.d.target.name || "the target"}, ${mjdToDate(f.time_mjd)}` }),
          el("span", { class: "in-ret", "aria-hidden": "true" }),
          node("span", "in-cap", `REAL · SPHEREx via NASA/IPAC IRSA · ${S.d.target.name || ""} · ${mjdToDate(f.time_mjd)} · λ ${fmt(f.wavelength_um, 3)} µm`));
      } else box.append(node("span", "in-cap static", "No analysis loaded yet · images appear after the first run"));
    } else if (kind === "film") {
      const n = S.frames.length, pick = n ? [0, 1, 2, 3, 4, 5].map((k) => S.frames[Math.round((k * (n - 1)) / 5)]) : [];
      const g = node("div", "in-grid");
      pick.forEach((f) => { const c = node("div", "in-cell"); const bar = node("span", "in-bar"); bar.style.background = lamColor(f.wavelength_um);
        c.append(el("img", { src: frameUrl(f), alt: `SPHEREx exposure ${mjdToDate(f.time_mjd)}, λ ${fmt(f.wavelength_um, 3)} µm` }), bar, node("span", "in-d", `${shortDate(f.time_mjd)} · ${fmt(f.wavelength_um, 2)} µm`)); g.append(c); });
      let h = 0; clearInterval(S.inFilm); S.inFilm = setInterval(() => { if (!box.isConnected || !box.classList.contains("fig-film")) return clearInterval(S.inFilm); g.querySelectorAll(".in-cell").forEach((c, k) => c.classList.toggle("hot", k === h)); h = (h + 1) % pick.length; }, 650);
      box.append(g, node("span", "in-cap static", n ? `${pick.length} of ${n} real exposures of ${S.d.target.name || "the target"} · colour bar = wavelength` : "No analysis loaded yet"));
    } else if (kind === "lambda") {
      const bar = node("div", "in-spec"); bar.style.background = `linear-gradient(90deg, ${[0.75, 1, 1.5, 2.2, 3.2, 5].map(lamColor).join(",")})`;
      const sc = node("div", "in-scale"); sc.append(node("span", "", "0.75 µm"), node("span", "", "102 spectral channels"), node("span", "", "5.0 µm"));
      const two = node("div", "in-two");
      const a = node("div", "in-card bad"); a.append(node("b", "", "Not like this"), node("span", "", "An exposure at 1.1 µm against one at 4.9 µm: the star looks “brighter”, but only the colour changed."));
      const b = node("div", "in-card good"); b.append(node("b", "", "Like this"), node("span", "", "Brightness compared only inside the same wavelength bin; motion fitted against the Gaia DR3 track."));
      two.append(a, b); box.append(node("span", "in-lab", "SPHEREx wavelength range"), bar, sc, two);
    } else if (kind === "steps") {
      const ol = node("ol", "in-steps");
      [["01", "Fetch every exposure", "All SPHEREx images that cover the target, from NASA/IPAC IRSA, with their pixel flags."],
       ["02", "Measure each one", "Position and brightness in every exposure, calibrated on the field stars around it."],
       ["03", "Compare fairly", "Motion against the Gaia DR3 track; brightness only between exposures at the same wavelength."],
       ["04", "Show the evidence", "Three plain answers, every check behind them, and a reproducible dossier to download."]]
        .forEach(([n, t, d]) => { const li = node("li"); const tx = node("span"); tx.append(node("b", "", t), node("span", "", d)); li.append(node("span", "dot in-n", n), tx); ol.append(li); });
      box.append(ol);
    } else if (kind === "targets") {
      const list = node("div", "in-targets");
      document.querySelectorAll("#chips li[data-q]").forEach((li) => {
        const r = li.querySelector(".tres"), row = node("div", "in-t");
        const res = node("span", `in-r ${r ? r.className.replace("tres", "").trim() : ""}`, r ? r.textContent : "—");
        row.append(node("span", "in-cat", li.querySelector("small").textContent), node("b", "", li.querySelector("span").textContent), res);
        list.append(row);
      });
      box.append(list);
    }
  }
  function render() {
    const s = SL[i];
    $("#inKicker").textContent = s.k; $("#inBody").textContent = s.b; $("#inNote").textContent = s.n;
    // title word by word (the full sentence stays in aria-label for screen readers)
    const tt = $("#inTitle"); tt.setAttribute("aria-label", s.t);
    tt.replaceChildren(...s.t.split(" ").map((w, k) => { const sp = el("span", { class: "w", "aria-hidden": "true" }, w + " "); sp.style.setProperty("--k", k); return sp; }));
    fig(s.fig);
    $("#inDots").replaceChildren(...SL.map((_, k) => { const li = el("li", { class: k === i ? "on" : k < i ? "past" : "" }); li.append(el("i")); li.style.setProperty("--dur", `${AUTO / 1000}s`); li.onclick = () => { i = k; render(); }; return li; }));
    arm();
    $("#inPos").textContent = `${i + 1} / ${SL.length}`;
    $("#inPrev").disabled = i === 0;
    $("#inCta").textContent = i === SL.length - 1 ? "Open Narvalis" : "Next";
    const m = $(".in-main"); m.classList.remove("swap"); void m.offsetWidth; m.classList.add("swap");
  }
  function open(cb, quiet) {
    i = 0; paused = false; onClose = cb || null; L.hidden = false; L.classList.remove("leaving"); if (!quiet) L.classList.add("entering");
    document.body.classList.add("intro-open"); render(); setTimeout(() => { L.classList.remove("entering"); $("#inNext").focus({ preventScroll: true }); }, 900);
  }
  function close() {
    if (L.hidden || L.classList.contains("leaving")) return;
    clearTimeout(timer);
    try { localStorage.setItem(KEY, "done"); } catch { }
    // the intro lifts away, the app fades up underneath, then the guided tour (if any) fades in
    L.classList.add("leaving"); document.body.classList.add("app-arrive");
    setTimeout(() => {
      L.hidden = true; L.classList.remove("leaving"); document.body.classList.remove("intro-open");
      const cb = onClose; onClose = null; if (cb) setTimeout(cb, 250);
      setTimeout(() => document.body.classList.remove("app-arrive"), 1200);
    }, reduce.matches ? 0 : 750);
  }
  $("#inNext").onclick = () => { manual(); i < SL.length - 1 ? (i++, render()) : close(); };
  $("#inPrev").onclick = () => { manual(); if (i > 0) { i--; render(); } };
  L.addEventListener("pointerenter", (e) => { if (e.pointerType === "mouse") { paused = true; arm(); } });
  $("#inSkip").onclick = close;
  document.addEventListener("keydown", (e) => {
    if (L.hidden) return;
    if (e.key === "ArrowRight") $("#inNext").click(); else if (e.key === "ArrowLeft") $("#inPrev").click(); else if (e.key === "Escape") close(); else return;
    e.preventDefault(); e.stopPropagation();
  }, true);
  let sx = null;   // swipe on phones
  L.addEventListener("touchstart", (e) => { sx = e.touches[0].clientX; }, { passive: true });
  L.addEventListener("touchend", (e) => { if (sx == null) return; const dx = e.changedTouches[0].clientX - sx; sx = null; if (Math.abs(dx) > 50) (dx < 0 ? $("#inNext") : $("#inPrev")).click(); });
  $("#aboutBtn").onclick = () => open();
  const seen = () => { try { return localStorage.getItem(KEY) === "done" || /[?&]intro=0/.test(location.search); } catch { return false; } };
  return { open, close, seen, onClose: (cb) => { if (L.hidden) cb(); else onClose = cb; }, get isOpen() { return !L.hidden; } };
})();

window.__narvalis = { get S() { return S; }, Zoom, fracToSky, skyToFrac };   // read-only hook for tests and the browser console

/* ---------- boot ---------- */
(async function boot() {
  const ul = $("#chips");
  for (const [query, label, hint] of TARGETS) {
    const li = el("li", { tabindex: 0, "data-q": query });
    li.append(el("span", {}, label), el("small", {}, hint), el("em", { class: "tres none" }, "not analysed yet"));
    li.onclick = () => {
      if (isPhone() && li.dataset.job) { setSection("sky"); loadJob(li.dataset.job); return; }
      $("#q").value = query; $("#q").focus();
    };
    li.onkeydown = (e) => e.key === "Enter" && li.onclick();
    ul.append(li);
  }
  { const any = el("li", { tabindex: 0, class: "anypos" }); any.append(el("span", {}, "Any RA / Dec"));
    any.onclick = () => { $("#q").value = ""; $("#q").focus(); }; any.onkeydown = (e) => e.key === "Enter" && any.onclick(); ul.append(any); }
  setClockMode(clockMode, false);
  await Promise.all([detectMode(), document.fonts ? document.fonts.ready : null]);
  checkServices(false);
  const jobs = await loadJobs();
  targetResults(jobs);
  clearSteps();
  const want = (location.hash.match(/job=([a-f0-9]{12})/) || [])[1];
  // Query by URL (embeddable): ?ra=133.795&dec=-7.245 · ?target=Barnard's Star (also ?q=) · optional &size=arcsec
  // &frames=N. An existing finished analysis of the same name opens directly; otherwise the query is only pre-filled.
  const P = new URLSearchParams(location.search);
  const urlQ = (P.get("target") || P.get("q") || (P.get("ra") && P.get("dec") ? `${P.get("ra")} ${P.get("dec")}` : "")).trim();
  if (urlQ) {
    $("#q").value = urlQ;
    if (P.get("size")) $("#size").value = P.get("size");
    if (P.get("frames")) $("#maxFrames").value = P.get("frames");
  }
  const norm = (x) => String(x || "").toLowerCase().replace(/[\s'’_-]+/g, "");
  const urlJob = urlQ ? (jobs.find((j) => j.state === "done" && j.request && norm(j.request.target_name) === norm(urlQ)) || {}).job_id : null;
  const first = want || urlJob || (jobs.find((j) => j.state === "done") || {}).job_id;
  if (isPhone()) setSection("targets");   // phones always open on EXPLORE (the last analysis is loaded behind it, one tap away in SKY)
  if (first) await loadJob(first).catch(() => { hideLoader(); });
  else { hideLoader(); $("#empty").hidden = false; }
  try { if (localStorage.getItem("epochlab_focus_v1") === "1") setFocus(true); } catch { }
  fitLayout(); if (S.d) reflow();
  const needIntro = !urlQ && (!Intro.seen() || /[?&]intro=1/.test(location.search));
  if (needIntro) Intro.open(null, true);            // the intro is already there when the opening animation ends
  await Splash.finish(needIntro ? "#intro .brand-mark" : null);
  // A link never starts an analysis by itself (link previews and crawlers would trigger downloads from IRSA):
  // it only fills the search box, and the visitor presses the arrow.
  if (urlQ && !want && !urlJob) {
    toast(S.mode === "live" ? `“${urlQ}” is ready in the search box — press the arrow to analyse it.`
      : `Opened with “${urlQ}”. This static demo cannot start new analyses; the five validated ones are listed in Explore.`, 7000);
  }
  const running = jobs.find((j) => j.state === "running" || j.state === "queued");
  if (running && S.mode === "live") poll(running.job_id);
  let seen = false;
  try { seen = localStorage.getItem("epochlab_tour_v1") === "done"; } catch { }
  const tour = () => { if (!seen && !urlQ && window.EpochTour) setTimeout(() => EpochTour.start(), 300); };
  if (needIntro) Intro.onClose(tour); else tour();
})();
