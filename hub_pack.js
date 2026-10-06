/* The hub's player packs (build_hub_packs.py). Served by the playerpacks app as /packs/pack.js.

   The cards are written by the build; this script only does what a page cannot know when it is built:
     - the coaches' notes on each card, their fields, and the note to this player at the top, fetched
       from the field planner when the page opens (shared ones only — a coach's private drafts never
       show on a player's pack, even to the coach who wrote them);
     - the field and wheel toggles;
     - for a coach, editing the note at the top in place. Card notes and fields are edited in the
       planner, which the card links to for a coach.

   Fields are drawn by the planner's own code (/static/fields.js, window.FieldPlanner.drawField), so an
   estimated field and a coaches' one share one drawing. */
(function () {
  "use strict";
  const HP = window.HP || {};
  const FP = window.FieldPlanner;
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const api = p => `/fields/${encodeURIComponent(HP.series)}/api/fields?pack=${encodeURIComponent(p)}`;
  const state = { cards: null, band: null, pick: {}, editing: false, msg: "" };

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
  const coachOpt = f => ({ name: f.name, plan: f.plan, cap: ["Coaches' field"].concat(f.phase ? [f.phase] : [], f.tags || []).join(" · ") });
  const autoOpt = c => ({ name: c.name, plan: { fielders: c.fielders, arrows: [], spare: c.spare }, cap: EST });

  /* Their bowlers' fields come in categories (new ball, old ball, bouncer…): a coaches' field saved
     in a category replaces the estimate, a category the coaches deleted stays gone, and any other
     field they set follows — the planner's own order. Our bowlers' fields: the coaches' first,
     then the estimates. */
  function options(box) {
    const bid = box.dataset.fb, auto = JSON.parse(box.dataset.opts || "[]"), mine = shared(bid);
    if (box.dataset.kind === "bowler") {
      const st = state.cards || {};
      const slotOf = f => f.seed || (f.option1 ? "option1" : "");
      const gone = s => s === "option1" ? (st.option1Saved || []).includes(bid) : (st.seededSaved || []).includes(`${bid}|${s}`);
      const out = [];
      auto.forEach(c => {
        const got = mine.find(f => slotOf(f) === c.slot);
        if (got) out.push(coachOpt(got));
        else if (!(state.cards && gone(c.slot))) out.push(autoOpt(c));
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
        tg.innerHTML = opts.map((c, k) => `<button type="button" class="${k === i ? "on" : ""}" data-k="${k}">${esc(c.name)}</button>`).join("");
        tg.querySelectorAll("button").forEach(b => b.addEventListener("click", () => { state.pick[key] = +b.dataset.k; drawFields(); }));
        row.appendChild(tg);
      }
      body.innerHTML = `<svg viewBox="-1.12 -1.12 2.24 2.24" role="img" aria-label="${esc(o.name)}"></svg><div class="cap">${esc(o.cap)}</div>`;
      if (FP) FP.drawField(body.querySelector("svg"), o.plan, box.dataset.hand);
      else body.innerHTML = '<p class="fnone">The field could not be drawn.</p>';
    });
  }

  // ── the coaches' notes on each card ──────────────────────────────────────────────────────
  const editHref = bid => `/fields/${encodeURIComponent(HP.series)}/?pack=${encodeURIComponent(HP.cardPack)}#b${encodeURIComponent(bid)}`;
  function notesOf(st, bid) {
    const saved = st && st.notes && st.notes[bid];
    const lines = saved ? saved.notes : (st && st.deck && st.deck[bid]);
    return (lines || []).filter(l => String(l).trim());
  }
  function drawNotes() {
    const st = state.cards;
    document.querySelectorAll("[data-notes]").forEach(el => {
      const bid = el.dataset.notes, lines = notesOf(st, bid);
      const edit = st && st.canEdit ? `<a href="${editHref(bid)}">Edit in the planner</a>` : "";
      if (!lines.length && !edit) { el.hidden = true; return; }
      el.innerHTML = `<div class="t"><b>Coaches' notes</b>${edit}</div>`
        + (lines.length ? lines.map(l => `<p>${esc(l)}</p>`).join("") : '<p class="cap">None yet.</p>');
      el.hidden = false;
    });
  }

  // ── the note to this player, at the top ──────────────────────────────────────────────────
  function drawBand() {
    const el = document.querySelector(".band-note");
    if (!el) return;
    const st = state.band, saved = st && st.notes && st.notes[HP.pid];
    const lines = ((saved && saved.notes) || []).filter(l => String(l).trim());
    const coach = !!(st && st.canEdit);
    if (state.editing && coach) {
      el.className = "band-note"; el.hidden = false;
      el.innerHTML = `<div class="t"><b>${esc(HP.bandTitle)}</b></div>`
        + `<textarea aria-label="Note to ${esc(HP.first)}">${esc(lines.join("\n"))}</textarea>`
        + `<div class="ed-row"><button type="button" data-a="save">Save</button><button type="button" class="ghost" data-a="cancel">Cancel</button>`
        + `<span class="msg">${esc(state.msg)}</span></div>`;
      el.querySelector('[data-a="cancel"]').addEventListener("click", () => { state.editing = false; state.msg = ""; drawBand(); });
      el.querySelector('[data-a="save"]').addEventListener("click", () => save(el.querySelector("textarea").value, saved));
      el.querySelector("textarea").focus();
      return;
    }
    if (!lines.length && !coach) { el.hidden = true; return; }
    el.className = "band-note" + (lines.length ? "" : " empty");
    const btn = coach ? `<button type="button" class="lnk" data-a="edit">${lines.length ? "Edit" : `Add a note for ${esc(HP.first)}`}</button>` : "";
    el.innerHTML = `<div class="t"><b>${esc(HP.bandTitle)}</b>${btn}</div>` + lines.map(l => `<p>${esc(l)}</p>`).join("");
    el.hidden = false;
    const b = el.querySelector('[data-a="edit"]');
    if (b) b.addEventListener("click", () => { state.editing = true; state.msg = ""; drawBand(); });
  }

  async function save(text, saved) {
    const lines = String(text || "").split("\n").map(l => l.trim()).filter(Boolean);
    state.msg = "Saving…"; drawBandMsg();
    let r, data = {};
    try {
      r = await fetch(`/fields/${encodeURIComponent(HP.series)}/api/notes`, {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-Requested-With": "fieldplanner" },
        body: JSON.stringify({ pack: HP.bandPack, batter_id: HP.pid, version: saved ? saved.version : 0, notes: lines }) });
      try { data = await r.json(); } catch (e) { data = { error: "The app did not answer as expected — you may have been signed out. Reload the page." }; }
    } catch (e) {
      state.msg = "Could not reach the app. Check the connection and try again."; drawBandMsg(); return;
    }
    if (r.status !== 200) { state.msg = data.error || `Could not save (${r.status}).`; drawBandMsg(); return; }
    state.editing = false; state.msg = "";
    await load(HP.bandPack, d => { state.band = d; });
    drawBand();
  }
  function drawBandMsg() { const m = document.querySelector(".band-note .msg"); if (m) m.textContent = state.msg; }

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
  // a jump to a card behind a squad row opens it
  function openTarget() {
    const id = decodeURIComponent(location.hash.slice(1));
    const el = id && document.getElementById(id);
    const d = el && el.closest("details");
    if (d) { d.open = true; el.scrollIntoView(); }
  }
  window.addEventListener("hashchange", openTarget);
  openTarget();
})();
