/* The scouting reports as web pages (report_web.py). Inlined into each page.

   The page is written whole by the build; this script does only what a page cannot know when it is built:
     - which scope is on show (all batters, one hand, one bowler type), and the toggles inside a section;
     - the jump strip, which goes to the section of the scope on show;
     - the coaches' notes and fields, fetched from the field planner when the page opens (shared ones
       only — the same rule as the packs, hub_pack.js).

   Fields are drawn by the planner's own code (/static/fields.js, window.FieldPlanner.drawField). */
(function () {
  "use strict";
  const HP = window.HP || {};
  const FP = window.FieldPlanner;
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ── the scope switch ─────────────────────────────────────────────────────────────────────
  const scopes = Array.from(document.querySelectorAll(".scope"));
  let scope = (scopes[0] && scopes[0].dataset.scope) || "all";
  function show(k, keepPlace) {
    if (!scopes.some(s => s.dataset.scope === k)) return;
    // keep the reader on the section they were reading when they change scope
    let at = null;
    if (keepPlace) {
      const cur = document.querySelector(`.scope[data-scope="${scope}"]`);
      const secs = cur ? Array.from(cur.querySelectorAll(".sx")) : [];
      const top = secs.find(s => s.getBoundingClientRect().bottom > 70);
      if (top) at = top.id.split("-").slice(1).join("-");
    }
    scope = k;
    scopes.forEach(s => { s.hidden = s.dataset.scope !== k; });
    document.querySelectorAll(".seg [data-scope]").forEach(b => {
      b.classList.toggle("on", b.dataset.scope === k);
      b.setAttribute("aria-selected", b.dataset.scope === k ? "true" : "false");
    });
    // a chip for a section this scope does not carry is hidden (By bowler type is all bowling only)
    document.querySelectorAll(".jump a[data-to]").forEach(a => {
      a.href = `#${k}-${a.dataset.to}`;
      a.hidden = !document.getElementById(`${k}-${a.dataset.to}`);
    });
    const u = new URL(location.href);
    if (k === scopes[0].dataset.scope) u.searchParams.delete("scope"); else u.searchParams.set("scope", k);
    history.replaceState(null, "", u.pathname + u.search + (at ? `#${k}-${at}` : ""));
    if (at) { const el = document.getElementById(`${k}-${at}`); if (el) el.scrollIntoView(); }
  }
  document.querySelectorAll(".seg [data-scope]").forEach(b => b.addEventListener("click", () => show(b.dataset.scope, true)));
  document.querySelectorAll(".jump a[data-to]").forEach(a => { a.hidden = !document.getElementById(`${scope}-${a.dataset.to}`); });
  const asked = new URLSearchParams(location.search).get("scope");
  if (asked) show(asked, false);
  else if (location.hash) {                       // an old link to a section of another scope
    const m = location.hash.slice(1).split("-")[0];
    if (m !== scope) show(m, false);
  }

  // ── the toggles inside a section (hands, Dots / Density) ─────────────────────────────────
  document.querySelectorAll("[data-switch]").forEach(box => {
    const bar = box.querySelector(":scope > .bar-row");
    const btns = bar ? Array.from(bar.querySelectorAll("[data-pane]")) : [];
    const ps = Array.from(box.querySelectorAll(":scope > .pane"));
    btns.forEach(b => b.addEventListener("click", () => {
      btns.forEach(x => x.classList.toggle("on", x === b));
      ps.forEach((p, i) => { p.hidden = i !== +b.dataset.pane; });
    }));
  });

  // ── fields ───────────────────────────────────────────────────────────────────────────────
  const state = { packs: {}, pick: {} };
  const EST = "Estimated from the data";
  function dayFirst(iso) {
    if (!iso) return "";
    const d = new Date(iso.endsWith("Z") ? iso : iso + "Z");
    if (isNaN(d)) return "";
    const p = n => String(n).padStart(2, "0");
    return `${p(d.getDate())}-${p(d.getMonth() + 1)}-${d.getFullYear()}`;
  }
  const coachOpt = f => ({ name: f.name, plan: f.plan, set: true,
    cap: ["Set by the coaches"].concat(f.phase ? [f.phase] : [], f.tags || [], dayFirst(f.updated_utc) ? [dayFirst(f.updated_utc)] : []).join(" · ") });
  const autoOpt = c => ({ name: c.name, plan: { fielders: c.fielders, arrows: [], spare: c.spare }, cap: EST });

  /* As the packs: a coaches' field saved in a category replaces the estimate, a category the
     coaches deleted stays gone, any other field they set follows. */
  function options(box) {
    const bid = box.dataset.fb, auto = JSON.parse(box.dataset.opts || "[]"), st = state.packs[box.dataset.pack];
    const mine = ((st && st.saved) || []).filter(f => f.batter_id === bid && !f.private);
    if (box.dataset.kind === "bowler") {
      const slotOf = f => f.seed || (f.option1 ? "option1" : "");
      const gone = s => s === "option1" ? ((st && st.option1Saved) || []).includes(bid) : ((st && st.seededSaved) || []).includes(`${bid}|${s}`);
      const out = [];
      auto.forEach(c => {
        const got = mine.find(f => slotOf(f) === c.slot);
        if (got) out.push(coachOpt(got));
        else if (!(st && gone(c.slot))) out.push(autoOpt(c));
      });
      return out.concat(mine.filter(f => !slotOf(f)).map(coachOpt));
    }
    const first = mine.filter(f => f.option1).concat(mine.filter(f => !f.option1));
    return first.map(coachOpt).concat(auto.map(autoOpt));
  }

  function drawFields() {
    document.querySelectorAll(".fb[data-fb]").forEach((box, n) => {
      const body = box.querySelector(".fbody");
      const opts = options(box);
      let row = box.querySelector(".row");
      if (!row) {
        row = document.createElement("div"); row.className = "row";
        const lbl = box.querySelector(".lbl"); box.insertBefore(row, lbl); row.appendChild(lbl);
      }
      const old = row.querySelector(".tg"); if (old) old.remove();
      if (!opts.length) { body.innerHTML = '<p class="fnone">No field yet.</p>'; return; }
      const key = `${box.dataset.pack}|${n}`, i = Math.min(state.pick[key] || 0, opts.length - 1), o = opts[i];
      if (opts.length > 1) {
        const tg = document.createElement("div"); tg.className = "tg";
        tg.innerHTML = opts.map((c, k) => `<button type="button" class="${k === i ? "on" : ""}${c.set ? " set" : ""}" data-k="${k}">${esc(c.name)}</button>`).join("");
        tg.querySelectorAll("button").forEach(b => b.addEventListener("click", () => { state.pick[key] = +b.dataset.k; drawFields(); }));
        row.appendChild(tg);
      }
      body.innerHTML = `<svg viewBox="-1.12 -1.12 2.24 2.24" role="img" aria-label="${esc(o.name)}"></svg><div class="cap${o.set ? " set" : ""}">${esc(o.cap)}</div>`;
      if (FP) FP.drawField(body.querySelector("svg"), o.plan, box.dataset.hand, { labelSize: 0.066 });
      else body.innerHTML = '<p class="fnone">The field could not be drawn.</p>';
    });
  }

  // ── the coaches' notes ───────────────────────────────────────────────────────────────────
  const editHref = (pack, bid) => `/fields/${encodeURIComponent(HP.series)}/?pack=${encodeURIComponent(pack)}#b${encodeURIComponent(bid)}`;
  function notesOf(st, bid) {
    const saved = st && st.notes && st.notes[bid];
    const lines = saved ? saved.notes : (st && st.deck && st.deck[bid]);
    return (lines || []).filter(l => String(l).trim());
  }
  /* A coach sees a dashed box where nothing is written, with a way into the planner; anyone else
     sees the notes only when some are written. */
  function drawNotes() {
    document.querySelectorAll("[data-notes]").forEach(el => {
      const st = state.packs[el.dataset.pack], coach = !!(st && st.canEdit);
      const bid = el.dataset.notes, lines = notesOf(st, bid);
      // an optional box (all bowling, one per type) shows only when written, coach or not
      if (!lines.length && (!coach || el.dataset.optional)) { el.hidden = true; return; }
      el.classList.toggle("empty", !lines.length);
      const edit = coach ? `<a href="${editHref(el.dataset.pack, bid)}">${lines.length ? "Edit in the planner" : "Add in the planner"}</a>` : "";
      el.innerHTML = `<div class="t"><b>${esc(el.dataset.title || "Coaches' notes")}</b>${edit}</div>`
        + (lines.length ? lines.map(l => `<p>${esc(l)}</p>`).join("") : "<p>None yet.</p>");
      el.hidden = false;
    });
  }

  async function load(pack) {
    try {
      const r = await fetch(`/fields/${encodeURIComponent(HP.series)}/api/fields?pack=${encodeURIComponent(pack)}`,
                            { credentials: "same-origin", cache: "no-store" });
      if (r.ok) state.packs[pack] = await r.json();
    } catch (e) { /* the page stands without the planner: estimates and no notes */ }
  }

  drawFields();
  if (HP.series && window.fetch) {
    const packs = new Set();
    document.querySelectorAll("[data-pack]").forEach(el => packs.add(el.dataset.pack));
    Promise.all(Array.from(packs).map(load)).then(() => { drawNotes(); drawFields(); });
  }
})();
