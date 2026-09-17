# Build Revolv Transcriber into a standalone Windows app folder.
#
#   .\build.ps1
#
# The result lands in dist\Revolv Transcriber\, with the .exe at its root.
# Expect 15 to 40 minutes and roughly 8 GB on the first run.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "No virtual environment at $python. Create it and install the pipeline dependencies first."
}

Write-Host "Checking build dependencies..." -ForegroundColor Cyan
& $python -m pip install --quiet --upgrade pyinstaller PySide6-Essentials psutil pillow
if ($LASTEXITCODE -ne 0) { throw "Dependency install failed." }

if (-not (Test-Path (Join-Path $root "revolv.ico"))) {
    Write-Host "Generating the icon..." -ForegroundColor Cyan
    & $python make_icon.py
}

Write-Host "Running PyInstaller. This takes a while." -ForegroundColor Cyan
& $python -m PyInstaller --noconfirm --clean RevolvTranscriber.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed. See the output above." }

$exe = Join-Path $root "dist\Revolv Transcriber\Revolv Transcriber.exe"
if (-not (Test-Path $exe)) { throw "The build finished but $exe is missing." }

$bytes = (Get-ChildItem (Split-Path $exe) -Recurse -File | Measure-Object -Property Length -Sum).Sum
Write-Host ""
Write-Host "Built $exe" -ForegroundColor Green
Write-Host ("Bundle size: {0:N1} GB" -f ($bytes / 1GB)) -ForegroundColor Green
Write-Host ""
Write-Host "Move the whole 'Revolv Transcriber' folder wherever you like, then make a"
Write-Host "shortcut to the .exe. Keep the folder together; the .exe needs _internal."
