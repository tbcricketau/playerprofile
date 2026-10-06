"""
build_hub_packs.py — the player packs the Coaches Hub serves (docs/PLAYER_PACK_REDESIGN.md).

    python build_hub_packs.py --slug south-africa-test-away-2026
    python build_hub_packs.py --slug south-africa-test-away-2026 --only 4040155 4220025

One page per player and pack: their batting pack (a card per opposition bowler, to their hand) and
a bowling pack per bowling type (a card per opposition batter, against that type). Each card reads
the coaches' notes first, then the facts, the figures, the field, the pictures and the vision. The
GitHub Pages packs (`build_player_site.py`) are untouched; this writes a separate tree,
`hub_pack_site/packs/<slug>/`, which the playerpacks app serves at `/packs/<slug>/`.

Pure assembly — no warehouse, no clip probing. It reads what the other builders wrote:

    data/pack_extras_<opp>.json        facts, figures, pictures   (build_pack_extras.py)
    data/bowler_plans_<opp>.json       their bowlers' fields       (build_bowler_plans.py)
    data/overview_<group>_<opp>.json   our fields to their batters (build_overview.py)
    data/opponent_about_<opp>.json     batting order, types, new-ball share
    player_site/<slug>/<p>-clips.json  the reels, as the Pages packs play them (build_player_site.py)

The coaches' notes, their fields and the per-player note at the top of a pack are not baked in: the
page fetches them from the field planner when it opens (`hub_pack.js`), shared ones only, so an
edit there shows here without a rebuild.

Generated text is facts only (Tom, 06-10-2026). Nothing here tells a player what to do — that is
the coaches', in their notes.
"""
import argparse
import hashlib
import html
import json
import math
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

PACK_JS = os.path.join(HERE, "hub_pack.js")
E = html.escape

_GROUP_LABEL = {"right_pace": "right-arm pace", "left_pace": "left-arm pace", "off_spin": "off spin",
                "leg_spin": "leg spin", "left_orthodox": "left-arm orthodox",
                "left_unorthodox": "left-arm wrist spin", "pace": "pace", "spin": "spin"}
_GROUP_CODE = {"right_pace": "RP", "left_pace": "LP", "off_spin": "OS", "left_orthodox": "LO",
               "leg_spin": "LS", "left_unorthodox": "LU", "pace": "p", "spin": "s"}
_TYPE_LABEL = {"right pace": "Right-arm pace", "left pace": "Left-arm pace", "off-spin": "Off spin",
               "off spin": "Off spin", "left-arm orthodox": "Left-arm orthodox", "leg-spin": "Leg spin",
               "leg spin": "Leg spin", "left-arm unorthodox": "Left-arm wrist spin",
               "right medium": "Right-arm medium", "left medium": "Left-arm medium"}
_FIELD_NAME = {"Early — first 30 balls": "First 30 balls", "Bouncer plan": "Bouncer"}
_ZONE_NAME = {"Third Man": "Third man", "Cover Point": "Cover point", "Mid-Off": "Mid-off", "Mid-On": "Mid-on",
              "Mid-Wicket": "Midwicket", "Square Leg": "Square leg", "Fine Leg": "Fine leg"}
_SECTORS = {"rhb": [("Third Man", -180, -135), ("Cover Point", -135, -90), ("Cover", -90, -45),
                    ("Mid-Off", -45, 0), ("Mid-On", 0, 45), ("Mid-Wicket", 45, 90),
                    ("Square Leg", 90, 135), ("Fine Leg", 135, 180)],
            "lhb": [("Fine Leg", -180, -135), ("Square Leg", -135, -90), ("Mid-Wicket", -90, -45),
                    ("Mid-On", -45, 0), ("Mid-Off", 0, 45), ("Cover", 45, 90),
                    ("Cover Point", 90, 135), ("Third Man", 135, 180)]}
_ROLE_RANK = {"Opener": 0, "Top order": 1, "Middle order": 2, "Lower order": 3}
_TIER_CHIP = {"xi": "XI", "squad": "Squad", "fringe": "Fringe"}


def _load(path, default=None):
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else default


def _rich(text):
    """Generated fact text carries <b> and nothing else; everything else is escaped."""
    s = E(str(text or ""), quote=False)
    return s.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")


def _num(v, dp=1):
    try:
        return f"{float(v):,.{dp}f}"
    except (TypeError, ValueError):
        return None


def _pct(v, dp=0):
    s = _num(v, dp)
    return s + "%" if s is not None else None


def _short(name):
    """The surname a card's buttons use: "Rabada", and "de Zorzi" with its particle."""
    bits = str(name or "").split()
    if len(bits) >= 3 and bits[-2].lower() in ("de", "du", "van", "von", "der", "le", "la", "ul", "al"):
        return " ".join(bits[-2:])
    return bits[-1] if bits else ""


