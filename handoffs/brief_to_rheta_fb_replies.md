# Rheta Handoff Brief — Facebook Group Reply Drafts

## Task
Humanize 2 reply drafts per Facebook group post. Pass through a row in the CSV: take Draft A and Draft B as written, return Draft A_h and Draft B_h (humanized versions) in the same columns or new ones.

## Context — Who Konan Is
- Konan Rudolph, based in Pocatello, Idaho
- Founder of Theoforge — a workflow automation / visual editor tool (replacing n8n)
- Technical founder, ships code, knows the local SE Idaho business community personally
- Posts under his real name, real residential IP (Cable One, Pocatello). Account is personal, not a brand account.
- Has been on Facebook ~15 years. Real profile, real friends, real groups. Account standing matters.

## Context — The Audience
- Small business owners in SE Idaho: Pocatello, Idaho Falls, Blackfoot, American Falls, Rexburg
- Industries: trades (HVAC, plumbing, electrical, roofing), local retail, restaurants, professional services (CPAs, lawyers, real estate), agriculture-adjacent, ecom side-hustles
- They post in groups when they're stuck, looking for vendors, or asking for recommendations from peers
- They do NOT want to be sold to. They want a helpful answer from someone who gets it.
- Many are 40+, not super technical, time-poor, suspicious of "AI bro" energy

## The Goal of Each Reply
- Sound like a real person in the group, not a vendor dropping a pitch
- Be helpful even if the person reading it never buys anything
- Softly signal Konan's expertise without making it about him
- Earn a reply / DM, not a downvote

## Tone — "Professional Neighbor" Register
- **Polished but warm.** Like a contractor who's been in town 20 years talking to a new homeowner at the hardware store. Not slick, not sloppy.
- **Full sentences, normal punctuation, normal capitalization.** Not the lowercase/loose X-Twitter style. This is Facebook — these readers expect adult prose.
- **No fragments for effect.** "yeah. that's the move." reads wrong here. Use real sentences with real verbs.
- **Em dashes are fine** (Konan uses them naturally) but don't lean on them as a stylistic crutch.
- **Humor, when used, is dry and observational** — not edgy, not meme-y. Think "dad who's seen some things," not "LinkedIn influencer."

## Hard Rules — What the Replies MUST NOT Do
- Open with "I help [X] with [Y]" — that's the AI pitch tell
- Open with "Great question!" or "Awesome post!" — empty flattery
- Close with "Let me know if you have questions" / "I look forward to connecting" / "Thanks for your time" — robotic closes
- Use "I'd love to" / "I would be happy to" / "Don't hesitate to reach out" — service-industry filler
- List Konan's capabilities in a tidy bullet format — read like a services page
- Use "leverage," "synergy," "circle back," "robust solution" — corporate drift
- Embed the reader's hypothetical words: "If you've ever felt X..." — just say the thing
- Frame with "The funny thing is..." / "It's interesting that..." — distancing language
- Make every reply start with the same word or pattern — vary the openers across the batch
- Be longer than 4-5 sentences unless the post genuinely needs a real technical answer

## Hard Rules — What the Replies SHOULD Do
- Open by *engaging the specific post* — quote or paraphrase the actual problem
- Add one piece of concrete value: a tip, a name, a question back, a small frame
- Mention Theoforge only when it directly solves the problem being asked — and even then, name it once, casually, no caps
- End with a question back to the poster, OR a clear "happy to talk if useful" with NO exclamation mark
- Be 60-180 words. Shorter is fine. Longer needs to earn it.

## Variety — Vary Across the Batch
- Different openers: "Quick take —" / "What worked for me was" / "I hit this last year" / "On [X] specifically —" / etc.
- Different closing energy: question / soft offer / observation / "DM me if useful" (with the right vibe)
- Don't let the same sentence structure repeat in 5+ consecutive drafts

## Two Drafts Per Post — The Difference
- **Draft A (soft-helpful):** Answer the question first. Mention Theoforge only if it fits naturally. No pitch.
- **Draft B (direct-offer):** Name the problem more directly. Name Theoforge. Offer a free 15-min look at the poster's specific situation.

The humanized versions should preserve this difference, just with the AI-isms stripped and the voice made real.

## What You Get
A CSV with columns: `post_url, group, poster_name, post_text, date, matched_phrase, draft_a, draft_b`

## What You Return
Same CSV with two new columns appended: `draft_a_h, draft_b_h` — the humanized versions. Don't change the existing columns. Add yours at the end.

## Process
1. Read the full CSV
2. For each row, take draft_a and draft_b
3. Rewrite each in Konan's voice per the rules above
4. Vary openers, structures, and closes across the batch — don't template-stamp
5. Save to `~/pantheon/inbox/rheta/outbox/fb_replies_humanized_<timestamp>.csv`
6. Send a handoff-complete message back to Hermes via the Pantheon messaging system

## When In Doubt
Ask: "Would Konan actually write this in a group comment at 9pm on a Tuesday?"
If no, rewrite.
