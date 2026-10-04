/* The coach view's plan packs (Pace, Spin): a technique switch, then a card per opposition batter with
   the plan, the figures, the coaches' notes and the field — the coaches' own from the field planner
   where one is saved, else the engine's suggested field.

   Served by the playerpacks app as /coach/pack.js, beside the pages build_coach_site.py writes. The
   fields are drawn by the planner's own code (/static/fields.js, window.FieldPlanner.drawField), so
   an engine field and a coach's field never disagree about geometry. The planner's notes and saved
   fields are fetched when the page opens, so an edit there shows here without a rebuild. */
(function () {
  "use strict";
  const PK = window.PK || {};
  const FPd = window.FieldPlanner;
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const n = v => v == null ? "" : Number(v).toLocaleString("en-AU");
  const PLAY = "&#9654;";
  const state = { g: (PK.groups && PK.groups[0] || {}).key, chip: {}, planner: {} };   // planner: group -> {saved, notes}
  const labelOf = g => ((PK.groups || []).find(x => x.key === g) || {}).long || g;
  const subs = () => (PK.groups || []).map(x => x.key);

  function dayFirst(iso) {
    if (!iso) return "";
    const d = new Date(iso.endsWith("Z") ? iso : iso + "Z");
    if (isNaN(d)) return iso;
    const p = x => String(x).padStart(2, "0");
    return `${p(d.getDate())}-${p(d.getMonth() + 1)}-${d.getFullYear()}`;
  }

  // ── the coaches' notes and fields, from the planner ─────────────────────────────────────
  // Every option the coaches have saved for this batter against this type: Option 1 first, then
  // the rest as they were made (the planner's own order).
  function savedFor(bid, g) {
    const st = state.planner[g];
    if (!st) return [];
    const mine = (st.saved || []).filter(f => f.batter_id === bid);
    return mine.filter(f => f.option1).concat(mine.filter(f => !f.option1));
  }
  function notesFor(bid, g) {
    const st = state.planner[g];
    const saved = st && st.notes && st.notes[bid];
    const lines = saved ? saved.notes : (st && st.deck && st.deck[bid]);
    return lines && lines.length ? lines : null;
  }
  function plannerHref(bid, g) {
    return PK.planner ? `/fields/${encodeURIComponent(PK.planner)}/?pack=${encodeURIComponent(g)}#b${bid}` : "";
  }
  function spareOf(plan) {
    const i = plan && plan.spare;
    return (typeof i === "number" && plan.fielders && plan.fielders[i] && FPd) ? FPd.names(plan.fielders)[i] : "";
  }

  // ── the cards ───────────────────────────────────────────────────────────────────────────
  // The short ball is a pace question, so the Spin pack has five figures, not six.
  const shortBall = () => PK.pack !== "spin";
  function fig(v, k, small) { return `<div class="fig"><div class="v${small ? " sm" : ""}">${v}</div><span class="k">${k}</span></div>`; }
  function figures(t, thin, g) {
    if (!t) return "";
    const cls = shortBall() ? "figs" : "figs f5";
    if (thin) return `<div class="${cls}">${fig(n(t.balls), "balls")}<div class="fig" style="grid-column:span ${shortBall() ? 5 : 4}"><div class="v sm muted">Too few balls vs ${esc(labelOf(g))} to rate.</div></div></div>`;
    const bpd = t.bpd ? Math.round(t.bpd) : `<span class="muted">${t.n_out} out</span>`;
    return `<div class="${cls}">${fig(n(t.balls), "balls")}${fig(bpd, "BPD")}${fig(t.false_pct != null ? Number(t.false_pct).toFixed(1) + "%" : "—", "false shot")}`
      + `${fig(t.area ? esc(t.area) : "—", "scores mostly", true)}`
      + (shortBall() ? fig(t.short ? esc(t.short) : '<span class="muted">too few</span>', "vs the short ball", true) : "")
      + `${fig(t.top_out ? esc(t.top_out) : "—", "most often out", true)}</div>`;
  }

  /* One panel for both kinds of field (Tom, 04-10-2026): the label and any tags across the top, the
     field, the options to switch between underneath, then the spare. A coaches' field takes the
     place of the auto-generated one once any is saved; its chips are the saved options. */
  function fieldPanel(b, g, row) {
    const link = plannerHref(b.id, g), key = b.id + "|" + g;
    const saved = savedFor(b.id, g);
    let label, linkText, options;                      // options: [{name, plan, tags, spare, title}]
    if (saved.length) {
      label = "Coaches' field"; linkText = "Open in the planner";
      options = saved.map(f => ({ name: f.name, plan: f.plan, tags: (f.phase ? [f.phase] : []).concat(f.tags || []),
        spare: spareOf(f.plan), title: `Set by ${f.updated_by || f.owner_name || ""} · ${dayFirst(f.updated_utc)}${f.private ? " · private draft" : ""}` }));
    } else {
      label = "Auto-generated field"; linkText = "Set a field in the planner";
      options = (row && row.fields || []).filter(c => c.fielders && c.fielders.length).map(c => ({
        name: c.label, plan: { fielders: c.fielders, arrows: [], spare: c.spare }, tags: [],
        spare: c.spare_name || spareOf({ fielders: c.fielders, spare: c.spare }), title: "" }));
    }
    if (!options.length)
      return `<div class="fhead"><span class="lbl">Field</span>${link ? `<a href="${link}">${linkText}</a>` : ""}</div>`
        + `<p class="fnone">No field yet — ${row && row.balls ? "too few balls vs " + esc(labelOf(g)) + " to generate one" : "no record vs " + esc(labelOf(g))}, and none set by the coaches.</p>`;
    const i = Math.min(state.chip[key] || 0, options.length - 1), o = options[i];
    return `<div class="fhead"><span class="lbl">${label}</span>`
      + `<span class="ftags">${o.tags.map(t => `<span class="tag">${esc(t)}</span>`).join("")}</span>`
      + (link ? `<a href="${link}">${linkText}</a>` : "") + `</div>`
      + `<svg viewBox="-1.12 -1.12 2.24 2.24" data-plan='${esc(JSON.stringify(o.plan))}' data-hand="${esc(b.hand)}" role="img" aria-label="${esc(o.name)} for ${esc(b.name)}"></svg>`
      + `<div class="chips">${options.map((c, k) => `<button type="button" class="${k === i ? "on" : ""}" data-chip="${k}"${c.title ? ` title="${esc(c.title)}"` : ""}>${esc(c.name)}</button>`).join("")}</div>`
      + (o.spare ? `<div class="setline"><span><b>Spare</b>${esc(o.spare)}</span></div>` : "");
  }

  function card(b) {
    const g = state.g, row = b.groups[g] || {}, thin = (row.balls || 0) < PK.minBalls;
    const notes = notesFor(b.id, g);
    let plan;
    if (row.error) plan = `<span class="thin">Profile could not be built — a pipeline failure, not a gap in their record.</span>`;
    else if (!row.balls) plan = `<span class="thin">No record vs ${esc(labelOf(g))}.</span>`;
    else if (thin) plan = `<span class="thin">Only ${n(row.balls)} balls faced vs ${esc(labelOf(g))} — too little to set a plan from.</span>`;
    else plan = row.plan || `<span class="thin">No clear length or line target.</span>`;
    const head = b.head ? `<img src="${esc(b.head)}" alt="" loading="lazy">` : `<span class="rav">${esc(b.initials)}</span>`;
    // name, the figures, the coaches' notes, then the scouting notes the build writes (Tom, 04-10-2026:
    // the coaches' notes matter most, so they sit above the generated ones)
    return `<article class="pcard" data-b="${esc(b.id)}" id="b${esc(b.id)}">
      <div>
        <div class="who">${head}<div><h3>${esc(b.name)}${b.tier ? `<span class="tier ${esc(b.tier)}">${esc(b.chip)}</span>` : ""}</h3><div class="hand">${esc(b.hand)}${b.role ? " · " + esc(b.role) : ""}</div></div></div>
        ${figures(row.threat, thin, g)}
        <div class="notes"><span class="lbl">Coaches' notes</span>${notes ? `<ul>${notes.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : `<p class="none">None yet${PK.planner ? " — add them in the planner." : "."}</p>`}</div>
        <div class="scout"><span class="lbl">Scouting notes</span><p class="plan">${plan}</p></div>
        <div class="acts">${b.vision && row.balls && !thin ? `<a href="${esc(b.vision)}">${PLAY} Vision</a>` : ""}${b.report ? `<a class="solid" href="${esc(b.report)}">View report</a>` : ""}</div>
      </div>
      <div class="fieldp">${fieldPanel(b, g, row)}</div>
    </article>`;
  }

  function render() {
    const box = document.getElementById("pk-cards");
    const tiers = [["xi", "Most likely XI"], ["squad", "In the squad"], ["fringe", "Fringe / outside chance"], ["", "Batters"]];
    box.innerHTML = tiers.map(([t, h]) => { const bs = PK.batters.filter(b => (b.tier || "") === t);
      return bs.length ? `<h2 class="tier ${t || "squad"}">${h}<span>${bs.length}</span></h2>` + bs.map(card).join("") : ""; }).join("");
    box.querySelectorAll("svg[data-plan]").forEach(s => {
      if (FPd) FPd.drawField(s, JSON.parse(s.dataset.plan), s.dataset.hand);
      else s.outerHTML = '<p class="fnone">The field could not be drawn (the planner script did not load).</p>';
    });
    box.querySelectorAll("[data-chip]").forEach(x => x.addEventListener("click", () => {
      state.chip[x.closest(".pcard").dataset.b + "|" + state.g] = +x.dataset.chip; render(); }));
    document.querySelectorAll(".seg button").forEach(x => x.classList.toggle("on", x.dataset.g === state.g));
  }

  document.querySelectorAll(".seg button").forEach(x => x.addEventListener("click", () => { state.g = x.dataset.g; render(); }));
  render();

  // the planner's current notes and fields for every sub-type this pack covers
  if (PK.planner && window.fetch) {
    subs().forEach(g => {
      fetch(`/fields/${encodeURIComponent(PK.planner)}/api/fields?pack=${encodeURIComponent(g)}`, { credentials: "same-origin", cache: "no-store" })
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (d) { state.planner[g] = d; render(); } })
        .catch(() => {});
    });
  }
})();
