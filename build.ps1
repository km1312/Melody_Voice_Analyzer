# Build Melody Tone Analyzer into a standalone Windows app folder.
#
#   .\build.ps1
#   .\build.ps1 -DistPath dist\staging
#
# The result lands in dist\Melody Tone Analyzer\, with the .exe at its root, or
# under -DistPath instead. Building somewhere else is how to rebuild while the
# app is running: PyInstaller cannot empty a folder Windows holds open, so
# build to a staging folder and swap it in once the app is closed.
# Expect 15 to 40 minutes and roughly 8 GB on the first run.

param(
    [string]$DistPath = "dist"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "No virtual environment at $python. Create it and install the pipeline dependencies first."
}

Write-Host "Checking build dependencies..." -ForegroundColor Cyan
& $python -m pip install --quiet --upgrade pyinstaller PySide6-Essentials psutil pillow jsonschema send2trash sounddevice
if ($LASTEXITCODE -ne 0) { throw "Dependency install failed." }

if (-not (Test-Path (Join-Path $root "revolv.ico"))) {
    Write-Host "Generating the icon..." -ForegroundColor Cyan
    & $python make_icon.py
}

# Seed the first-run HuggingFace token into the bundle. The source carries none:
# the token comes from REVOLV_HF_TOKEN or, failing that, from this machine's own
# settings file, and goes into a gitignored data file that the spec packs and
# this script deletes again once PyInstaller has finished.
$tokenFile = Join-Path $root "revolv\assets\hf_token.txt"
$token = $env:REVOLV_HF_TOKEN
$tokenSource = "REVOLV_HF_TOKEN"
if (-not $token) {
    # The current settings folder first, then the one the app used before it
    # was renamed from Revolv Transcriber.
    foreach ($folder in @("MelodyToneAnalyzer", "RevolvTranscriber")) {
        $settingsFile = Join-Path $env:LOCALAPPDATA "$folder\settings.json"
        if (Test-Path $settingsFile) {
            try { $token = (Get-Content $settingsFile -Raw | ConvertFrom-Json).hf_token } catch { $token = $null }
            $tokenSource = "this machine's settings"
            if ($token) { break }
        }
    }
}
if ($token) {
    Set-Content -Path $tokenFile -Value ([string]$token).Trim() -Encoding ascii -NoNewline
    Write-Host "Seeding the bundle with the HuggingFace token from $tokenSource." -ForegroundColor Cyan
} else {
    if (Test-Path $tokenFile) { Remove-Item $tokenFile }
    Write-Host "No HuggingFace token found in REVOLV_HF_TOKEN or settings.json; the build will ask for one in Settings." -ForegroundColor Yellow
}

try {
    Write-Host "Running PyInstaller. This takes a while." -ForegroundColor Cyan
    & $python -m PyInstaller --noconfirm --clean --distpath $DistPath MelodyToneAnalyzer.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed. See the output above." }
} finally {
    if (Test-Path $tokenFile) { Remove-Item $tokenFile }
}

$exe = Join-Path (Join-Path $root $DistPath) "Melody Tone Analyzer\Melody Tone Analyzer.exe"
if (-not (Test-Path $exe)) { throw "The build finished but $exe is missing." }

$bytes = (Get-ChildItem (Split-Path $exe) -Recurse -File | Measure-Object -Property Length -Sum).Sum
Write-Host ""
Write-Host "Built $exe" -ForegroundColor Green
Write-Host ("Bundle size: {0:N1} GB" -f ($bytes / 1GB)) -ForegroundColor Green
Write-Host ""
Write-Host "Move the whole 'Melody Tone Analyzer' folder wherever you like, then make a"
Write-Host "shortcut to the .exe. Keep the folder together; the .exe needs _internal."
