#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
UI_ROOT="$ROOT/mcode-ui"
FRONTEND="$UI_ROOT/frontend"
APP_DIR="$UI_ROOT/dist/Mcode.app"
CONTENTS="$APP_DIR/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"

cd "$FRONTEND"
if [ ! -d node_modules ]; then
  npm install
fi
npm run build

rm -rf "$APP_DIR"
mkdir -p "$MACOS" "$RESOURCES"

cp "$UI_ROOT/macos/Info.plist" "$CONTENTS/Info.plist"

# App icon from mcode logo
ICONSET="$RESOURCES/app.iconset"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"
LOGO="$FRONTEND/public/mcode-logo.jpg"
if [ -f "$LOGO" ]; then
  for size in 16 32 64 128 256 512; do
    sips -z $size $size "$LOGO" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null 2>&1
    sips -z $((size*2)) $((size*2)) "$LOGO" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null 2>&1
  done
  iconutil -c icns "$ICONSET" -o "$RESOURCES/app.icns" 2>/dev/null || true
  rm -rf "$ICONSET"
fi
rsync -a --delete "$FRONTEND/dist/" "$RESOURCES/frontend-dist/"
rsync -a --delete --exclude='__pycache__/' --exclude='*.pyc' "$UI_ROOT/backend/" "$RESOURCES/backend/"
rsync -a --delete --exclude='__pycache__/' --exclude='*.pyc' "$ROOT/mini_agent_lab/" "$RESOURCES/mini_agent_lab/"
rsync -a --delete --exclude='__pycache__/' --exclude='*.pyc' "$ROOT/scripts/" "$RESOURCES/scripts/"

SWIFT_MODULE_CACHE="$(mktemp -d "${TMPDIR:-/tmp}/mcode-swift-module-cache.XXXXXX")"
export CLANG_MODULE_CACHE_PATH="$SWIFT_MODULE_CACHE"
swiftc \
  "$UI_ROOT/macos/McodeApp.swift" \
  -o "$MACOS/Mcode" \
  -framework Cocoa \
  -framework WebKit \
  -framework Speech \
  -framework AVFoundation \
  -framework Security

chmod +x "$MACOS/Mcode"
codesign --force --deep -s - "$APP_DIR" >/dev/null
codesign --verify --deep --strict "$APP_DIR"
echo "$APP_DIR"
