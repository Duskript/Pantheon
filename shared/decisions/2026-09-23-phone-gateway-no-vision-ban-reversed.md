# 2026-09-23 — Phone Gateway: NO-VISION ban reversed; device identity corrected

**Decision:** Replace the outright NO-VISION prohibition on phone interaction in the
`pantheon-phone-gateway` skill with a **tiered rule** — XML first, vision as
escalation fallback, wake-first when the screen is off. Correct the skill's device
identity from "Pixel 7 @ `192.168.1.18:5555`" (dead) to **Pixel 9 (`tokay`) at
Tailscale `100.124.86.15:5555`** as the gateway, with the **Pixel 6 (`oriole_beta`)**
on USB as secondary. Ban hardcoded LAN addresses in the skill entirely.

**Reverses:** the NO-VISION HARD CONSTRAINT written 2026-07-19 in
`pantheon/god-packages/shared-skills/pantheon-phone-gateway/SKILL.md`
(and the device identity it carried).

**Reason for reversal:** the constraint encoded a *capability* limit, not an
architectural principle — it was written when `deepseek-v4-flash` had no vision.
The fleet moved to `deepseek-v4.1-flash` (vision-capable) around mid-to-late
September 2026, roughly two months before the stale rationale was noticed. The
surviving principle is "XML is cheaper and more deterministic — prefer it," which
is a preference, not a prohibition.

**Rationale:** The device identity in this skill had been wrong for ~2 months *and
it is a HARD CONSTRAINT every god loads*, so a wrong answer propagated everywhere.
Worse, the class of error is not "wrong constant" but "constant cannot work": the
Pixel 9's LAN address drifted `.18` → `.19` → `.11` within a single month, each one
"correct" when written. Any fixed LAN IP in this skill is a time bomb. Tailscale
(`pixel-9`) was verified working with `adb connect` and is stable across DHCP,
subnet moves, and reboots.

Measured evidence for the tiering (Pixel 9 lock screen, same moment, both paths):
XML recovered all 6 text strings exactly at ~0 tokens; vision additionally located
the icon-only controls (fingerprint, flashlight, home) that carried **no text and no
`content-desc` in 0 of 79 XML nodes**; and on a screen-off capture XML still
reported state via resource-ids while vision saw a pure black rectangle. Neither
path is a superset, so the correct rule is tiered rather than either-or.

**Alternatives considered:**
- **Keep the NO-VISION ban.** Rejected — rationale void since ~Sep 2026; the
  prohibition forbids the one thing XML cannot do (icon-only controls).
- **Replace XML with vision.** Rejected — vision is blind when the screen is dark,
  costs image tokens per call, and is non-deterministic; XML wins on text, cost,
  and determinism.
- **Patch the IP constant to `.11`.** Rejected — the address had already changed
  twice; this repeats the same failure with better data.
- **Adopt ARTEMIS wholesale to replace uiautomator2.** Rejected — ARTEMIS *depends
  on* `uiautomator2>=3.5.0`; it is a LangGraph VLM layer *above* it, and its Flash
  profile costs ≥1 model call per step against a daemon that currently costs zero.

**Evidence:**
- `~/athenaeum/Codex-God-thoth/research/artemis-android-automation-eval/report.md`
  §7 (constraint revision), §8 (helper installed, coexistence corrected), §9 (both
  phones, attach-script bugs).
- Live ADB probes 2026-09-23: `.18` → no route to host; `.19` → no route to host;
  `.11` → Pixel 9 `tokay`; Tailscale `100.124.86.15:5555` → Pixel 9 `tokay`.
- `getprop ro.product.device` on the USB device returns `oriole` (Pixel 6); no
  `panther` (Pixel 7) transport exists on this host.
- Empirical vision check: generated image containing random code `ZQ7K42`, read back
  correctly first try on `deepseek-v4.1-flash`; fleet census shows all 9 god profiles
  on `deepseek-v4.1-flash`.
- Config backups date the fleet move: `v4flash=13–14, v4.1=0` through 2026-08-25;
  `v4.1=5` by 2026-09-19/21.
- Operator correction, 2026-09-23: *"the no vision hard constraint was because
  deepseek V4 flash was not a vision model but v4.1 is"* — verified correct.

**Reversibility:** easy. The skill is text; reverting to the prior wording is a
single file edit. The device-identity correction should not be reverted — the old
value pointed at a device that does not exist.

**Decided by:** Thoth on 2026-09-23 (operator-directed; rationale reversal originated
with the operator)

**Operator sign-off:** konan — explicit approval 2026-09-23 ("Yeah do it") after
being shown the evidence and the open questions.

**Affected:**
- `pantheon/god-packages/shared-skills/pantheon-phone-gateway/SKILL.md` (rewritten,
  v2.0.0)
- `pantheon/scripts/phone-daemon.py` (dead default + bare-`adb` bugs fixed)
- `pantheon/scripts/phone_screen.py` (new shared screen backend)
- `phone/artemis-accessibility-helper` skill (new)
- Every Pantheon god (all load this HARD CONSTRAINT skill)
- `~/athenaeum/Codex-God-thoth/research/artemis-android-automation-eval/report.md`