def _hash(path):
    try:
        return hashlib.sha1(open(path, "rb").read()).hexdigest()[:10]
    except OSError:
        return "0"


# ── pieces of a card ──────────────────────────────────────────────────────────────────────────
def _avatar(pid, name, img, cls="av"):
    if img:
        return f'<img class="{cls}" src="{E(img)}" alt="" loading="lazy">'
    bits = [b for b in re.split(r"[\s.-]+", str(name or "")) if b]
    ini = (bits[0][:1] + bits[-1][:1]).upper() if bits else "?"
    return f'<span class="{cls} ini">{E(ini)}</span>'


def _head(pid, name, img, tier, sub):
    chip = f'<span class="chip {E(tier)}">{_TIER_CHIP[tier]}</span>' if tier in _TIER_CHIP else ""
    return (f'<div class="hd o1">{_avatar(pid, name, img)}<div><div class="nm"><span>{E(name)}</span>{chip}'
            f'</div><div class="sb">{E(sub)}</div></div></div>')


def _label(t):
    return f'<div class="lbl">{E(t)}</div>'


def _notes_slot(bid):
    """Filled from the planner when the page opens; stays hidden when no coach has written any."""
    return f'<div class="cn o2" data-notes="{E(bid)}" hidden></div>'


def _facts(facts):
    if not facts:
        return ""
    rows = "".join(f'<span class="k">{E(f.get("label", ""))}</span><span class="v">{_rich(f.get("text"))}</span>'
                   for f in facts)
    return f'<div class="o3">{_label("The numbers")}<div class="facts">{rows}</div></div>'


def _figures(items):
    items = [(v, k) for v, k in items if v is not None][:6]
    if not items:
        return ""
    cells = "".join(f'<div class="fg"><div class="v">{v}</div><div class="k">{E(k)}</div></div>' for v, k in items)
    return f'<div class="figs o4">{cells}</div>'


def _field(bid, title, opts, hand, kind):
    """The field block. Drawn in the browser by the planner's own code, so an estimated field and a
    coaches' one share a drawing; the coaches' fields are merged in when the page has fetched them."""
    # `data-fb`, not `data-field`: check_site reads data-field as a field-map image to resolve
    data = json.dumps(opts, ensure_ascii=False, separators=(",", ":"))
    return (f'<div class="fb o5" data-fb="{E(bid)}" data-kind="{kind}" data-hand="{hand}" '
            f"data-opts='{E(data)}'>{_label(title)}<div class=\"fbody\"></div></div>")


def _zones_svg(zones, lhb):
    tot = sum(zones.values()) or 1
    mx = max(zones.values()) if zones else 1
    mix = lambda t: "#%02x%02x%02x" % tuple(round(a + (b - a) * t) for a, b in zip((238, 244, 238), (13, 91, 59)))
    p = ['<circle cx="0" cy="0" r="1.005" fill="#fff" stroke="#0d5b3b" stroke-width=".012"/>']
    for name, lo, hi in _SECTORS["lhb" if lhb else "rhb"]:
        runs = zones.get(name, 0)
        t = 0.12 + 0.88 * runs / (mx or 1)
        x1, y1 = math.sin(math.radians(lo)), math.cos(math.radians(lo))
        x2, y2 = math.sin(math.radians(hi)), math.cos(math.radians(hi))
        p.append(f'<path d="M0 0 L{x1:.4f} {y1:.4f} A1 1 0 0 0 {x2:.4f} {y2:.4f} Z" fill="{mix(t)}" '
                 f'stroke="#fff" stroke-width=".014"/>')
        mid = math.radians((lo + hi) / 2)
        lx, ly = 0.66 * math.sin(mid), 0.66 * math.cos(mid)
        ink, sub = ("#fff", "rgba(255,255,255,.85)") if t > 0.55 else ("#122219", "#5a6b61")
        p.append(f'<text x="{lx:.3f}" y="{ly - .05:.3f}" font-size=".078" text-anchor="middle" fill="{sub}" '
                 f'font-weight="600">{_ZONE_NAME.get(name, name)}</text>')
        p.append(f'<text x="{lx:.3f}" y="{ly + .085:.3f}" font-size=".15" text-anchor="middle" fill="{ink}" '
                 f'font-weight="700" font-family="Barlow Condensed, Barlow, sans-serif">{int(runs):,}</text>')
        p.append(f'<text x="{lx:.3f}" y="{ly + .17:.3f}" font-size=".066" text-anchor="middle" fill="{sub}" '
                 f'font-weight="600">{runs / tot * 100:.0f}%</text>')
    p.append('<rect x="-.05" y="-.09" width=".1" height=".18" fill="#d8c08a" stroke="#b89a5c" stroke-width=".006"/>')
    return (f'<svg class="zw" viewBox="-1.06 -1.06 2.12 2.12" role="img" aria-label="Runs by fielding zone">'
            f'{"".join(p)}</svg>')


