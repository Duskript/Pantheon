"""Phase 0 ingest scripts — load tax data into the Athenaeum.

This package contains the parsers and loaders that turn raw US government
data (IRC Title 26 from uscode.house.gov, 26 CFR from ecfr.gov, Tax Court
opinions from CourtListener) into structured records ready to be loaded
into the Codex-Tax-US Athenaeum codex.

Modules:
    - irc: USLM-format IRC XML parser. Emits IRCSection records (~2,276 sections).
    - cfr: eCFR-format Treasury Regulations XML parser. Emits CFRSection records (~6,154 sections).
    - codex: Loads parsed records into the Athenaeum as Codex-Tax-US markdown documents.

Each parser is memory-efficient (uses iterparse / iter for streaming) so
we can handle 100+ MB of source XML without blowing up the heap.
"""

from .irc import IRCSection, parse_irc_xml, parse_and_dump
from .cfr import CFRSection, parse_cfr_xml, parse_cfr_and_dump
from .codex import load_codex, CODEX_NAME

__all__ = [
    "IRCSection",
    "parse_irc_xml",
    "parse_and_dump",
    "CFRSection",
    "parse_cfr_xml",
    "parse_cfr_and_dump",
    "load_codex",
    "CODEX_NAME",
]
