"""26 CFR (Treasury Regulations) parser.

Parses the eCFR XML format used by the National Archives Office of the
Federal Register, downloaded from ecfr.gov's bulk API.

The schema is:
    ECFR > DIV1 (title) > DIV3 (chapter) > DIV4 (subchapter)
    > DIV5 (part) > DIV6 (subpart) > DIV8 (section)

Each DIV8 with TYPE="SECTION" is one regulation section. Section number
is in the N attribute (e.g., "1.1-1", "1.162-1", "20.2031-1").

Each section becomes one record:
    {
        "section_num": "1.162-1",
        "citation": "26 CFR § 1.162-1",
        "heading": "Business expenses",
        "text": "...",
        "parent_title": "26",
        "parent_chapter": "1",
        "parent_subchapter": "A",
        "parent_part": "1",
        "parent_subpart": "A",
        "source_url": "https://www.ecfr.gov/current/title-26/section-1.162-1",
        "issue_date": "2026-06-30",
        "fetched_at": "2026-07-02",
    }
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from lxml import etree


@dataclass
class CFRSection:
    """One section of the Treasury Regulations (26 CFR)."""

    section_num: str
    citation: str
    heading: str
    text: str
    parent_title: str
    parent_chapter: str
    parent_subchapter: str | None
    parent_part: str
    parent_subpart: str | None
    source_url: str
    issue_date: str
    fetched_at: str

    def to_dict(self) -> dict:
        return asdict(self)


def text_content(elem) -> str:
    """Extract all text content from a section element.

    We concatenate <P> elements (paragraphs) and <HEAD> (the section
    heading). Skips <EXTRACT> and <FP> (footnotes/table extracts) since
    those are reference material rather than the regulation text itself.
    """
    parts: list[str] = []
    head = elem.find("HEAD")
    if head is not None:
        htext = "".join(head.itertext()).strip()
        if htext:
            parts.append(htext)
    for p in elem.findall("P"):
        text = "".join(p.itertext()).strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def parse_cfr_xml(xml_path: Path, issue_date: str = "2026-06-30") -> Iterator[CFRSection]:
    """Stream-parse 26 CFR XML and yield CFRSection records.

    We walk the tree and emit one record per DIV8 with TYPE="SECTION".
    The N attribute on each ancestor DIV gives us the parent hierarchy.
    """
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    tree = etree.parse(str(xml_path))
    root = tree.getroot()

    # Walk all DIV8 sections
    for section in root.findall(".//DIV8"):
        if section.get("TYPE") != "SECTION":
            continue

        section_num = section.get("N", "").strip()
        if not section_num:
            continue

        # Walk up parents to get hierarchy
        parent_title = "26"
        parent_chapter = ""
        parent_subchapter = None
        parent_part = ""
        parent_subpart = None
        p = section.getparent()
        while p is not None:
            tag = p.tag
            n = p.get("N", "")
            typ = p.get("TYPE", "")
            if tag == "DIV5" and typ == "PART":
                parent_part = n
            elif tag == "DIV6" and typ == "SUBPART":
                parent_subpart = n
            elif tag == "DIV4" and typ == "SUBCHAP":
                parent_subchapter = n
            elif tag == "DIV3" and typ == "CHAPTER":
                parent_chapter = n
            p = p.getparent()

        # Get heading from HEAD element
        head = section.find("HEAD")
        heading = ""
        if head is not None:
            heading = "".join(head.itertext()).strip()
            # Strip leading "§<num>. " from heading
            heading = re.sub(r"^§\s*[0-9A-Za-z.\-]+\s*", "", heading).strip()

        # Get full text
        text = text_content(section)

        # Build citation and source URL
        citation = f"26 CFR § {section_num}"
        # The source URL pattern: eCFR uses hyphens, not dots
        url_section = section_num.replace(".", "-").replace("--", "-")
        source_url = f"https://www.ecfr.gov/current/title-26/section-{url_section}"

        yield CFRSection(
            section_num=section_num,
            citation=citation,
            heading=heading,
            text=text,
            parent_title=parent_title,
            parent_chapter=parent_chapter,
            parent_subchapter=parent_subchapter,
            parent_part=parent_part,
            parent_subpart=parent_subpart,
            source_url=source_url,
            issue_date=issue_date,
            fetched_at=fetched_at,
        )


def parse_cfr_and_dump(xml_path: Path, out_path: Path, issue_date: str = "2026-06-30") -> int:
    """Parse the 26 CFR XML and write sections to a JSONL file.

    Returns the number of sections written.
    """
    count = 0
    with open(out_path, "w") as out:
        for section in parse_cfr_xml(xml_path, issue_date):
            out.write(json.dumps(section.to_dict()) + "\n")
            count += 1
            if count % 1000 == 0:
                print(f"  parsed {count} sections...", flush=True)
    return count


if __name__ == "__main__":
    import sys

    xml = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/cfr_title26.xml")
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("data/cfr_sections.jsonl")
    issue = sys.argv[3] if len(sys.argv) > 3 else "2026-06-30"

    print(f"Parsing {xml} (issue {issue}) -> {out}")
    n = parse_cfr_and_dump(xml, out, issue)
    print(f"Done. {n} sections written to {out}.")
