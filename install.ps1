# Termiball - Windows installer
$ErrorActionPreference = "Stop"
$REPO_URL    = "https://raw.githubusercontent.com/NeelPPatel05/Termiball/main/termiball.py"
$INSTALL_DIR = "$env:LOCALAPPDATA\Programs\termiball"
$SCRIPT_PATH = "$INSTALL_DIR\termiball.py"
$WRAPPER     = "$INSTALL_DIR\termiball.cmd"

Write-Host "  TERMIBALL - NBA Live Tracker - Windows Installer" -ForegroundColor Yellow
Write-Host ""

$python = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3") { $python = $cmd; Write-Host "[OK] Found $ver" -ForegroundColor Green; break }
    } catch {}
}
if (-not $python) { Write-Host "[X] Python 3 not found. Download from https://python.org" -ForegroundColor Red; exit 1 }

Write-Host "[*] Checking windows-curses..." -ForegroundColor Cyan
& $python -m pip install windows-curses --quiet
Write-Host "[OK] windows-curses ready" -ForegroundColor Green

New-Item -ItemType Directory -Force -Path $INSTALL_DIR | Out-Null
Write-Host "[*] Downloading termiball.py..." -ForegroundColor Cyan
Invoke-WebRequest -Uri $REPO_URL -OutFile $SCRIPT_PATH -UseBasicParsing
Write-Host "[OK] Downloaded" -ForegroundColor Green

Set-Content -Path $WRAPPER -Value "@echo off`r`n$python `"$SCRIPT_PATH`" %*" -Encoding ASCII
Write-Host "[OK] Created launcher" -ForegroundColor Green

$currentPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($currentPath -notlike "*$INSTALL_DIR*") {
    [Environment]::SetEnvironmentVariable("PATH", "$currentPath;$INSTALL_DIR", "User")
    Write-Host "[OK] Added to PATH - restart terminal" -ForegroundColor Yellow
} else {
    Write-Host "[OK] Already on PATH" -ForegroundColor Green
}

Write-Host ""
Write-Host "Done! Restart your terminal then run: termiball" -ForegroundColor Green
