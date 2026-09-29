---
name: pantheon-phone-gateway
version: "2.0.0"
description: "Phone gateway for Pantheon: device identity, address resolution, and the tiered XML-first/vision-fallback rule. EVERY Pantheon god MUST use ADB for phone interaction. Load before any phone task."
allowed-tools: Terminal, Bash
---

# Pantheon Phone Gateway

## 🔴 HARD CONSTRAINT — XML FIRST

**Every Pantheon god. Non-negotiable.**

When a task involves a phone, you MUST read the screen through the
**accessibility hierarchy (structured XML)** and prefer it over anything
image-based. The phone's screen is **structured data**, not a picture. Interact
with it that way.

**Tiered rule** (revised 2026-09-23 — replaces the old outright NO-VISION ban):

1. **XML first** (`dump_hierarchy` / helper `/hierarchy.xml`) — labelled elements,
   text, resource-ids, bounds, structure, and screen-off state. Cheap, exact,
   deterministic. This is the default and it is usually sufficient.
2. **Vision as fallback** — only when XML genuinely cannot answer: icon-only
   controls with no text and no `content-desc`, custom Canvas/Compose/Flutter
   rendering, an empty or text-free hierarchy, or layout ambiguity.
3. **Wake first** — if a capture is black, the screen is off. Neither path helps.
   Press power via ADB (`input keyevent 26`) or the helper's `action=power_dialog`.

> **Why the old ban was removed:** it was written 2026-07-19 as a *capability*
> limit — `deepseek-v4-flash` had no vision. The fleet moved to
> `deepseek-v4.1-flash` (vision-capable) around mid-to-late September 2026, so the
> rationale was void for ~2 months before it was noticed. The surviving principle
> is **"XML is cheaper and more deterministic — prefer it,"** which is a
> preference, not a prohibition.

**Measured evidence for the tiering** (Pixel 9 lock screen, same moment, both paths):

| | XML | Vision |
|---|---|---|
| Text recovered | **all 6 strings**, exact | same, plus layout |
| Icon-only controls | **0 of 79 nodes** described them | located all immediately |
| Screen-off | still reports state via resource-ids | **blind** — black rectangle |
| Cost | ~0 tokens | image tokens per call |
| Determinism | exact resource-ids + bounds | model-dependent |

Do NOT use browser vision, computer-use/CDP, or `scrcpy` video for routine taps.

---

## Phone Identity — CHECK, DO NOT ASSUME

> ⚠️ This section was **wrong for ~2 months** and it is a HARD CONSTRAINT every god
> loads. It claimed "Pixel 7 @ `192.168.1.18:5555`" — that device does not exist
> and the address has been dead since ~2026-07. Verified live 2026-09-23.

| Property | Value |
|---|---|
| **Gateway phone** | **Pixel 9** (codename `tokay`) — Konan's main phone |
| **Address (canonical)** | **Tailscale `100.124.86.15:5555`** (hostname `pixel-9`) |
| **Secondary phone** | **Pixel 6** (`oriole_beta`) — USB serial `21251FDF60016K` |
| **ADB binary** | `/home/konan/.local/bin/adb` — **NOT in PATH** |
| **Python venv** | `/home/konan/.phone-control-venv/` (Python 3.12, uiautomator2 3.7.0) |
| **Android version** | 17 / SDK 37 on **both** phones |

**There is no Pixel 7.** A Pixel 7 would report codename `panther`; if you see
`oriole` that is a Pixel 6. Confirm with `getprop ro.product.device`, never by
remembering.

### 🚨 NEVER hardcode the LAN address — it drifts

Measured drift on one phone in one month:

```
192.168.1.18:5555  -> dead   ("No route to host")
192.168.1.19:5555  -> dead   ("No route to host")
192.168.1.11:5555  -> live   (DHCP)
```

A fixed LAN IP **cannot work** as a constant here. Resolve in this order:

1. `PANTHEON_PHONE_ADB_ADDR` env var, if set
2. Tailscale `pixel-9` (stable across DHCP, subnet moves, and reboots)
3. A transport `adb devices -l` already knows (`model:Pixel_9`)
4. Last-known LAN IP — last resort, may be stale

