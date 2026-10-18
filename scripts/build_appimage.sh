#!/usr/bin/env bash
# Build "NMS Shipwright-x86_64.AppImage" on Linux.
#
#   scripts/build_appimage.sh
#
# Builds the PyInstaller app folder (via build_app.py), wraps it in an AppDir, and runs
# appimagetool. The app has no native window on Linux -- it serves a local page and opens
# your browser. No Man's Sky itself is found at runtime (Steam/Proton), nothing is bundled.
set -euo pipefail
cd "$(dirname "$0")/.."

NAME="NMS Shipwright"
APPDIR="dist/${NAME}.AppDir"
OUT="dist/NMS_Shipwright-x86_64.AppImage"
VERSION="$(grep -oP '^VERSION = "\K[^"]+' webapp/version.py)"

echo ">> building the app folder"
python scripts/build_app.py --no-installer

echo ">> assembling the AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
cp -r "dist/${NAME}/." "$APPDIR/usr/bin/"
cp build/app.png "$APPDIR/nms-shipwright.png"

# a no-space launcher name keeps the .desktop file simple
ln -sf "${NAME}" "$APPDIR/usr/bin/nms-shipwright"

cat > "$APPDIR/AppRun" <<EOF
#!/bin/bash
HERE="\$(dirname "\$(readlink -f "\$0")")"
exec "\$HERE/usr/bin/${NAME}" "\$@"
EOF
chmod +x "$APPDIR/AppRun"

cat > "$APPDIR/nms-shipwright.desktop" <<EOF
[Desktop Entry]
Name=NMS Shipwright
Exec=nms-shipwright
Icon=nms-shipwright
Type=Application
Categories=Utility;Game;
Terminal=false
Comment=No Man's Sky ship designer and save editor
EOF

echo ">> fetching appimagetool"
TOOL="$(mktemp)"
curl -sSL -o "$TOOL" \
  https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x "$TOOL"

echo ">> packaging $OUT"
# --appimage-extract-and-run avoids needing FUSE on CI runners
ARCH=x86_64 VERSION="$VERSION" "$TOOL" --appimage-extract-and-run "$APPDIR" "$OUT"
echo "built: $OUT"
