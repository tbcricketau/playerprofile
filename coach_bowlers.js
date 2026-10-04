/* The coach view's Their bowlers page (Batting plans, Tom 04-10-2026): a switch for our batter's hand,
   then a card per opposition bowler with how to play them, the coaches' notes, the figures to that
   hand, their reels and report, and the field they are likely to set by category — or the coaches'
   own fields from the planner's bowler side, once any is saved.

   Served by the playerpacks app as /coach/bowlers.js, beside the page build_coach_site.py writes
   from data/bowler_plans_<opp>.json. Fields are drawn by the planner's own code (/static/fields.js),
   and the planner's notes and fields are fetched when the page opens, as on the Pace and Spin packs. */
(function () {
  "use strict";
  const BK = window.BK || {};
  const FPd = window.FieldPlanner;
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  // the how-to-play lines carry <b> for the length and line they name, and nothing else
  const rich = s => esc(s).replace(/&lt;(\/?)b&gt;/g, "<$1b>");
  const n = v => v == null ? "—" : Number(v).toLocaleString("en-AU");
  const PLAY = "&#9654;";
  const state = { h: (BK.hands && BK.hands[0] || {}).key || "RHB", chip: {}, planner: {} };   // planner: page -> {saved, notes}
  const handOf = h => (BK.hands || []).find(x => x.key === h) || {};
  const word = h => h === "LHB" ? "left-handers" : "right-handers";

  function dayFirst(iso) {
    if (!iso) return "";
    const d = new Date(iso.endsWith("Z") ? iso : iso + "Z");
    if (isNaN(d)) return iso;
    const p = x => String(x).padStart(2, "0");
    return `${p(d.getDate())}-${p(d.getMonth() + 1)}-${d.getFullYear()}`;
  }

  // ── the coaches' notes and fields, from the planner's page for this hand ────────────────
  const plannerState = () => state.planner[handOf(state.h).page];
  /* The options in the planner's own order: each category as the coaches saved it, else as
     generated (a category a coach deleted stays gone), then the coaches' other fields. */
  function optionsFor(b, x) {
    const st = plannerState() || {}, mine = (st.saved || []).filter(f => f.batter_id === b.id);
    const slotOf = f => f.seed || (f.option1 ? "option1" : "");
    const gone = s => s === "option1" ? (st.option1Saved || []).includes(b.id) : (st.seededSaved || []).includes(`${b.id}|${s}`);
    const coach = f => ({ name: f.name, plan: f.plan, tags: f.tags || [], spare: spareOf(f.plan), notes: [], coach: true,
      title: `Set by ${f.updated_by || f.owner_name || ""} · ${dayFirst(f.updated_utc)}${f.private ? " · private draft" : ""}` });
    const auto = c => ({ name: c.label, plan: { fielders: c.fielders, arrows: [], spare: c.spare }, tags: [],
      spare: c.spare_name || spareOf({ fielders: c.fielders, spare: c.spare }), notes: c.notes || [], adjusted: c.adjusted, title: "" });
    const out = [];
    (x.fields || []).forEach(c => {
      const got = mine.find(f => slotOf(f) === c.slot);
      if (got) out.push(coach(got));
      else if (!gone(c.slot) && c.fielders && c.fielders.length) out.push(auto(c));
    });
    return out.concat(mine.filter(f => !slotOf(f)).map(coach));
  }
  function notesFor(bid) {
    const st = plannerState(), saved = st && st.notes && st.notes[bid];
    return saved && saved.notes.length ? saved.notes : null;
  }
  function plannerHref(bid) {
    const page = handOf(state.h).page;
    return BK.planner && page ? `/fields/${encodeURIComponent(BK.planner)}/?pack=${encodeURIComponent(page)}#b${bid}` : "";
  }
  function spareOf(plan) {
    const i = plan && plan.spare;
    return (typeof i === "number" && plan.fielders && plan.fielders[i] && FPd) ? FPd.names(plan.fielders)[i] : "";
  }

  // ── the cards ───────────────────────────────────────────────────────────────────────────
  function fig(v, k) { return `<div class="fig"><div class="v">${v}</div><span class="k">${k}</span></div>`; }
  function figures(b, x) {
    const one = v => v == null ? "—" : Number(v).toFixed(1);
    const parts = [fig(n(x.n_balls), "balls"), fig(n(x.n_wkts), "wickets"), fig(one(x.bowl_avg), "average"),
      fig(x.economy == null ? "—" : Number(x.economy).toFixed(2), "economy"), fig(one(x.strike_rate), "Bowl SR")];
    if (b.pace) parts.push(fig(x.avg_spd == null ? "—" : `${Math.round(x.avg_spd)}<small>/${Math.round(x.max_spd_99)}</small>`, "km/h · top"),
                           fig(x.short_pct == null ? "—" : Math.round(x.short_pct) + "%", "short"));
    parts.push(fig(x.round_pct == null ? "—" : Math.round(x.round_pct) + "%", "round the wicket"));
    return `<div class="figs fn" style="--n:${parts.length}">${parts.join("")}</div>`;
  }
  function htp(x) {
    const rows = [["respect", "Respect"], ["attack", "Attack"], ["watch", "Watch"]].filter(([k]) => ((x.how_to_play || {})[k] || []).length);
    return rows.length ? `<div class="htp">${rows.map(([k, lab]) => `<div class="row"><span class="k">${lab}</span><ul>`
      + x.how_to_play[k].map(l => `<li>${rich(l)}</li>`).join("") + "</ul></div>").join("")}</div>` : "";
  }

  /* One panel, the same as the Pace and Spin cards: the label and any tags on top, the field, the
     options underneath, then the spare. The label says whose field is on show. */
  function fieldPanel(b, x) {
    const link = plannerHref(b.id), key = b.id + "|" + state.h, options = optionsFor(b, x);
    const linkText = "Open in the planner";
    if (!options.length)
      return `<div class="fhead"><span class="lbl">Field</span>${link ? `<a href="${link}">${linkText}</a>` : ""}</div><p class="fnone">No field for this hand yet.</p>`;
    const i = Math.min(state.chip[key] || 0, options.length - 1), o = options[i];
    const label = o.coach ? "Coaches' field" : "Auto-generated field";
    const est = !o.coach ? `<ul class="est">${o.notes.map(t => `<li>${esc(t)}</li>`).join("")}<li>${o.adjusted
      ? `Our estimate: the stock field for their type to ${word(state.h)}, adjusted to their record.`
      : `The stock field for their type to ${word(state.h)}${o.name === "Bouncer plan" ? "" : " — too few balls to adjust it to them"}.`} Not yet checked against vision.</li></ul>` : "";
    return `<div class="fhead"><span class="lbl">${label}</span>`
      + `<span class="ftags">${o.tags.map(t => `<span class="tag">${esc(t)}</span>`).join("")}</span>`
      + (link ? `<a href="${link}">${linkText}</a>` : "") + `</div>`
      + `<svg viewBox="-1.12 -1.12 2.24 2.24" data-plan='${esc(JSON.stringify(o.plan))}' data-hand="${state.h}" role="img" aria-label="${esc(o.name)} for ${esc(b.name)}"></svg>`
      + `<div class="chips">${options.map((c, k) => `<button type="button" class="${k === i ? "on" : ""}" data-chip="${k}"${c.title ? ` title="${esc(c.title)}"` : ""}>${esc(c.name)}</button>`).join("")}</div>`
      + (o.spare ? `<div class="setline"><span><b>Spare</b>${esc(o.spare)}</span></div>` : "") + est;
  }

  function reels(b) {
    const r = (b.reels || {})[state.h] || {}, s = state.h[0];
    return [["stock", "stock", "Stock ball"], ["wicket", "wkt", "Wickets"], ["new_ball", "nb", "New ball"]]
      .filter(([k]) => r[k]).map(([, key, lab]) => `<a href="${esc(b.vision)}#${key}${s}">${PLAY} ${lab}</a>`).join("");
  }

  function card(b) {
    const x = (b.hands || {})[state.h] || {}, balls = x.n_balls || 0, notes = notesFor(b.id);
    const head = b.head ? `<img src="${esc(b.head)}" alt="" loading="lazy">` : `<span class="rav">${esc(b.initials)}</span>`;
    let read;
    if (!balls) read = `<p class="plan"><span class="thin">No Test balls to ${word(state.h)}.</span></p>`;
    else read = (balls < BK.minBalls ? `<p class="plan"><span class="thin">Only ${n(balls)} balls to ${word(state.h)} — read the figures with care.</span></p>` : "") + htp(x);
    return `<article class="pcard" data-b="${esc(b.id)}" id="b${esc(b.id)}">
      <div>
        <div class="who">${head}<div><h3>${esc(b.name)}${b.tier ? `<span class="tier ${esc(b.tier)}">${esc(b.chip)}</span>` : ""}</h3><div class="t">${esc(b.type)}</div></div></div>
        ${read}
        <div class="notes"><span class="lbl">Coaches' notes · vs ${word(state.h)}</span>${notes ? `<ul>${notes.map(l => `<li>${esc(l)}</li>`).join("")}</ul>` : `<p class="none">None yet${BK.planner ? " — add them in the planner." : "."}</p>`}</div>
        ${balls ? figures(b, x) : ""}
        <div class="acts">${reels(b)}${b.report ? `<a class="solid" href="${esc(b.report)}">View report</a>` : ""}</div>
      </div>
      <div class="fieldp">${fieldPanel(b, x)}</div>
    </article>`;
  }

  function render() {
    const box = document.getElementById("bk-cards");
    const tiers = [["xi", "Most likely XI"], ["squad", "In the squad"], ["fringe", "Fringe / outside chance"], ["", "Their bowlers"]];
    box.innerHTML = tiers.map(([t, h]) => { const bs = (BK.bowlers || []).filter(b => (b.tier || "") === t);
      return bs.length ? `<h2 class="tier ${t || "squad"}">${h}<span>${bs.length}</span></h2>` + bs.map(card).join("") : ""; }).join("");
    box.querySelectorAll("svg[data-plan]").forEach(s => {
      if (FPd) FPd.drawField(s, JSON.parse(s.dataset.plan), s.dataset.hand);
      else s.outerHTML = '<p class="fnone">The field could not be drawn (the planner script did not load).</p>';
    });
    box.querySelectorAll("[data-chip]").forEach(x => x.addEventListener("click", () => {
      state.chip[x.closest(".pcard").dataset.b + "|" + state.h] = +x.dataset.chip; render(); }));
    document.querySelectorAll(".seg button").forEach(x => x.classList.toggle("on", x.dataset.h === state.h));
  }

  document.querySelectorAll(".seg button").forEach(x => x.addEventListener("click", () => { state.h = x.dataset.h; render(); }));
  render();

  // the planner's current notes and fields for both hands
  if (BK.planner && window.fetch) {
    (BK.hands || []).forEach(h => {
      fetch(`/fields/${encodeURIComponent(BK.planner)}/api/fields?pack=${encodeURIComponent(h.page)}`, { credentials: "same-origin", cache: "no-store" })
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (d) { state.planner[h.page] = d; render(); } })
        .catch(() => {});
    });
  }
})();
