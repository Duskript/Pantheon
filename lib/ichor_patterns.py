"""Ichor Tier A — Zero-LLM Pattern Registry.

Compiled regex patterns for all extraction types.
Each type has 15+ patterns covering varied phrasings, tenses, and styles.
Patterns are compiled once at import time for zero per-call overhead.
"""

import re
from typing import Dict, List

EVENT_TYPE_META: Dict[str, Dict] = {
    "decision": {
        "description": "Choices made, paths selected",
        "baseline_confidence": 0.8,
    },
    "commitment": {
        "description": "Promises, deadlines, action items",
        "baseline_confidence": 0.8,
    },
    "fact": {
        "description": "Declarative statements about self, system, or world",
        "baseline_confidence": 0.7,
    },
    "preference": {
        "description": "Likes, dislikes, tastes, opinions",
        "baseline_confidence": 0.7,
    },
    "correction": {
        "description": "User correcting the assistant",
        "baseline_confidence": 0.9,
    },
    "insight": {
        "description": "Aha moments, realizations, breakthroughs",
        "baseline_confidence": 0.7,
    },
    "blocker": {
        "description": "Stuck points, errors, unsolved problems",
        "baseline_confidence": 0.8,
    },
    "reference": {
        "description": "Resources, tools, links mentioned",
        "baseline_confidence": 0.6,
    },
    "follow_up": {
        "description": "Things to revisit later",
        "baseline_confidence": 0.7,
    },
}

ALL_TYPES: List[str] = list(EVENT_TYPE_META.keys())

# ── Decision patterns ──────────────────────────────────────────────────
_DECISION = [
    r"(let's|we(?:'ll)?)\s+go\s+with",
    r"(?:i've|we've)\s+decided",
    r"(?:i|we)\s+(?:choose|chose|picked|selected|opted)",
    r"settled\s+on",
    r"(?:final|made\s+a)\s+decision",
    r"going\s+with",
    r"we(?:'ll)?\s+(?:use|try|do)\s+that",
    r"voted\s+for",
    r"recommend(?:ed|s)?\s+(?:we|the|using)",
    r"we\s+agreed\s+(?:to|on|that)",
    r"decided\s+(?:to|on|that)",
    r"(?:my|our)\s+pick\s+is",
    r"(?:i|we)'?ll\s+stick\s+with",
    r"let's\s+(?:do|try|use)\s+that",
    r"that's\s+(?:the\s+)?plan",
    r"(?:i|we)\s+made\s+(?:a|the|our)\s+choice",
    r"my\s+(?:final|ultimate)\s+answer",
    r"vote\s+(?:for|on|is)",
    r"(?:chosen|selected)\s+path",
    r"(?:i|we)'?ll\s+go\s+ahead\s+with",
    r"signing\s+off\s+on",
    r"we're?\s+(?:going|opting|leaning)\s+(?:with|for|toward)",
    r"(?:it's|that's)\s+(?:settled|decided|agreed)",
    r"approved\s+(?:the|this|that|your)",
]

# ── Commitment patterns ────────────────────────────────────────────────
_COMMITMENT = [
    r"by\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"tomorrow|tonight|end\s+of\s+day|end\s+of\s+week|next\s+week|"
    r"the\s+weekend|midnight)",
    r"deadline\s+(?:is|by|of)",
    r"i\s+(?:will|'ll)\s+",
    r"i\s+promise",
    r"(?:i'll|i\s+will)\s+(?:handle|take\s+care\s+of|look\s+into|"
    r"send|check|do\s+that|implement|build|fix|create|write|"
    r"update|push|deploy|review|test|refactor)",
    r"(?:todo|to-do|to\s+do|action\s+item|task\s+item)",
    r"remind\s+me\s+to",
    r"follow\s+up\s+(?:on|with)",
    r"i\s+owe\s+(?:you|it)",
    r"i'll\s+get\s+(?:back|on\s+it|to\s+it|this\s+done)",
    r"(?:my|our)\s+commitment",
    r"i'll\s+take\s+(?:care\s+of|ownership\s+of)",
    r"(?:assigned|delegated|responsible\s+for)",
    r"by\s+(?:end\s+of|the\s+end\s+of)\s+(?:day|week|month|today|tomorrow|quarter)",
    r"due\s+(?:by|on|date)",
    r"i'll\s+make\s+sure",
    r"(?:my|the)\s+responsibility",
    r"(?:i'm|i\s+am)\s+(?:on\s+it|handling\s+it|working\s+on\s+it)",
    r"i'll\s+circle\s+back",
    r"(?:timeline|ETA|estimated\s+completion)",
    r"i'll\s+(?:let\s+you\s+know|keep\s+you\s+posted|update\s+you)",
    r"(?:committed|pledged|promised)\s+to",
    r"(?:target|aiming|shooting)\s+for",
    r"(?:deadline|due|drop\s+dead)\s+date",
]