def _wheel(bid, x, lhb, pics_url):
    zones = x.get("zones") or {}
    if not zones:
        return ""
    spider = (x.get("pics") or {}).get("wheel")
    tot = int(sum(zones.values()))
    panes = [("Zones", _zones_svg(zones, lhb))]
    if spider:
        panes.append(("Spider", f'<img class="sp" src="{E(pics_url + spider)}" alt="Wagon wheel: every scoring shot" loading="lazy">'))
    btns = "".join(f'<button type="button" class="{"on" if i == 0 else ""}" data-pane="{i}">{n}</button>'
                   for i, (n, _) in enumerate(panes)) if len(panes) > 1 else ""
    body = "".join(f'<div class="pane"{"" if i == 0 else " hidden"}>{p}</div>' for i, (_, p) in enumerate(panes))
    side = "on the right" if lhb else "on the left"
    return (f'<div class="wb o6" data-switch><div class="row">{_label("Where they score")}'
            f'<div class="tg">{btns}</div></div>{body}'
            f'<div class="cap">{tot:,} runs · off side {side}</div></div>')


def _pics(title, x, caption, pics_url):
    pics = x.get("pics") or {}
    if not (pics.get("pitch") and pics.get("bee")):
        return ""
    return (f'<div class="o7">{_label(title)}<div class="pics">'
            f'<img class="pm" src="{E(pics_url + pics["pitch"])}" alt="Pitch map: where they pitched" loading="lazy">'
            f'<div><img class="bh" src="{E(pics_url + pics["bee"])}" alt="Beehive: where they passed the stumps" loading="lazy">'
            f'<div class="cap">{E(caption)}</div></div></div></div>')


def _vision(buttons, h2h, none_text, star_note=""):
    """Reel buttons play over the page (cricket_core.video's in-page player, which binds
    `a.vlink[data-pl]` on load — so they are written here, never drawn by script). One full-width
    row each, the clip count on the right (Tom, 06-10-2026: buttons sized by their labels did not line
    up). The text is plain — the play mark and the count are CSS — because a declared fallback reel
    ends in `*`, which is how audit_pack_hands tells it from a pooled one, as on the Pages packs."""
    b = "".join(f'<a class="vlink rl" data-pl="{E(k)}" data-n="{n}" href="{E(href)}">{E(t)}</a>'
                for k, href, t, n in buttons)
    if h2h:
        k, href, t, n = h2h
        b += f'<a class="vlink rl h2h" data-pl="{E(k)}" data-n="{n}" href="{E(href)}">{E(t)}</a>'
    tail = "".join(f'<div class="cap">{E(t)}</div>' for t in (star_note, none_text) if t)
    return f'<div class="o8">{_label("Vision")}<div class="reels">{b}</div>{tail}</div>' if (b or tail) else ""


def _card(anchor, left, right):
    """Two columns from a laptop up (facts beside the field and pictures); on a phone the `oN`
    classes put every block in one column in the order the mock-ups set."""
    return (f'<article class="pc" id="{E(anchor)}"><div class="cl">{"".join(left)}</div>'
            f'<div class="cr">{"".join(right)}</div></article>')


def _more(anchor, name, sub, img, card_html):
    """A squad (not XI) player: one row, the full card behind it."""
    return (f'<details class="more" id="m-{E(anchor)}"><summary>{_avatar(anchor, name, img, "av sm")}'
            f'<span class="t"><b>{E(name)}</b><span>{E(sub)}</span></span><span class="ch">›</span></summary>'
            f'{card_html}</details>')


# ── reels from the Pages packs' clip file ─────────────────────────────────────────────────────
class Clips:
    """One of our players' clip sidecar: which reels exist, how many clips, and the titles the
    builder gave them (which say when a reel stands in from the other hand or is recent bowling)."""

    def __init__(self, path, url, vision_url):
        self.url, self.vision_url = url, vision_url
        self.data = _load(path, {}) or {}

    def get(self, key):
        v = self.data.get(key) or {}
        return v if v.get("items") else None

    def button(self, key, label):
        v = self.get(key)
        return (key, f"{self.vision_url}#{key}", label, len(v["items"])) if v else None

    def count(self, key):
        v = self.get(key)
        return len(v["items"]) if v else 0

    def snippet(self):
        """The in-page player, pointed at the sidecar (fetched on the first click)."""
        if not self.data:
            return ""
        from cricket_core.video import inline_player_snippet
        playlists = {k: v.get("items") or [] for k, v in self.data.items()}
        titles = {k: v.get("title") or "" for k, v in self.data.items()}
        return inline_player_snippet(playlists, titles, src=self.url)


