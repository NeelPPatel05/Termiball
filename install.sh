#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
#  Termiball — install script (macOS / Linux)
#  Usage: curl -fsSL https://raw.githubusercontent.com/you/termiball/main/install.sh | bash
# ──────────────────────────────────────────────────────────────────────────────
set -e

REPO_URL="https://raw.githubusercontent.com/you/termiball/main/termiball.py"
INSTALL_DIR="$HOME/.local/bin"
SCRIPT_NAME="termiball"
TARGET="$INSTALL_DIR/$SCRIPT_NAME"

# ── colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}${BOLD}[termiball]${RESET} $*"; }
success() { echo -e "${GREEN}${BOLD}[✓]${RESET} $*"; }
warn()    { echo -e "${YELLOW}${BOLD}[!]${RESET} $*"; }
error()   { echo -e "${RED}${BOLD}[✗]${RESET} $*" >&2; exit 1; }

# ── banner ────────────────────────────────────────────────────────────────────
echo -e "${YELLOW}${BOLD}"
cat << 'EOF'
  ████████╗███████╗██████╗ ███╗   ███╗██╗██████╗  █████╗ ██╗     ██╗
  ╚══██╔══╝██╔════╝██╔══██╗████╗ ████║██║██╔══██╗██╔══██╗██║     ██║
     ██║   █████╗  ██████╔╝██╔████╔██║██║██████╔╝███████║██║     ██║
     ██║   ██╔══╝  ██╔══██╗██║╚██╔╝██║██║██╔══██╗██╔══██║██║     ██║
     ██║   ███████╗██║  ██║██║ ╚═╝ ██║██║██████╔╝██║  ██║███████╗███████╗
     ╚═╝   ╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚═╝╚═════╝ ╚═╝  ╚═╝╚══════╝╚══════╝
EOF
echo -e "${RESET}"
info "NBA Live Tracker — installer"
echo ""

# ── check python ──────────────────────────────────────────────────────────────
if command -v python3 &>/dev/null; then
    PY=$(command -v python3)
    PY_VER=$("$PY" --version 2>&1)
    success "Found $PY_VER"
else
    error "Python 3 is required but not found. Install from https://python.org"
fi

# ── check curl ────────────────────────────────────────────────────────────────
if ! command -v curl &>/dev/null; then
    error "curl is required but not found. Install curl and retry."
fi

# ── create install dir ────────────────────────────────────────────────────────
mkdir -p "$INSTALL_DIR"
info "Installing to $TARGET"

# ── download ──────────────────────────────────────────────────────────────────
info "Downloading termiball.py..."
curl -fsSL "$REPO_URL" -o "$TARGET"
chmod +x "$TARGET"
success "Downloaded termiball.py"

# ── fix shebang to use local python3 ─────────────────────────────────────────
sed -i.bak "1s|.*|#!${PY}|" "$TARGET" && rm -f "${TARGET}.bak"

# ── PATH check ────────────────────────────────────────────────────────────────
if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then
    warn "$INSTALL_DIR is not in your PATH."
    echo ""
    echo "  Add this line to your shell config (~/.bashrc, ~/.zshrc, etc.):"
    echo ""
    echo -e "    ${BOLD}export PATH=\"\$HOME/.local/bin:\$PATH\"${RESET}"
    echo ""
    echo "  Then restart your terminal or run:"
    echo -e "    ${BOLD}source ~/.bashrc${RESET}  (or ~/.zshrc)"
    echo ""
else
    success "$INSTALL_DIR is already on your PATH"
fi

# ── done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}Installation complete!${RESET}"
echo ""
echo -e "  Run it with:  ${BOLD}termiball${RESET}"
echo -e "  Update:       ${BOLD}curl -fsSL <url> | bash${RESET} (same command)"
echo ""
