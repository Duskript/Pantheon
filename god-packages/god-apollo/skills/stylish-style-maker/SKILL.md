---
name: stylish-style-maker
description: Suno style tag generator — creates JSON-style const blocks for Suno style prompts
category: creative
---

# Stylish Style Maker — Suno Style Tag Generator

## Trigger
Load this skill when the user says:
- "Make a style for [artist(s)]"
- "Generate a style tag"
- "I want to explore a sonic identity"
- "Fuse these two artists"
- "Suggest a style collision"

## Overview
You generate JSON-style `const` blocks for Suno style prompts. These
blocks describe the sonic DNA of an artist or fusion of artists and
go directly into Suno's Style Prompt field.

**Three modes:**
1. **Single Artist** — fill the template for one artist
2. **Fusion** — collide 2–3 artists into one merged block
3. **Suggest** — propose an interesting collision from the user's known influence list

**You do not add default ingredients.** The user does creative surgery
from here. Output is the clean JSON-style block — clean representation
of source artists only.

---

## MODE 1 — Single Artist

When the user names one artist:

1. First check `~/athenaeum/Codex-Apollo/knowledge/styles/` for any existing style reference
2. Also search Mnemosyne across Codex-Apollo for prior artist breakdowns
3. Fill the const block template with the artist's sonic DNA.

**Template:**
```javascript
const [Artist]Sound [Producer]Producer = {
  era: "[era]",
  genre: "[genre(s)]",
  style: "[stylistic description]",
  vocals: "[vocal description]",
  mood: "[mood descriptors]",
  instrumentation: "[key instruments and production elements]",
  mastering: "[mastering and production style]"
};
```

**Example (reference):**
```javascript
const beatlesSound georgemartinProducer = {
  era: "1960s",
  genre: "rock, pop, psychedelic, baroque pop",
  style: "melodic songwriting, innovative harmonies, shifting structures, psychedelic textures, experimental studio layering",
  vocals: "male, British, versatile mix of smooth tenor and raw edge, tight harmonies, playful to emotional delivery, distinctive Liverpudlian inflection",
  mood: "optimistic, whimsical, introspective, experimental, warm, bittersweet",
  instrumentation: "jangly guitars, piano, sitar, orchestral strings, brass, tape loops, inventive percussion, layered studio effects",
  mastering: "masterpiece, polished and clear, warm analog depth, wide stereo panorama, 24 bit resolution, 192 khz sample rate, classic 60s Abbey Road production style"
};
```

**Rules:**
- Be accurate — research the artist's actual producers, era, and style
- If you don't know a specific producer, describe the production style instead
- 4–8 items per field is the sweet spot — too few is generic, too many is noise
- The `era` field should be specific (e.g. "1998-2003, late 90s nu-metal, early 2000s alternative")
- The `mastering` field should always include a hi-fi descriptor and sample rate (24 bit, 192 khz) unless the artist's actual master is characteristically lo-fi

---

## MODE 2 — Fusion

When the user names 2–3 artists to collide:

1. Generate individual blocks for each artist in your reasoning
2. Merge them into ONE block that represents their intersection

**Fusion template format:**
```javascript
const [ArtistA][ArtistB]Sound [ProducerA][ProducerB]Producer = {
  era: "[combined era range, including specific years from each]",
  genre: "[merged genre vocabulary — what the intersection sounds like]",
  style: "[merged stylistic description — what happens when these worlds collide]",
  vocals: "[combined vocal characteristics — priority to the more distinctive]",
  mood: "[merged mood vocabulary]",
  instrumentation: "[combined instrumentation — keep the signature elements from each]",
  mastering: "[merged production style — describe what the blend would sound like]"
};
```

**Fusion example (from your history):**
```javascript
const BeatlesPinkFloydSound GeorgeMartinAlanParsonsProducer = {
  era: "1967-1975, late 60s psychedelic, early 70s progressive rock",
  genre: "psychedelic rock, art rock, progressive pop, symphonic rock",
  style: "experimental studio layering, conceptual song structures, cinematic transitions, melodic hooks meets atmospheric soundscapes, tape loops, sonic experimentation",
  vocals: "male, British, double-tracked leads, ethereal harmonies, dynamic range from soft whispers to raw soulful belts, dreamy reverb-drenched delivery",
  mood: "introspective, transcendental, melancholic, whimsical, epic, philosophical, hypnotic",
  instrumentation: "Hammond organ, Mellotron, Fender Stratocaster with delay, grand piano, slide guitar, orchestral brass, Moog synthesizer, heartbeat percussion, found sounds",
  mastering: "masterpiece, ultra-wide stereo imaging, lush analog warmth, high dynamic range, pristine clarity, 24 bit resolution, 192 khz sample rate, immersive hi-fi production style"
};
```

**Rules:**
- **No default ingredients** — the fusion is a pure representation of the source artists
- The producer field merges both names: `[ArtistAProducer][ArtistBProducer]`
- If naming both producers makes the field too long, describe the production style instead
- The fusion should honestly represent the intersection — don't force fit
- The user will do creative tweaking afterward (adding shoegaze wall of sound, cello, etc.)

---

## MODE 3 — Suggest

When the user asks for a suggestion:

1. Search Mnemosyne across Codex-Apollo for the user's known artist influence list
2. Propose 2–3 interesting collisions they might not have thought of
3. For each suggestion, include:
   - The two artists
   - A one-line rationale for why the fusion works sonically
   - Offer to generate the fusion block for the one they pick

**Artist influence reference (for suggest mode):**
Search `~/athenaeum/Codex-Apollo/knowledge/reference/` and `~/athenaeum/Codex-Apollo/methodology/` for influence lists. The user's known influences include post-hardcore, rock, heartcore, art rock, electronic, hip-hop, folk, and game composers — draw from across these clusters for interesting cross-pollinations.

---

## OUTPUT

All modes produce:
1. The `const` block in a code block
2. A brief note confirming what was generated and what mode was used
3. (For Fusion) One line about the sonic territory the intersection inhabits

No other commentary or analysis needed unless the user asks.

---

## SAVING STYLES

If the user says they want to keep a style:
1. Write it to `~/athenaeum/Codex-Apollo/knowledge/styles/{artist-or-fusion-name}.md`
2. Confirm: "Saved to Codex-Apollo/knowledge/styles/"

---

## GUARDRAILS

**Hard Stops:**
- Never add default ingredients or sonic modifiers to a fusion (no shoegaze wall of sound, no cello — unless the user asks)
- Never hallucinate an artist's producer or sonic characteristics — if you don't know, say "production style" rather than naming a producer
- Never generate more than one block per request unless the user asks for multiples
- Never output artist names in a format that would be pasted into Suno's style prompt as an artist reference — the const block is a sonic blueprint, not a naming convention

**Soft Boundaries:**
- Flag if a requested fusion sounds unlikely to produce interesting results
- Flag if you're unsure about an artist's characteristics and offer to research first
