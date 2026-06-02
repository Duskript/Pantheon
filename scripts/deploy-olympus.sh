#!/usr/bin/env bash
# deploy-olympus.sh — Build & deploy Olympus UI to Pantheon WebUI
set -euo pipefail

OLYMPUS_DIR="$HOME/Olympus-UI"
WEBUI_DIR="$HOME/pantheon/webui"
STATIC_DIR="$WEBUI_DIR/static"

echo "🔨 Building Olympus UI..."
cd "$OLYMPUS_DIR"
npx vite build 2>&1 | tail -5

echo ""
echo "🧹 Cleaning old assets..."
rm -rf "$STATIC_DIR/assets/"*

echo "📦 Copying new build..."
cp -r dist/assets/* "$STATIC_DIR/assets/"
for f in favicon.svg manifest.json sw.js icons.svg; do
  [ -f "dist/$f" ] && cp "dist/$f" "$STATIC_DIR/"
done

echo "📄 Updating entry points..."
cp dist/index.html "$STATIC_DIR/index.html"
cp dist/index.html "$WEBUI_DIR/hermes-ui.html"

echo "🔄 Restarting server..."
# pantheon-webui is a user-level systemd unit; use --user (not sudo)
systemctl --user restart pantheon-webui
sleep 2

echo ""
echo "✅ Deploy complete"
echo "   JS: $(grep -o 'index-[^\"]*\.js' "$WEBUI_DIR/hermes-ui.html")"
curl -s -o /dev/null -w "   HTTP: %{http_code}\n" http://localhost:8787/
