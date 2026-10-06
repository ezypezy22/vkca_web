#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
#  VK Contest Analyzer — macOS Build Script
#  Run from the folder containing vkca_web.spec:  ./build_mac.sh
#
#  Output: dist/VK Contest Analyzer.app
#          dist/VKContestAnalyzer-<version>-macos-<arch>.dmg
#
#  Builds for the architecture of the Python used (arm64 on Apple Silicon,
#  x86_64 on Intel). Set PYTHON=/path/to/python3 to pick one explicitly;
#  needs Python 3.10+ (Apple's bundled /usr/bin/python3 is 3.9).
#
#  The result is ad-hoc signed only — see the README section on macOS for
#  what users have to do to open an unsigned app.
# ═══════════════════════════════════════════════════════════════════════════
set -euo pipefail
cd "$(dirname "$0")"

APP_NAME="VK Contest Analyzer"
VENV=".buildvenv-mac"

echo
echo " VK Contest Analyzer - macOS Build"
echo " ================================="
echo

if [[ "$(uname)" != "Darwin" ]]; then
    echo "[ERROR] build_mac.sh must run on macOS." >&2; exit 1
fi
if [[ ! -f vkca_web.spec || ! -f web/server.py ]]; then
    echo "[ERROR] Run build_mac.sh from the vkca_web/ folder." >&2; exit 1
fi

# ── Python check ──────────────────────────────────────────────────────────
py_ok() { "$1" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; }
if [[ -z "${PYTHON:-}" ]]; then
    for cand in python3.13 python3.12 python3.11 python3.10 python3; do
        if command -v "$cand" >/dev/null && py_ok "$cand"; then PYTHON="$cand"; break; fi
    done
fi
if [[ -z "${PYTHON:-}" ]] && command -v uv >/dev/null; then
    uv python install 3.12
    PYTHON="$(uv python find 3.12)"
fi
if [[ -z "${PYTHON:-}" ]] || ! py_ok "$PYTHON"; then
    echo "[ERROR] Python 3.10+ not found. Install one (python.org, Homebrew or uv)" >&2
    echo "        or set PYTHON=/path/to/python3." >&2
    exit 1
fi
echo " Python: $("$PYTHON" --version) ($PYTHON)"

# ── Install dependencies ──────────────────────────────────────────────────
echo
echo "[1/4] Installing dependencies..."
[[ -d "$VENV" ]] || "$PYTHON" -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip --quiet
"$VENV/bin/pip" install --upgrade pyinstaller pyinstaller-hooks-contrib --quiet
# web/requirements-web.txt rather than requirements.txt: the packaged app is
# web mode only, and the spec excludes matplotlib/numpy/PIL anyway.
"$VENV/bin/pip" install -r web/requirements-web.txt orjson --quiet
ARCH="$("$VENV/bin/python" -c 'import platform; print(platform.machine())')"
echo "      Done. (arch: $ARCH)"

# ── Icon ──────────────────────────────────────────────────────────────────
echo "[2/4] Generating assets/icon.icns..."
ICONSET="build/icon.iconset"
rm -rf "$ICONSET"; mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
    sips -z $size $size assets/icon.png --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    sips -z $((size*2)) $((size*2)) assets/icon.png --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o assets/icon.icns
echo "      Done."

# ── Build ─────────────────────────────────────────────────────────────────
echo "[3/4] Building (this takes 2-5 minutes first time)..."
rm -rf "dist/VKContestAnalyzer" "dist/$APP_NAME.app" "build/VKContestAnalyzer"
"$VENV/bin/pyinstaller" vkca_web.spec --noconfirm

# ── DMG ───────────────────────────────────────────────────────────────────
echo "[4/4] Creating DMG..."
VERSION="$(tr -d '[:space:]' < VERSION)"
DMG="dist/VKContestAnalyzer-${VERSION}-macos-${ARCH}.dmg"
STAGE="build/dmg"
rm -rf "$STAGE" "$DMG"; mkdir -p "$STAGE"
cp -R "dist/$APP_NAME.app" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null

echo
echo " ================================="
echo "  BUILD COMPLETE"
echo "  dist/$APP_NAME.app"
echo "  $DMG"
echo " ================================="
