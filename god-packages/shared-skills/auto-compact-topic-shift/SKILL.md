---
name: auto-compact-topic-shift
description: "Use when you need to detect topic shifts in conversation and automatically trigger context compaction. Universal skill for all Pantheon gods."
version: 1.0.0
author: Pantheon
license: MIT
metadata:
  hermes:
    tags: [pantheon, universal, topic-shift, compaction, session-management]
    related_skills: []
    config:
      auto_compact_topic_shift:
        auto_threshold:
          description: "Confidence threshold (0.0-1.0) above which to auto-trigger compaction without asking"
          type: float
          default: 0.75
        suggest_threshold:
          description: "Confidence threshold (0.0-1.0) above which to suggest a topic shift to the user"
          type: float
          default: 0.40
        compaction_style:
          description: "What to do on detection: 'compress' (compact context in-place) or 'new_session' (signal for a fresh session)"
          type: string
          default: "compress"
        enabled:
          description: "Master toggle — set false to disable topic-shift detection"
          type: boolean
          default: true
---

# Auto-Compact: Topic Shift Detection

**Purpose:** Automatically detect when the user shifts topics mid-conversation and trigger context compaction — keeping session context clean and avoiding token waste.

This is a **universal Pantheon skill** designed for all gods (Hermes, Hephaestus, Apollo, and any future god). Load it in your SOUL.md or profile config to get topic-shift awareness in every session.

## Overview

Conversations naturally drift between topics. Without detection, the old topic's context stays in the window — wasting tokens, diluting focus, and making the god less responsive. This skill teaches you to:

1. **Maintain** an awareness of the current conversational topic
2. **Detect** when the user's message represents a semantic shift
3. **Calculate** a confidence score for the shift
4. **Act** based on configurable thresholds

---

## How Topic-Shift Detection Works

### 1. Track Current Topic

After every exchange, maintain a compact "current topic" label in your working context — a short phrase (3-8 words) describing the active subject.

**Examples:**
- `"Pantheon knowledge graph layer implementation"`
- `"Debugging the MCP server import error"`
- `"Apollo's lyric-writing workflow setup"`

Derive this label from the last 3-5 exchanges. If you've just started a session, the first user message defines the initial topic.

### 2. Detect Shift on Each Incoming Message

When a new user message arrives:

```
confidence = analyze_shift(current_topic, new_message)
```

Your **shift confidence score** factors:
- **Lexical change** (0.0–0.4): New keywords, named entities, or jargon unrelated to current topic
- **Semantic distance** (0.0–0.4): The core intent of the message — is it a follow-up question, elaboration, or a completely new request?
- **Structural cues** (0.0–0.2): Exact phrase matches like "new topic", "anyway", "speaking of X", "let's talk about", or message begins with a standalone noun/name with no connective phrasing

Total confidence is a weighted sum: `(lexical × 0.4) + (semantic × 0.4) + (structural × 0.2)`

### 3. Act Based on Confidence

```
if confidence >= auto_threshold (0.75):
    → AUTO-TRIGGER: Compact context, acknowledge shift, start fresh focus
elif confidence >= suggest_threshold (0.40):
    → SUGGEST: "Looks like we're shifting topics — mind if I compress and refocus?"
else:
    → CONTINUE: Update current topic label, respond normally
```

---

## Actions

### `compress` (default)

When auto-triggering:
1. **Acknowledge** the shift briefly in your response: "Switching gears — "
2. **Compress** the recent conversation by summarizing key decisions/artifacts into your working context
3. **Reset** your current topic label to the new topic
4. **Continue** responding to the user's message in the new topic context

### `new_session`

When auto-triggering:
1. **Acknowledge** the shift
2. **Signal** for a fresh session using available session management tools
3. **Start fresh** with the new topic as the initial context

---

## Configuration

Configure per-god via their `config.yaml` under `skills.auto_compact_topic_shift`:

```yaml
skills:
  auto_compact_topic_shift:
    auto_threshold: 0.75        # auto-trigger at 75% confidence
    suggest_threshold: 0.40     # suggest at 40% confidence
    compaction_style: compress  # 'compress' or 'new_session'
    enabled: true               # master toggle
```

If not set, defaults from the skill frontmatter apply.

---

## Common Pitfalls

1. **False positives on follow-up questions** — A user asking "how does that connect to X?" is NOT a topic shift; it's a connection request. Check that the message introduces genuinely new entities/subject matter, not just a broadening of the current topic.

2. **Over-triggering on short messages** — A one-word response like "cool" or "okay" is not a topic shift. Skip analysis on messages under 5 words unless they contain explicit structural cues ("anyway", "new topic").

3. **Under-triggering after long context** — After 50+ exchanges, even subtle shifts should trigger because the context window is already strained. Lower your effective thresholds by 10% when conversation history exceeds 30 exchanges.

4. **Conflicting with built-in compression** — The agent already has `compression.enabled` and `compression.threshold` for token-based compression. This skill is for *semantic* topic-shift detection, not token management. They complement each other.

5. **God-specific confusion** — If you're a single-purpose god (e.g., Apollo focused on lyric writing), topic shifts are rare. Raise `auto_threshold` to 0.90 to avoid false triggers. If you're a generalist god (Hermes), keep defaults.

6. **Don't compress mid-task** — If the user's topic shift is followed by "and now let me explain further about X", delay compaction until the user has finished their full statement. Only act on a complete user turn.

---

## Verification Checklist

- [ ] Skill is installed in the god's profile skills directory
- [ ] SOUL.md or config references the skill for auto-loading
- [ ] New session starts with skill loaded (verify via `/skills` or response behavior)
- [ ] Obvious topic shift triggers the expected action
- [ ] Follow-up questions on the same topic do NOT trigger
- [ ] Short messages (< 5 words) do NOT trigger falsely
- [ ] Thresholds can be overridden in config.yaml
- [ ] Disabling via `enabled: false` stops all detection
