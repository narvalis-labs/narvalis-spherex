/* First-visit guided tour: spotlight + explanation card for each part of the interface. */
"use strict";
(function () {
  // The tour works in both desktop layouts. In the cockpit each part is its own module, so the spotlight frames
  // the whole module; in the classic page it frames the part, and evidence steps switch the tab first.
  const ck = () => document.body.classList.contains("ck");
  const q = (s) => document.querySelector(s);
  const mod = (id) => q(`.ck-mod[data-mod="${id}"]`);
  const pick = (id, classic) => () => (ck() ? mod(id) : q(classic));
  const tab = (name) => () => { if (!ck() && window.selectTab) selectTab(name); };
  const STEPS = [
    { t: "WELCOME", b: "Narvalis checks whether a star really moves or changes brightness in real SPHEREx images. This tour shows each part of the screen. Use → / ← or the buttons; Esc to skip." },
    { sel: "#form", t: "SEARCH", b: "Start here. Type a name (resolved with SIMBAD) or coordinates as “RA Dec” in degrees, then press the arrow. The sliders button holds options: number of frames, cutout size, control stars, Gaia on/off." },
    { sel: pick("targets", "#chips"), t: "CHALLENGE TARGETS", b: "The five objects named in the Space Apps challenge. Click one to fill the search box. Barnard’s Star and ε Indi B test motion; RW Aur and R Dra test brightness changes; WISE 0855 is a very faint test case." },
    { sel: pick("jobs", "#jobs"), t: "ANALYSES", b: "Every analysis run on this server, newest first. Click one to open it again; finished results load instantly because downloads are cached." },
    { sel: "#steps", t: "LIVE PIPELINE", b: "While an analysis runs, these stages light up in real time: resolve the name, query IRSA, download the cutouts, measure every exposure, then fit motion and variability. The percentage in the viewer is the real job progress." },
    { sel: "#stage", t: "THE VIEWER", b: "Each frame is a real SPHEREx exposure, north up, shown in grey as measured brightness. White cross = where Gaia says the star should be at that exact date. Red ring = where we measured it; the filled ellipse is the uncertainty. Dotted line = the predicted track. Bar = 30 arcseconds." },
    { sel: ".seg", t: "EPOCH / DIFFERENCE", b: "Switch to Matched-λ diff to subtract another epoch taken at the same wavelength. Something that moved leaves a dark-bright pair; something static disappears. Shortcut: d." },
    { sel: ".dock .dock-row", t: "PLAYBACK", b: "Play the sequence (space), step with ← →, set the speed. “Same λ” only shows epochs at the same wavelength, so brightness can be compared fairly. “False colour” tints frames by wavelength — off by default, because the real data have no colour." },
    { sel: "#timeline", t: "TIMELINE", b: "One tick per exposure, placed at its date. Its colour is the wavelength SPHEREx observed it at. SPHEREx sees the same star at a different wavelength on each visit." },
    { sel: ".legends", t: "SCALES", b: "Left: the wavelength colour scale; the white mark is the current frame. Right: the real brightness range of the frame in MJy/sr. All epochs at the same wavelength share this scale, so brighter on screen means brighter in the data. Dark red pixels have no valid data." },
    { sel: pick("target", ".target"), t: "TARGET", b: "Name, position and distance (from the Gaia parallax). The thumbnail follows the current frame." },
    { sel: pick("strip", "#strip"), t: "TIME SEQUENCE", b: "Every analysed exposure in date order. Click any thumbnail to jump to it." },
    { sel: () => (ck() ? null : q(".tabs")), t: "EVIDENCE TABS", b: "The results are grouped in five tabs: Motion, Brightness, Spectrum, Checks and Frame. The number on Checks turns red if any automatic check fails." },
    { sel: pick("motion", ".panels"), before: tab("motion"), t: "MOTION", b: "Measured proper motion against the Gaia value and the difference in σ. Every exposure is first re-calibrated with the Gaia stars of its own field (differential astrometry); those stars then act as controls. The chart shows how far each measurement lands from the predicted track (cyan = RA, amber = Dec); points around zero mean they agree." },
    { sel: pick("bright", ".panels"), before: tab("bright"), t: "BRIGHTNESS", b: "Light curve with one line per wavelength band, coloured with the wavelength scale. Variability is only tested between epochs at the same wavelength." },
    { sel: pick("sed", ".panels"), before: tab("sed"), t: "SPECTRUM", b: "SPHEREx sees the target at a different wavelength on every visit, so the time series also traces its spectrum from 0.75 to 5 µm. Points are coloured by date: for a steady source they line up on one curve; for a variable star, epochs separate. Approximate (aperture photometry), not a calibrated spectrum." },
    { sel: pick("checks", ".panels"), before: tab("checks"), t: "AUTOMATIC CHECKS", b: "Each check states its rule (hover it), including static control stars that must come out static. A significant result marks a candidate for follow-up — never a discovery." },
    { sel: pick("frame", ".panels"), before: tab("frame"), t: "FRAME DETAILS", b: "Everything about the exposure on screen: archive file, detector, time, wavelength, photometry method and the calibration offset applied to it." },
    { sel: "#zPin", t: "RESEARCH PINS", b: "Move the mouse over the image to read the exact RA/Dec under the pointer. Turn on the pin (or press P) and click to mark a sky position: the pin stays on that spot in every exposure — handy to see if something moves past it — and appears on the sky map. Each pin can be copied, shown on the map or analysed." },
    { sel: pick("sky", ".block.sky"), t: "SKY CONTEXT", b: "A 2MASS view (1997–2001) of the same patch of sky, for orientation only — it is not SPHEREx data. For fast stars, + marks the catalogue position around 2000 and ○ where the star is now." },
    { sel: pick("exports", ".actions"), t: "EXPORT & REPRODUCE", b: "Download the full dossier (every archive URL with its SHA-256, every parameter and result), the per-epoch CSV, or a ZIP bundle. Anyone can re-run it with: python -m epochlab.cli reproduce dossier.json" },
    { sel: "#layoutBtn", t: "LAYOUT", b: () => ck()
        ? "You are in the Cockpit: every part of the page is a module. Open this menu to pick a preset (Default, Astrometry, Variability, Present), Drag any module by its title bar and resize it from any edge or corner; the × on a module hides it. Your layout is stored only in this browser. Classic switches back to the three-column page."
        : "You are in the Classic three-column page. Open this menu to switch to the Cockpit, where every part of the page becomes a module you can move, resize or hide, with presets for astrometry, variability or presenting." },
    { sel: () => (ck() ? mod("motion") : null), t: "TRY IT · RESIZE", interactive: "resizestop",
      b: "Every module is flexible. Drag one of the corners of this module (they light up in red) to make it bigger or smaller — go on, try it now.",
      ok: "✓ That’s it. Any edge or corner works, and the layout is saved in this browser." },
    { sel: () => (ck() ? mod("sed")?.querySelector(".ck-head") : null), t: "TRY IT · MOVE", interactive: "dragstop",
      b: "Grab a module by its title bar and drop it somewhere else; the others make room. Try moving this one.",
      ok: "✓ Moved. The × on a module hides it (with Undo), and Reset in the layout menu restores the default." },
    { sel: "#connBtn", t: "CONNECTIONS", b: "The antenna shows the status of NASA/IPAC IRSA, where the SPHEREx images come from (green: answering, amber: answering with errors, grey: no link). Click it to test every service the analysis uses — image search, downloads, Gaia, name resolvers — from this server, with the answer time of each." },
    { sel: ".clockbox", t: "CLOCK", b: "Clock: click to switch UTC → MJD (the date unit SPHEREx frames carry) → local time. Bars = IRSA checked live from this server: four = answering, two + red = answering with server errors, one red = unreachable. The chip next to it re-checks on click." },
    { t: "READY", b: "That’s it. Pick a challenge target or type coordinates to start. You can replay this tour any time with the ? button." },
  ];
  // phones: one section at a time (bottom navigation), so the tour has its own path through Explore → Sky → Results
  const PHONE_STEPS = [
    { t: "WELCOME", b: "Narvalis checks whether a star really moves or changes brightness in real SPHEREx images. This short tour shows each part of the app." },
    { sec: "targets", sel: "#form", t: "SEARCH", b: "Start here: type a star’s name or “RA Dec” in degrees and tap the arrow. Every image comes from NASA/IPAC IRSA." },
    { sec: "targets", sel: "#chips", t: "CHALLENGE TARGETS", b: "The five objects of the Space Apps challenge, with the result of your latest analysis of each. Tap one to open it." },
    { sec: "targets", sel: "#jobs", t: "YOUR ANALYSES", b: "Every analysis run on this server. Tap to open; finished ones load instantly. The × deletes one (on the computer running the server)." },
    { sec: "sky", sel: "#stage", t: "THE VIEWER", b: "A real SPHEREx exposure, north up. White cross = where Gaia predicts the star at that date; red ring = where it was measured. Pinch to zoom; the corner button opens full screen." },
    { sec: "sky", sel: ".centerbar .seg", t: "EPOCH / DIFFERENCE", b: "Same-λ diff subtracts another exposure at the same wavelength: a moving star leaves a dark-bright pair, a static one disappears." },
    { sec: "sky", sel: ".dock .transport", t: "PLAYBACK", b: "Play the exposures in time order, or step one by one." },
    { sec: "sky", sel: ".film-wrap", t: "EXPOSURES", b: "Every exposure as a thumbnail; the colour bar is its wavelength. Tap or swipe to move through time." },
    { sec: "sky", sel: "#storyMini", t: "THE THREE ANSWERS", b: "Does it move, does its brightness change, can I trust it — in short. Tap any of them for the full result." },
    { sec: "sky", sel: "#zPin", t: "PINS", b: "Turn on the pin and tap the image to mark a sky position. It stays on that spot in every exposure and on the sky map; the list in Explore lets you copy it or analyse it." },
    { sec: "results", sel: "#story", t: "RESULTS", b: "The answers — motion, brightness, distance and trust — with their numbers and plots. “Full analysis” opens every table, check and export below." },
    { sel: ".mnav", t: "SECTIONS", b: "Explore to search, Sky for the images, Results for the answers." },
    { sel: "#aboutBtn", t: "ABOUT", b: "Replay the introduction to the project any time from here, and this tour from the ? button." },
    { t: "READY", b: "That’s it. Pick a challenge target or type coordinates to start." },
  ];
  const phone = () => matchMedia("(max-width:760px), (max-width:1100px) and (orientation:portrait)").matches;
  let ghost = null, preview = null;
  function ghostOff() { ghost && ghost.remove(); preview && preview.remove(); ghost = preview = null; }
  function ghostOn(kind) {
    ghostOff();
    ghost = document.createElement("div"); ghost.className = `tour-ghost g-${kind}`; ghost.setAttribute("aria-hidden", "true");
    ghost.innerHTML = '<svg viewBox="0 0 24 24"><path d="M5 3l14 8-6.2 1.6L9.6 19z"/></svg>';
    preview = document.createElement("div"); preview.className = `tour-preview p-${kind}`; preview.setAttribute("aria-hidden", "true");
    document.body.append(preview, ghost);
  }
  function ghostPlace(target, kind) {
    if (!ghost || !target) return;
    const m = (target.closest(".grid-stack-item") || target).getBoundingClientRect(), h = target.getBoundingClientRect();
    Object.assign(preview.style, { left: `${m.left}px`, top: `${m.top}px`, width: `${m.width}px`, height: `${m.height}px` });
    if (kind === "resizestop") Object.assign(ghost.style, { left: `${m.right - 12}px`, top: `${m.bottom - 12}px` });
    else Object.assign(ghost.style, { left: `${h.left + 70}px`, top: `${h.top + h.height / 2 - 4}px` });
  }
  const elOf = (s) => (!s.sel ? null : typeof s.sel === "function" ? s.sel() : q(s.sel));
  let i = 0, hole, card, active = false, prevFocus = null, tryOff = null;

  const visible = (el) => { if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== "hidden"; };
  // on phones a section may be hidden behind the bottom navigation: it counts as visible if it can be revealed
  const revealable = (el) => el && window.revealForTour && matchMedia("(max-width:760px), (max-width:1100px) and (orientation:portrait)").matches && el.closest(".left,.right,.center");
  const steps = () => phone() ? PHONE_STEPS : STEPS.filter((s) => { if (!s.sel) return true; const el = elOf(s); return visible(el) || revealable(el); });

  function build() {
    hole = document.createElement("div"); hole.className = "tour-hole";
    card = document.createElement("div"); card.className = "tour-card"; card.setAttribute("role", "dialog"); card.setAttribute("aria-modal", "true"); card.setAttribute("aria-live", "polite");
    card.innerHTML = `<div class="tour-top"><span class="tour-n dot"></span><button class="tour-skip" type="button">SKIP ✕</button></div>
      <h3 class="tour-t dot"></h3><p class="tour-b"></p>
      <div class="tour-bottom"><div class="tour-dots"></div><div><button class="tour-prev round" type="button" aria-label="Previous">‹</button><button class="tour-next pill" type="button">NEXT</button></div></div>`;
    document.body.append(hole, card);
    card.querySelector(".tour-skip").onclick = end;
    card.querySelector(".tour-prev").onclick = () => go(i - 1);
    card.querySelector(".tour-next").onclick = () => go(i + 1);
    hole.onclick = () => go(i + 1);
  }

  function typeTitle(el, text) {
    el.textContent = ""; let k = 0;
    clearInterval(el._t);
    el._t = setInterval(() => { el.textContent = text.slice(0, ++k); if (k >= text.length) clearInterval(el._t); }, 28);
  }

  function place() {
    const list = steps(), s = list[i]; if (!s) return;
    const pad = 8, vw = innerWidth, vh = innerHeight;
    const target = elOf(s);
    let r;
    if (target) {
      const b = target.getBoundingClientRect();
      r = { x: b.left - pad, y: b.top - pad, w: b.width + 2 * pad, h: b.height + 2 * pad };
      hole.classList.remove("center");
    } else {
      r = { x: vw / 2, y: vh / 2, w: 0, h: 0 }; hole.classList.add("center");
    }
    Object.assign(hole.style, { left: `${r.x}px`, top: `${r.y}px`, width: `${r.w}px`, height: `${r.h}px` });
    const cw = Math.min(380, vw - 24); card.style.width = `${cw}px`;
    const ch = card.offsetHeight;
    let x, y;
    if (!target) { x = (vw - cw) / 2; y = (vh - ch) / 2; }
    else if (r.y + r.h + ch + 16 < vh) { x = r.x; y = r.y + r.h + 12; }          // below
    else if (r.y - ch - 12 > 0) { x = r.x; y = r.y - ch - 12; }                  // above
    else if (r.x + r.w + cw + 16 < vw) { x = r.x + r.w + 12; y = r.y; }          // right
    else if (r.x - cw - 12 > 0) { x = r.x - cw - 12; y = r.y; }                  // left
    else { x = (vw - cw) / 2; y = vh - ch - 12; }                                // overlay at bottom
    card.style.left = `${Math.max(12, Math.min(x, vw - cw - 12))}px`;
    card.style.top = `${Math.max(12, Math.min(y, vh - ch - 12))}px`;
  }

  function go(n) {
    const list = steps();
    if (n >= list.length) return end();
    i = Math.max(0, n);
    const s = list[i];
    if (s.before) s.before();
    if (s.sec && window.setSection) { if (document.body.dataset.m !== s.sec) window.setSection(s.sec); }
    else if (s.sel && window.revealForTour && !phone()) window.revealForTour(elOf(s));
    card.querySelector(".tour-n").textContent = `${String(i + 1).padStart(2, "0")} / ${String(list.length).padStart(2, "0")}`;
    typeTitle(card.querySelector(".tour-t"), s.t);
    card.querySelector(".tour-b").textContent = typeof s.b === "function" ? s.b() : s.b;
    card.querySelector(".tour-prev").disabled = i === 0;
    card.querySelector(".tour-next").textContent = i === list.length - 1 ? "START" : "NEXT";
    const dots = card.querySelector(".tour-dots"); dots.replaceChildren();
    list.forEach((_, k) => { const d = document.createElement("i"); if (k === i) d.className = "on"; else if (k < i) d.className = "past"; dots.append(d); });
    card.classList.remove("in"); void card.offsetWidth; card.classList.add("in");
    // interactive steps: the spotlight lets clicks through, the target pulses, and the step confirms when it is done
    document.querySelectorAll(".tour-try").forEach((x) => x.classList.remove("tour-try"));
    hole.classList.toggle("interactive", !!s.interactive);
    if (tryOff) { removeEventListener("epochlab:moduleedit", tryOff); tryOff = null; }
    if (s.interactive) {
      const tg = elOf(s); const m = tg && (tg.closest(".grid-stack-item") || tg); if (m) m.classList.add("tour-try", `try-${s.interactive}`);
      ghostOn(s.interactive); ghostPlace(tg, s.interactive);
      tryOff = (e) => { if (e.detail && e.detail.kind !== s.interactive) return; ghostOff();
        const b = card.querySelector(".tour-b"); b.textContent = s.ok; b.classList.add("tour-ok");
        card.querySelector(".tour-next").textContent = "NEXT"; setTimeout(place, 50); };
      addEventListener("epochlab:moduleedit", tryOff);
    }
    card.querySelector(".tour-b").classList.remove("tour-ok");
    const target = elOf(s);
    if (target) {
      const b = target.getBoundingClientRect();
      if (b.top < 0 || b.bottom > innerHeight) { target.scrollIntoView({ block: phone() ? "start" : "center", behavior: "smooth" }); setTimeout(place, 420); }
    }
    place(); if (phone()) setTimeout(place, 140);
    if (s.interactive) { clearInterval(go.follow); go.follow = setInterval(() => { if (!active) return clearInterval(go.follow); place(); ghostPlace(elOf(s), s.interactive); }, 250); }
    else { clearInterval(go.follow); ghostOff(); }
    card.querySelector(".tour-next").focus({ preventScroll: true });
  }

  function key(e) {
    if (!active) return;
    if (e.key === "Escape") { e.preventDefault(); end(); }
    else if (e.key === "ArrowRight" || e.key === "Enter") { e.preventDefault(); e.stopImmediatePropagation(); go(i + 1); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); e.stopImmediatePropagation(); go(i - 1); }
    else if (e.key === " ") { e.preventDefault(); e.stopImmediatePropagation(); }
  }

  function start() {
    if (active) return;
    if (!hole) build();
    // close menus and leave edit mode so the spotlight shows the page as it is used
    const lm = q("#layoutMenu"); if (lm) lm.hidden = true;
    if (window.EpochCockpit && EpochCockpit.editing) EpochCockpit.setEditing(false);
    const adv = q("#adv"); if (adv) adv.hidden = true;
    active = true; prevFocus = document.activeElement;
    document.body.classList.add("touring");
    hole.hidden = card.hidden = false;
    go(0);
  }
  function end() {
    if (window.selectTab && !ck()) selectTab("motion");
    if (window.setSection && matchMedia("(max-width:760px), (max-width:1100px) and (orientation:portrait)").matches) setSection("targets");
    active = false; document.body.classList.remove("touring");
    document.querySelectorAll(".tour-try").forEach((x) => x.classList.remove("tour-try", "try-resizestop", "try-dragstop"));
    if (tryOff) { removeEventListener("epochlab:moduleedit", tryOff); tryOff = null; } clearInterval(go.follow); ghostOff();
    if (hole) { hole.hidden = card.hidden = true; }
    try { localStorage.setItem("epochlab_tour_v1", "done"); } catch { }
    window.dispatchEvent(new Event("epochlab:tourend"));
    if (prevFocus && prevFocus.focus) prevFocus.focus({ preventScroll: true });
  }

  addEventListener("keydown", key, true);
  addEventListener("resize", () => active && place());
  addEventListener("scroll", () => active && place(), true);
  window.EpochTour = { start, end };
})();
