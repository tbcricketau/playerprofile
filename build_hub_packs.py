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


def _head(pid, name, img, tier, sub, sample="", report=""):
    """Photo, name, the XI chip, the type line, and the sample the card's figures rest on ("Tests ·
    193 wickets to right-handers") — so every card states its basis before any number (round 2,
    11-10-2026). Top right, the player's web report where one is built (Tom, 10-11-2026: as the old
    packs' View report). Nothing on a card leads into the planner, for a coach either."""
    chip = f'<span class="chip {E(tier)}">{_TIER_CHIP[tier]}</span>' if tier in _TIER_CHIP else ""
    smp = f'<div class="smp">{E(sample)}</div>' if sample else ""
    rep = f'<a class="rep" href="{E(report)}">View report</a>' if report else ""
    return (f'<header class="hd o1">{_avatar(pid, name, img)}<div class="hdt"><div class="nm"><span>{E(name)}</span>{chip}'
            f'</div><div class="sb">{E(sub)}</div>{smp}</div>{rep}</header>')


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
    return f'<div class="fx o5"><div class="facts">{rows}</div></div>'


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
    return (f'<div class="fb o3" data-fb="{E(bid)}" data-kind="{kind}" data-hand="{hand}" '
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


# Sweeps against spin, ramps against pace (build_shot_types.py, Tom 10-11-2026). The sweep colours are
# the first three of the charting skill's checked categorical palette, in its fixed order.
_SPIN_GROUPS = {"off_spin", "leg_spin", "left_orthodox", "left_unorthodox", "spin"}
_SHOT_LABEL = {"sweep": "Sweep", "reverse": "Reverse sweep", "slog": "Slog sweep",
               "ramp": "Ramp", "reverse_ramp": "Reverse ramp"}
_SHOT_COLOUR = {"sweep": "#2a78d6", "reverse": "#eb6834", "slog": "#1baf7a"}
_SHOT_KEY = {"sweep": "swp", "reverse": "rsw", "slog": "slg", "ramp": "rmp", "reverse_ramp": "rrm"}
_SHOT_TITLE = {"sweep": "Sweeps", "reverse": "Reverse sweeps", "slog": "Slog sweeps",
               "ramp": "Ramps", "reverse_ramp": "Reverse ramps"}


def _many(n, word):
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def _shots(shot, group):
    """How often they play each sweep (spin) or ramp (pace), as a share of their balls against the
    type, with what it brought them."""
    kinds, balls = (shot or {}).get("kinds") or {}, (shot or {}).get("balls") or 0
    if not kinds or not balls:
        return ""
    spin = group in _SPIN_GROUPS
    cells = []
    for kind, k in kinds.items():
        sr = f" · SR {100 * k['runs'] / k['n']:.0f}" if k["n"] else ""
        sw = f'<i style="background:{_SHOT_COLOUR[kind]}"></i>' if spin else ""
        cells.append(f'<div class="fg"><div class="v">{100 * k["n"] / balls:.1f}%<small class="ln">'
                     f'{_many(k["n"], "ball")} · {_many(k["runs"], "run")}{sr} · {k["outs"]} out</small></div>'
                     f'<div class="k">{sw}{E(_SHOT_LABEL[kind])}</div></div>')
    title = f"{'Sweeps' if spin else 'Ramps'} v {_GROUP_LABEL.get(group, group)}"
    # no caption under the figures (Tom, 10-11-2026): the sample line already gives the balls
    return f'<div class="shots o5">{_label(title)}<div class="figs">{"".join(cells)}</div></div>'


def _sweeps_svg(lines, lhb):
    """Every scoring sweep as one line from the striker, coloured by the sweep (Tom, 10-11-2026: no
    dot at the end). Drawn as the zones are: the bowler at the bottom, a right-hander's off side on
    the left. The angle is batter-relative, positive to the off side for either hand."""
    p = ['<circle cx="0" cy="0" r="1.005" fill="#fcfcfb" stroke="#0d5b3b" stroke-width=".012"/>',
         '<circle cx="0" cy="0" r=".42" fill="none" stroke="#c9d6cd" stroke-width=".008" stroke-dasharray=".03 .025"/>',
         '<rect x="-.035" y="-.09" width=".07" height=".18" fill="#d8c08a" stroke="#b89a5c" stroke-width=".006"/>']
    for kind, ang, ln, runs, day in lines:
        r = min(float(ln), 103) / 100
        x = (1 if lhb else -1) * math.sin(math.radians(float(ang))) * r
        y = math.cos(math.radians(float(ang))) * r
        d = str(day or "")
        tip = f"{_SHOT_LABEL[kind]} · {_many(int(runs), 'run')}" + (f" · {d[8:10]}-{d[5:7]}-{d[:4]}" if len(d) >= 10 else "")
        # a wider see-through line under the drawn one, so the hover finds a 2-pixel line
        p.append(f'<g><title>{E(tip)}</title><line x1="0" y1="0" x2="{x:.4f}" y2="{y:.4f}" stroke="{_SHOT_COLOUR[kind]}" '
                 f'stroke-width=".013" stroke-linecap="round" opacity=".9"/><line x1="0" y1="0" x2="{x:.4f}" '
                 f'y2="{y:.4f}" stroke="transparent" stroke-width=".05"/></g>')
    left, right = ("LEG", "OFF") if lhb else ("OFF", "LEG")
    p.append(f'<text x="-.98" y="-.93" font-size=".07" fill="#5a6b61" font-weight="600">{left}</text>')
    p.append(f'<text x=".98" y="-.93" font-size=".07" fill="#5a6b61" font-weight="600" text-anchor="end">{right}</text>')
    return (f'<svg class="zw" viewBox="-1.06 -1.06 2.12 2.12" role="img" aria-label="Every scoring sweep, '
            f'coloured by the sweep">{"".join(p)}</svg>')


def _sweeps_pane(shot, lhb, group):
    lines = (shot or {}).get("lines") or []
    if not lines:
        return None
    n = {k: sum(1 for ln in lines if ln[0] == k) for k in _SHOT_COLOUR}
    leg = "".join(f'<span><i style="background:{c}"></i>{_SHOT_LABEL[k]} <b>{n[k]}</b></span>'
                  for k, c in _SHOT_COLOUR.items() if n[k])
    return (f'{_sweeps_svg(lines, lhb)}<div class="sleg">{leg}</div>'
            f'<div class="cap mid">Every scoring sweep v {E(_GROUP_LABEL.get(group, group))}, one line each</div>')


def _wheel(bid, x, lhb, pics_url, shot=None, group=""):
    zones = x.get("zones") or {}
    if not zones:
        return ""
    spider = (x.get("pics") or {}).get("wheel")
    tot = int(sum(zones.values()))
    panes = [("Zones", _zones_svg(zones, lhb))]
    if spider:
        panes.append(("Spider", f'<img class="sp" src="{E(pics_url + spider)}" alt="Wagon wheel: every scoring shot" loading="lazy">'))
    sweeps = _sweeps_pane(shot, lhb, group) if group in _SPIN_GROUPS else None
    if sweeps:
        panes.append(("Sweeps", sweeps))
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
    cap = f'<div class="cap">{E(caption)}</div>' if caption else ""
    return (f'<div class="px o7">{_label(title)}<div class="pics">'
            f'<img class="pm" src="{E(pics_url + pics["pitch"])}" alt="Pitch map: where they pitched" loading="lazy">'
            f'<div><img class="bh" src="{E(pics_url + pics["bee"])}" alt="Beehive: where they passed the stumps" loading="lazy">'
            f'{cap}</div></div></div>')


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
    reels = f'<div class="reels">{b}</div>' if b else ""
    return f'<div class="vis o8">{_label("Vision")}{reels}{tail}</div>' if (b or tail) else ""


def _card(anchor, head, plan, nums):
    """Two halves (Tom, 11-10-2026): the plan — the coaches' notes, the field, the vision — and the
    numbers — figures, facts, pictures. On a phone the plan comes first, every block in one column
    in the order of the `oN` classes; from a laptop up the plan is the left half and the numbers the
    right, under a header that spans both."""
    return (f'<article class="pc" id="{E(anchor)}">{head}<div class="plan">{"".join(plan)}</div>'
            f'<div class="nums">{"".join(nums)}</div></article>')


def _summary(anchor, name, sub, img, tier, facts, buttons, h2h, h2h_label, star_note, detail):
    """One opposition player in a pack's list, as the old packs had it (Tom, 10-11-2026): a row that
    opens in place to the coaches' notes when any are written (first, Tom 11-11-2026), their summary
    points, the reels and the footage of you against them, with View coach notes and fields into the
    full card on its own page."""
    chip = f'<span class="chip {E(tier)}">{_TIER_CHIP[tier]}</span>' if tier in _TIER_CHIP else ""
    pts = ('<ul class="sfacts">' + "".join(f"<li>{_rich(f)}</li>" for f in facts) + "</ul>" if facts
           else '<p class="cap">Not enough data on this player yet.</p>')
    none = ("No available footage." if not buttons and not h2h
            else f"{h2h_label}: no available footage." if not h2h else None)
    return (f'<details class="opp" id="{E(anchor)}"><summary>{_avatar(anchor, name, img, "av sm")}'
            f'<span class="t"><span class="nm"><b>{E(name)}</b>{chip}</span><span>{E(sub)}</span></span>'
            f'<a class="rep" href="{E(detail)}" onclick="event.stopPropagation()">View coach notes and fields</a></summary>'
            f'<div class="sbody">{_notes_slot(anchor[1:])}{pts}{_vision(buttons, h2h, none, star_note)}</div></details>')


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


def _bowler_reels(clips, bid, hand, about, dom=None):
    """Stock, wicket and new-ball reels to our batter's hand — or the declared stand-in from the
    other hand, labelled with the hand it shows. `dom` names the about reels carrying domestic
    one-day footage (domestic_topup.py), starred and footnoted. Returns (buttons, footnote)."""
    H = "L" if hand == "LHB" else "R"
    out, borrowed = [], set()
    for kind, kk, lab in (("stock", "stock", "Stock ball"), ("wicket", "wkt", "Wicket balls"),
                          ("new_ball", "nb", "New ball")):
        key = f"{kk}{H}_{bid}"
        v = clips.get(key)
        home = (dom or {}).get(f"{kind}_clips_{hand.lower()}")
        if home:
            borrowed.add("Domestic one-day")
        if v:
            t = "Recent bowling" if str(v.get("title", "")).startswith("Recent bowling") else lab
            fmt = (about or {}).get(f"clip_format_{kind}_{hand.lower()}")
            if fmt:
                borrowed.add(str(fmt))
            out.append((key, f"{clips.vision_url}#{key}", t + ("*" if fmt or home else ""), clips.count(key)))
            continue
        for O, word in (("L", "left-handers"), ("R", "right-handers")):
            if O == H:
                continue
            xkey = f"{kk}X{O}_{bid}"
            if clips.get(xkey):
                out.append((xkey, f"{clips.vision_url}#{xkey}", f"{lab} · to {word}" + ("*" if home else ""),
                            clips.count(xkey)))
    # An analyst's hand-cut variations, if a set has been published for this series. One reel, not
    # one per hand: an off cutter is an off cutter whoever faces it (Tom, 09-11-2026). Added after
    # the hand reels, never in place of one.
    vkey = f"var_{bid}"
    if clips.get(vkey):
        out.append((vkey, f"{clips.vision_url}#{vkey}", "Variations", clips.count(vkey)))
    return out, (f"* {' and '.join(sorted(borrowed))} footage" if borrowed else "")


def _batter_reels(clips, bid, group, about, fmt, shot=None, dom=None):
    """Scoring and dismissal reels against our bowler's exact type, then the sweeps or ramps. A reel
    the builder had to widen (another format, a wider type, Cricket-21 first-class footage, or the
    domestic one-day cricket beside a short ODI record) is starred and footnoted. Returns (buttons,
    footnote)."""
    out, note = _scoring_reels(clips, bid, group, about, fmt)
    notes = [note] if note else []
    # the reels of a short record read with its domestic one-day cricket (domestic_topup.py)
    home = {"sco": (dom or {}).get(f"scoring_clips_{group}"), "dsm": (dom or {}).get(f"dismissal_clips_{group}")}
    for i, (k, href, t, n) in enumerate(out):
        if home.get(k[:3]):
            out[i] = (k, href, t if t.endswith("*") else t + "*", n)
            notes.append("* Includes domestic one-day footage")
    # a sweep or ramp reel against the exact type, or against the wider spin or pace set when the
    # exact type has none, starred like the scoring reels (build_shot_types.py, 10-11-2026)
    for kind, rv in ((shot or {}).get("reels") or {}).items():
        scope = rv.get("scope") or group
        b = clips.button(f"{_SHOT_KEY[kind]}{_GROUP_CODE.get(scope, '')}_{bid}",
                         _SHOT_TITLE[kind] + ("*" if scope != group else ""))
        if b:
            out.append(b)
            if scope != group:
                notes.append(f"* Footage against {_GROUP_LABEL.get(scope, scope)}")
    return out, " · ".join(dict.fromkeys(notes))


def _scoring_reels(clips, bid, group, about, fmt):
    """Scoring and dismissal reels against our bowler's exact type. Returns (buttons, footnote)."""
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


def _batter_field_opts(row, fmt="Test", group="", hand="RHB"):
    opts = [{"slot": "", "name": _FIELD_NAME.get(f["label"], f["label"]),
             "fielders": [{"angle": p["angle"], "radius": p["radius"]} for p in f["fielders"]],
             "spare": f.get("spare")}
            for f in (row or {}).get("fields") or [] if f.get("fielders") and "alternative" not in f["label"]]
    if not opts and fmt != "Test":
        # white-ball: the GPS-measured fields per phase, in the planner slots they were seeded into
        # (build_planner_batters), so a coach's edit there replaces the one here (30-10-2026)
        from whiteball_fields import phase_fields
        opts = [{"slot": c["slot"], "name": c["label"], "spare": None,
                 "fielders": [{"angle": p["angle"], "radius": p["radius"]} for p in c["fielders"]]}
                for c in phase_fields(fmt, group, hand)]
    return opts


# ── the two kinds of card ─────────────────────────────────────────────────────────────────────
def _bowler_sub(meta, plan, hand, new_ball_min):
    """The line under a bowler's name: their type and nothing else (Tom, 10-11-2026). The summary
    points carry the new ball and, where the angle matters, over and round the wicket."""
    return _TYPE_LABEL.get(str(meta.get("type") or plan.get("type") or "").lower(), meta.get("type") or "Bowler")


def bowler_card(bid, meta, plan, x, hand, clips, img, pics_url, tier, new_ball_min, fmt, opp_short, report="",
                domestic=None, dom_reels=None):
    word = "left-handers" if hand == "LHB" else "right-handers"
    sub = _bowler_sub(meta, plan, hand, new_ball_min)
    fmt_pl = {"Test": "Tests", "ODI": "ODIs", "T20I": "T20Is"}.get(fmt, fmt)
    if domestic:                                    # a short ODI record, topped up (domestic_topup.py)
        import domestic_topup as DT
        fmt_pl = DT.sample_words(domestic, fmt_pl)
    n_w = (x or {}).get("n_wkts") or 0
    sample = (f"{fmt_pl} · {n_w:,} wicket{'s' if n_w != 1 else ''} to {word}" if (x or {}).get("n_balls")
              else f"No {fmt} balls to {word}")
    plan_half = [_notes_slot(bid)]
    nums = []
    if (x or {}).get("n_balls"):
        spin = x.get("spd_lo") is not None or not plan.get("pace", True)
        st = x.get("stumps") or {}
        # the bowler's own rate alone, without the type average (Tom, 10-11-2026)
        stumps = ((f'{st["rate"]:.1f}%', "Hit stumps %") if st.get("rate") is not None else (None, ""))
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
        nums.append(_figures(figs))
        nums.append(_facts(x.get("facts")))
        nums.append(_pics("Their wicket balls", x, "", pics_url))
    opts = _bowler_field_opts((plan.get("hands") or {}).get(hand))
    plan_half.append(_field(bid, "Their field", opts, hand, "bowler"))
    reels, note = _bowler_reels(clips, bid, hand, meta, dom_reels)
    h2h = clips.button(f"hbat_{bid}", f"You v {opp_short}")
    none = None
    if not reels and not h2h:
        none = "No available footage."
    elif not h2h:
        none = f"You v {opp_short}: no available footage."
    plan_half.append(_vision(reels, h2h, none, note))
    return _card(f"b{bid}", _head(bid, meta["name"], img, tier, sub, sample, report), plan_half, nums)


def batter_card(bid, meta, x, row, group, clips, img, pics_url, tier, fmt, opp_short, source, report="",
                shot=None, domestic=None, dom_reels=None):
    lhb = (meta.get("hand") or "").upper().startswith("L")
    role = (meta.get("role") or "").lower()
    sub = " · ".join([("Left-hander" if lhb else "Right-hander")]
                     + ([role] if role else [])
                     + (["figures from first-class cricket"] if source == "both" else []))
    hand = "LHB" if lhb else "RHB"
    glabel = _GROUP_LABEL.get(group, group)
    fmt_pl = {"Test": "Tests", "ODI": "ODIs", "T20I": "T20Is"}.get(fmt, fmt)
    fmt_one = fmt
    if domestic:                                    # a short ODI record, topped up (domestic_topup.py)
        import domestic_topup as DT
        fmt_pl = DT.sample_words(domestic, fmt_pl)
        fmt_one =fmt_pl if not domestic.get("odi") else fmt + " and domestic one-day"
    n = (x or {}).get("balls") or 0
    thin = not x or x.get("thin") or not x.get("balls")
    sample = (f"{fmt_pl} · {n:,} balls v {glabel}" if not thin
              else f"{'Only ' + format(n, ',') if n else 'No'} {fmt_one} balls v {glabel}")
    plan_half = [_notes_slot(bid), _field(bid, "Your field", _batter_field_opts(row, fmt, group, hand), hand, "batter")]
    nums = []
    # a small sample still shows its numbers and pictures, under its "Only N balls" line (Tom, 10-11-2026)
    if n:
        # under three dismissals there is no balls-per-dismissal figure; the count says why
        bpd = ((f'{x["bpd"]:.0f}', "Balls per dismissal") if x.get("bpd")
               else (f'{int(x.get("n_out") or 0)}', "Dismissals"))
        figs = [(_num(x.get("balls"), 0), "Balls"), (_num(x.get("average")), "Average"), bpd,
                (_pct(x.get("false_pct"), 1), "False shots"), (_pct(x.get("off_pct")), "Runs off side")]
        if group.endswith("pace") and x.get("short_false") is not None:
            # drawn on any sample since 10-11-2026, so it carries its own count
            sb = x.get("short_balls")
            figs.append((_pct(x["short_false"]) + (f'<small class="ln">of {sb:,} short</small>' if sb else ""),
                         "False v short ball"))
        slow = (shot or {}).get("slow") if group.endswith("pace") else None
        if slow:
            # coded slower balls: slower ball, cutters, back of the hand, knuckle ball (Tom, 10-11-2026)
            figs.append((_pct(slow["false_pct"]) + f'<small class="ln">of {slow["balls"]:,} slower</small>',
                         "False v slower ball"))
        if len(figs) > 6:
            figs = figs[1:]       # Balls makes way, as mocked: the sample line under the name gives it
        nums.append(_figures(figs))
        nums.append(_facts(x.get("facts")))
        nums.append(_shots(shot, group))
        nums.append(_wheel(bid, x, lhb, pics_url, shot, group))
        n_d = x.get("n_dismissals") or 0
        nums.append(_pics("Their dismissals", x, f"{n_d:,} dismissal{'s' if n_d != 1 else ''}", pics_url))
    reels, note = _batter_reels(clips, bid, group, meta, fmt, shot, dom_reels)
    h2h = clips.button(f"hbowl_{bid}", f"You to {opp_short}")
    none = None
    if not reels and not h2h:
        none = "No available footage."
    elif not h2h:
        none = f"You to {opp_short}: no available footage."
    plan_half.append(_vision(reels, h2h, none, note))
    return _card(f"b{bid}", _head(bid, meta["name"], img, tier, sub, sample, report), plan_half, nums)


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


def _player_head(name, img, sub, tabs, back_href, back_label):
    """The way back is always on show, laptop included, and says where it goes (11-10-2026)."""
    t = "".join(f'<a href="{E(h)}" class="{"on" if on else ""}">{E(lbl)}</a>' for lbl, h, on in tabs)
    return (f'<header class="ph"><div class="in"><a class="back" href="{E(back_href)}">‹ {E(back_label)}</a>'
            f'<div class="who">{_avatar("", name, img, "av lg")}<div><h1>{E(name)}</h1><div class="sb">{E(sub)}</div></div></div>'
            f'<nav class="ptabs">{t}</nav></div></header>')


def _section(title, sub, lead, xi_rows, more_rows):
    """The likely XI, then the rest of the squad, every player a row that opens the same way
    (Tom, 10-11-2026)."""
    s = f' <span>{E(sub)}</span>' if sub else ""
    out = f"<h2 class='sec'>{E(title)}{s}</h2><p class='lead'>{E(lead)}</p><div class='opps'>{''.join(xi_rows)}</div>"
    if more_rows:
        out += f"<h2 class='sec' id='also'>Also in the squad</h2><div class='opps'>{''.join(more_rows)}</div>"
    return out


def _detail(path, title, head, card, hp, js_v, fields_v, snippet):
    """One opposition player's full card on its own page, opened from View report in a pack's list.
    It goes back to the list and links nowhere else (Tom, 10-11-2026: not to the scouting report)."""
    open(path, "w", encoding="utf-8").write(
        _page(title, head + f"<main class='wrap hpw'>{card}</main>", hp, js_v, fields_v, snippet))


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
    # white-ball: each bowler's usual overs per phase (build_over_split.py), the summary's second point
    splits = (_load(os.path.join(DATA, f"over_split_{opp}.json"), {}) or {}).get("bowlers") or {}
    # their sweeps against spin, ramps against pace, false shots against slower balls (build_shot_types.py)
    shots = (_load(os.path.join(DATA, f"shot_types_{opp}.json"), {}) or {}).get("batters") or {}
    # a short ODI record read with its domestic one-day cricket: who, and which reels carry it
    import domestic_topup as DT
    dom_reels = (DT.load(opp).get("reels") or {}) if fmt == "ODI" else {}
    topped = (lambda pid, role: DT.topped(opp, pid, role)) if fmt == "ODI" else (lambda pid, role: None)
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
    # batting order (Tom, 06-10-2026); the likely XI first, then the rest of the squad
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
        hp = {"series": planner, "kind": "bat", "pid": str(pid), "hand": hand, "first": name.split()[0],
              "cardPack": f"vs_{hand.lower()}", "bandPack": "us_bat", "bandTitle": "From the batting coach"}
        xi, more = [], []
        for bid in bowl_order:
            meta, plan = about_bowl[bid] or {}, plans.get(bid) or {}
            x = ((extras["bowlers"].get(bid) or {}).get("hands") or {}).get(hand)
            tier = tiers.get(bid) or plan.get("tier") or ""
            nm, face = meta.get("name") or bid, img(bid, meta.get("name"))
            # the full card on its own page; the audit reads its kind from the "-batting.html" ending
            detail = f"{pslug}-v{bid}-batting.html"
            dom = topped(bid, "bowl")
            _detail(os.path.join(s_dir, detail), f"{name} — {nm}",
                    _player_head(name, my_img, f"{hand_word} · Batting pack · {nm}", [], bat_href, "All bowlers"),
                    bowler_card(bid, meta, plan, x, hand, clips, face, "pics/", tier, new_ball_min, fmt, short(nm),
                                domestic=dom, dom_reels=dom_reels.get(bid)),
                    hp, js_v, fields_v, snippet)
            pages += 1
            # the summary points, as the old packs read them: the about facts, and the over/round
            # split where the angle matters to this hand (build_player_site._over_round_point)
            facts = list(meta.get("facts") or [])
            # the usual overs per phase, straight after the speeds (Tom, 10-11-2026)
            over_split = (splits.get(str(bid)) or {}).get("text")
            if over_split:
                facts.insert(1 if facts else 0, over_split)
            orp = BPS._over_round_point(meta, hand.lower())
            if orp:
                facts.append(orp)
            if dom:
                facts.insert(0, DT.label(dom))        # first, so nothing is read before it
            reels, note = _bowler_reels(clips, bid, hand, meta, dom_reels.get(bid))
            label = f"You v {short(nm)}"
            (xi if tier == "xi" else more).append(_summary(
                f"b{bid}", nm, _bowler_sub(meta, plan, hand, new_ball_min), face, tier, facts, reels,
                clips.button(f"hbat_{bid}", label), label, note, detail))
        body = (_player_head(name, my_img, f"{hand_word} · Batting pack",
                             [(lbl, h, h == bat_href) for lbl, h in tab_list], "index.html", series_name)
                + "<main class='wrap hpw'><section class='band-note' hidden></section>"
                + _section("Their attack", f"{fmt_pl} · to {'left' if hand == 'LHB' else 'right'}-handers",
                           "Tap a bowler for their summary, the coaches' notes and the vision. "
                           "View coach notes and fields opens everything on them.", xi, more) + "</main>")
        open(os.path.join(s_dir, bat_href), "w", encoding="utf-8").write(
            _page(f"{name} — batting", body, hp, js_v, fields_v, snippet))
        pages += 1

        # ── a bowling pack per type: their batters, against our bowler's type ───────────────────
        for bt, group, href in bowl_pages:
            ov = _load(os.path.join(DATA, f"overview_{group}_{opp}.json"), {}) or {}
            rows = {str(r.get("bid")): r for r in ov.get("rows") or []}
            glabel = _GROUP_LABEL.get(group, group)
            hp = {"series": planner, "kind": "bowl", "pid": str(pid), "group": group, "first": name.split()[0],
                  "cardPack": group, "bandPack": "us_bowl", "bandTitle": "From the bowling coach"}
            gword = glabel[:1].upper() + glabel[1:]
            tw = "spin" if group in ("off_spin", "leg_spin", "left_orthodox", "left_unorthodox", "spin") else "pace"
            xi, more = [], []
            for bid in bat_order:
                meta = about_bat[bid] or {}
                eb = extras["batters"].get(bid) or {}
                x = (eb.get("groups") or {}).get(group)
                shot = ((shots.get(bid) or {}).get("groups") or {}).get(group)
                tier = tiers.get(bid) or ""
                nm, face = meta.get("name") or bid, img(bid, meta.get("name"))
                detail = f"{href[:-len('.html')]}-v{bid}.html"     # keeps "-bowling-" for the audit
                dom = topped(bid, "bat")
                _detail(os.path.join(s_dir, detail), f"{name} — {nm}",
                        _player_head(name, my_img, f"{gword} · Bowling pack · {nm}", [], href, "All batters"),
                        batter_card(bid, meta, x, rows.get(bid), group, clips, face, "pics/", tier, fmt,
                                    short(nm), eb.get("source"), shot=shot, domestic=dom,
                                    dom_reels=dom_reels.get(bid)),
                        hp, js_v, fields_v, snippet)
                pages += 1
                # the summary points, as the old packs read them: the facts for this macro type, with
                # the exact type's plan from its overview row in place of the macro one
                facts = list(meta.get(f"facts_{tw}") or [])
                plan_line = (rows.get(bid) or {}).get("plan")
                if plan_line:
                    facts = [plan_line if str(f).startswith("Plan for ") else f for f in facts]
                    if not any(str(f).startswith("Plan for ") for f in facts):
                        facts.insert(1 if facts else 0, plan_line)
                if dom:
                    facts.insert(0, DT.label(dom))    # first, so nothing is read before it
                lhb = (meta.get("hand") or "").upper().startswith("L")
                sub = " · ".join(["Left-hander" if lhb else "Right-hander"]
                                 + ([meta["role"].lower()] if meta.get("role") else []))
                reels, note = _batter_reels(clips, bid, group, meta, fmt, shot, dom_reels.get(bid))
                label = f"You to {short(nm)}"
                (xi if tier == "xi" else more).append(_summary(
                    f"b{bid}", nm, sub, face, tier, facts, reels, clips.button(f"hbowl_{bid}", label),
                    label, note, detail))
            body = (_player_head(name, my_img, f"{gword} · Bowling pack",
                                 [(lbl, h, h == href) for lbl, h in tab_list], "index.html", series_name)
                    + "<main class='wrap hpw'><section class='band-note' hidden></section>"
                    + _section("Their batters", f"{fmt_pl} · v {glabel}",
                               "Tap a batter for their summary, the coaches' notes and the vision. "
                               "View coach notes and fields opens everything on them.", xi, more) + "</main>")
            open(os.path.join(s_dir, href), "w", encoding="utf-8").write(
                _page(f"{name} — bowling ({bt})", body, hp, js_v, fields_v, snippet))
            pages += 1

    # ── the squad index: a list of names, each with its packs (Tom, 10-11-2026: as the old packs) ──
    groups = [("Batter", "Batters"), ("Wicketkeeper", "Wicketkeepers"), ("All-rounder", "All-rounders"),
              ("Bowler", "Bowlers")]
    known = {r for r, _ in groups}
    lists = []
    for role, head in groups + [("", "Squad")]:
        rows = [r for r in index_rows if (r[2] == role if role else r[2] not in known)]
        if not rows:
            continue
        def row(pid, nm, rl, p, b):
            packs = [("Batting", f"{p}-batting.html")] + [
                ("Bowling" if len(b) == 1 else f"Bowling: {bt.capitalize()}", f"{p}-bowling-{bt}.html") for bt in b]
            chips = "".join(f'<a class="pk" href="{E(h)}">{E(lbl)}</a>' for lbl, h in packs)
            return (f'<li><span class="who">{_avatar(pid, nm, img(pid, nm), "av")}'
                    f'<span><b>{E(nm)}</b><span>{E(rl)}</span></span></span><span class="pks">{chips}</span></li>')
        lists.append(f"<h2 class='sec'>{E(head)} <span>{len(rows)}</span></h2>"
                     f"<ul class='roster'>{''.join(row(*r) for r in rows)}</ul>")
    lead = " · ".join(x for x in (smeta.get("subtitle") or entry.get("subtitle") or "", "tap Batting or Bowling") if x)
    # data-hub-nav: the playerpacks app takes this link out for the players' login, whose link opens
    # one series and leads nowhere else (Tom, 10-11-2026). Coaches keep it.
    idx = (f"<header class='ph'><div class='in'><a class='back' data-hub-nav href='../index.html'>‹ Series</a>"
           f"<div class='who'><div><h1>{E(series_name)}</h1>"
           f"<div class='sb'>{E(lead)}</div></div></div></div></header>"
           f"<main class='wrap hpw'>{''.join(lists)}</main>")
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
