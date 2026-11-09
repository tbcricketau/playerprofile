/* The hub's player packs (build_hub_packs.py). Served by the playerpacks app as /packs/pack.js.

   The cards are written by the build; this script only does what a page cannot know when it is built:
     - the coaches' notes on each card, their fields, and the note to this player at the top, fetched
       from the field planner when the page opens (shared ones only — a coach's private drafts never
       show on a player's pack, even to the coach who wrote them);
     - the field and wheel toggles.
   Nothing on a pack leads to editing, for a coach either (Tom, 10-11-2026): notes and fields are set
   in the planner, and a note box with nothing in it is not shown.

   Fields are drawn by the planner's own code (/static/fields.js, window.FieldPlanner.drawField), so an
   estimated field and a coaches' one share one drawing. */
(function () {
  "use strict";
  const HP = window.HP || {};
  const FP = window.FieldPlanner;
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const api = p => `/fields/${encodeURIComponent(HP.series)}/api/fields?pack=${encodeURIComponent(p)}`;
  const state = { cards: null, band: null, pick: {} };
  // the planner's seeded slots, in order (playerpacks fieldstore.SEED_SLOTS)
  const SLOTS = ["option1", "c2", "c3", "c4", "c5", "c6", "c7", "c8"];

  // ── the wheel: Zones / Spider ────────────────────────────────────────────────────────────
  document.querySelectorAll("[data-switch]").forEach(box => {
    box.querySelectorAll("[data-pane]").forEach(b => b.addEventListener("click", () => {
      box.querySelectorAll("[data-pane]").forEach(x => x.classList.toggle("on", x === b));
      box.querySelectorAll(".pane").forEach((p, i) => { p.hidden = i !== +b.dataset.pane; });
    }));
  });

  // ── fields ───────────────────────────────────────────────────────────────────────────────
  const EST = "Estimated from the data";
  function shared(bid) {
    const st = state.cards || {};
    return (st.saved || []).filter(f => f.batter_id === bid && !f.private);
  }
  function dayFirst(iso) {
    if (!iso) return "";
    const d = new Date(iso.endsWith("Z") ? iso : iso + "Z");
    if (isNaN(d)) return "";
    const p = n => String(n).padStart(2, "0");
    return `${p(d.getDate())}-${p(d.getMonth() + 1)}-${d.getFullYear()}`;
  }
  // a field the coaches set is marked as theirs: on its toggle and under the drawing (11-10-2026)
  const coachOpt = f => ({ name: f.name, plan: f.plan, set: true,
    cap: ["Set by the coaches"].concat(f.phase ? [f.phase] : [], f.tags || [], dayFirst(f.updated_utc) ? [dayFirst(f.updated_utc)] : []).join(" · ") });
  const autoOpt = c => ({ name: c.name, plan: { fielders: c.fielders, arrows: [], spare: c.spare }, cap: EST });

  /* Their bowlers' fields come in categories (new ball, old ball, bouncer…): a coaches' field saved
     in a category replaces the estimate, a category the coaches deleted stays gone, and any other
     field they set follows — the planner's own order. Our bowlers' fields read the same way when
     their estimates were seeded into the planner too (white-ball, 30-10-2026: each carries its
     slot); a Test pack's carry none, so there the coaches' come first, then the estimates.
     A coaches' field saved in a slot that is no longer seeded (the ODI most-set alternatives, taken
     out 10-11-2026) still shows, in its slot's place: hiding it would lose it, as far as a coach can tell. */
  function options(box) {
    const bid = box.dataset.fb, auto = JSON.parse(box.dataset.opts || "[]"), mine = shared(bid);
    if (box.dataset.kind === "bowler" || auto.some(c => c.slot)) {
      const st = state.cards || {};
      const slotOf = f => f.seed || (f.option1 ? "option1" : "");
      const gone = s => s === "option1" ? (st.option1Saved || []).includes(bid) : (st.seededSaved || []).includes(`${bid}|${s}`);
      const rank = s => { const i = SLOTS.indexOf(s); return i < 0 ? SLOTS.length : i; };
      const slots = [...new Set(auto.map(c => c.slot).concat(mine.map(slotOf).filter(Boolean)))]
        .sort((a, b) => rank(a) - rank(b));
      const out = [];
      slots.forEach(s => {
        const got = mine.find(f => slotOf(f) === s), c = auto.find(a => a.slot === s);
        if (got) out.push(coachOpt(got));
        else if (c && !(state.cards && gone(s))) out.push(autoOpt(c));
      });
      return out.concat(mine.filter(f => !slotOf(f)).map(coachOpt));
    }
    const first = mine.filter(f => f.option1).concat(mine.filter(f => !f.option1));
    return first.map(coachOpt).concat(auto.map(autoOpt));
  }

  function drawFields() {
    document.querySelectorAll(".fb[data-fb]").forEach(box => {
      const body = box.querySelector(".fbody") || box;
      const opts = options(box);
      let row = box.querySelector(".row");
      if (!row) {                                       // the label, then the toggles beside it
        row = document.createElement("div"); row.className = "row";
        const lbl = box.querySelector(".lbl"); box.insertBefore(row, lbl); row.appendChild(lbl);
      }
      const old = row.querySelector(".tg"); if (old) old.remove();
      if (!opts.length) { body.innerHTML = '<p class="fnone">No field yet.</p>'; return; }
      const key = box.dataset.fb, i = Math.min(state.pick[key] || 0, opts.length - 1), o = opts[i];
      if (opts.length > 1) {
        const tg = document.createElement("div"); tg.className = "tg";
        tg.innerHTML = opts.map((c, k) => `<button type="button" class="${k === i ? "on" : ""}${c.set ? " set" : ""}" data-k="${k}">${esc(c.name)}</button>`).join("");
        tg.querySelectorAll("button").forEach(b => b.addEventListener("click", () => { state.pick[key] = +b.dataset.k; drawFields(); }));
        row.appendChild(tg);
      }
      body.innerHTML = `<svg viewBox="-1.12 -1.12 2.24 2.24" role="img" aria-label="${esc(o.name)}"></svg><div class="cap${o.set ? " set" : ""}">${esc(o.cap)}</div>`;
      // labels a size up from the planner's: at 340 px wide its .05 is 7 px
      if (FP) FP.drawField(body.querySelector("svg"), o.plan, box.dataset.hand, { labelSize: 0.066 });
      else body.innerHTML = '<p class="fnone">The field could not be drawn.</p>';
    });
  }

  // ── the coaches' notes on each card ──────────────────────────────────────────────────────
  function notesOf(st, bid) {
    const saved = st && st.notes && st.notes[bid];
    const lines = saved ? saved.notes : (st && st.deck && st.deck[bid]);
    return (lines || []).filter(l => String(l).trim());
  }
  // shown only when some are written, to coaches and players alike (Tom, 10-11-2026)
  function drawNotes() {
    document.querySelectorAll("[data-notes]").forEach(el => {
      const lines = notesOf(state.cards, el.dataset.notes);
      el.hidden = !lines.length;
      el.innerHTML = lines.length ? `<div class="t"><b>Coaches' notes</b></div>` + lines.map(l => `<p>${esc(l)}</p>`).join("") : "";
    });
  }

  // ── the note to this player, at the top: shown only when one is written ─────────────────
  function drawBand() {
    const el = document.querySelector(".band-note");
    if (!el) return;
    const st = state.band, saved = st && st.notes && st.notes[HP.pid];
    const lines = ((saved && saved.notes) || []).filter(l => String(l).trim());
    el.hidden = !lines.length;
    el.innerHTML = lines.length ? `<div class="t"><b>${esc(HP.bandTitle)}</b></div>` + lines.map(l => `<p>${esc(l)}</p>`).join("") : "";
  }

  // ── load ─────────────────────────────────────────────────────────────────────────────────
  async function load(pack, put) {
    try {
      const r = await fetch(api(pack), { credentials: "same-origin", cache: "no-store" });
      if (r.ok) put(await r.json());
    } catch (e) { /* the page stands without the planner: estimates and no notes */ }
  }

  drawFields();
  if (HP.series && window.fetch) {
    load(HP.cardPack, d => { state.cards = d; }).then(() => { drawNotes(); drawFields(); });
    load(HP.bandPack, d => { state.band = d; }).then(drawBand);
  }
})();
