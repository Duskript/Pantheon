"""
USER_OBSERVATIONS_PROMPT_ADDITION — appended to AIAgent._MEMORY_REVIEW_PROMPT
and _COMBINED_REVIEW_PROMPT by the pantheon-ichor-nudge plugin.

Extends the existing LLM call (same context window, same inference) to also
output structured observations about users. Zero extra LLM calls.

This is Tier 1 (Fast Extract) — explicit facts and preferences only.
Tier 2 (Deep Reason) — deduction, induction, contradictions — lives in
the Dreamer-equivalent cron (not yet implemented).
"""
USER_OBSERVATIONS_PROMPT_ADDITION = """

### User Observations

Also scan the conversation for new things you learned about the user(s) and
output them as structured observations. These observations will be stored in
Pantheon's user memory system so ALL gods can understand this user better in
future interactions.

Output as a JSON block at the END of your response (after ICHOR_EVENTS if both
are present):

USER_OBSERVATIONS
[
  {
    "subject": "konan",
    "category": "preference",
    "content": "Prefers plan-first execution with no clarification loops on Telegram",
    "confidence": 0.9,
    "evidence": ["msg-3", "msg-7"]
  }
]

CATEGORIES (pick the best fit):

  fact          — Verifiable, durable information. "Konan uses Tailscale for
                  remote access." "Runs Ubuntu on a Beelink U55."
                  "Currently building Pantheon user memory system."

  preference    — Likes, dislikes, work style, communication preferences.
                  "Prefers plan-first execution over clarify loops."
                  "Dislikes hedging and academic padding."
                  "Wants infrastructure built before it's needed."

  commitment    — Promise, deadline, or action item the user has taken on.
                  "Promised to review Olympus UI by Friday."
                  "Committed to migrating PostgreSQL by end of week."
                  Include deadline if stated.

  project       — Current project, goal, or focus area.
                  "Building a multi-user reasoning memory system."
                  "Working on Pantheon god summoning feature."
                  Include status if known (planning, building, blocked, done).

  relationship  — How the user relates to specific gods, tools, or other users.
                  "Trusts Thoth for deep research tasks."
                  "Delegates infrastructure builds to Hephaestus."
                  "Frustrated with Hermes when responses are too verbose."

  environment   — Technical environment, tools, setup.
                  "Runs Ollama locally for embeddings."
                  "Uses deepseek-v4-flash via OpenCode Go for daily tasks."
                  "Has PostgreSQL 16 on Beelink U55."

  emotional     — Mood, energy level, frustration signals, excitement.
                  "Frustrated with project pace — looking for quick wins."
                  "Energized by architectural discussions."
                  "Low energy today — keep responses short."
                  ONLY include if the signal is clear and strong.
                  Confidence should be >= 0.7 for emotional observations.

  contradiction — New information that conflicts with a prior observation.
                  "Previously said project ships Friday, now says Monday."
                  Include what changed FROM and TO.

  gap           — Something you'd expect to know but don't.
                  "Hasn't mentioned Hephaestus in 3 weeks — may be blocked."
                  "Unknown whether PostgreSQL migration has been tested."

RULES:

- ONLY extract NEW observations — check the existing observations provided
  below and do NOT repeat anything already known about this user.

- Each observation must be SELF-CONTAINED. Someone reading it without the
  conversation should fully understand it. Replace pronouns with names.
  "Konan prefers X" NOT "He prefers X".

- Use ABSOLUTE dates/times. "committed on May 25, 2026" NOT "committed today".

- CONFIDENCE scoring:
  0.9-1.0 = explicitly stated, no ambiguity
  0.7-0.8 = strongly implied but not literally said
  0.5-0.6 = reasonable inference from context
  Below 0.5 = do NOT extract

- EVIDENCE: reference specific message numbers or quoted snippets that support
  each observation. This allows future verification.

- If the user corrected you or a god about something, that is HIGH-PRIORITY.
  Corrections are strong preference signals. Category: preference.

- EMPTY ARRAY if nothing new was learned. Do not fabricate observations.
  Do not extract generic pleasantries ("user said hello").
  Do not extract observations about god behavior, only user behavior.

- Attributed observations: if the user talks about someone else, attribute
  correctly. "Konan said Alice prefers dark mode" → subject: "alice", but
  note the source is secondhand (lower confidence).

EXISTING OBSERVATIONS ABOUT THIS USER:
{existing_observations}
"""
