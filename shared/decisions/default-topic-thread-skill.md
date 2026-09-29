# Decision: Default “make this a topic thread” behavior

Date: 2026-08-12

Konan requested that when he says “make this a topic thread” / “spin this into a dedicated thread” / similar, all gods should create a Discord thread and seed it with enough context to continue work there.

Implemented as a shared profile skill copied into active god profile skill trees:

- `topic-thread-from-conversation`
- location per profile: `~/.hermes/profiles/<god>/skills/pantheon/topic-thread-from-conversation/SKILL.md`

Default behavior encoded:

1. Act immediately on the phrase; do not ask for confirmation.
2. Create a Discord thread anchored to the triggering message when possible.
3. Post a compact context seed inside the thread.
4. Split seed messages to stay under Discord’s 2000-character limit.
5. Report the thread name and ID back to the parent chat.

Initial active profiles targeted: apollo, caduceus, hephaestus, hephaestus-qa, hermes, iris, kairos, marvin, mercer, rheta, thoth.