def _bowler_reels(clips, bid, hand, about):
    """Stock, wicket and new-ball reels to our batter's hand — or the declared stand-in from the
    other hand, labelled with the hand it shows. Returns (buttons, footnote)."""
    H = "L" if hand == "LHB" else "R"
    out, borrowed = [], set()
    for kind, kk, lab in (("stock", "stock", "Stock ball"), ("wicket", "wkt", "Wicket balls"),
                          ("new_ball", "nb", "New ball")):
        key = f"{kk}{H}_{bid}"
        v = clips.get(key)
        if v:
            t = "Recent bowling" if str(v.get("title", "")).startswith("Recent bowling") else lab
            fmt = (about or {}).get(f"clip_format_{kind}_{hand.lower()}")
            if fmt:
                borrowed.add(str(fmt))
            out.append((key, f"{clips.vision_url}#{key}", t + ("*" if fmt else ""), clips.count(key)))
            continue
        for O, word in (("L", "left-handers"), ("R", "right-handers")):
            if O == H:
                continue
            xkey = f"{kk}X{O}_{bid}"
            if clips.get(xkey):
                out.append((xkey, f"{clips.vision_url}#{xkey}", f"{lab} · to {word}", clips.count(xkey)))
    return out, (f"* {' and '.join(sorted(borrowed))} footage" if borrowed else "")


def _batter_reels(clips, bid, group, about, fmt):
    """Scoring and dismissal reels against our bowler's exact type. A reel the builder had to widen
    (another format, a wider type, or Cricket-21 first-class footage) is starred and footnoted.
    Returns (buttons, footnote)."""
    code = _GROUP_CODE.get(group, "")
    scope = str((about or {}).get(f"clip_scope_{group}") or "")
    note = ""
    if scope and scope != f"{fmt}:{group}":
        sf, _, sg = scope.partition(":")
        note = ("* First-class footage" if sf == "C21" else f"* {sf} footage" if sf != fmt
                else f"* Footage against {_GROUP_LABEL.get(sg, sg)}" if sg != group else "")
    out = []
    for kk, lab in (("sco", "Scoring shots"), ("dsm", "Dismissals")):
        b = clips.button(f"{kk}{code}_{bid}", lab + ("*" if note else ""))
        if b:
            out.append(b)
    return out, (note if out else "")


# ── fields ────────────────────────────────────────────────────────────────────────────────────
def _bowler_field_opts(plan_hand):
    return [{"slot": f.get("slot", ""), "name": _FIELD_NAME.get(f["label"], f["label"]),
             "fielders": [{"angle": p["angle"], "radius": p["radius"]} for p in f["fielders"]],
             "spare": f.get("spare")}
            for f in (plan_hand or {}).get("fields") or [] if f.get("fielders")]


def _batter_field_opts(row):
    return [{"slot": "", "name": _FIELD_NAME.get(f["label"], f["label"]),
             "fielders": [{"angle": p["angle"], "radius": p["radius"]} for p in f["fielders"]],
             "spare": f.get("spare")}
            for f in (row or {}).get("fields") or [] if f.get("fielders") and "alternative" not in f["label"]]


# ── the two kinds of card ─────────────────────────────────────────────────────────────────────
def _bowler_sub(meta, plan, hand, new_ball_min):
    typ = _TYPE_LABEL.get(str(meta.get("type") or plan.get("type") or "").lower(), meta.get("type") or "Bowler")
    bits = [typ]
    nb = plan.get("new_ball") if plan.get("new_ball") is not None else meta.get("new_ball")
    if nb is not None and nb >= new_ball_min:
        bits.append(f"new ball in {nb:.0f}% of innings")
    rnd = meta.get("round_lhb" if hand == "LHB" else "round_rhb")
    if rnd is not None and rnd >= 20:
        bits.append(f"{rnd:.0f}% round the wicket")
    return " · ".join(bits[:2])