# ── Fact patterns ──────────────────────────────────────────────────────
_FACT = [
    r"(?:i'm|i\s+am)\s+(?:based|located|situated)\s+in",
    r"(?:i|we)\s+(?:live|work)\s+(?:in|at|for)\s+",
    r"my\s+name\s+is",
    r"we\s+use\s+",
    r"it's\s+(?:a|an)\s+",
    r"(?:currently|actually|technically)\s+(?:we|it|the|this)",
    r"runs\s+on\s+",
    r"written\s+in\s+",
    r"built\s+(?:with|using|on\s+top\s+of)",
    r"powered\s+by",
    r"(?:developed|created|written)\s+(?:in|with|using|for)",
    r"the\s+(?:system|app|tool|service|platform)\s+(?:is|uses|runs)",
    r"i've\s+been\s+(?:working|using|doing)\s+(?:on|with|this\s+for)",
    r"(?:platform|environment|setup|architecture|infrastructure)\s+is",
    r"hosted\s+on\s+",
    r"deployed\s+(?:on|via|to|using)",
    r"(?:configured|setup|set\s+up)\s+(?:as|with|using|to)",
    r"(?:database|db|storage)\s+(?:is|uses|runs)",
    r"(?:role|job|position|title)\s+(?:is|as|of)",
    r"i\s+(?:work\s+(?:as|for)|am\s+(?:a|an))\s+",
    r"(?:founded|started|launched|created)\s+(?:in|on|at)\s+\d{4}",
    r"(?:years?\s+of\s+experience|been\s+(?:doing|working)\s+this\s+for)",
    r"(?:department|team|group|org|organization)\s+(?:is|called|named)",
    r"our\s+(?:stack|tech\s+stack|toolchain|setup)\s+(?:is|uses|includes)",
]

# ── Preference patterns ────────────────────────────────────────────────
_PREFERENCE = [
    r"i\s+prefer\s+",
    r"i\s+like\s+",
    r"i\s+(?:love|enjoy|appreciate)\s+",
    r"i\s+hate\s+",
    r"i(?:'m|\\s+am)\s+not\s+(?:a\s+)?fan\s+of",
    r"(?:my|our)\s+favou?rite",
    r"(?:i'd|i\s+would)\s+rather",
    r"prefer\s+(?:not\s+to|to|over)",
    r"i\s+(?:really|totally|absolutely)\s+(?:like|love|hate)",
    r"(?:personal|strong)\s+preference",
    r"if\s+it\s+were\s+up\s+to\s+me",
    r"i'd\s+(?:pick|choose|go\s+with|vote\s+for)",
    r"i(?:'m|\\s+am)\s+more\s+of\s+(?:a|an)\s+",
    r"i\s+(?:don't|do\s+not)\s+(?:like|enjoy|appreciate)",
    r"(?:not|never)\s+(?:a\s+)?fan",
    r"(?:my|personal)\s+go-to",
    r"i'm\s+not\s+(?:really\s+)?into",
    r"would\s+rather\s+not",
    r"(?:big|huge)\s+(?:fan|supporter)\s+of",
    r"i'd\s+(?:rather|prefer)\s+(?:not|to)",
    r"(?:i'm|i)\s+(?:really\s+)?into",
    r"i\s+can't\s+(?:stand|bear)\s+",
    r"what\s+(?:i|we)\s+(?:really|actually)\s+(?:want|need|prefer)",
]