```bash
# Resolve the gateway without hardcoding:
adb connect "$(tailscale status | awk '$2=="pixel-9"{print $1":5555"}')"
```

---

## Two Hierarchy Backends

### Backend A (default): uiautomator2 — full UiAutomation control

Best for **acting**: taps, typing, swipes, app control. Holds the UiAutomation
connection **exclusively** — only one uiautomator2 client can drive a device at a time.

### Backend B (light): ARTEMIS accessibility helper — read-only screen access

`com.artemis.helper` v1.2.0 (36.5 KB, from `google/artemis`) is an
`AccessibilityService` that serves the hierarchy over **loopback-only HTTP**:

```
GET /ping                                     liveness, no auth
GET /hierarchy.xml  |  /dump_xml              XML hierarchy   ← the useful one
GET /dump           |  /hierarchy             same tree wrapped in JSON
GET /snapshot                                 hierarchy + screenshot (heavy)
POST /action        |  /rpc                   gesture injection
```

Auth: header **`X-Artemis-Token`** (or `?token=`, or JSON `token`). Every endpoint
except `/ping` requires it. Every wrong token → `401 unauthorized`.

**Backend selection:**

```
Tier 1  ARTEMIS helper  — /hierarchy.xml      (light: no app_process server needed)
Tier 2  uiautomator2    — dump_hierarchy()    (fallback; required for actions)
```

**🚨 The two backends CANNOT serve at the same time.**

This is the single most mis-read thing about the helper. Android unbinds every
accessibility service while a `UiAutomation` connection is alive, so while a
uiautomator2 server runs the helper is **silent**:

| State | `/ping` | `/hierarchy.xml` |
|---|---|---|
| No holder | OK | full tree |
| uiautomator2 server alive | **no response** | **0 bytes** |
| Holder stopped | OK — auto-revives, no reinstall, token still valid | restored |

It is **alternation, not coexistence.** The helper never *holds* UiAutomation (so
it is never the blocker), but it is *suppressed by* a holder. It auto-revives the
instant the holder stops.

**Full setup / re-attach:** `~/phone-apks/artemis/artemis-helper-attach.sh [serial]`
— idempotent, self-resolving, prints the cause on failure.
Port map: `~/phone-apks/artemis/attached-ports.txt` (serial → host port).
Two devices **cannot share a host port**: Pixel 9 → `18888`, Pixel 6 → `18889`.

**When NOT to use the helper:** inside a uiautomator2 task (you'll get 0 bytes and
waste a step). Use it for passive/monitor reads only.

---

## 🔴 Android 17 (SDK 37) Pitfalls — both phones

**`d.info` is BROKEN.** Raises
`RPCUnknownError -32001: java.lang.IllegalStateException: ApplicationSharedMemory
not initialized` at `UiDevice.getDisplaySizeDp`. The bundled `com.wetest.uia2` server
is too old for SDK 37 semantics.

```python
# BROKEN on Android 17
d.info                       # ✗ RPCUnknownError -32001
d.deviceInfo                 # ✗ same

# Use these instead — all still work
d.window_size()              # ✓ (w, h)
d.app_current()              # ✓ package/activity
d.dump_hierarchy()           # ✓ uses a different code path
```

**Finding the UiAutomation holder:** `ps -A` reports it as a bare `app_process`,
so the marker only appears in the full command line.

```bash
adb -s "$DEV" shell ps -A -o args | grep -E 'uia2\.Main|io\.appium\.uiautomator2'
```

Do **not** treat a bare `com.github.uiautomator` process as proof of a holder — that
package can run as an ordinary app process while holding nothing. Corroborate with
port `9008` listening (`:2330` in `/proc/net/tcp`).

---

## 🚨 CRITICAL: PYTHONPATH Conflict

Hermes exports `PYTHONPATH=/home/konan/.hermes/vendor/py311`, whose Python 3.11 PIL
conflicts with the venv's 3.12 PIL. **Every phone automation script MUST clear it.**

```bash
# Preferred for one-liners
PYTHONPATH="" /home/konan/.phone-control-venv/bin/python3 -c "..."
```

Without this you get: `ImportError: cannot import name '_imaging' from 'PIL'`.

