# Web app — durable, shareable reports with mint-on-demand video

**Problem it solves.** A standalone report `.html` bakes a video SAS that expires in ~72 h
(user-delegation SAS is capped at 7 days by Azure). Players need clips to work for ~6 months.
The fix is to **mint a fresh SAS at view time** instead of baking one — which needs a running
app with an identity that can authenticate to storage. Hence `webapp.py`.

## What's built (MVP — works now, on your SSO)
`playerprofile/webapp.py` — a small Flask app:
- **`/clip?stem=<blob-stem>`** — mints a fresh SAS + resolves the extension, 302-redirects the
  `<video>` to the playable URL. Called by the player each time a clip opens → video never goes
  stale. ✅ verified (returns a live 6-hour SAS).
- **`/hawkeye?blob=<blob>`** — same, for Hawkeye multi-angle clips.
- **`/`** — index of rendered reports (from the `*.playlists.json` sidecars) + PDF links.
- **`/r/<name>`** — serves the interactive report with its player rewired to the mint endpoints.
- **`/player/<name>`** — standalone all-playlists player (quick clip review), mint-based.
- **`/pdf/<name>`** — the PDF.

Run: `.\venv\Scripts\python.exe webapp.py` → http://127.0.0.1:8062

## The one IT dependency (for public + shareable)
Locally it authenticates with **your** SSO (device-code, cached) — so it works for you now, but
isn't yet a public URL others can open. To host it (Azure App Service / Container App) so anyone
with the link gets working video for months:
1. Give the app a **managed identity** with **Storage Blob Data Reader** on
   `auscricketfairplayase` (Fairplay) and `amshawkeyeupload` (Hawkeye). *(Same class of RBAC
   grant as the Virtualeye ask — bundle them.)*
2. Swap `_credential` so the shared `ludis_cricket.video` auth uses that managed identity when
   running in Azure (env-detected) instead of device-code. **No other code changes.**
3. Deploy (Dockerfile or App Service zip). The report links become e.g.
   `https://scouting.<...>.azurewebsites.net/r/nahid_rana_bowling_pace_test_lhb`.

## Coverage of the sharing options (as agreed)
| Need | PDF | Web app |
|---|---|---|
| Permanent / printable / offline | ✅ | ➖ (charts+text offline if saved; video needs network) |
| Video for ~6 months | ➖ | ✅ (SAS minted per view) |
| One shareable link | file | ✅ (once hosted) |

## Follow-ons
- Re-render reports so `/r` cleanly swaps the baked player (markers added to `report.py`;
  batting_report.py still to add).
- Index: label reports by hand (All / vs LHB / vs RHB) — currently shows both.
- Auth on the hosted app (so only staff/players can view) — Static Web Apps / App Service easy-auth.
- Offline pack: a "download for offline" that bundles the PDF (video links noted as online-only).
