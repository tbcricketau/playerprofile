import os

from ludis_cricket.config import DATA_SCHEMA  # re-export — single source of truth

# ── Player photos ───────────────────────────────────────────────────────────────
# Backend: "local" reads from photos/ only; "sharepoint" also fetches from a
# SharePoint document library via Microsoft Graph (cached to .photo_cache/, with
# the local photos/ folder as fallback).  Flip via the photo_backend env var once
# the app registration has Sites.Selected on the scouting site.
PHOTO_BACKEND        = os.getenv("photo_backend", "local")
SHAREPOINT_HOSTNAME  = os.getenv("sp_hostname", "australiancricket.sharepoint.com")
SHAREPOINT_SITE_PATH = os.getenv("sp_site_path", "")            # e.g. "sites/Scouting"
PHOTO_LIBRARY        = os.getenv("sp_photo_library", "Documents")
PHOTO_FOLDER         = os.getenv("sp_photo_folder", "player_photos")
