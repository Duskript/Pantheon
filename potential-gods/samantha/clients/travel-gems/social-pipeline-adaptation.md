# Travel Gems — Social Pipeline Adaptation

**Goal:** point the existing Pantheon social stack (Kairos pipeline + Rheta copy)
at a travel advisor without rebuilding it.

---

## What already exists (and what we reuse as-is)

| Layer | Existing asset | Reuse |
|---|---|---|
| Strategy | `mkt-content-strategy`, `content-topic-rotation-audit` | As-is — pillars change, machinery doesn't |
| Signal | `current-signal-research`, `last30days` | As-is, but the query set becomes travel-specific |
| Copy | Rheta (`rheta-copywriting`, `mkt-social`, `mkt-copy-editing`) | Needs a **travel voice guide** seeded from Erica's real posts |
| Pipeline | `social-content-pipeline` (gated), `signal-gated-campaign-workflows` | As-is — gates are the point |
| Visual | `mkt-ad-creative`, image generation | **Limited** — travel needs real photos, not generated ones |

**The one thing we must NOT reuse:** AI-generated destination imagery. A travel
advisor posting a synthetic beach destroys the entire credibility play. Real photos
or licensed stock, never generated scenery.

---

## What actually changes

### 1. The CTA changes
Generic marketing CTA: "buy now / learn more."
Travel advisor CTA: **"DM me / save this / start planning early."** Booking windows
are long. The metric is a conversation started, not a checkout.

### 2. The calendar is seasonal, not editorial
Post timing is driven by **booking windows**, not by content whims:

| Post month | Sells |
|---|---|
| Jan-Feb | Spring break, summer Europe (peak booking window) |
| Mar-Apr | Summer trips, Alaska, Mediterranean cruises |
| May-Jun | Last-minute summer, fall foliage planning |
| Jul-Aug | Fall + holiday trips, ski season |
| Sep-Oct | Holiday, winter sun, spring 2027 |
| Nov-Dec | Next-year planning, gift-of-travel, warm-weather escapes |

Every post should answer: *what is a client supposed to book right now?*

### 3. Photos are the bottleneck
Content volume is capped by asset supply, not by copy. Plan around it:
- Erica's own trips → primary source, highest credibility
- Client trips → only with written permission, tagged or credited as approved
- Fora marketing library → check usage rights per asset
- Licensed stock → fallback, must look non-stocky

**Rule:** no post ships without an asset attached. A great caption with a gray box
is dead weight.

### 4. Compliance layers on top
- Fora affiliate disclosure where required
- No client names/photos without written permission on file
- Never publish net rates, commission details, or supplier contract terms
- Don't imply guaranteed perks or pricing

---

## Content pillars (v1 — six)

| Pillar | Share | Example |
|---|---|---|
| **Destination intel** | 30% | "The 4 hotels in Positano worth the splurge, and the one that isn't" |
| **Trip reveals** | 20% | Real itinerary, real photos, what it cost in points vs cash |
| **Planning craft** | 20% | "Why I book your flights before your hotel" / mistake-of-the-week |
| **Client wins** | 15% | Testimonial, upgrade secured, crisis averted (permission required) |
| **Seasonal urgency** | 10% | "If you want Tuscany in June, we should talk this month" |
| **Personal / behind-the-scenes** | 5% | Erica at the desk, the unglamorous part, her own travel |

Personal content is deliberately capped — it builds trust but doesn't sell trips.
If Erica wants to be the face, this ratio shifts and the whole plan is rewritten.

---

## Platform priority

| Platform | Role | Cadence | Format |
|---|---|---|---|
| **Instagram** | Primary — discovery + DM conversion | 3-4/wk | Carousels (intel), Reels (destinations), Stories (polls, trip-day) |
| **Facebook** | Trust + referrals + local network | 1-2/wk | Cross-post best IG content; long-form client wins |
| **Pinterest** | Long-tail search, slow burn | 5 pins/wk, batched monthly | Repurpose IG carousels as pin graphics |
| **TikTok** | Optional | Skip until IG is consistent | Requires camera comfort |

**Do not spread thin.** Instagram consistency for 8 weeks beats four half-run
accounts. Add platforms only after the approval loop runs without friction.

---

## Pipeline stages (gated)

```
1. SIGNAL      Weekly: what's booking, what's trending, what's coming due
2. BRIEF       Kairos produces 4-6 content briefs with angle + asset need
3. ASSET       Erica supplies photos OR we pull licensed stock → asset attached
4. COPY        Rheta drafts in Erica's voice (post + first comment + hashtags)
5. EDIT        Sweep pass: AI-isms out, specificity in, CTA clear
6. APPROVAL    Erica approves in one message: "1,3,5 yes, 2 change the CTA"
7. SCHEDULE    Batched into the week's slots
8. MEASURE     Saves, shares, profile visits, DMs — not likes
9. LEARN       Winners/losers feed the next brief
```

**No stage skips approval.** Ever. A travel advisor's reputation is her only
inventory.

---

## Samantha's role in the pipeline

Samantha is **not** the content producer. She is the raw-material supplier and the
scorekeeper. Concretely, every Monday she delivers to Kairos:

1. **Trips in motion** — who's traveling where, which are shareable with permission
2. **Wins** — upgrades confirmed, crises resolved, reviews received
3. **Destination pulses** — supplier news, new hotel openings, entry-requirement changes
4. **Calendar pressure** — which seasons are under-booked and need a push
5. **Last week's numbers** — saves, shares, profile visits, DMs, inquiries attributed

And she reports back to Erica in the weekly review: what the content actually
produced. Content with no attribution is a hobby.

---

## 8-week launch plan

| Week | Focus |
|---|---|
| 1 | Voice guide seeded from Erica's real posts; IG grid refreshed; bio + link |
| 2 | First 3 carousels (destination intel) + 1 Reel; establish approval rhythm |
| 3 | Client-win post; Stories with polls; Pinterest board setup |
| 4 | Seasonal urgency post tied to an actual booking deadline |
| 5 | Batch a month of Pinterest; test a carousel vs Reel on the same topic |
| 6 | Double down on the winning format; kill the loser |
| 7 | First "planning craft" series — 3-part mini-series |
| 8 | Review: what drove DMs and inquiries? Rewrite pillars based on evidence |

---

## Metrics that matter

- **DMs and inquiry-form submissions** attributed to social
- **Saves** (intent signal — the closest thing to a booking intent on IG)
- **Shares** (reach multiplier)
- **Profile visits → link clicks** (conversion path)
- **Follower quality** — inbound from her target destinations, not vanity volume

Likes are noise. Report them last or not at all.

---

## Open questions

1. Is Erica willing to be on camera? Changes the whole format mix.
2. Does she have a photo backlog from her own travels? How many usable images?
3. Any client photos already permissioned?
4. Which platforms does she actually enjoy using? (Sustainable > optimal.)
5. Who responds to DMs — her, or does Samantha draft?