# ── Correction patterns ────────────────────────────────────────────────
_CORRECTION = [
    r"no[.,]\s+(?:that's|that\s+is)\s+(?:wrong|incorrect|not\s+right|not\s+correct)",
    r"actually[.,]\s+",
    r"i\s+meant\s+",
    r"not\s+that[.,]",
    r"you\s+(?:misunderstood|got\s+that\s+wrong|misinterpreted)",
    r"that's\s+not\s+(?:what\s+(?:i|we)?|right|correct|true|accurate)",
    r"let\s+me\s+(?:clarify|rephrase|correct|be\s+clear)",
    r"i\s+didn't\s+(?:say|mean|ask)\s+that",
    r"to\s+clarify[,.]",
    r"that(?:'s|\s+is)\s+not\s+(?:quite|exactly|really)\s+(?:right|what|accurate)",
    r"(?:correction|correcting|let\s+me\s+fix)",
    r"wait[.,]\s+(?:no|that|i)",
    r"not\s+(?:exactly|quite|really)[.,]",
    r"re-read|misread|my\s+bad",
    r"that(?:'s|\s+is)\s+(?:the\s+)?opposite",
    r"on\s+second\s+thought",
    r"that's\s+not\s+(?:how|what|where|when|why)\s+",
    r"i\s+(?:think|believe)\s+you(?:'re|\s+are)\s+(?:confused|mistaken|wrong)",
    r"no[,.]\s+(?:actually|that's|what)",
    r"mis(?:read|understood|heard|interpreted)",
    r"let\s+me\s+re(?:phrase|state|word)",
    r"(?:that's|that\s+is)\s+(?:completely|totally)\s+(?:wrong|incorrect|off)",
]

# ── Insight patterns ───────────────────────────────────────────────────
_INSIGHT = [
    r"(?:wait|aha|oh)[.,]\s+(?:i\s+see|that\s+means|i\s+get\s+it|"
    r"that's\s+interesting|now\s+i|that's\s+the|i\s+understand)",
    r"i\s+(?:just\s+)?realized",
    r"that\s+(?:means|implies|suggests|indicates)",
    r"(?:interesting|fascinating|notable|remarkable)[.,]",
    r"i\s+(?:never\s+)?thought\s+of\s+(?:it|that)\s+"
    r"(?:that\s+way|like\s+that|before)",
    r"that\s+(?:changes|explains|clarifies|connects)",
    r"(?:key|main|important|crucial)\s+"
    r"(?:takeaway|insight|point|finding|observation)",
    r"(?:now|so)\s+(?:that|this)\s+(?:makes|is)\s+(?:sense|the|a\s+lot)",
    r"it's\s+(?:like|as\s+if|almost\s+as\s+if)",
    r"that\s+(?:never|doesn't)\s+occurred?\s+to\s+me",
    r"(?:connection|pattern|trend)\s+(?:between|across|emerg|notice)",
    r"(?:realization|discovery|breakthrough|epiphany)",
    r"dawned\s+on\s+me",
    r"(?:clicked|fell\s+into\s+place|connected\s+the\s+dots)",
    r"(?:deeper|broader|bigger|wider)\s+"
    r"(?:meaning|implication|picture|context)",
    r"oh\s+(?:that's|i|right|yeah)",
    r"never\s+thought\s+of\s+it\s+(?:that\s+way|like\s+that)",
    r"interesting\s+(?:point|perspective|angle|take)",
    r"i\s+(?:notice|see|spot|observe)\s+(?:a|an|the|that)",
    r"(?:there's|here's)\s+(?:a\s+)?(?:connection|link|relationship)\s+between",
    r"hold\s+on[.,]\s+(?:that|i|let)",
    r"(?:ah|oh|aha)\s*!",
    r"(?:wait|hold\s+on)[,.]?\s*(?:that|this|i)\s+(?:means|is|has)",
]

