"""
photos.py — resolve player profile images from local disk or SharePoint.

`get_photo_bytes(bowler_id)` resolves in order:
    local cache (.photo_cache/) -> photos/ folder -> SharePoint (Graph) -> None

SharePoint access reuses the same MSAL client-credentials app as the SQL layer
(app_id / app_secret), swapping the scope to Microsoft Graph.  Images live at
{PHOTO_FOLDER}/{bowler_id}.{png|jpg} inside a document library on the configured
site.  The app registration needs Graph **Sites.Selected** granted on that site.

Everything degrades gracefully: if SharePoint is unconfigured, unreachable, or
the permission isn't granted yet, callers just get None (emoji placeholder).
"""
import base64
import os

import config

_HERE = os.path.dirname(__file__)
_LOCAL_DIR = os.path.join(_HERE, "photos")
_CACHE_DIR = os.path.join(_HERE, ".photo_cache")

_GRAPH = "https://graph.microsoft.com/v1.0"
_EXTS = (".png", ".jpg", ".jpeg")   # accepted image types, in preference order
_missing: set = set()   # per-process negative cache — avoid re-hitting 404s
_ids: dict = {}         # cached site_id / drive_id


def _find(directory: str, bid: str) -> str | None:
    for ext in _EXTS:
        p = os.path.join(directory, f"{bid}{ext}")
        if os.path.exists(p):
            return p
    return None


def _mime(data: bytes) -> str:
    return "image/png" if data[:8].startswith(b"\x89PNG") else "image/jpeg"


# ── Microsoft Graph ─────────────────────────────────────────────────────────────
def _graph_token() -> str | None:
    from ludis_cricket.warehouse import get_params_data_warehouse, get_token
    params, _ = get_params_data_warehouse()
    params = dict(params, scope=["https://graph.microsoft.com/.default"])
    tok = get_token(params) or {}
    return tok.get("access_token")


def _graph_get(url: str):
    import requests
    token = _graph_token()
    if not token:
        return None
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=20)
    return resp if resp.status_code == 200 else None


def _site_id() -> str | None:
    if "site" in _ids:
        return _ids["site"]
    host = config.SHAREPOINT_HOSTNAME
    path = config.SHAREPOINT_SITE_PATH.strip("/")
    url = f"{_GRAPH}/sites/{host}:/{path}" if path else f"{_GRAPH}/sites/{host}"
    resp = _graph_get(url)
    _ids["site"] = resp.json().get("id") if resp else None
    return _ids["site"]


def _drive_id() -> str | None:
    if "drive" in _ids:
        return _ids["drive"]
    sid = _site_id()
    did = None
    if sid:
        resp = _graph_get(f"{_GRAPH}/sites/{sid}/drives")
        drives = resp.json().get("value", []) if resp else []
        want = config.PHOTO_LIBRARY.strip().lower()
        did = next((d["id"] for d in drives if d.get("name", "").lower() == want), None)
        if not did and drives:      # fall back to the site's default library
            did = drives[0]["id"]
    _ids["drive"] = did
    return did


def _fetch_sharepoint(bid: str):
    """Return (bytes, ext) for the first matching PNG/JPG, or None."""
    did = _drive_id()
    if not did:
        return None
    folder = config.PHOTO_FOLDER.strip("/")
    for ext in _EXTS:
        rel = f"{folder}/{bid}{ext}" if folder else f"{bid}{ext}"
        resp = _graph_get(f"{_GRAPH}/drives/{did}/root:/{rel}:/content")
        if resp:
            return resp.content, ext
    return None


# ── Public API ──────────────────────────────────────────────────────────────────
def get_photo_bytes(bowler_id) -> bytes | None:
    bid = str(bowler_id)

    hit = _find(_CACHE_DIR, bid) or _find(_LOCAL_DIR, bid)
    if hit:
        with open(hit, "rb") as f:
            return f.read()

    if config.PHOTO_BACKEND == "sharepoint" and bid not in _missing:
        try:
            result = _fetch_sharepoint(bid)
        except Exception:
            result = None
        if result:
            data, ext = result
            os.makedirs(_CACHE_DIR, exist_ok=True)
            with open(os.path.join(_CACHE_DIR, f"{bid}{ext}"), "wb") as f:
                f.write(data)
            return data
        _missing.add(bid)

    return None


def get_photo_data_uri(bowler_id) -> str | None:
    data = get_photo_bytes(bowler_id)
    if not data:
        return None
    return f"data:{_mime(data)};base64," + base64.b64encode(data).decode()