def bowler_card(bid, meta, plan, x, hand, clips, img, pics_url, tier, new_ball_min, fmt, opp_short):
    word = "left-handers" if hand == "LHB" else "right-handers"
    sub = _bowler_sub(meta, plan, hand, new_ball_min)
    left = [_head(bid, meta["name"], img, tier, sub), _notes_slot(bid)]
    right = []
    if not (x or {}).get("n_balls"):
        left.append(f'<p class="thin o3">No {fmt} balls to {word}.</p>')
    else:
        spin = x.get("spd_lo") is not None or not plan.get("pace", True)
        left.append(_facts(x.get("facts")))
        st = x.get("stumps") or {}
        stumps = ((f'{st["rate"]:.1f}%', f'Hit the stumps · type {st["expected"]:.1f}')
                  if st.get("rate") is not None and st.get("expected") is not None else (None, ""))
        if spin:
            spd = (f'{x["avg_spd"]:.0f}<small> {x["spd_lo"]:.0f}–{x["spd_hi"]:.0f}</small>'
                   if x.get("avg_spd") and x.get("spd_lo") and x.get("spd_hi") else None)
            figs = [(spd, "km/h · range"), (_num(x.get("bowl_avg")), "Average"), (_num(x.get("strike_rate")), "Bowl SR"),
                    (_num(x.get("economy"), 2), "Economy"), (_num(x.get("n_wkts"), 0), "Wickets"), stumps]
        else:
            spd = (f'{x["avg_spd"]:.0f}<small> /{x["top_spd"]:.0f}</small>'
                   if x.get("avg_spd") and x.get("top_spd") else None)
            figs = [(spd, "km/h · top"), (_num(x.get("bowl_avg")), "Average"), (_num(x.get("strike_rate")), "Bowl SR"),
                    (_num(x.get("economy"), 2), "Economy"), (_pct(x.get("short_pct")), "Short balls"), stumps]
            if figs[4][0] is None:
                figs[4] = (_num(x.get("n_wkts"), 0), "Wickets")
        left.append(_figures(figs))
        n_w = x.get("n_wkts") or 0
        right.append(_pics("Their wicket balls", x, f"{n_w:,} wicket{'s' if n_w != 1 else ''} to {word}", pics_url))
    opts = _bowler_field_opts((plan.get("hands") or {}).get(hand))
    right.insert(0, _field(bid, "Their field", opts, hand, "bowler"))
    reels, note = _bowler_reels(clips, bid, hand, meta)
    h2h = clips.button(f"hbat_{bid}", f"You v {opp_short}")
    none = None
    if not reels and not h2h:
        none = "No available footage."
    elif not h2h:
        none = f"You v {opp_short}: no available footage."
    left.append(_vision(reels, h2h, none, note))
    return _card(f"b{bid}", left, right)


def batter_card(bid, meta, x, row, group, clips, img, pics_url, tier, fmt, opp_short, source):
    lhb = (meta.get("hand") or "").upper().startswith("L")
    role = (meta.get("role") or "").lower()
    sub = " · ".join([("Left-hander" if lhb else "Right-hander")]
                     + ([role] if role else [])
                     + (["figures from first-class cricket"] if source == "both" else []))
    hand = "LHB" if lhb else "RHB"
    glabel = _GROUP_LABEL.get(group, group)
    left = [_head(bid, meta["name"], img, tier, sub), _notes_slot(bid)]
    right = [_field(bid, "Your field", _batter_field_opts(row), hand, "batter")]
    if not x or x.get("thin") or not x.get("balls"):
        n = (x or {}).get("balls") or 0
        left.append(f'<p class="thin o3">{"Only " + format(n, ",") if n else "No"} {fmt} balls against {glabel}.</p>')
    else:
        left.append(_facts(x.get("facts")))
        # under three dismissals there is no balls-per-dismissal figure; the count says why
        bpd = ((f'{x["bpd"]:.0f}', "Balls per dismissal") if x.get("bpd")
               else (f'{int(x.get("n_out") or 0)}', "Dismissals"))
        figs = [(_num(x.get("balls"), 0), "Balls"), (_num(x.get("average")), "Average"), bpd,
                (_pct(x.get("false_pct"), 1), "False shots"), (_pct(x.get("off_pct")), "Runs off side")]
        if group.endswith("pace") and x.get("short_false") is not None:
            figs.append((_pct(x["short_false"]), "False v short ball"))
        left.append(_figures(figs))
        right.append(_wheel(bid, x, lhb, pics_url))
        n_d = x.get("n_dismissals") or 0
        right.append(_pics("Their dismissals", x, f"{n_d:,} dismissal{'s' if n_d != 1 else ''} v {glabel}", pics_url))
    reels, note = _batter_reels(clips, bid, group, meta, fmt)
    h2h = clips.button(f"hbowl_{bid}", f"You to {opp_short}")
    none = None
    if not reels and not h2h:
        none = "No available footage."
    elif not h2h:
        none = f"You to {opp_short}: no available footage."
    left.append(_vision(reels, h2h, none, note))
    return _card(f"b{bid}", left, right)


# ── pages ─────────────────────────────────────────────────────────────────────────────────────
def _css():
    from cricket_core import webcharts as wc
    return wc.CSS + open(os.path.join(HERE, "hub_pack.css"), encoding="utf-8").read()


