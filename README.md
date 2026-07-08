# Player Profile

Streamlit scouting app — player profile reports for Test cricket (bowler pace/spin
profiles, batter profiles, pitch maps, danger zones, spell analysis) with printable
PDF report generation.

## Run locally

```powershell
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m streamlit run app.py
```

`app.py` is the entry point. `run.py` is a deployment shim for the Ludis platform
(runs `app.py` on port 8060) — don't run it locally.

**Reports:** `build_reports.py` (bowling) and `build_batting_reports.py` (batting)
render PDFs into `reports/` (gitignored — regenerate as needed). `report_bowlers.csv`
lists which players to build. Bump `REPORT_VERSION` in `version.py` and note the
change in `CHANGELOG.md` whenever report output changes.

**Photos:** the local `photos/` folder holds player images (source, committed).
Optionally a SharePoint/Graph backend can fetch more, cached to `.photo_cache/`
(gitignored) — enable via the `photo_backend` env var (see `config.py`).

## Data

- **Live data** comes from the Azure SQL warehouse via `cricket_core.warehouse`
  (non-interactive MSAL auth); schema is `cricket_core.config.DATA_SCHEMA`.

### Reference-data dependency (important)

This app reads **pre-built bowler profiles** produced by the sibling project
[`referencebuilder`](../referencebuilder):

| File (`referencebuilder/data/`)      | Built by (`referencebuilder/scripts/`) |
|--------------------------------------|----------------------------------------|
| `bowler_speed_profile.csv`           | `build_bowler_speed_profile.py`        |
| `bowler_movement_profile.csv`        | `build_bowler_movement_profile.py`     |
| `bowler_repeatability_profile.csv`   | `build_bowler_repeatability_profile.py`|
| `bowler_crease_profile.csv`          | `build_bowler_crease_profile.py`       |

`profile.py` references these by **absolute path** (`c:\Projects\referencebuilder\data\…`),
so the projects must live as **siblings under `c:\Projects\`**. To (re)generate the
profiles — and to see when they need refreshing (new data drop, `DATA_SCHEMA` change,
new matches) — see **`referencebuilder/RUNBOOK.md`**.

> Note: the absolute paths in `profile.py` are brittle; a future cleanup could
> switch to a relative/`REFERENCE_DATA_DIR`-style lookup like livematchdashboard uses.
