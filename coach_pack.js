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
  const state = { g: (PK.groups && PK.groups[0] || {}).key, chip: {}, view: {}, planner: {} };   // planner: group -> {saved, notes}
  const labelOf = g => ((PK.groups || []).find(x => x.key === g) || {}).long || g;
  const subs = () => (PK.groups || []).map(x => x.key);
  const SLOTS = ["option1", "c2", "c3", "c4", "c5", "c6", "c7", "c8"];   // the planner's seeded slots, in order

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
  // Drawn however few the balls (Tom, 10-11-2026): the balls figure states the sample. Only the plan
  // line, a claim, still needs PK.minBalls.
  // False v slower ball sits beside the short ball on the Pace pack (Tom, 10-11-2026), from
  // build_shot_types.py: coded slower balls, the count under the rate.
  function figures(t, sh) {
    if (!t) return "";
    const slow = shortBall() && sh && sh.slow;
    const cls = !shortBall() ? "figs f5" : slow ? "figs fn" : "figs";
    const bpd = t.bpd ? Math.round(t.bpd) : `<span class="muted">${t.n_out} out</span>`;
    return `<div class="${cls}"${slow ? ' style="--n:7"' : ""}>${fig(n(t.balls), "balls")}${fig(bpd, "BPD")}${fig(t.false_pct != null ? Number(t.false_pct).toFixed(1) + "%" : "—", "false shot")}`
      + `${fig(t.area ? esc(t.area) : "—", "scores mostly", true)}`
      + (shortBall() ? fig(t.short ? esc(t.short) : '<span class="muted">too few</span>', "vs the short ball", true) : "")
      + (slow ? fig(`${Math.round(slow[1])}%<small class="ln">of ${n(slow[0])} slower</small>`, "false v slower ball") : "")
      + `${fig(t.top_out ? esc(t.top_out) : "—", "most often out", true)}</div>`;
  }

  // ── sweeps against spin, ramps against pace (build_shot_types.py, Tom 10-11-2026) ─────────
  // The sweep colours are the hub packs' own, so a coach sees the same key in both places.
  const SHOT = { sweep: ["Sweep", "#2a78d6"], reverse: ["Reverse sweep", "#eb6834"], slog: ["Slog sweep", "#1baf7a"],
    ramp: ["Ramp", ""], reverse_ramp: ["Reverse ramp", ""] };
  const TYPE = { right_pace: "right-arm pace", left_pace: "left-arm pace", off_spin: "off spin", leg_spin: "leg spin",
    left_orthodox: "left-arm orthodox", left_unorthodox: "left-arm wrist spin" };
  const many = (v, w) => `${n(v)} ${w}${v === 1 ? "" : "s"}`;
  function shotsBlock(sh, g) {
    if (!sh) return "";
    const kinds = Object.entries(sh.kinds || {});
    const cells = kinds.map(([k, [c, runs, outs]]) => {
      const sr = c ? ` · SR ${Math.round(100 * runs / c)}` : "";
      const sw = SHOT[k][1] ? `<i style="background:${SHOT[k][1]}"></i>` : "";
      return `<div class="fig"><div class="v">${(100 * c / sh.balls).toFixed(1)}%<small class="ln">${many(c, "ball")} · ${many(runs, "run")}${sr} · ${outs} out</small></div><span class="k">${sw}${esc(SHOT[k][0])}</span></div>`;
    }).join("");
    return `<div class="shots"><span class="lbl">${PK.pack === "spin" ? "Sweeps" : "Ramps"} v ${esc(TYPE[g] || labelOf(g))}</span>`
      + `<div class="figs fn" style="--n:${kinds.length}">${cells}</div>`
      + `<p class="cap">Share of their ${n(sh.balls)} balls. SR = runs per 100 balls.</p></div>`;
  }
  // Every scoring sweep as one line from the striker, coloured by the sweep, no dot at the end.
  // Drawn as the hub's wheel: the bowler at the bottom, a right-hander's off side on the left. The
  // angle is batter-relative, positive to the off side for either hand.
  function sweepsPanel(b, sh, g) {
    const lhb = /^l/i.test(b.hand || "");
    const p = ['<circle cx="0" cy="0" r="1.005" fill="#fcfcfb" stroke="#0d5b3b" stroke-width=".012"/>',
      '<circle cx="0" cy="0" r=".42" fill="none" stroke="#c9d6cd" stroke-width=".008" stroke-dasharray=".03 .025"/>',
      '<rect x="-.035" y="-.09" width=".07" height=".18" fill="#d8c08a" stroke="#b89a5c" stroke-width=".006"/>'];
    const count = {};
    sh.lines.forEach(([k, a, l, r]) => {
      count[k] = (count[k] || 0) + 1;
      const rad = Math.min(l, 103) / 100, t = a * Math.PI / 180;
      const x = ((lhb ? 1 : -1) * Math.sin(t) * rad).toFixed(4), y = (Math.cos(t) * rad).toFixed(4);
      p.push(`<g><title>${esc(SHOT[k][0])} · ${many(r, "run")}</title><line x1="0" y1="0" x2="${x}" y2="${y}" stroke="${SHOT[k][1]}" stroke-width=".013" stroke-linecap="round" opacity=".9"/>`
        + `<line x1="0" y1="0" x2="${x}" y2="${y}" stroke="transparent" stroke-width=".05"/></g>`);
    });
    const [left, right] = lhb ? ["LEG", "OFF"] : ["OFF", "LEG"];
    p.push(`<text x="-.98" y="-.93" font-size=".07" fill="#5a6b61" font-weight="600">${left}</text>`
      + `<text x=".98" y="-.93" font-size=".07" fill="#5a6b61" font-weight="600" text-anchor="end">${right}</text>`);
    const leg = Object.keys(SHOT).filter(k => count[k]).map(k =>
      `<span><i style="background:${SHOT[k][1]}"></i>${esc(SHOT[k][0])} <b>${count[k]}</b></span>`).join("");
    // the field drawing's own frame, so the ground is the same size whichever view is showing
    return `<svg class="sweeps" viewBox="-1.12 -1.12 2.24 2.24" role="img" aria-label="Every scoring sweep by ${esc(b.name)}, coloured by the sweep">${p.join("")}</svg>`
      + `<div class="sleg">${leg}</div><p class="cap">Every scoring sweep v ${esc(TYPE[g] || labelOf(g))}, one line each</p>`;
  }

  /* One panel for both kinds of field (Tom, 04-10-2026): the label and any tags across the top, the
     field, the options to switch between underneath, then the spare. A coaches' field takes the
     place of the auto-generated one once any is saved; its chips are the saved options. */
  function fieldPanel(b, g, row) {
    const link = plannerHref(b.id, g), key = b.id + "|" + g;
    const saved = savedFor(b.id, g);
    let label, linkText, options;                      // options: [{name, plan, tags, spare, title}]
    const autos = (row && row.fields || []).filter(c => c.fielders && c.fielders.length);
    const coachOpt = f => ({ name: f.name, plan: f.plan, tags: (f.phase ? [f.phase] : []).concat(f.tags || []),
      spare: spareOf(f.plan), coach: true,
      title: `Set by ${f.updated_by || f.owner_name || ""} · ${dayFirst(f.updated_utc)}${f.private ? " · private draft" : ""}` });
    const autoOpt = c => ({ name: c.label, plan: { fielders: c.fielders, arrows: [], spare: c.spare }, tags: [],
      spare: c.spare_name || spareOf({ fielders: c.fielders, spare: c.spare }), title: c.basis || "" });
    if (autos.some(c => c.slot)) {
      /* White-ball (30-10-2026): every auto field was seeded into the planner in its own slot, so it
         reads as the planner does. A field saved in a slot replaces that one, a slot a coach deleted
         stays gone, the coaches' other fields follow. A field saved in a slot that is no longer
         seeded (the ODI most-set alternatives, 10-11-2026) still shows in its slot's place. */
      const st = state.planner[g] || {};
      const slotOf = f => f.seed || (f.option1 ? "option1" : "");
      const gone = s => s === "option1" ? (st.option1Saved || []).includes(b.id) : (st.seededSaved || []).includes(`${b.id}|${s}`);
      const rank = s => { const i = SLOTS.indexOf(s); return i < 0 ? SLOTS.length : i; };
      const slots = [...new Set(autos.map(c => c.slot).concat(saved.map(slotOf).filter(Boolean)))]
        .sort((p, q) => rank(p) - rank(q));
      options = [];
      slots.forEach(s => {
        const got = saved.find(f => slotOf(f) === s), c = autos.find(a => a.slot === s);
        if (got) options.push(coachOpt(got));
        else if (c && !gone(s)) options.push(autoOpt(c));
      });
      options = options.concat(saved.filter(f => !slotOf(f)).map(coachOpt));
      linkText = saved.length ? "Open in the planner" : "Set a field in the planner";
    } else if (saved.length) {
      label = "Coaches' field"; linkText = "Open in the planner";
      options = saved.map(coachOpt);
    } else {
      label = "Auto-generated field"; linkText = "Set a field in the planner";
      options = autos.map(autoOpt);
    }
    if (!options.length)
      return `<div class="fhead"><span class="lbl">Field</span>${link ? `<a href="${link}">${linkText}</a>` : ""}</div>`
        + `<p class="fnone">No field yet — ${PK.autoFields === false ? "fields are generated for Tests only"
          : row && row.balls ? "too few balls vs " + esc(labelOf(g)) + " to generate one" : "no record vs " + esc(labelOf(g))}, and none set by the coaches.</p>`;
    const i = Math.min(state.chip[key] || 0, options.length - 1), o = options[i];
    if (!label) label = o.coach ? "Coaches' field" : "Auto-generated field";
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
        ${figures(row.threat, row.shots)}
        <div class="notes"><span class="lbl">Coaches' notes</span>${notes ? `<ul>${notes.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : `<p class="none">None yet${PK.planner ? " — add them in the planner." : "."}</p>`}</div>
        <div class="scout"><span class="lbl">Scouting notes</span><p class="plan">${plan}</p></div>
        ${shotsBlock(row.shots, g)}
        <div class="acts">${b.vision && row.balls && !thin ? `<a href="${esc(b.vision)}">${PLAY} Vision</a>` : ""}${b.report ? `<a class="solid" href="${esc(b.report)}">View report</a>` : ""}</div>
      </div>
      <div class="fieldp">${rightPanel(b, g, row)}</div>
    </article>`;
  }

  // The field panel, with a Field | Sweeps switch on a Spin card that has a sweep to draw (Tom,
  // 10-11-2026): the card keeps its height, the wheel takes the field's place while it is shown.
  function rightPanel(b, g, row) {
    const sh = row.shots;
    if (PK.pack !== "spin" || !sh || !sh.lines || !sh.lines.length) return fieldPanel(b, g, row);
    const view = state.view[b.id + "|" + g] === "sweeps" ? "sweeps" : "field";
    const btn = (v, t) => `<button type="button" class="${view === v ? "on" : ""}" data-view="${v}">${t}</button>`;
    return `<div class="chips pview">${btn("field", "Field")}${btn("sweeps", "Sweeps")}</div>`
      + (view === "sweeps" ? sweepsPanel(b, sh, g) : fieldPanel(b, g, row));
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
    box.querySelectorAll("[data-view]").forEach(x => x.addEventListener("click", () => {
      state.view[x.closest(".pcard").dataset.b + "|" + state.g] = x.dataset.view; render(); }));
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
