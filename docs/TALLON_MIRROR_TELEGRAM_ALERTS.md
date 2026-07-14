# Mirror Konan's Inbound Telegram Alerts on Tallon's Pantheon

## What Konan just deployed

Konan's `clawforge-messenger.py` now fires a Telegram alert to the home
channel (Konan's chat_id `1460056890`) every time a cross-instance
request lands. End-to-end verified: published a self-test, got a real
Telegram message with `🔴 Clawforge in: self-test:test-runner → marvin@konan`.

## What Data needs to do on Tallon's box

The same code already exists in `scripts/clawforge-messenger.py` on
the Pantheon repo. Tallon's install bundle already ships it. Data
just needs three small steps to enable the alerts on his side.

### Step 1 — pull the latest messenger from Pantheon

```bash
cd ~/pantheon
git pull
```

The latest `scripts/clawforge-messenger.py` has the alert code. If
Tallon's repo is already at the post-bundle commit (9823331 or
later), he's fine. If not, the pull brings the alert code in.

### Step 2 — give his messenger access to a Telegram bot token

The alert helper looks up `TELEGRAM_BOT_TOKEN` from (in order):
1. the messenger's environment
2. `~/.hermes/.env`
3. `~/.hermes/clawforge-tokens.env`

**If Tallon already has a PantheonMarvinBot-style bot for his own
side:** just set the token in his messenger's systemd drop-in (the
pattern Konan uses):

```bash
mkdir -p ~/.config/systemd/user/clawforge-messenger.service.d/
cat > ~/.config/systemd/user/clawforge-messenger.service.d/override.conf << 'EOF'
[Service]
Environment="TELEGRAM_BOT_TOKEN=<your-bot-token-here>"
Environment="TELEGRAM_HOME_CHANNEL=<your-chat-id-here>"
EOF
chmod 600 ~/.config/systemd/user/clawforge-messenger.service.d/override.conf
```

**If Tallon does NOT have a bot yet:** he can either

- (a) point at Konan's `PantheonMarvinBot` and chat_id `1460056890`
  (Cyber's DM) — Konan and Cyber will see Tallon's alerts. Pragmatic
  for now, since Cyber is the one who needs to know when things
  cross the bus. Token in the bundle or shared out-of-band.

- (b) set up his own bot via @BotFather and have alerts go to
  Tallon's own Telegram DM. Cleaner long-term, more setup.

For the federation to be useful, **both sides need to see the same
alerts** so neither side is blind to inbound traffic. Konan's bot
sending to Cyber's chat works as a shared visibility pane.

### Step 3 — change the hardcoded chat_id in the messenger

`DEFAULT_TELEGRAM_CHAT_ID` is currently hardcoded to
`"1460056890"` (Cyber). If Tallon wants alerts in his own chat,
he has two options:

- (a) leave it as 1460056890 and use Konan's bot (acceptable
  during initial federation bring-up — Cyber is the human
  in the loop and needs to know when messages cross the bus)
- (b) edit `DEFAULT_TELEFORGE_CHAT_ID` in the script and replace
  with Tallon's own chat_id, before restarting the messenger

### Step 4 — restart his messenger and verify

```bash
systemctl --user daemon-reload
systemctl --user restart clawforge-messenger.service
sleep 3
journalctl --user -u clawforge-messenger.service -n 10 --no-pager
```

**Expected log line:**
```
telegram alerts: ENABLED (chat_id=1460056890)
```

If you see that line, alerts are live. To do a self-test, Data
can have Tallon's hermes publish a request to Konan:

```bash
python3 ~/pantheon/scripts/clawforge-messenger.py ask hermes --instance konan --timeout 10 "self-test from talon"
```

Konan's side will catch it, dispatch, and send a Telegram alert
to chat_id 1460056890 with a 🟢 icon.

## What to do if the log shows "telegram alerts: DISABLED"

The token isn't reaching the messenger. Check in order:

1. `cat ~/.config/systemd/user/clawforge-messenger.service.d/override.conf`
   — make sure the file has `Environment="TELEGRAM_BOT_TOKEN=..."` with
   the real token (not a placeholder)
2. `systemctl --user show clawforge-messenger.service -p Environment`
   — should list `TELEGRAM_BOT_TOKEN=...`
3. `cat ~/.hermes/.env | grep TELEGRAM` — if the token is here instead,
   uncomment the line and put the real value (the file ships with the
   line commented out by default)
4. `cat ~/.hermes/clawforge-tokens.env | grep TELE` — Tallon's bundle
   doesn't include a Telegram token, only the NATS token, so this
   won't have it

If all four are empty, the token genuinely isn't set. Set it in
the drop-in (Step 2) and restart.

## What to do if the alert fires but no Telegram message arrives

The helper logs:
- `telegram alert sent (status=200, chat_id=..., len=...)` on success
- `telegram alert non-200: status=... body=...` on Telegram error
- `telegram alert failed: <ExceptionType>: <message>` on network error

The first one means Telegram accepted the message. If you see it
in the log but nothing in your Telegram, check:

- the `chat_id` is correct (you can verify with `getUpdates`:
  `curl https://api.telegram.org/bot<TOKEN>/getUpdates`)
- the bot has been started in that chat (send `/start` to the bot
  in the target chat before relying on inbound alerts)

## What this gives us

With alerts on both sides, neither Konan/Cyber nor Tallon/Data are
blind to cross-instance traffic. The next time either side sends a
`claw.request.*` to the other, the human in the loop on the
receiving side gets a Telegram notification within ~100ms, regardless
of whether they're at a terminal or not.

Without these alerts, the 13:58Z install fix report from Tallon
was dispatched and replied to in the background, but neither Cyber
nor Marvin was notified. This closes that gap.
