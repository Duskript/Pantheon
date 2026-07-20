---
name: pantheon-phone-gateway
version: "1.0.0"
description: "HARD CONSTRAINT + procedures for interacting with the Pixel 7 phone gateway. EVERY Pantheon god MUST use ADB + uiautomator2 for phone interaction. Vision/browser/screenshots are FORBIDDEN for phone tasks."
allowed-tools: Terminal, Bash
---

# Pantheon Phone Gateway

## 🔴 HARD CONSTRAINT — NO VISION ON THE PHONE

**This is non-negotiable for every Pantheon god.**

When the task involves the Pixel 7 phone (`192.168.1.18:5555`), you MUST use the ADB + uiautomator2 stack. You MUST NOT use:
- Browser vision / screenshots
- Computer-use / CDP
- Forwarding phone screenshots to vision models
- Any image-based interaction with the phone

The phone's screen is **structured XML data**, not an image. Interact with it that way.

## Phone Identity

| Property | Value |
|----------|-------|
| **Device** | Pixel 7 |
| **ADB address** | `192.168.1.18:5555` |
| **ADB binary** | `/home/konan/.local/bin/adb` |
| **Python venv** | `/home/konan/.phone-control-venv/` |
| **Python** | 3.12 (uv-managed) |
| **uiautomator2** | v3.7.0 |
| **adbutils** | v2.12.0 |
| **PIL/Pillow** | v12.2.0 (in venv) |

## Gateway Architecture

There are **two layers** of phone interaction:

### Layer 1: Notification Daemon (automated, always running)

A background daemon at `/home/konan/pantheon/scripts/phone-daemon.py` polls every 10 seconds via `adb shell dumpsys notification --noredact`. It:
- Reads all phone notifications
- Routes by app package name (Facebook Messenger → high, LinkedIn → medium, etc.)
- Writes notification log to `~/pantheon/phone-daemon/notifications.jsonl`
- Queues high-priority notifications for reply to `~/pantheon/phone-daemon/reply_queue.jsonl`
- No LLM calls — pure Python routing

This daemon handles **passive monitoring**. Gods should NOT duplicate this work.

### Layer 2: Active Phone Control (what gods do on request)

When a god needs to **actively interact** with the phone — read a screen, tap, type, swipe — use the ADB + uiautomator2 stack below.

## Connection Setup

```bash
# Verify ADB is available
/home/konan/.local/bin/adb devices

# Ensure phone is connected
/home/konan/.local/bin/adb connect 192.168.1.18:5555

# Verify connection
/home/konan/.local/bin/adb -s 192.168.1.18:5555 shell getprop ro.product.model
# Should return: Pixel 7
```

## 🚨 CRITICAL: PYTHONPATH Conflict

The Hermes agent exports `PYTHONPATH=/home/konan/.hermes/vendor/py311`, which contains a Python 3.11 PIL that conflicts with the venv's Python 3.12 PIL. **Every phone automation script MUST clear PYTHONPATH.**

### Option A: PYTHONPATH="" (preferred for one-liners)

```bash
PYTHONPATH="" /home/konan/.phone-control-venv/bin/python3 -c "
import uiautomator2 as u2
d = u2.connect('192.168.1.18:5555')
print(d.info)
"
```

### Option B: Unset in shell (preferred for scripts)

```bash
PYTHONPATH="" source /home/konan/.phone-control-venv/bin/activate
# or
unset PYTHONPATH
source /home/konan/.phone-control-venv/bin/activate
python3 -c "import uiautomator2 as u2; print('OK')"
```

### Option C: Inside Python (for standalone scripts)

```python
import sys
# Remove Hermes vendor path if present
sys.path = [p for p in sys.path if '/home/konan/.hermes/vendor/' not in p]
import uiautomator2 as u2
```

**Without this fix, you'll get:** `ImportError: cannot import name '_imaging' from 'PIL'`

## Python via phone-control-venv

