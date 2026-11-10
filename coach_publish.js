/* Publish to players (Tom, 10-11-2026). Served as /coach/publish.js, on every Scouting page of a
   series (build_coach_site.py) and on the field planner's pages for a coach (playerpacks fieldplanner).

   A coach's save shows in Scouting at once. The player packs show the series as it stood at its last
   publish (playerpacks fieldstore.published_state). This bar says when that was, what has changed
   since and who changed it, and sends the lot when a coach presses Publish to players. A publish adds
   one row to a log and changes nothing a coach wrote. */
(function () {
  "use strict";
  const el = document.querySelector(".pub[data-series]");
  if (!el || !window.fetch) return;
  const api = `/fields/${encodeURIComponent(el.dataset.series)}/api/publish`;
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  if (!document.getElementById("pub-css")) {
    const st = document.createElement("style");
    st.id = "pub-css";
    st.textContent = ".pub{display:flex;flex-wrap:wrap;align-items:center;gap:8px 14px;margin:10px 0 4px;"
      + "padding:8px 12px;border-left:3px solid #e8b300;background:#fbf6e6;border-radius:4px;font-size:14px;color:#22332a}"
      + ".pub[hidden]{display:none}.pub .pt{flex:1 1 320px}.pub button{font:600 14px Barlow,system-ui,sans-serif;"
      + "background:#0d5b3b;color:#fff;border:0;border-radius:4px;padding:6px 14px;cursor:pointer}"
      + ".pub button[disabled]{opacity:.55;cursor:default}.pub .pm{flex-basis:100%;font-size:13px;color:#0d5b3b}"
      + ".pub .pm.err{color:#a3261c}";
    document.head.appendChild(st);
  }

  // "YYYY-MM-DD HH:MM:SS" in UTC -> the reader's own time, day first
  function when(s) {
    const d = new Date(String(s || "").replace(" ", "T") + "Z");
    if (isNaN(d)) return "";
    const p = n => String(n).padStart(2, "0");
    return `${p(d.getDate())}-${p(d.getMonth() + 1)}-${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`;
  }
  const many = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;

  let busy = false;
  function draw(st, msg, err) {
    const p = st.pending || {}, f = p.fields || 0, nb = p.notes || 0;
    const since = st.first ? `Players see the plans as they stood at ${when(st.at)}`
      : `Last published to players ${when(st.at)}${st.by ? " by " + esc(st.by) : ""}`;
    const bits = [f ? many(f, "field") : "", nb ? `the notes on ${many(nb, "player")}` : ""].filter(Boolean);
    const what = bits.length ? `${bits.join(" and ")} changed since${(p.by || []).length ? " (" + p.by.map(esc).join(", ") + ")" : ""}`
      : "Nothing has changed since";
    el.innerHTML = `<span class="pt">${since}. ${what}.</span>`
      + `<button type="button"${bits.length ? "" : " disabled"}>Publish to players</button>`
      + (msg ? `<span class="pm${err ? " err" : ""}">${esc(msg)}</span>` : "");
    el.hidden = false;
    const b = el.querySelector("button");
    b.addEventListener("click", () => send(b, bits.join(" and ")));
  }

  async function load(msg, err) {
    if (busy) return;
    try {
      const r = await fetch(api, { credentials: "same-origin", cache: "no-store" });
      if (r.ok) draw(await r.json(), msg, err);
    } catch (e) { /* the page stands without the bar */ }
  }

  async function send(b, what) {
    if (!window.confirm(`Publish ${what || "the plans"} to the players? The player packs show them straight away.`)) return;
    busy = true;
    b.disabled = true;
    let msg = "", err = false;
    try {
      const r = await fetch(api, {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-Requested-With": "fieldplanner" },
        body: JSON.stringify({ publish: true }) });
      const d = await r.json().catch(() => ({}));
      if (r.ok) msg = "Published. The player packs show these plans now.";
      else { msg = d.error || "Not published. Try again."; err = true; }
    } catch (e) { msg = "Not published: the connection dropped. Try again."; err = true; }
    busy = false;
    load(msg, err);
  }

  load();
  // a coach saving fields on this page should see the count move without reloading it
  setInterval(() => { if (document.visibilityState === "visible") load(); }, 30000);
})();
