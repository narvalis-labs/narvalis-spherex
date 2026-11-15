/* EpochLab — customisable "cockpit" layout (desktop only).
 *
 * The classic three-column page stays the source of truth: every module here is an existing part of
 * that page, moved (not copied) into a GridStack grid, so app.js keeps writing into the same elements
 * by id. Leaving cockpit mode, or shrinking to a phone, puts every part
 * back exactly where it was. The layout (mode, preset, module positions) is stored only in this
 * browser (localStorage); nothing is sent to the server.
 *
 * GridStack.js 12 (MIT) is bundled in web/vendor/gridstack.
 */
(function () {
  "use strict";
  const KEY = "epochlab_layout_v2"; // v2: re-fitted default layout (older saved layouts are not reused)
  const PHONE_MQ = "(max-width:760px), (max-width:1100px) and (orientation:portrait)";
  const ROWS = 12; // the grid is drawn for 12 rows filling the screen; it scrolls if the user goes beyond
  const $ = (s, r = document) => r.querySelector(s);

  // module id -> title and the parts of the classic page it holds
  const MODULES = {
    viewer:  { title: "Viewer",            parts: () => [$(".col.center")] },
    target:  { title: "Target",            parts: () => [$(".card > .target")] },
    strip:   { title: "Time sequence",     parts: () => [$(".card > .sect.seq")] },
    motion:  { title: "Motion",            parts: () => [$('.panel[data-panel="motion"]')] },
    bright:  { title: "Brightness",        parts: () => [$('.panel[data-panel="bright"]')] },
    sed:     { title: "Spectrum",          parts: () => [$('.panel[data-panel="sed"]')] },
    checks:  { title: "Checks",            parts: () => [$('.panel[data-panel="checks"]')], badge: "#checkBadge" },
    frame:   { title: "Frame",             parts: () => [$('.panel[data-panel="frame"]')] },
    targets: { title: "Challenge targets", parts: () => [$("#chips").closest("section")] },
    jobs:    { title: "Analyses",          parts: () => [$("#jobs").closest("section")] },
    sky:     { title: "Sky context",       parts: () => [$(".block.sky")] },
    exports: { title: "Export",            parts: () => [$(".actions")] },
  };

  // [id, x, y, w, h] on a 12 x 12 grid
  const PRESETS = {
    default: { label: "Default", items: [
      ["viewer", 0, 0, 6, 8], ["targets", 0, 8, 2, 4], ["jobs", 2, 8, 2, 4], ["exports", 4, 8, 2, 4],
      ["target", 6, 0, 3, 3], ["sky", 9, 0, 3, 3],
      ["motion", 6, 3, 3, 5], ["bright", 9, 3, 3, 5], ["sed", 6, 8, 3, 4], ["checks", 9, 8, 3, 4]] },
    astro: { label: "Astrometry", items: [
      ["viewer", 0, 0, 6, 8], ["motion", 6, 0, 6, 6], ["checks", 6, 6, 3, 6],
      ["target", 9, 6, 3, 3], ["exports", 9, 9, 3, 3], ["sky", 0, 8, 3, 4], ["jobs", 3, 8, 3, 4]] },
    vari: { label: "Variability", items: [
      ["bright", 0, 0, 7, 6], ["sed", 7, 0, 5, 6], ["viewer", 0, 6, 5, 6], ["strip", 5, 6, 4, 2],
      ["checks", 5, 8, 4, 4], ["motion", 9, 6, 3, 3], ["exports", 9, 9, 3, 3]] },
    present: { label: "Present", items: [
      ["viewer", 0, 0, 8, 12], ["target", 8, 0, 4, 2], ["motion", 8, 2, 4, 4],
      ["bright", 8, 6, 4, 3], ["checks", 8, 9, 4, 3]] },
  };

  const st = load();
  let grid = null, root = null, stash = null, active = false, editing = false;
  const mods = {};          // id -> {el, body}
  const homes = new Map();  // part node -> comment placeholder in the classic page

  function load() {
    try {
      const s = JSON.parse(localStorage.getItem(KEY) || "null");
      if (s && (s.mode === "cockpit" || s.mode === "classic")) return { mode: s.mode, preset: s.preset || null, items: Array.isArray(s.items) ? s.items : null };
    } catch { /* storage unavailable or corrupt: use defaults */ }
    return { mode: "cockpit", preset: "default", items: null };
  }
  function save() {
    if (grid && active) st.items = grid.engine.nodes.map((n) => [n.id, n.x, n.y, n.w, n.h]);
    try { localStorage.setItem(KEY, JSON.stringify(st)); } catch { /* ignore */ }
  }
  const isPhone = () => matchMedia(PHONE_MQ).matches;
  const notify = () => { clearTimeout(notify.t); notify.t = setTimeout(() => {
    window.dispatchEvent(new Event("resize"));
    window.dispatchEvent(new CustomEvent("epochlab:layout", { detail: { mode: active ? "cockpit" : "classic" } }));
  }, 60); };

  /* ---------- building ---------- */
  function svg(path) { return `<svg class="i" viewBox="0 0 24 24" aria-hidden="true">${path}</svg>`; }
  function buildModule(id) {
    const m = MODULES[id];
    const el = document.createElement("div");
    el.className = "grid-stack-item";
    el.setAttribute("gs-id", id);
    el.innerHTML = `<div class="grid-stack-item-content ck-mod" data-mod="${id}">
      <div class="ck-head"><span class="ck-grip" aria-hidden="true">${svg('<circle cx="9" cy="7" r="1"/><circle cx="15" cy="7" r="1"/><circle cx="9" cy="12" r="1"/><circle cx="15" cy="12" r="1"/><circle cx="9" cy="17" r="1"/><circle cx="15" cy="17" r="1"/>')}</span>
        <span class="ck-title">${m.title}</span><span class="ck-badge badge"></span>
        <button type="button" class="ck-x" aria-label="Hide ${m.title}">${svg('<path d="M6 6l12 12M18 6 6 18"/>')}</button></div>
      <div class="ck-body"></div></div>`;
    el.querySelector(".ck-x").onclick = () => hide(id);

    mods[id] = { el, body: el.querySelector(".ck-body") };
    if (m.badge) mirrorBadge(m.badge, el.querySelector(".ck-badge"));
    stash.append(el);
  }
  /* one module fills the work area for a closer look; the same button, Esc or the backdrop restore it */
  let maxed = null;
  function maximise(id) {
    const want = maxed === id ? null : id;
    if (maxed && mods[maxed]) { const c = mods[maxed].el.querySelector(".ck-mod"); c.classList.remove("ck-maxed"); c.querySelector(".ck-maxb").setAttribute("aria-pressed", "false"); }
    maxed = want; document.body.classList.toggle("ck-has-max", !!want);
    let bd = document.querySelector(".ck-backdrop");
    if (want && !bd) { bd = document.createElement("div"); bd.className = "ck-backdrop"; document.body.append(bd); }
    if (!want && bd) bd.remove();
    if (want) { const c = mods[want].el.querySelector(".ck-mod"); c.classList.add("ck-maxed"); c.querySelector(".ck-maxb").setAttribute("aria-pressed", "true"); }
    setTimeout(() => { dispatchEvent(new Event("resize")); dispatchEvent(new CustomEvent("epochlab:layout")); }, 60);
  }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && maxed) { e.stopPropagation(); maximise(maxed); } }, true);
  document.addEventListener("click", (e) => { if (maxed && e.target.classList && e.target.classList.contains("ck-backdrop")) maximise(maxed); });
  function mirrorBadge(sel, target) {
    const src = $(sel);
    if (!src) return;
    const copy = () => { target.textContent = src.textContent; target.className = "ck-badge " + src.className; target.hidden = !src.textContent.trim(); };
    new MutationObserver(copy).observe(src, { childList: true, characterData: true, subtree: true, attributes: true });
    copy();
  }
  function ensureBuilt() {
    if (root) return;
    root = document.createElement("div");
    root.id = "cockpit";
    root.className = "cockpit grid-stack";
    root.setAttribute("aria-label", "Customisable layout");
    stash = document.createElement("div");
    stash.className = "ck-stash";
    stash.hidden = true;
    $("main.layout").after(root, stash);
    Object.keys(MODULES).forEach(buildModule);
  }

  /* ---------- moving the classic parts in and out ---------- */
  function adopt() {
    for (const [id, m] of Object.entries(MODULES)) {
      for (const part of m.parts()) {
        if (!part) continue;
        if (!homes.has(part)) { const ph = document.createComment("cockpit:" + id); part.before(ph); homes.set(part, ph); }
        mods[id].body.append(part);
      }
    }
    // in the cockpit every evidence panel is visible at once
    document.querySelectorAll(".panel").forEach((p) => p.classList.add("on"));
  }
  function release() {
    for (const [part, ph] of homes) ph.after(part);
    const tab = $(".tabs button.on");
    if (window.selectTab) window.selectTab(tab ? tab.dataset.tab : "motion");
  }

  /* ---------- grid ---------- */
  // row height from the WINDOW (space below the header, above the footer), never from the grid's own height:
  // the grid grows when modules are rearranged, and measuring it fed back into ever taller rows
  const cellH = () => {
    const top = ($(".top") || root).getBoundingClientRect().bottom, foot = ($(".foot") || {}).offsetHeight || 0;
    return Math.max(40, Math.floor((innerHeight - top - foot - 18) / ROWS));
  };
  function place(items) {
    grid.batchUpdate();
    grid.removeAll(false);
    Object.values(mods).forEach(({ el }) => stash.append(el));
    for (const [id, x, y, w, h] of items) {
      if (!mods[id]) continue;
      const el = mods[id].el;
      root.append(el);
      grid.makeWidget(el, { x, y, w, h, id, minW: 2, minH: id === "viewer" ? 5 : 2 });
    }
    grid.batchUpdate(false);
    refreshMenu();
    notify();
  }
  function activate() {
    if (active || isPhone()) return;
    ensureBuilt();
    adopt();
    document.body.classList.add("ck");
    active = true;
    if (!grid) {
      grid = GridStack.init({ column: 12, cellHeight: cellH(), margin: 6, float: false, animate: true,
        handle: ".ck-head", staticGrid: false, alwaysShowResizeHandle: false, resizable: { handles: "n,e,s,w,ne,se,sw,nw" } }, root);
      grid.on("change added removed", () => { save(); notify(); });
      grid.on("resizestop dragstop", (e) => { st.preset = null; save(); refreshMenu(); notify(); window.dispatchEvent(new CustomEvent("epochlab:moduleedit", { detail: { kind: e.type } })); });
    } else grid.cellHeight(cellH());
    place(st.items || PRESETS[st.preset || "default"].items);
  }
  function deactivate() {
    if (!active) return;
    save();
    active = false;
    document.body.classList.remove("ck", "ck-edit");
    release();
    notify();
  }
  function hide(id) {
    if (!grid || !mods[id]) return;
    grid.removeWidget(mods[id].el, false);
    stash.append(mods[id].el);
    st.preset = null; save(); refreshMenu(); notify();
    toast(`${MODULES[id].title} hidden`, () => show(id));
  }
  /* a hidden module is easy to lose: say where it went, offer undo, and count hidden modules on the layout button */
  let toastEl = null, toastT = 0;
  function toast(msg, undo) {
    if (!toastEl) { toastEl = document.createElement("div"); toastEl.className = "ck-toast"; toastEl.setAttribute("role", "status"); document.body.append(toastEl); }
    toastEl.innerHTML = `<span>${msg} · bring it back from the layout button</span><button type="button">Undo</button>`;
    toastEl.querySelector("button").onclick = () => { undo(); toastEl.classList.remove("on"); };
    toastEl.classList.add("on"); clearTimeout(toastT); toastT = setTimeout(() => toastEl.classList.remove("on"), 5000);
  }
  function show(id) {
    if (!grid || !mods[id]) return;
    const el = mods[id].el;
    root.append(el);
    grid.makeWidget(el, { w: id === "viewer" ? 6 : 4, h: id === "viewer" ? 8 : 4, autoPosition: true, id, minW: 2, minH: 2 });
    st.preset = null; save(); refreshMenu(); notify();
  }
  function setEditing(on) {
    editing = on;
    document.body.classList.toggle("ck-edit", on);
    // modules can always be moved (title bar) and resized (any edge or corner); Customise only adds hide buttons
    refreshMenu();
  }
  function setMode(mode) {
    st.mode = mode;
    if (mode === "cockpit") activate(); else { setEditing(false); deactivate(); }
    save(); refreshMenu();
  }
  function applyPreset(k) {
    st.preset = k; st.items = null;
    if (!active) setMode("cockpit"); else place(PRESETS[k].items);
    save(); refreshMenu();
  }

  /* ---------- header menu ---------- */
  let btn = null, menu = null;
  function buildMenu() {
    btn = $("#layoutBtn"); menu = $("#layoutMenu");
    if (!btn || !menu) return;
    btn.onclick = (e) => { e.stopPropagation(); const open = menu.hidden; menu.hidden = !open; btn.setAttribute("aria-expanded", String(open)); refreshMenu(); };
    document.addEventListener("click", (e) => { if (!menu.hidden && !menu.contains(e.target) && e.target !== btn) { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); } });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !menu.hidden) { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); btn.focus(); } });
  }
  function refreshMenu() {
    if (!menu) return;
    const shown = new Set(grid && active ? grid.engine.nodes.map((n) => n.id) : []);
    const hidden = Object.keys(MODULES).filter((id) => !shown.has(id));
    // badge: modules the user hid by hand (a chosen preset hides some on purpose; "frame" is off by default)
    const base = new Set(PRESETS.default.items.map((x) => x[0]));
    const userHidden = active && !st.preset ? hidden.filter((id) => base.has(id)).length : 0;
    if (btn) { btn.dataset.hidden = userHidden ? String(userHidden) : ""; btn.title = userHidden ? `Layout · ${userHidden} hidden module${userHidden > 1 ? "s" : ""} — open to bring back` : "Layout"; }
    const b = (label, on, act, extra = "") => `<button type="button" class="lm-b${on ? " on" : ""}" data-act="${act}" ${extra}>${label}</button>`;
    menu.innerHTML = `
      <div class="label">Layout</div>
      <div class="lm-row">${b("Classic", st.mode === "classic", "mode:classic")}${b("Cockpit", st.mode === "cockpit", "mode:cockpit")}</div>
      <div class="label">Presets</div>
      <div class="lm-row wrap">${Object.entries(PRESETS).map(([k, p]) => b(p.label, active && st.preset === k, "preset:" + k)).join("")}</div>
      <div class="lm-row">${b("Reset", false, "reset", active ? "" : "disabled")}</div>
      ${active && hidden.length ? `<div class="label">Hidden modules</div><div class="lm-row wrap">${hidden.map((id) => b("+ " + MODULES[id].title, false, "show:" + id)).join("")}${hidden.length > 1 ? b("Show all", false, "showall") : ""}</div>` : ""}
      <p class="lm-note">${editing ? "Drag a module by its title bar, resize from its edges, × hides it." : "Drag a module by its title bar, resize it from any edge or corner, × hides it. Stored only in this browser."}</p>`;
    menu.querySelectorAll("[data-act]").forEach((x) => (x.onclick = (e) => {
      e.stopPropagation();
      const [a, v] = x.dataset.act.split(":");
      if (a === "mode") setMode(v);
      else if (a === "preset") applyPreset(v);
      else if (a === "edit") setEditing(!editing);
      else if (a === "reset") applyPreset("default");
      else if (a === "show") show(v);
      else if (a === "showall") Object.keys(MODULES).filter((id) => !new Set(grid.engine.nodes.map((n) => n.id)).has(id)).forEach(show);
    }));
  }

  /* ---------- boot ---------- */
  buildMenu();
  if (typeof GridStack === "undefined") {
    if (btn) btn.hidden = true; // library missing: the classic layout keeps working
  } else {
    if (st.mode === "cockpit") activate();
    const mq = matchMedia(PHONE_MQ);
    const onMq = () => { if (mq.matches) deactivate(); else if (st.mode === "cockpit") activate(); refreshMenu(); };
    mq.addEventListener ? mq.addEventListener("change", onMq) : mq.addListener(onMq);
    let t = null;
    addEventListener("resize", () => { clearTimeout(t); t = setTimeout(() => { if (grid && active) grid.cellHeight(cellH()); }, 80); });
  }
  refreshMenu();
  window.EpochCockpit = { setMode, applyPreset, setEditing, get active() { return active; }, get editing() { return editing; } };
})();
