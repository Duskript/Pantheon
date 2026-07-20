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
for f in favicon.svg manifest.json manifest.webmanifest sw.js icons.svg; do
  [ -f "dist/$f" ] && cp "dist/$f" "$STATIC_DIR/"
done
for f in dist/workbox-*.js; do
  [ -f "$f" ] && cp "$f" "$STATIC_DIR/"
done

echo "📄 Updating entry points..."
sed \
  -e 's|"/assets/|"/static/assets/|g' \
  -e 's|"/favicon.svg"|"/static/favicon.svg"|g' \
  -e 's|"/manifest.webmanifest"|"/static/manifest.webmanifest"|g' \
  dist/index.html > "$STATIC_DIR/index.html"
cp "$STATIC_DIR/index.html" "$WEBUI_DIR/hermes-ui.html"

echo "🔄 Restarting server..."
# pantheon-webui is a user-level systemd unit; use --user (not sudo)
systemctl --user restart pantheon-webui

echo "⏳ Waiting for WebUI readiness..."
http_code="000"
for _ in {1..30}; do
  if systemctl --user is-active --quiet pantheon-webui; then
    http_code="$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 http://localhost:8787/olympus/ || true)"
    case "$http_code" in
      200|302|401|403)
        break
        ;;
    esac
  fi
  sleep 1
done

case "$http_code" in
  200|302|401|403)
    ;;
  *)
    echo ""
    echo "❌ Deploy copied assets, but WebUI did not become ready"
    echo "   HTTP: $http_code"
    systemctl --user status pantheon-webui --no-pager || true
    exit 1
    ;;
esac

echo ""
echo "✅ Deploy complete"
echo "   JS: $(grep -o 'index-[^\"]*\.js' "$WEBUI_DIR/hermes-ui.html")"
echo "   HTTP: $http_code"