# ── Blocker patterns ───────────────────────────────────────────────────
_BLOCKER = [
    r"(?:stuck|blocked|can't\s+figure|can't\s+find|can't\s+get)",
    r"(?:error|issue|problem|bug|exception|failure)\s+"
    r"(?:says|is|with|in|occurr|thrown|getting|from|during|at)",
    r"(?:doesn't|don't|won't|can't|isn't|aren't)\s+work",
    r"this\s+(?:isn't|is\s+not)\s+(?:working|behaving|expected)",
    r"(?:failed|failure|crash|crashing|broken|breaking|not\s+responding)",
    r"i\s+(?:can't|can't\s+seem\s+to|can't\s+get)\s+",
    r"(?:having|running\s+into|hitting|encountering)\s+"
    r"(?:trouble|issues|problems|errors|an\s+issue)",
    r"(?:unexpected|strange|weird|odd|unusual)\s+"
    r"(?:behavior|result|error|output|response)",
    r"(?:timeout|tim(?:ed?|ing)\s+out|taking\s+too\s+long|hanging|freezing)",
    r"(?:permission|access|auth|credential|denied|forbidden|unauthorized)",
    r"(?:missing|not\s+found|doesn't\s+exist|no\s+such|unreachable)",
    r"(?:dependency|conflict|incompatible|version\s+mismatch)",
    r"can't\s+(?:connect|reach|resolve|find|access|open|read|write)",
    r"(?:compiler|linter|syntax|type|import)\s+"
    r"(?:error|issue|problem|failure)",
    r"(?:debugging|diagnos|traceback|stack\s+trace)",
    r"(?:workaround|hack|fix|patch|solution)\s+(?:for|needed|didn't)",
    r"(?:bottleneck|performance\s+issue|slow|"
    r"memory\s+leak|cpu\s+spike|disk\s+full)",
    r"(?:won't|can't|doesn't)\s+(?:compile|build|start|connect|load)",
    r"(?:null|undefined|none|nil)\s+(?:pointer|reference|error)",
    r"(?:conflict|merge\s+conflict|collision)",
    r"stuck\s+(?:on|in|at|with)",
    r"blocked\s+(?:by|on|from)",
    r"(?:failing|failure)\s+(?:test|build|check|stage)",
]

# ── Reference patterns ─────────────────────────────────────────────────
_REFERENCE = [
    r"check\s+(?:out|this)\s+",
    r"(?:see|look\s+at)\s+this",
    r"there's\s+(?:a|an|this)\s+"
    r"(?:\w+\s+)?"
    r"(?:tool|library|package|repo|repository|service|api|framework|app|resource)",
    r"(?:read|check|look\s+at)\s+(?:the\s+)?docs",
    r"https?://[^\s]+",
    r"(?:github\.com|npmjs\.com|pypi\.org|docs?\.[^\s]+)",
    r"referenc(?:e|ed|ing)\s+",
    r"saw\s+(?:this|a)\s+(?:post|article|video|tutorial|talk|paper|blog)",
    r"(?:documentation|docs|wiki|guide|tutorial|example)\s+(?:at|for|on|is)",
    r"(?:i'd|you|we)\s+(?:check|look|read)\s+(?:out|at|up)\s+",
    r"(?:link|url|resource|source)\s+(?:to|at|is|here)",
    r"(?:recommended|suggested|popular|widely\s+used)\s+"
    r"(?:tool|library|framework|package)",
    r"(?:found|stumbled\s+across|came\s+across|discovered)\s+"
    r"(?:a|an|this|that)",
    r"(?:article|paper|thread|discussion)\s+(?:on|at|about)",
    r"\bRFC\s*\d+\b",
    r"\b(?:PR|issue|ticket)\s*#?\s*\d+",
    r"credit\s+(?:to|goes\s+to|for)",
    r"(?:tutorial|guide|walkthrough|how-to|demo)\s+(?:on|for|at|about)",
    r"(?:book|paper|thesis|article|publication)\s+(?:called|titled|by|about)",
    r"(?:mentioned|linked|shared|posted)\s+(?:by|in|on|about)",
    r"(?:source\s+code|repo|repository)\s+(?:at|is|here|for)",
]

