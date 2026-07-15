"""
photos.py — player images for this project's reports and apps.

Headshots live in the ESTATE-WIDE store, `cricket_core.headshots` (cricket-core/headshots/,
fed from cricket.com.au — see that module for the full pipeline). This wrapper adds one thing:
a project-local override folder, `photos/`, checked FIRST — it holds the hand-collected
opposition photos that predate the CA pipeline, and lets you drop a replacement file for
anyone without touching the shared store.

    get_photo_bytes(player_id, fmt=None, name=None)
        photos/{id}.{png|jpg}  (project override / legacy)
     -> cricket_core.headshots (format-aware kit variants; auto-fetches from CA when `name`
        is given and the player isn't stored yet)
     -> None  (callers show the placeholder)
"""
import base64
import os

from cricket_core import headshots

_HERE = os.path.dirname(__file__)
_LOCAL_DIR = os.path.join(_HERE, "photos")
_EXTS = (".png", ".jpg", ".jpeg")


def _local(bid: str) -> str | None:
    for ext in _EXTS:
        p = os.path.join(_LOCAL_DIR, f"{bid}{ext}")
        if os.path.exists(p):
            return p
    return None


def _mime(data: bytes) -> str:
    return "image/png" if data[:8].startswith(b"\x89PNG") else "image/jpeg"


def get_photo_path(bowler_id, fmt=None, name=None) -> str | None:
    """Path of the best available image (local override first, then the shared store,
    fetching from CA by name if needed)."""
    bid = str(bowler_id)
    hit = _local(bid) or headshots.find(bid, fmt)
    if not hit and headshots.ensure(bid, name):
        hit = headshots.find(bid, fmt)
    return hit


def get_photo_bytes(bowler_id, fmt=None, name=None) -> bytes | None:
    hit = get_photo_path(bowler_id, fmt, name)
    if hit:
        with open(hit, "rb") as f:
            return f.read()
    return None


def get_photo_data_uri(bowler_id, fmt=None, name=None) -> str | None:
    data = get_photo_bytes(bowler_id, fmt, name)
    if not data:
        return None
    return f"data:{_mime(data)};base64," + base64.b64encode(data).decode()