The daemon strips it in-process, right after its imports in `phone-daemon.py`.

---

## Gateway Architecture

### Layer 1: Notification Daemon (automated, always running)

`/home/konan/pantheon/scripts/phone-daemon.py` polls every 10s via
`adb shell dumpsys notification --noredact`. Routes by app package
(Messenger → high, LinkedIn → medium, …). Writes
`~/pantheon/phone-daemon/notifications.jsonl`, queues reply-worthy ones to
`reply_queue.jsonl`. **No LLM calls — pure Python routing.** Gods should NOT
duplicate this.

Note: it reads *notifications* (a dumpsys call, not UiAutomation), so the
accessibility helper does not change how it works.

### Layer 2: Active Phone Control (what gods do on request)

Use `phone_screen.py` (preferred) or raw ADB + uiautomator2.

```bash
PYTHONPATH="" /home/konan/.phone-control-venv/bin/python3 \
  /home/konan/pantheon/scripts/phone_screen.py --probe
```

---

## uiautomator2 Quick Reference

```python
import uiautomator2 as u2
d = u2.connect(DEV)                      # DEV from the resolution order above

# Read
d.app_current()                          # ✓ current package/activity
d.dump_hierarchy()                       # ✓ XML string
d.window_size()                          # ✓ (w, h)
# d.info / d.deviceInfo                  # ✗ BROKEN on Android 17

# Find
d(text="Settings")
d(resourceId="com.example:id/button")
d(className="android.widget.TextView")
d(text="OK").exists
[el.text for el in d(className="android.widget.TextView")]

# Act
d(text="Settings").click()
d.click(x, y)
d(text="Search").set_text("hello world")
d.swipe(sx, sy, ex, ey);  d.swipe_ext("up")
d.press("home"); d.press("back"); d.press("recent")

# Apps
d.app_start("com.facebook.orca"); d.app_stop("com.facebook.orca")
```

## Known App Package IDs

| App | Package |
|-----|---------|
| Facebook Messenger | `com.facebook.orca` |
| Facebook | `com.facebook.katana` |
| Twitter/X | `com.twitter.android` |
| LinkedIn | `com.linkedin.android` |
| Bluesky | `xyz.blueskyweb.app` |
| Reddit | `com.reddit.frontpage` |
| eBay | `com.ebay.mobile` |
| Instagram | `com.instagram.android` |
| Gmail | `com.google.android.gm` |
| WhatsApp | `com.whatsapp` |
| Discord (Aliucord) | `com.aliucord` |

## Verification Checklist (before acting on phone)

1. [ ] Device resolves? → `adb -s "$DEV" get-state` (not a hardcoded IP)
2. [ ] Right phone? → `getprop ro.product.device` (`tokay` = Pixel 9)
3. [ ] Using ADB / XML first? (never browser vision for routine taps)
4. [ ] Reading the hierarchy, not a screenshot?
5. [ ] Screen on? If not, wake it first.
6. [ ] If using the helper: no uiautomator2 holder running, else expect 0 bytes

## Troubleshooting

**"adb: command not found"** → not in PATH. Use `/home/konan/.local/bin/adb`
(or `PANTHEON_ADB_BIN`).

**"No route to host"** → the LAN IP drifted. Use the Tailscale address.

**"ImportError: cannot import name '_imaging'"** → PYTHONPATH pollution. Clear it.

**Helper returns 0 bytes** → a UiAutomation holder is suppressing it (check
`ps -A -o args`), or the accessibility service is not actually enabled — a
`settings put` right after `pm install` is **silently pruned**. Re-read the setting
and retry up to 5×; see `artemis-helper-attach.sh`.

**Accessibility setting reads `null` after a "successful" write** → same prune bug.
Never trust the write's exit code; read the value back.

## Related

- Daemon: `/home/konan/pantheon/scripts/phone-daemon.py`
- Screen backend: `/home/konan/pantheon/scripts/phone_screen.py`
- Helper APK + attach script: `~/phone-apks/artemis/`
- Daemon state: `~/pantheon/phone-daemon/`
- Evaluation report: `~/athenaeum/Codex-God-thoth/research/artemis-android-automation-eval/report.md`
