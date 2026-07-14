"""IRC Title 26 parser.

Parses the USLM (United States Legislative Markup) XML format used by the
US House Office of Law Revision Counsel at uscode.house.gov.

Each section becomes one record:
    {
        "section_num": "199A",
        "citation": "26 U.S.C. § 199A",
        "heading": "Qualified business income deduction",
        "text": "<full text content>",
        "parent_subtitle": "A",
        "parent_chapter": "1",
        "source_url": "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title26-section199A",
        "release_point": "119-100",
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


# USLM namespace — the actual URI, not the prefix
USLM_URI = "http://xml.house.gov/schemas/uslm/1.0"
USLM_SECTION_TAG = f"{{{USLM_URI}}}section"


@dataclass
class IRCSection:
    """One section of the Internal Revenue Code."""

    section_num: str
    citation: str
    heading: str
    text: str
    parent_subtitle: str | None
    parent_chapter: str | None
    source_url: str
    release_point: str
    fetched_at: str

    def to_dict(self) -> dict:
        return asdict(self)


def strip_ns(tag: str) -> str:
    """Strip XML namespace from a tag name."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def text_content(elem) -> str:
    """Extract all text content from an element and its children, concatenated."""
    if elem is None:
        return ""
    parts = []
    for t in elem.iter():
        tag = strip_ns(t.tag)
        if tag in ("p", "header", "heading", "chapeau", "text", "quoted-block", "table"):
            text = "".join(t.itertext()).strip()
            if text:
                parts.append(text)
    if not parts:
        return "".join(elem.itertext()).strip()
    return "\n\n".join(parts)


def parse_irc_xml(xml_path: Path, release_point: str = "119-100") -> Iterator[IRCSection]:
    """Stream-parse the IRC XML and yield IRCSection records.

    The USLM format nests sections inside:
        title > subtitle > chapter > subchapter > part > section

    We walk the tree and emit one record per <section> element.
    """
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Use iterparse for memory efficiency on a 55MB file
    context = etree.iterparse(str(xml_path), events=("end",), tag=USLM_SECTION_TAG)
    print(f"  iterparse tag: {USLM_SECTION_TAG}", flush=True)

    subtitle = ""
    chapter = ""
    subchapter = ""
    part = ""

    for event, elem in context:
        # Walk up parents to find subtitle/chapter/subchapter/part
        parent = elem.getparent()
        path = []
        while parent is not None:
            path.append(parent)
            parent = parent.getparent()

        # Reset on each section emission (path is local)
        local_subtitle = ""
        local_chapter = ""
        local_subchapter = ""
        local_part = ""
        for p in path:
            tag = strip_ns(p.tag)
            if tag == "subtitle":
                local_subtitle = "".join(p.itertext()).strip().split("\n")[0][:30] or p.get("id", "")
            elif tag == "chapter":
                local_chapter = p.get("id", "")
            elif tag == "subchapter":
                local_subchapter = p.get("id", "")
            elif tag == "part":
                local_part = p.get("id", "")

        # Get section identifier — the identifier attr is "/us/usc/t26/s1"
        identifier = elem.get("identifier", "").strip()
        if identifier:
            # Extract section number from "/us/usc/t26/s<NUM>"
            m = re.search(r"/s(.+)$", identifier)
            if m:
                section_num = m.group(1)
            else:
                section_num = identifier
        else:
            section_num = ""

        if not section_num:
            # Fallback: try the <num> child element
            num_elem = elem.find(f"{{{USLM_URI}}}num")
            if num_elem is not None:
                section_num = "".join(num_elem.itertext()).strip()

        if not section_num:
            # Last resort: try the <header> text
            header = elem.find(f"{{{USLM_URI}}}header")
            if header is not None:
                htext = "".join(header.itertext()).strip()
                m = re.match(r"§\s*([0-9A-Za-z\-]+)\.\s*(.*)", htext)
                if m:
                    section_num = m.group(1)
                else:
                    section_num = htext[:50]

        # Get heading
        heading = ""
        header = elem.find(f"{{{USLM_URI}}}header")
        if header is not None:
            htext = "".join(header.itertext()).strip()
            # Strip leading "§<num>. " if present
            htext = re.sub(r"^§\s*[0-9A-Za-z\-]+\.\s*", "", htext)
            heading = htext

        # Get text content (everything in the section minus the header)
        text = text_content(elem)
        if header is not None and text.startswith(heading):
            text = text[len(heading):].strip()
        # Also strip leading "§<num>. " from the text
        text = re.sub(r"^§\s*[0-9A-Za-z\-]+\.\s*", "", text).strip()

        # Build citation
        citation = f"26 U.S.C. § {section_num}"
        source_url = (
            f"https://uscode.house.gov/view.xhtml"
            f"?req=granuleid:USC-prelim-title26-section{section_num}"
        )

        yield IRCSection(
            section_num=section_num,
            citation=citation,
            heading=heading,
            text=text,
            parent_subtitle=local_subtitle or None,
            parent_chapter=local_chapter or None,
            source_url=source_url,
            release_point=release_point,
            fetched_at=fetched_at,
        )

        # Free memory
        elem.clear()
        while elem.getprevious() is not None:
            del elem.getparent()[0]


def parse_and_dump(xml_path: Path, out_path: Path, release_point: str = "119-100") -> int:
    """Parse the IRC XML and write sections to a JSONL file.

    Returns the number of sections written.
    """
    count = 0
    with open(out_path, "w") as out:
        for section in parse_irc_xml(xml_path, release_point):
            out.write(json.dumps(section.to_dict()) + "\n")
            count += 1
            if count % 500 == 0:
                print(f"  parsed {count} sections...")
    return count


if __name__ == "__main__":
    import sys

    xml = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/usc26.xml")
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("data/irc_sections.jsonl")
    release = sys.argv[3] if len(sys.argv) > 3 else "119-100"

    print(f"Parsing {xml} (release {release}) -> {out}")
    n = parse_and_dump(xml, out, release)
    print(f"Done. {n} sections written to {out}.")
