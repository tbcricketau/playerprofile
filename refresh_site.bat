@echo off
REM Refreshes the scouting-reports static site with a fresh video SAS and redeploys to GitHub
REM Pages. Run by the "Scouting Reports Refresh" scheduled task every ~5 days (the SAS lasts
REM ~6.5 days). Uses your cached SSO login; if it stops working, run once interactively to
REM re-auth:  venv\Scripts\python.exe publish_site.py
cd /d C:\Ludis\playerprofile
call venv\Scripts\python.exe publish_site.py --deploy-repo https://github.com/tbcricketau/scouting-reports.git >> refresh.log 2>&1
echo %DATE% %TIME% exit=%ERRORLEVEL% >> refresh.log
