# One-command environment build for this project (see c:\Projects\README.md).
# Creates the venv, installs requirements (incl. the sibling cricket-core editable),
# activates the secret-scan git hooks, and runs the sanity checks.
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

if (-not (Test-Path (Join-Path $here "..\cricket-core"))) {
    Write-Warning "cricket-core not found as a sibling folder. Clone it first:"
    Write-Warning "  git clone https://github.com/tbcricketau/cricket-core.git $((Resolve-Path (Join-Path $here '..')).Path)\cricket-core"
    exit 1
}

Write-Output "== venv =="
py -3.12 -m venv venv
$env:SETUPTOOLS_USE_DISTUTILS = "local"   # Python 3.12 dropped distutils
.\venv\Scripts\python.exe -m pip install --quiet --upgrade pip setuptools wheel

Write-Output "== requirements =="
.\venv\Scripts\python.exe -m pip install --quiet -r requirements.txt --no-build-isolation

Write-Output "== git hooks (secret scan) =="
if (Test-Path .githooks) { git config core.hooksPath .githooks; Write-Output "core.hooksPath -> .githooks" }

Write-Output "== sanity checks =="
.\venv\Scripts\python.exe -c "import cricket_core; print('cricket_core OK')"
$numpyCheck = @"
import importlib.util
spec = importlib.util.find_spec('numpy')
if spec is None:
    print('numpy: not installed (fine - stdlib is the house default)')
else:
    import numpy
    print('numpy', numpy.__version__, 'loads OK (WDAC/ISG check passed)')
"@
.\venv\Scripts\python.exe -c $numpyCheck

Write-Output ""
Write-Output "Setup complete. Warehouse needs the app_id / app_secret env vars (README section 4)."
