@echo off
REM Refreshes the scouting-reports static site with a fresh video SAS and redeploys to GitHub
REM Pages, BEHIND THE SHARED PASSWORD GATE (deploy_scouting.py encrypts each page; the password
REM is read from .scouting_pw). Run by the "Scouting Reports Refresh" scheduled task every ~5 days
REM (the SAS lasts ~6.5 days). Uses your cached SSO login; if it stops working, run once
REM interactively to re-auth:  venv\Scripts\python.exe publish_site.py
REM
REM RESET THE PASSWORD: edit .scouting_pw (one line, the shared password) then run this .bat (or
REM wait for the scheduled task) — every page re-encrypts with the new password on the next deploy.
cd /d C:\Projects\playerprofile
call venv\Scripts\python.exe deploy_scouting.py --repo https://github.com/tbcricketau/scouting-reports.git >> refresh.log 2>&1
echo %DATE% %TIME% exit=%ERRORLEVEL% >> refresh.log
