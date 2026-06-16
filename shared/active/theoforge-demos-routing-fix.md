# TheoForge demos routing/display fix — 2026-06-14

Iris debugged production display issues on relay7 for:
- https://theoforgesolutions.com/demos/demos.html
- https://theoforgesolutions.com/demos/ledger.html
- https://theoforgesolutions.com/demos/ledger/demo.html
- https://theoforgesolutions.com/demos/pantheon.html

## Root causes
1. `/etc/caddy/Caddyfile` served `/demos/*.html` via narrow rewrites but did not consistently strip `/demos/` for child assets (`assets/*`, `modal.css`, `modal.js`, monograms). With the production Host header, Caddy returned 404 for support assets; Cloudflare cached some 404s.
2. `demos.html` JS set `.card` elements to `opacity: 0` and depended on IntersectionObserver to reveal them. In production/browser QA, the observer did not restore opacity, leaving demo cards invisible.
3. Ledger/Pantheon product pages inserted real 2048px JPG monograms in the footer without constraining `.footer__brand-mark img`, causing a giant footer image spill.
4. The Pantheon card CTA on `demos.html` pointed at `https://theoforgesolutions.com/pantheon/` instead of `/demos/pantheon.html`; the footer Pantheon link also needed to be normalized to the demo URL.
5. Ledger product page in mobile browser "Desktop site"/portrait mode used the desktop `.hero { min-height: 100vh; padding: 180px 0 120px; }` behavior, reserving a full phone-height parchment slab after the hero content before `The Problem` section.

## Fixes applied on relay7
- Patched `/etc/caddy/Caddyfile`:
  - `handle_path /demos/*` -> `root * /var/www/theoforge/demos-site` + `file_server`
  - everything else reverse-proxies to v9 app at `127.0.0.1:4321`
  - added `Cache-Control: no-store, max-age=0` for `/demos/*` while demos are actively iterating
- Cache-busted deployed HTML asset refs with `?v=irisfix-20260614-0040`.
- Patched deployed `demos.html` so cards are visible by default.
- Patched deployed `demos.html` Pantheon links:
  - Pantheon card CTA now resolves to `/demos/pantheon.html`
  - footer Pantheon link now resolves to `https://theoforgesolutions.com/demos/pantheon.html`
- Patched deployed `ledger.html` responsive hero rules:
  - `max-width: 960px`: `.hero { min-height:auto; padding:120px 0 72px; overflow:visible; }`
  - portrait `max-width: 1024px`: `.hero { min-height:auto; padding:112px 0 72px; overflow:visible; }`
  - `.hero__dash { transform:none; }` in compact/portrait modes
- Patched deployed `ledger.html` and `pantheon.html` with image constraints:
  - `.footer__brand-mark img { width: 100%; height: 100%; object-fit: contain; display: block; }`
  - Pantheon nav image constraint added too.

## Source-of-truth patches mirrored locally
- `/home/konan/workspace/demos-site/index.html` — card visibility fallback + Pantheon link fix
- `/home/konan/workspace/ledger-product-page/index.html` — footer image constraints + mobile desktop-mode hero fix
- `/home/konan/workspace/pantheon-platform-page/index.html` — footer/nav image constraints

## Verified
- Origin and public cache-busted URLs returned 200 for pages/assets.
- Demos index visually renders cards/images/monograms.
- Demos page Pantheon product-page CTA resolves to `https://theoforgesolutions.com/demos/pantheon.html` and browser-click/JS-click navigation lands on the Pantheon product page.
- Ledger product page loads, no console errors; nav/footer monograms constrained.
- Ledger mobile desktop-mode/portrait verification at `980x1800`: hero height reduced from `1800px` to `636px`; `The Problem` begins at `636px` instead of below a huge blank slab. Visual screenshot confirmed the hero, dashboard, CTA, and problem section are visible without the empty gap.
- Pantheon product page loads, no console errors; nav/footer monograms constrained.
- Interactive Ledger demo loads and renders styled app shell, no console errors.

## Backups on relay7
- Caddy backups: `/etc/caddy/Caddyfile.bak-iris-demos-routing-*`, `/etc/caddy/Caddyfile.bak-iris-no-store-demos-*`
- HTML backups in `/var/www/theoforge/demos-site/`: `*.bak-iris-*`, including `demos.html.bak-iris-pantheon-link-*` and `ledger.html.bak-iris-mobile-desktop-*`

## Pantheon mobile memory animation fix — 2026-06-14
- Issue: On mobile, the Memory Stack ScrollTrigger pinned with `start: top 70%`, putting the orbit/core mostly below the fold. Users saw a dark blank area and only the top card/bottom of the graphic.
- Fix: Patched `/home/konan/workspace/pantheon-platform-page/index.html` and deployed `/var/www/theoforge/demos-site/pantheon.html`.
- CSS: added mobile memory rules at `max-width: 640px` to reduce padding, scale rings to viewport width, shrink core/nodes, and keep the query panel within the phone viewport.
- JS: changed memory ScrollTrigger to use `start: top 18%` and `end: +=950` on mobile while preserving desktop `start: top 70%` / `end: +=1600`.
- Verified live at phone-like viewport `577x770`: memory stage top `137`, bottom `637`; ring/core visible; after scroll node1 opacity `1`, node2 animating, core still visible. Backup: `pantheon.html.bak-iris-mobile-memory-*`.