# ── Follow-up patterns ─────────────────────────────────────────────────
_FOLLOW_UP = [
    r"(?:we'll|let's)\s+"
    r"(?:come\s+back|revisit|circle\s+back|check\s+back|return)\s*(?:to)?",
    r"for\s+(?:later|another\s+time|next\s+time|another\s+session|"
    r"the\s+future|another\s+day)",
    r"(?:remind|ping|message)\s+me",
    r"save\s+(?:that|this|it)\s+for",
    r"(?:pending|deferred|on\s+hold|postponed|delayed|tabled)",
    r"(?:tabled|parked|shelved|backburner|back\s+burner)",
    r"(?:next|follow-up|next\s+step)\s+"
    r"(?:step|action|item|task|phase|stage|thing)",
    r"we'll\s+(?:pick|get|come|handle)\s+(?:this|it|that)\s+"
    r"(?:back|up|to|later)",
    r"(?:let's|we'll)\s+(?:leave|put|set)\s+(?:this|it|that)\s+"
    r"(?:for|aside|until)",
    r"(?:future|separate|another)\s+"
    r"(?:PR|branch|ticket|issue|task|session|conversation|time)",
    r"(?:not|don't)\s+(?:now|yet)[,.]\s+(?:let's|we'll|but)",
    r"when\s+(?:i'm|you're|we're)\s+(?:back|ready|free|available)",
    r"(?:TODO|FIXME|HACK|XXX)\b",
    r"(?:deferred|deferring)\s+(?:to|for|until)",
    r"(?:spinning|splitting)\s+(?:off|out|into)",
    r"(?:later|eventually|someday|down\s+the\s+road)\s+(?:tho|though|maybe)",
    r"(?:save|keep)\s+(?:this|that|it)\s+(?:for|until|till)",
    r"(?:can|will)\s+(?:come|get)\s+back\s+to\s+(?:this|that|it)",
    r"(?:set\s+aside|put\s+aside|note\s+for)\s+",
    r"(?:future\s+work|future\s+enhancement|v2|version\s+2|next\s+version)",
    r"(?:we'll|i'll)\s+(?:continue|pick\s+up|resume)\s+(?:this|later|next)",
]

# ── Compiled patterns ──────────────────────────────────────────────────
PATTERNS: Dict[str, List[re.Pattern]] = {
    "decision": [re.compile(p, re.I) for p in _DECISION],
    "commitment": [re.compile(p, re.I) for p in _COMMITMENT],
    "fact": [re.compile(p, re.I) for p in _FACT],
    "preference": [re.compile(p, re.I) for p in _PREFERENCE],
    "correction": [re.compile(p, re.I) for p in _CORRECTION],
    "insight": [re.compile(p, re.I) for p in _INSIGHT],
    "blocker": [re.compile(p, re.I) for p in _BLOCKER],
    "reference": [re.compile(p, re.I) for p in _REFERENCE],
    "follow_up": [re.compile(p, re.I) for p in _FOLLOW_UP],
}


def get_patterns_for_type(event_type: str) -> List[re.Pattern]:
    """Get compiled patterns for a specific event type."""
    return PATTERNS.get(event_type, [])


def compile_all() -> Dict[str, List[re.Pattern]]:
    """Return the compiled pattern dict (already compiled at module level)."""
    return PATTERNS


def pattern_count() -> int:
    """Return total number of individual patterns across all types."""
    return sum(len(ps) for ps in PATTERNS.values())


def type_pattern_counts() -> Dict[str, int]:
    """Return dict of type -> pattern count."""
    return {t: len(ps) for t, ps in sorted(PATTERNS.items())}