All phone automation scripts use the dedicated venv at `/home/konan/.phone-control-venv/`.

```bash
PYTHONPATH="" /home/konan/.phone-control-venv/bin/python3 << 'EOF'
import uiautomator2 as u2
d = u2.connect("192.168.1.18:5555")
# Your code here
EOF
```

## uiautomator2 Quick Reference

### Connect to device

```python
import uiautomator2 as u2
d = u2.connect("192.168.1.18:5555")
```

### Read screen state (NEVER screenshot)

```python
# Get current activity
print(d.app_current())

# Dump UI hierarchy XML
xml = d.dump_hierarchy()  # Returns XML string

# Find elements by text
d(text="Settings")

# Find by resource ID
d(resourceId="com.example:id/button")

# Find by class name
d(className="android.widget.TextView")

# Check if element exists
if d(text="OK").exists:
    d(text="OK").click()

# Get all text on screen
all_text = [el.text for el in d(className="android.widget.TextView")]
```

### Interact

```python
# Tap
d(text="Settings").click()
d.click(x, y)  # Coordinate tap

# Type
d(text="Search").set_text("hello world")
d.clear_text()  # Clear input field

# Swipe
d.swipe(sx, sy, ex, ey)  # Swipe from (sx,sy) to (ex,ey)
d.swipe_ext("up")  # Predefined directions: up/down/left/right

# Press hardware buttons
d.press("home")
d.press("back")
d.press("recent")
```

### App management

```python
# Open app
d.app_start("com.facebook.orca")  # Facebook Messenger
d.app_start("com.twitter.android")

# Stop app
d.app_stop("com.facebook.orca")

# Get app info
info = d.app_info("com.facebook.orca")
```

### Screen info

```python
# Screen size
w, h = d.window_size()

# Orientation
print(d.orientation)  # 'natural', 'left', 'right', 'upsidedown'

# Current package/activity
print(d.app_current())
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

## Common ADB Shell Commands (fallback)

```bash
# Screen on/off
adb -s 192.168.1.18:5555 shell input keyevent 26  # Power button toggle

# Unlock (swipe up)
adb -s 192.168.1.18:5555 shell input swipe 540 1500 540 500

# Get notifications
adb -s 192.168.1.18:5555 shell dumpsys notification --noredact

# Take screenshot to file (LAST RESORT — for debugging only)
adb -s 192.168.1.18:5555 shell screencap -p /sdcard/screen.png
adb -s 192.168.1.18:5555 pull /sdcard/screen.png /tmp/phone_screen.png

# Get device info
adb -s 192.168.1.18:5555 shell getprop
```

## Verification Checklist (before acting on phone)

1. [ ] Is the phone connected? → `adb devices` shows `192.168.1.18:5555`
2. [ ] Am I using ADB or uiautomator2? (NEVER browser/vision)
3. [ ] Am I reading the UI hierarchy XML? (NEVER screenshot)
4. [ ] Is the screen on? → If not, press power button via ADB
5. [ ] Is the device unlocked? → If not, swipe to unlock

## Troubleshooting

**"ADB not found"** → Use full path: `/home/konan/.local/bin/adb`

**"No devices connected"** → Reconnect: `/home/konan/.local/bin/adb connect 192.168.1.18:5555`

**"ImportError: cannot import name '_imaging'"** → The venv's PIL conflicts with Hermes's PIL when PYTHONPATH is polluted. Run the python script directly from the venv's Python binary:
```
/home/konan/.phone-control-venv/bin/python3 -c "import uiautomator2 as u2"
```

**Screen off** → Press power button:
```python
d.press("power")
```

## Related

- Notification daemon: `/home/konan/pantheon/scripts/phone-daemon.py`
- Daemon logs: `/home/konan/pantheon/phone-daemon/daemon.log`
- Notification history: `/home/konan/pantheon/phone-daemon/notifications.jsonl`
- Reply queue: `/home/konan/pantheon/phone-daemon/reply_queue.jsonl`
