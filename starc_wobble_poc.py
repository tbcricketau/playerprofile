"""starc_wobble_poc.py — proof of concept: CAN WE SEE the wobble-seam vs out-swinger
difference in footage? STARC ONLY (per scope).

Selects new-ball deliveries by the coder labels (2827/2828):
  * out_swing    — genuine out-swingers (movement_in_air_group = Out Swing)
  * wobble_proxy — "No Swing but still seams" (the wobble behavioural proxy — highest
                   false-shot rate in the earlier analysis)
resolves their broadcast Fairplay clips (Starc isn't in any Hawkeye-covered match, so
broadcast is the only angle), and writes a side-by-side review player:
reports/starc_wobble_vs_swing.player.html

Run:  .\venv\Scripts\python.exe -u starc_wobble_poc.py
"""
import warnings

warnings.filterwarnings("ignore")

from profile import build_profile
from cricket_core.video import (
    playlist_item, resolve_playlist, build_player_html, get_fairplay_sas,
)

STARC = "1300007"


def _caption(r):
    bits = []
    if r.get("over_n") is not None:
        bits.append(f"Ov {r['over_n']}")
    lb = r.get("ball_type")
    if lb:
        bits.append(f"{lb[0].lower()} {lb[1]}")
    if r.get("ball_speed_n"):
        bits.append(f"{r['ball_speed_n']:.0f} km/h")
    sd = r.get("seam_dir")
    if sd and sd != "straight":
        bits.append(f"seams {sd}")
    if r.get("is_wicket"):
        bits.append((r.get("how_out") or "wicket").lower())
    elif r.get("is_false_shot"):
        bits.append("false shot")
    d = r.get("match_date")
    if d:
        bits.append(d)
    return " · ".join(bits)


def main():
    get_fairplay_sas(ttl_hours=72)
    P = build_profile(STARC, hand="All")
    df = [r for r in P["df"] if r.get("clip_stem") and r.get("over_n") is not None
          and r["over_n"] <= 25]

    out_swing = [r for r in df if r.get("swing_dir") == "out"]
    wobble = [r for r in df if r.get("swing_dir") == "straight"
              and r.get("seam_dir") in ("in", "away")]

    def prep(rows, cap=10):
        rows.sort(key=lambda r: r.get("match_date") or "", reverse=True)     # clip coverage
        rows.sort(key=lambda r: (not r.get("is_wicket"), not r.get("is_false_shot")))
        items = [playlist_item(r.get("delivery_id"), r["clip_stem"], _caption(r))
                 for r in rows[: cap * 4]]
        resolved, avail, _ = resolve_playlist(items, drop_missing=True)
        return resolved[:cap]

    pls = {}
    a = prep(out_swing)
    if a:
        pls["out_swing"] = a
    b = prep(wobble)
    if b:
        pls["wobble_proxy"] = b
    print(f"candidates: out-swing {len(out_swing)}, wobble-proxy {len(wobble)}; "
          f"resolved: {len(a)} / {len(b)}")
    if not pls:
        print("no clips resolvable — nothing to review")
        return
    out = r"reports/starc_wobble_vs_swing.player.html"
    build_player_html(
        pls, out, title="Starc — out-swinger vs wobble-seam (PoC)",
        subtitle="New ball (≤25 ov) · labelled by coders (2827/2828) · broadcast angle · "
                 "illustrative balls (wickets/false shots) first",
        titles={"out_swing": "Out-swingers", "wobble_proxy": "Wobble proxy (no swing, seams)"})
    print("player ->", out)


if __name__ == "__main__":
    main()