def _page(title, body, hp=None, js_v="0", fields_v="0", snippet=""):
    from cricket_core import webcharts as wc
    from cricket_core.video import click_guard
    data = (f"<script>window.HP={json.dumps(hp, ensure_ascii=False)};</script>"
            f"<script src='/static/fields.js?v={fields_v}'></script>"
            f"<script src='../pack.js?v={js_v}' defer></script>") if hp is not None else ""
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{E(title)}</title>{wc.head_links()}<style>{_css()}</style>"
            f"{click_guard() if snippet else ''}</head><body class='hp'><!--hub-bar-->{body}{data}{snippet}</body></html>")


def _player_head(name, img, sub, tabs, index_href):
    t = "".join(f'<a href="{E(h)}" class="{"on" if on else ""}">{E(lbl)}</a>' for lbl, h, on in tabs)
    return (f'<header class="ph"><div class="in"><a class="back" href="{E(index_href)}">‹ Squad</a>'
            f'<div class="who">{_avatar("", name, img, "av lg")}<div><h1>{E(name)}</h1><div class="sb">{E(sub)}</div></div></div>'
            f'<nav class="ptabs">{t}</nav></div></header>')


def _section(title, sub, chips, xi_cards, more_cards):
    ch = ("<nav class='jump'>" + "".join(f'<a href="#{E(a)}">{E(n)}</a>' for n, a in chips) + "</nav>") if chips else ""
    s = f' <span>{E(sub)}</span>' if sub else ""
    out = f"<h2 class='sec'>{E(title)}{s}</h2>{ch}{''.join(xi_cards)}"
    if more_cards:
        out += f"<h2 class='sec'>Also in the squad</h2><div class='mores'>{''.join(more_cards)}</div>"
    return out


