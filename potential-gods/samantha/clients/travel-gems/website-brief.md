# Travel Gems — Website Build Brief

**Client:** Erica — Travel Gems
**Status:** DRAFT — brand + scope pending Erica's answers
**Related:** `../README.md`, `questionnaire.md` §5

---

## What we're building

A credible, fast, mobile-first site for a Fora-affiliated travel advisor whose job
is to convert curiosity into a booked inquiry. Not a brochure. Not a blog with a
logo on it.

**Primary job of the site:** get a qualified inquiry into Erica's inbox — or
straight into Samantha's triage queue.

**Secondary jobs:** establish taste and credibility, rank for a small set of
destination + "travel advisor" searches, give social content somewhere to land.

---

## Brand assets on hand

Location: `/home/konan/pantheon/shared/clients/travel-gem/`

| File | Use |
|---|---|
| `logo6.ai` | Source (Illustrator) — for edits |
| `logo6.eps` | Print / vendor handoff |
| `logo6.pdf` | Client-facing / print |
| `logo6.svg` | **Web** — primary use |
| `logo6.png` | Raster fallback, social |
| `logo6.jpg` | Legacy / email signatures |

**Observation that matters:** every format is **monochrome gray (~#A9A9A9 on
white)**. That's the uncolored version of the mark. Design implications:

1. Either the brand has no color system yet, or the color version wasn't sent.
   **Ask Erica for the color version and hex codes before design starts.**
2. Gray-on-white is weak for a travel brand — it reads corporate/placeholder, and
   it fails contrast for small sizes. If no color exists, we propose one.
3. The logo lockup includes **"an Affiliate of Fora Travel"** — this is a
   compliance asset, not decoration. Keep it legible at every size; do not crop it.

**Provisional palette** (until Erica approves): deep teal `#0FA3A3` (the ocean,
used as the Samantha accent), warm sand `#F3E8DA` (backgrounds), ink `#1A1A1A`
(text), gold `#C9A227` (accents/CTAs). Elegant, not neon.

**Typography direction:** the wordmark is a high-contrast connecting script; pair
it with a clean geometric sans for body. Script is for the logo only — never for
headings or UI.

---

## Site structure (v1)

| Page | Job | Notes |
|---|---|---|
| **Home** | Establish taste + capture inquiry | Hero, one-line positioning, 3 signature trips, proof, CTA |
| **About Erica** | Trust | Real photo, real story, Fora affiliation stated plainly |
| **Signature Trips** | Show the product | 3-6 curated trip concepts by type (not by destination) |
| **Destinations** | SEO surface | Start with her 3 money-markers, expand quarterly |
| **Inquire** | Conversion | Smart intake form (see below) |
| **Journal** *(Phase 2)* | SEO + social proof | Only if we commit to a cadence — a dead blog hurts |
| **Legal** | Compliance | Terms, privacy, Fora disclosure, seller-of-travel language |

**Deliberately excluded from v1:** booking engine, payments, client portal, live
availability. She books through Fora. The site sells the conversation.

---

## The inquiry form is the product

This form feeds Samantha. It should ask exactly what she'd otherwise ask by email,
so the first reply can be substantive instead of "tell me more."

Proposed fields:

1. Name, email, phone (optional)
2. Where do you want to go, and roughly when? (free text beats a dropdown here)
3. Who's traveling — adults, kids, ages?
4. What kind of trip — beach, city, adventure, cruise, honeymoon, celebration, other
5. Budget range *(optional, but offer ranges — it saves everyone time)*
6. Have you worked with a travel advisor before?
7. How did you find us?
8. Anything else we should know?

**Wiring:** form → webhook → Samantha's inbox triage → she drafts a first reply in
Erica's voice within the hour, staged for approval. This is the single best demo
of the whole system working, so build it early.

---

## Technical recommendation

| Decision | Choice | Why |
|---|---|---|
| Framework | **Astro** (static output) | Fast, near-zero maintenance, great SEO, cheap to host |
| Hosting | Hostinger VPS (same box) or Cloudflare Pages | She already has Hostinger; static is free either way |
| CMS | Markdown in git; Tina/Sveltia later if she wants to self-edit | No WordPress = no plugin CVEs |
| Forms | Serverless endpoint on the VPS + spam trap | No third-party form SaaS dependency |
| Analytics | GA4 or Umami (self-hosted) | Privacy-friendly, and Umami avoids cookie banners |
| Email capture | Double opt-in, welcome sequence 2 emails max | Don't build a newsletter we can't feed |
| Images | AVIF/WebP, lazy-loaded, real travel photography | This is a taste business — photo quality is the brand |

**Non-negotiables:** Lighthouse ≥95 on mobile, LCP <2.5s, readable without JS,
accessible contrast (the gray logo will fail at small sizes — fix by using the ink
variant).

---

## Compliance notes

- Fora advisors must present themselves as affiliated, not as Fora itself. Keep
  the lockup and a footer line: *"Travel Gems is an affiliate of Fora Travel."*
- Never state or imply that pricing/availability is guaranteed unless pulled live.
- Do not publish supplier names/perks in a way that violates partner agreements.
- Any testimonial or client photo needs written permission on file.

---

## Timeline

| Phase | Work | Duration |
|---|---|---|
| 0 | Brand answers + logo color version + domain access | 2-3 days (blocked on Erica) |
| 1 | Home, About, Inquire, legal, deploy | 1 week |
| 2 | Signature Trips, 3 destination pages, SEO basics, analytics | 1 week |
| 3 | Journal cadence + inquiry→Samantha automation live | ongoing |

---

## Open questions (blocking design)

1. Color version of the logo, or should we propose a palette?
2. Domain — registered at GoDaddy? DNS access confirmed?
3. Is she the face of the brand or is it a company brand?
4. Does she want to write, or are drafts acceptable?
5. Which three destinations do we build pages for first?
