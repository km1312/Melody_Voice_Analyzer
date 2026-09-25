<#
.SYNOPSIS
Prove, at the operating-system level, that Melody sends nothing anywhere
(PRD PR-3).

.DESCRIPTION
Adds Windows Firewall outbound-block rules for the Melody executable and,
optionally, a local model server executable, then prints how to confirm
them. The app already refuses non-loopback endpoints in code and sets the
HuggingFace offline switches once models are cached; these rules make the
same promise in a place no Python bug can reach. Loopback traffic is not
affected by the Windows Firewall, so the local model keeps working.

Run from an elevated PowerShell. Re-running replaces the rules.

.EXAMPLE
.\tools\verify_offline.ps1
.\tools\verify_offline.ps1 -AppExe "D:\apps\Melody Tone Analyzer\Melody Tone Analyzer.exe" -ServerExe "C:\llama\llama-server.exe"

.NOTES
Remove the rules again with:
    Remove-NetFirewallRule -DisplayName "Melody offline*"
#>
param(
    [string]$AppExe = "",
    [string]$ServerExe = ""
)

$ErrorActionPreference = "Stop"

if (-not ([Security.Principal.WindowsPrincipal] `
        [Security.Principal.WindowsIdentity]::GetCurrent()
        ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "Firewall rules need an elevated PowerShell. Right-click, Run as administrator."
    exit 1
}

if (-not $AppExe) {
    $root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Definition)
    $candidates = @(
        (Join-Path $root "dist\Melody Tone Analyzer\Melody Tone Analyzer.exe"),
        (Join-Path $root ".venv\Scripts\python.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { $AppExe = $candidate; break }
    }
}
if (-not $AppExe -or -not (Test-Path $AppExe)) {
    Write-Error "Could not find the app executable. Pass -AppExe explicitly."
    exit 1
}

$targets = @(@{Name = "Melody offline (app)"; Exe = $AppExe })
if ($ServerExe) {
    if (-not (Test-Path $ServerExe)) {
        Write-Error "Server executable not found: $ServerExe"
        exit 1
    }
    $targets += @{Name = "Melody offline (model server)"; Exe = $ServerExe }
}

foreach ($target in $targets) {
    Get-NetFirewallRule -DisplayName $target.Name -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule
    New-NetFirewallRule -DisplayName $target.Name `
        -Direction Outbound -Action Block -Program $target.Exe `
        -Profile Any | Out-Null
    Write-Host "Blocked outbound traffic for $($target.Exe)" -ForegroundColor Green
}

Write-Host ""
Write-Host "Confirm the rules:" -ForegroundColor Cyan
Write-Host '  Get-NetFirewallRule -DisplayName "Melody offline*" | Format-Table DisplayName, Enabled, Action'
Write-Host ""
Write-Host "Loopback (127.0.0.1) is not filtered by the Windows Firewall, so a"
Write-Host "local model on this machine keeps working. First-run model downloads"
Write-Host "will fail while these rules exist; run the first download before"
Write-Host "adding them, or remove them for that one run:"
Write-Host '  Remove-NetFirewallRule -DisplayName "Melody offline*"'
Write-Host ""
Write-Host "Full-machine check: disable the network adapter and run"
Write-Host '  & "Melody Tone Analyzer.exe" --selftest some-clip.wav'
Write-Host "Exit code 0 with the adapter off is the whole claim, proved."
