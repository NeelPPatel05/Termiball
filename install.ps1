# ──────────────────────────────────────────────────────────────────────────────
#  Termiball — install script (Windows PowerShell)
#  Usage: irm https://raw.githubusercontent.com/you/termiball/main/install.ps1 | iex
# ──────────────────────────────────────────────────────────────────────────────
$ErrorActionPreference = "Stop"

$REPO_URL    = "https://raw.githubusercontent.com/you/termiball/main/termiball.py"
$INSTALL_DIR = "$env:LOCALAPPDATA\Programs\termiball"
$SCRIPT_PATH = "$INSTALL_DIR\termiball.py"
$WRAPPER     = "$INSTALL_DIR\termiball.cmd"

# ── banner ────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ████████╗███████╗██████╗ ███╗   ███╗██╗██████╗  █████╗ ██╗     ██╗" -ForegroundColor Yellow
Write-Host "  ╚══██╔══╝██╔════╝██╔══██╗████╗ ████║██║██╔══██╗██╔══██╗██║     ██║" -ForegroundColor Yellow
Write-Host "     ██║   █████╗  ██████╔╝██╔████╔██║██║██████╔╝███████║██║     ██║" -ForegroundColor Yellow
Write-Host "     ██║   ██╔══╝  ██╔══██╗██║╚██╔╝██║██║██╔══██╗██╔══██║██║     ██║" -ForegroundColor Yellow
Write-Host "     ██║   ███████╗██║  ██║██║ ╚═╝ ██║██║██████╔╝██║  ██║███████╗███████╗" -ForegroundColor Yellow
Write-Host "     ╚═╝   ╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚═╝╚═════╝ ╚═╝  ╚═╝╚══════╝╚══════╝" -ForegroundColor Yellow
Write-Host ""
Write-Host "  NBA Live Tracker — Windows Installer" -ForegroundColor Cyan
Write-Host ""

# ── check Python ──────────────────────────────────────────────────────────────
$python = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3") {
            $python = $cmd
            Write-Host "[✓] Found $ver" -ForegroundColor Green
            break
        }
    } catch {}
}

if (-not $python) {
    Write-Host "[✗] Python 3 not found." -ForegroundColor Red
    Write-Host "    Download from: https://python.org/downloads"
    Write-Host "    Make sure to check 'Add Python to PATH' during install."
    exit 1
}

# ── check Windows Terminal support ────────────────────────────────────────────
# curses on Windows requires windows-curses
Write-Host "[*] Checking for windows-curses..." -ForegroundColor Cyan
try {
    $check = & $python -c "import curses" 2>&1
    Write-Host "[✓] curses available" -ForegroundColor Green
} catch {
    Write-Host "[!] Installing windows-curses..." -ForegroundColor Yellow
    & $python -m pip install windows-curses --quiet
    Write-Host "[✓] windows-curses installed" -ForegroundColor Green
}

# ── create install directory ──────────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path $INSTALL_DIR | Out-Null
Write-Host "[*] Installing to $INSTALL_DIR" -ForegroundColor Cyan

# ── download script ───────────────────────────────────────────────────────────
Write-Host "[*] Downloading termiball.py..." -ForegroundColor Cyan
Invoke-WebRequest -Uri $REPO_URL -OutFile $SCRIPT_PATH -UseBasicParsing
Write-Host "[✓] Downloaded termiball.py" -ForegroundColor Green

# ── create .cmd wrapper so you can just type 'termiball' ─────────────────────
$wrapperContent = "@echo off`r`n$python `"$SCRIPT_PATH`" %*"
Set-Content -Path $WRAPPER -Value $wrapperContent -Encoding ASCII
Write-Host "[✓] Created launcher: termiball.cmd" -ForegroundColor Green

# ── add to user PATH ──────────────────────────────────────────────────────────
$currentPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($currentPath -notlike "*$INSTALL_DIR*") {
    [Environment]::SetEnvironmentVariable("PATH", "$currentPath;$INSTALL_DIR", "User")
    Write-Host "[✓] Added $INSTALL_DIR to PATH" -ForegroundColor Green
    Write-Host ""
    Write-Host "[!] Restart your terminal for PATH changes to take effect." -ForegroundColor Yellow
} else {
    Write-Host "[✓] Already on PATH" -ForegroundColor Green
}

# ── done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Installation complete!" -ForegroundColor Green
Write-Host ""
Write-Host "  Run it with:  termiball" -ForegroundColor White
Write-Host "  (Restart your terminal first if this is a fresh install)"
Write-Host ""
