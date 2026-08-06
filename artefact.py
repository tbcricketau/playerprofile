"""Publish a profile as an artefact, so renderings become consumers.

`playerprofile` computes per-player derived truth (`profile.build_profile` /
`batter_profile`) and then renders it. The expensive, reusable half is the profile; the
cheap, editorial half is the document. Promoting the profile to a **published artefact** —
the same move `referencebuilder` makes with its CSVs — lets a coach dossier, a player
one-pager, a deck slide or a handoff each be a small consumer instead of a fork of the
profile code. Architecture: `../FUTURE_PROJECTS.md` §"should `playerprofile` split?".

This module is **additive**. It does not touch the existing render path — `report.py` and
`batting_report.py` keep calling `build_profile()` directly. Nothing about the live sites
changes by importing this.

    from artefact import publish, load
    publish(bowler_id)                  # -> data/profiles/bowler_<id>.json
    P = load("bowler", bowler_id)       # a consumer reads the artefact, not the warehouse

**Bulk delivery lists are excluded.** `raw`, `df`, `legal` and `beaten_df` are the balls the
metrics were computed from — large, and player data. The artefact carries the derived truth
(metrics, zones, fingerprint, dismissals, danger areas), which is what a rendering needs.
Anything needing the balls should build the profile itself.

Artefacts are written under `data/profiles/` and are **gitignored** like every other
generated output here.
"""
from __future__ import annotations

import json
from pathlib import Path

ARTEFACT_VERSION = 1

ROOT = Path(__file__).parent
PROFILE_DIR = ROOT / "data" / "profiles"

# The delivery lists the metrics were derived from — excluded from the artefact.
BULK_KEYS = {"raw", "df", "legal", "beaten_df"}


def _jsonable(o):
    """Last-resort coercion so a profile always serialises. Sets/tuples become lists;
    anything exotic becomes its string form rather than failing the whole publish."""
    if isinstance(o, (set, frozenset, tuple)):
        return list(o)
    if hasattr(o, "isoformat"):
        return o.isoformat()
    return str(o)


def to_artefact(P: dict, kind: str = "bowler") -> dict:
    """The publishable view of a profile dict: derived truth, no bulk delivery lists."""
    body = {k: v for k, v in P.items() if k not in BULK_KEYS}
    pid = P.get("bowler_id") or P.get("batter_id") or P.get("player_id")
    return {
        "artefact_version": ARTEFACT_VERSION,
        "kind": kind,
        "player_id": str(pid) if pid is not None else None,
        "name": P.get("name"),
        "excluded": sorted(BULK_KEYS & set(P)),   # honest about what was dropped
        "profile": body,
    }


def path_for(kind: str, player_id) -> Path:
    return PROFILE_DIR / f"{kind}_{player_id}.json"


def publish(P_or_id, kind: str = "bowler", **build_kwargs) -> Path:
    """Write a profile artefact and return its path.

    Pass an already-built profile dict (cheap — no rebuild), or a player id to build first.
    """
    if isinstance(P_or_id, dict):
        P = P_or_id
    elif kind == "bowler":
        from profile import build_profile
        P = build_profile(str(P_or_id), **build_kwargs)
    else:
        raise ValueError(f"Pass a built profile dict for kind={kind!r}, or a bowler id.")

    art = to_artefact(P, kind=kind)
    if not art["player_id"]:
        raise ValueError("Profile has no player id — cannot name the artefact.")
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    out = path_for(kind, art["player_id"])
    out.write_text(json.dumps(art, indent=1, default=_jsonable), encoding="utf-8")
    return out


def load(kind: str, player_id) -> dict:
    """Read a published artefact. Returns the full envelope; `["profile"]` is the profile."""
    p = path_for(kind, player_id)
    if not p.exists():
        raise FileNotFoundError(f"No {kind} artefact for {player_id} at {p}. Publish it first.")
    return json.loads(p.read_text(encoding="utf-8"))


def published(kind: str | None = None) -> list[Path]:
    """Every artefact on disk, optionally filtered to one kind."""
    if not PROFILE_DIR.exists():
        return []
    return sorted(PROFILE_DIR.glob(f"{kind or '*'}_*.json"))
