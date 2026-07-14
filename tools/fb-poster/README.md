# fb-poster

Post to Facebook (personal timeline, Page, or group) from your laptop,
exiting through **CachyOS as a residential SOCKS5 proxy**, using
`invisible-playwright`'s patched Firefox that passes Meta's bot
detection.

Built for low-cadence personal use, not automation at scale.

## How it works

```
laptop (100.115.50.41)
  └─ invisible-playwright / patched Firefox
       └─ SOCKS5 tunnel (SSH -D 1080)
            └─ CachyOS (100.114.60.103)  ←  real residential IP
                 └─ Facebook
```

- Your real residential IP, your real timezone, a deterministic
  Firefox fingerprint that doesn't look like a bot.
- Cookies persist between runs — you log in once.
- Human-like mouse paths and per-character typing jitter.

## One-time setup

```bash
cd ~/pantheon/tools/fb-poster
./post.sh --login          # log in to Facebook, saves cookies
```

The Firefox window will open, you complete whatever 2FA / challenge
Meta throws at you, and once you see your News Feed, the script saves
your session and exits.

## Day-to-day usage

```bash
# Post to your personal timeline
./post.sh "Just shipped a new Theoforge demo. DM me."

# Post to a Facebook Page you admin
./post.sh --page theoforge "New automation flow live today"

# Post to a Pocatello group
./post.sh --group pocatello-business "Hey locals — looking for beta testers"

# Verify the proxy is actually exiting where you think it is
./post.sh --check-ip

# Walk the flow without clicking Post (sanity check)
./post.sh --dry-run "test text"
```

## File layout

```
fb-poster/
├── post.sh                ← CLI wrapper (start here)
├── post.py                ← core script
├── config.yaml            ← proxy + timezone + seed
├── bin/tunnel.sh          ← SSH SOCKS5 launcher (idempotent)
├── profiles/default/      ← cookies / fingerprint storage
└── logs/                  ← tunnel log + future run logs
```

## What breaks and when

- **Facebook UI changes** — selectors in `post.py` are a rotating
  list. If a post silently fails, the post body gets typed but
  "Post" can't be clicked. Update `COMPOSER_SELECTORS` /
  `POST_BUTTON_SELECTORS` and try again.
- **2FA / "Suspicious login" wall** — re-run `--login`, complete
  the challenge manually, cookies update.
- **CachyOS reboots** — tunnel dies. Re-running `post.sh`
  auto-restarts it (liveness check via curl).
- **Account gets challenged** — slow down, drop cadence. This is
  not a tool that should be used to spam.

## What this is NOT

- Not for bulk posting, scraping, or multi-account management
- Not a tool to bypass bans
- Not a public proxy — never expose the SOCKS5 port to the LAN

If you need any of those, build a separate tool with a paid
residential proxy and isolated identity per account.

## Dependencies

- Python 3.11+ (you're on 3.14, fine)
- `invisible-playwright` (auto-downloads patched Firefox on first
  use)
- `pyyaml`
- SSH access to CachyOS with a configured key

## Crontab / god workflow

This tool is safe to wire into a cron job or a god handoff — just
remember cookies expire every ~60 days, so leave a 6-month cadence
on `--login` reminder if you go that route.