def build(slug, out_root, only=None, clips_root=None):
    import build_player_site as BPS
    from build_coach_site import _series, _fmt_level, _opp_key, _about, _tiers
    from squads import roster
    entry = _series(slug)
    fmt, level = _fmt_level(entry)
    fmt = {"test": "Test", "odi": "ODI", "t20i": "T20I", "t20": "T20"}.get(str(fmt).lower(), fmt)
    fmt_pl = {"Test": "Tests", "ODI": "ODIs", "T20I": "T20Is"}.get(fmt, fmt)
    opp = _opp_key(slug)
    planner = entry.get("planner_series") or ""
    extras = _load(os.path.join(DATA, f"pack_extras_{opp}.json"))
    if not extras:
        raise SystemExit(f"no data/pack_extras_{opp}.json — run build_pack_extras.py --slug {slug} first")
    plans_doc = _load(os.path.join(DATA, f"bowler_plans_{opp}.json"), {}) or {}
    plans = plans_doc.get("bowlers") or {}
    new_ball_min = plans_doc.get("new_ball_min") or 10
    about_bowl, about_bat = _about(slug)
    tiers = _tiers(entry)
    squads = _load(os.path.join(HERE, "squads.json"), {})
    players = _load(os.path.join(HERE, "players.json"), {})
    smeta = squads.get(slug) or {}
    series_name = smeta.get("name") or entry.get("name") or slug
    our_hands = BPS._our_hands(slug)
    our_groups = BPS._our_bowl_groups(slug)

    clips_root = clips_root or os.path.join(HERE, "player_site")
    nested = os.path.isdir(os.path.join(clips_root, slug))
    clip_dir = os.path.join(clips_root, slug) if nested else clips_root
    clip_url = f"/players/{slug}/" if nested else "/players/"

    s_dir = os.path.join(out_root, "packs", slug)
    os.makedirs(os.path.join(s_dir, "img"), exist_ok=True)
    os.makedirs(os.path.join(s_dir, "pics"), exist_ok=True)

    # pictures: only the ones the extras name, copied beside the pages
    pic_src = os.path.join(HERE, "reports", "pics", opp)
    want = set()
    for b in (extras.get("bowlers") or {}).values():
        for x in (b.get("hands") or {}).values():
            want.update((x.get("pics") or {}).values())
    for b in (extras.get("batters") or {}).values():
        for x in (b.get("groups") or {}).values():
            want.update((x.get("pics") or {}).values())
    missing = [f for f in want if not os.path.exists(os.path.join(pic_src, f))]
    if missing:
        raise SystemExit(f"{len(missing)} picture(s) named in pack_extras_{opp}.json are not in "
                         f"{os.path.relpath(pic_src, HERE)} (e.g. {missing[0]}) — re-run build_pack_extras.py")
    for f in want:
        shutil.copy2(os.path.join(pic_src, f), os.path.join(s_dir, "pics", f))

    def img(pid, name):
        dst = os.path.join(s_dir, "img", f"{pid}.png")
        if not os.path.exists(dst):
            src = os.path.join(clip_dir, "img", f"{pid}.png")
            if os.path.exists(src):
                shutil.copy2(src, dst)
            else:
                try:
                    from photos import get_photo_path
                    p = get_photo_path(pid, fmt=fmt, name=name)
                    if p:
                        shutil.copy2(p, dst)
                except Exception:
                    pass
        return f"img/{pid}.png" if os.path.exists(dst) else None

    # the script, under a URL that changes with its content
    shutil.copy2(PACK_JS, os.path.join(out_root, "packs", "pack.js"))
    js_v = _hash(PACK_JS)
    fields_v = _hash(os.path.join(HERE, "..", "playerpacks", "static", "fields.js"))
    short = _short

    # opposition order: a batting pack opens on the new-ball bowlers, a bowling pack runs down the
    # batting order (Tom, 06-10-2026); the likely XI as cards, the rest of the squad behind a row
    def nb_of(bid):
        p = plans.get(bid) or {}
        v = p.get("new_ball") if p.get("new_ball") is not None else (about_bowl.get(bid) or {}).get("new_ball")
        return v or 0

    bowl_order = sorted(about_bowl, key=lambda b: (nb_of(b) < new_ball_min, -nb_of(b) if nb_of(b) >= new_ball_min else 0,
                                                  -((about_bowl[b] or {}).get("order") or 0)))
    bat_order = sorted(about_bat, key=lambda b: (_ROLE_RANK.get((about_bat[b] or {}).get("role"), 4),
                                                -((about_bat[b] or {}).get("order") or 0)))

    pages, index_rows = 0, []
    for pid in roster(slug):
        rec = players.get(str(pid)) or {"name": str(pid), "role": "Unknown"}
        name, pslug = rec.get("name") or str(pid), BPS._slug(rec.get("name") or str(pid))
        bts = rec.get("bowl_types") or []
        index_rows.append((pid, name, rec.get("role") or "", pslug, bts))
        if only and str(pid) not in only:
            continue
        clips = Clips(os.path.join(clip_dir, f"{pslug}-clips.json"), f"{clip_url}{pslug}-clips.json",
                      f"{clip_url}{pslug}-vision.html")
        snippet = clips.snippet()
        hand = (our_hands.get(str(pid)) or our_hands.get(pid) or "rhb").upper()
        hand_word = "Left-hander" if hand == "LHB" else "Right-hander"
        my_img = img(pid, name)
        bat_href = f"{pslug}-batting.html"
        bowl_pages = [(bt, (our_groups.get(str(pid)) or {}).get(bt) or bt, f"{pslug}-bowling-{bt}.html") for bt in bts]
        tab_list = [("Batting", bat_href)] + [
            ("Bowling" if len(bts) == 1 else f"Bowling: {bt.capitalize()}", h) for bt, _g, h in bowl_pages]
        if bowl_pages and (rec.get("role") or "") == "Bowler":
            tab_list = tab_list[1:] + tab_list[:1]           # a bowler's pack opens on bowling

        # ── the batting pack: their bowlers, to our batter's hand ────────────────────────────
        xi, more, chips = [], [], []
        for bid in bowl_order:
            meta, plan = about_bowl[bid] or {}, plans.get(bid) or {}
            x = ((extras["bowlers"].get(bid) or {}).get("hands") or {}).get(hand)
            tier = tiers.get(bid) or plan.get("tier") or ""
            c = bowler_card(bid, meta, plan, x, hand, clips, img(bid, meta.get("name")), "pics/", tier,
                            new_ball_min, fmt, short(meta.get("name") or ""))
            if tier == "xi":
                xi.append(c)
                chips.append((short(meta.get("name") or bid), f"b{bid}"))
            else:
                more.append(_more(bid, meta.get("name") or bid, _bowler_sub(meta, plan, hand, new_ball_min),
                                  img(bid, meta.get("name")), c))
        hp = {"series": planner, "kind": "bat", "pid": str(pid), "hand": hand, "first": name.split()[0],
              "cardPack": f"vs_{hand.lower()}", "bandPack": "us_bat", "bandTitle": "From the batting coach"}
        body = (_player_head(name, my_img, f"{hand_word} · {series_name}",
                             [(lbl, h, h == bat_href) for lbl, h in tab_list], "index.html")
                + "<main class='wrap hpw'><section class='band-note' hidden></section>"
                + _section("Their attack", f"{fmt_pl} · to {'left' if hand == 'LHB' else 'right'}-handers",
                           chips, xi, more) + "</main>")
        open(os.path.join(s_dir, bat_href), "w", encoding="utf-8").write(
            _page(f"{name} — batting", body, hp, js_v, fields_v, snippet))
        pages += 1

        # ── a bowling pack per type: their batters, against our bowler's type ───────────────────
        for bt, group, href in bowl_pages:
            ov = _load(os.path.join(DATA, f"overview_{group}_{opp}.json"), {}) or {}
            rows = {str(r.get("bid")): r for r in ov.get("rows") or []}
            glabel = _GROUP_LABEL.get(group, group)
            xi, more, chips = [], [], []
            for bid in bat_order:
                meta = about_bat[bid] or {}
                eb = extras["batters"].get(bid) or {}
                x = (eb.get("groups") or {}).get(group)
                tier = tiers.get(bid) or ""
                c = batter_card(bid, meta, x, rows.get(bid), group, clips, img(bid, meta.get("name")), "pics/",
                                tier, fmt, short(meta.get("name") or ""), eb.get("source"))
                if tier == "xi":
                    xi.append(c)
                    chips.append((short(meta.get("name") or bid), f"b{bid}"))
                else:
                    lhb = (meta.get("hand") or "").upper().startswith("L")
                    sub = " · ".join(["Left-hander" if lhb else "Right-hander"]
                                     + ([meta["role"].lower()] if meta.get("role") else []))
                    more.append(_more(bid, meta.get("name") or bid, sub, img(bid, meta.get("name")), c))
            hp = {"series": planner, "kind": "bowl", "pid": str(pid), "group": group, "first": name.split()[0],
                  "cardPack": group, "bandPack": "us_bowl", "bandTitle": "From the bowling coach"}
            body = (_player_head(name, my_img, f"{glabel[:1].upper() + glabel[1:]} · {series_name}",
                                 [(lbl, h, h == href) for lbl, h in tab_list], "index.html")
                    + "<main class='wrap hpw'><section class='band-note' hidden></section>"
                    + _section("Their batters", f"{fmt_pl} · v {glabel}", chips, xi, more) + "</main>")
            open(os.path.join(s_dir, href), "w", encoding="utf-8").write(
                _page(f"{name} — bowling ({bt})", body, hp, js_v, fields_v, snippet))
            pages += 1

    # ── the squad index ──────────────────────────────────────────────────────────────────────────
    groups = [("Batter", "Batters"), ("Wicketkeeper", "Wicketkeepers"), ("All-rounder", "All-rounders"),
              ("Bowler", "Bowlers")]
    known = {r for r, _ in groups}
    tiles = []
    for role, head in groups + [("", "Squad")]:
        rows = [r for r in index_rows if (r[2] == role if role else r[2] not in known)]
        if not rows:
            continue
        def tile(pid, nm, rl, p, b):
            packs = ["Batting"] + (["Bowling"] if len(b) == 1 else ["Pace and spin"] if b else [])
            if b and rl == "Bowler":                     # a bowler's pack opens on bowling
                href, packs = f"{p}-bowling-{b[0]}.html", packs[1:] + packs[:1]
            else:
                href = f"{p}-batting.html"
            return (f'<a class="tile" href="{E(href)}">{_avatar(pid, nm, img(pid, nm), "av")}'
                    f'<span><b>{E(nm)}</b><span>{E(" · ".join(packs))}</span></span></a>')
        items = "".join(tile(*r) for r in rows)
        tiles.append(f"<h2 class='sec'>{E(head)}</h2><div class='tiles'>{items}</div>")
    idx = (f"<header class='ph'><div class='in'><div class='who'><div><h1>{E(series_name)}</h1>"
           f"<div class='sb'>{E(entry.get('subtitle') or '')}</div></div></div></div></header>"
           f"<main class='wrap hpw'>{''.join(tiles)}</main>")
    open(os.path.join(s_dir, "index.html"), "w", encoding="utf-8").write(_page(f"{series_name} — player packs", idx))

    # the list of series, rebuilt from what is on disk so a second series never drops the first
    series_rows = []
    for d in sorted(os.listdir(os.path.join(out_root, "packs"))):
        if os.path.isfile(os.path.join(out_root, "packs", d, "index.html")):
            m = squads.get(d) or {}
            series_rows.append(f'<a class="tile" href="{E(d)}/index.html"><span><b>{E(m.get("name") or d)}</b>'
                               f'<span>{len(m.get("players") or [])} players</span></span></a>')
    open(os.path.join(out_root, "packs", "index.html"), "w", encoding="utf-8").write(_page(
        "Player packs", "<header class='ph'><div class='in'><div class='who'><div><h1>Player packs</h1></div></div></div>"
                        f"</header><main class='wrap hpw'><div class='tiles'>{''.join(series_rows)}</div></main>"))
    print(f"{slug}: {pages} pack page(s), {len(index_rows)} on the squad index -> {os.path.relpath(s_dir, HERE)}")
    return s_dir


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--out", default=os.path.join(HERE, "hub_pack_site"))
    ap.add_argument("--only", nargs="*", help="rebuild these of our players' pages, leave the rest")
    ap.add_argument("--clips", help="where the Pages packs were built (default player_site)")
    a = ap.parse_args(argv)
    build(a.slug, a.out, only=set(a.only) if a.only else None, clips_root=a.clips)


if __name__ == "__main__":
    main()
