param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

foreach ($Required in @("modern_shell.py", "DunoonDaemon_portable.spec", "icon.ico", "VERSION.txt")) {
    if (-not (Test-Path (Join-Path $Root $Required))) {
        throw "Missing required build file: $Required"
    }
}

$Version = (Get-Content .\VERSION.txt -Raw).Trim()
Write-Host "Dunoon Daemon v$Version portable EXE forge" -ForegroundColor Cyan
Write-Host "Python: $Python"

if (Test-Path .\build) { Remove-Item .\build -Recurse -Force }
if (Test-Path .\dist)  { Remove-Item .\dist  -Recurse -Force }

& $Python -m PyInstaller --noconfirm --clean .\DunoonDaemon_portable.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

$Exe = Join-Path $Root "dist\DunoonDaemon.exe"
if (-not (Test-Path $Exe)) { throw "Build finished without dist\DunoonDaemon.exe" }

$Hash = Get-FileHash $Exe -Algorithm SHA256
Write-Host ""
Write-Host "FORGE COMPLETE" -ForegroundColor Green
Write-Host "EXE: $Exe"
Write-Host "SHA-256: $($Hash.Hash)"
Write-Host ""
Write-Host "Release packaging law: keep the proven external bin folder beside DunoonDaemon.exe." -ForegroundColor Yellow
