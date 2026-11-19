#!/usr/bin/env python3
"""Range-preserving editor for the Pantheon project-ideas document.

The document is shared with other gods, so this module never re-serialises
it. Every mutation rewrites only the exact line ranges it has to touch and
leaves every other byte alone: tables, ad-hoc bullets, nested headings and
prose inside an entry all round-trip untouched.

Public API works on plain text. Callers own I/O and locking.

    parse(text)                       -> document model
    payload(text)                     -> JSON-safe listing for UIs
    apply_op(text, op)                -> (new_text, result)

`apply_op` is the single funnel used both by the direct (online) path and by
the replay of queued offline operations, so a replayed op behaves exactly
like a live one.
"""

import hashlib
import re
from datetime import date

SECTION_RE = re.compile(r"^##\s+(?P<name>.*\S)\s*$")
ENTRY_RE = re.compile(r"^###\s+(?P<title>.*\S)\s*$")
BULLET_RE = re.compile(r"^[-*]\s+\*\*(?P<key>[^*]+?)\s*:\*\*\s*(?P<value>.*)$")
BLANK_RE = re.compile(r"^\s*$")

DASHES = (" \u2014 ", " \u2013 ", " - ")
DONE_WORDS = ("done", "complete", "completed", "shipped")


# ---------------------------------------------------------------- utilities

def _lines(text):
    return text.split("\n")


def _join(lines):
    return "\n".join(lines)


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def content_sha(text):
    """Stable fingerprint of a whole document, for cheap change detection."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _strip_trailing_blanks(lines, start, end):
    """Index just past the last non-blank line in lines[start:end]."""
    i = end
    while i > start and BLANK_RE.match(lines[i - 1]):
        i -= 1
    return i


def _split_title(raw):
    for dash in DASHES:
        if dash in raw:
            title, _, subtitle = raw.partition(dash)
            return title.strip(), subtitle.strip()
    return raw.strip(), ""


def _today():
    return date.today().isoformat()


# ------------------------------------------------------------------ parsing

def _parse_entry(lines, start, end):
    """Describe one `###` entry occupying lines[start:end]."""
    raw_title = ENTRY_RE.match(lines[start]).group("title")
    title, subtitle = _split_title(raw_title)

    bullets = {}
    order = []
    tail_after_bullet = None
    i = start + 1
    while i < end:
        match = BULLET_RE.match(lines[i])
        if not match:
            i += 1
            continue
        key = match.group("key").strip().lower()
        j = i + 1
        continuation = []
        while j < end and not BULLET_RE.match(lines[j]) and not lines[j].startswith("#"):
            continuation.append(lines[j])
            j += 1
        value_lines = [match.group("value")] + continuation
        while value_lines and BLANK_RE.match(value_lines[-1]):
            value_lines.pop()
        bullets[key] = {
            "key": match.group("key").strip(),
            "value": "\n".join(value_lines).strip(),
            "start": i,
            "end": j,
        }
        order.append(key)
        tail_after_bullet = j
        i = j

    return {
        "start": start,
        "end": end,
        "title": title,
        "subtitle": subtitle,
        "raw_title": raw_title,
        "status": bullets.get("status", {}).get("value", ""),
        "tags": bullets.get("tags", {}).get("value", ""),
        "added": bullets.get("added", {}).get("value", ""),
        "notes": bullets.get("notes", {}).get("value", ""),
        "bullets": bullets,
        "order": order,
        "last_bullet_end": tail_after_bullet if tail_after_bullet is not None else start + 1,
        "_block": _join(lines[start:end]),
    }


def parse(text):
    """Break the document into header, sections and entries."""
    lines = _lines(text)
    section_starts = [i for i, line in enumerate(lines) if SECTION_RE.match(line)]
    header_end = section_starts[0] if section_starts else len(lines)

    sections = []
    for index, start in enumerate(section_starts):
        end = section_starts[index + 1] if index + 1 < len(section_starts) else len(lines)
        name = SECTION_RE.match(lines[start]).group("name")
        entry_starts = [i for i in range(start + 1, end) if ENTRY_RE.match(lines[i])]
        entries = []
        for pos, entry_start in enumerate(entry_starts):
            entry_end = entry_starts[pos + 1] if pos + 1 < len(entry_starts) else end
            entries.append(_parse_entry(lines, entry_start, entry_end))
        sections.append({"name": name, "start": start, "end": end, "entries": entries})

    return {"lines": lines, "header": _join(lines[:header_end]), "sections": sections}


def entry_id(entry, occurrence=0):
    """Id for an entry, derived from its title line only.

    Status, notes and tag edits must not change an entry's id — otherwise a
    queued offline edit would invalidate its own follow-up op. A rename does
    change it, which is correct: the entry is no longer the same thing.
    """
    return "%s:%d" % (_sha(entry["raw_title"]), occurrence)


def _collect_ids(doc):
    found = {}
    seen = {}
    for s_index, section in enumerate(doc["sections"]):
        for e_index, entry in enumerate(section["entries"]):
            key = entry["raw_title"]
            occurrence = seen.get(key, 0)
            seen[key] = occurrence + 1
            found[entry_id(entry, occurrence)] = (s_index, e_index)
    return found


def payload(text, section_filter=None):
    """JSON-safe listing, grouped by section."""
    doc = parse(text)
    sections = []
    statuses = {}
    open_count = 0
    done_count = 0

    for section in doc["sections"]:
        if section_filter is not None and section["name"] != section_filter:
            continue
        entries = []
        seen = {}
        for entry in section["entries"]:
            key = entry["raw_title"]
            occurrence = seen.get(key, 0)
            seen[key] = occurrence + 1
            status = entry["status"] or ""
            if status:
                statuses[status] = statuses.get(status, 0) + 1
            if status.strip().lower() in DONE_WORDS:
                done_count += 1
            else:
                open_count += 1
            entries.append({
                "id": entry_id(entry, occurrence),
                "block_sha": _sha(entry["_block"]),
                "title": entry["title"],
                "subtitle": entry["subtitle"],
                "status": status,
                "tags": entry["tags"],
                "added": entry["added"],
                "notes": entry["notes"][:4000],
                "notes_truncated": len(entry["notes"]) > 4000,
                "lines": entry["end"] - entry["start"],
            })
        sections.append({"name": section["name"], "count": len(entries), "entries": entries})

    return {
        "sections": sections,
        "statuses": sorted(statuses),
        "counts": {
            "sections": len(sections),
            "entries": open_count + done_count,
            "open": open_count,
            "done": done_count,
        },
    }


# ---------------------------------------------------------------- lookups

def _find_section(doc, name):
    wanted = (name or "").strip().lower()
    for section in doc["sections"]:
        if section["name"].strip().lower() == wanted:
            return section
    return None


def _find_entry(doc, ident):
    """Locate an entry by id; fall back to treating the id as a title."""
    ids = _collect_ids(doc)
    if ident in ids:
        s_index, e_index = ids[ident]
        return doc["sections"][s_index]["entries"][e_index], s_index
    wanted = (ident or "").strip().lower()
    for s_index, section in enumerate(doc["sections"]):
        for entry in section["entries"]:
            if entry["title"].strip().lower() == wanted:
                return entry, s_index
    return None, None


def _locate_by_start(doc, s_index, start):
    for entry in doc["sections"][s_index]["entries"]:
        if entry["start"] == start:
            return entry
    raise KeyError("entry moved unexpectedly at line %d" % start)


# --------------------------------------------------------------- line edits

def _replace_range(lines, start, end, replacement):
    return lines[:start] + list(replacement) + lines[end:]


def _block_lines(entry):
    """Entry lines with trailing blanks removed (separators stay behind)."""
    lines = _lines(entry["_block"])
    return lines[:_strip_trailing_blanks(lines, 0, len(lines))]


def _write_bullet(lines, entry, key, value):
    """Rewrite (or create) one bullet in an entry block, in place."""
    bullet = entry["bullets"].get(key.lower())

    if bullet:
        start = bullet["start"]
        end = _strip_trailing_blanks(lines, start, bullet["end"])
        if value is None or value == "":
            return _replace_range(lines, start, end, [])
        parts = str(value).split("\n")
        body = ["- **%s:** %s" % (bullet["key"], parts[0])] + parts[1:]
        return _replace_range(lines, start, end, body)

    if value is None or value == "":
        return lines
    label = "Notes" if key.lower() == "notes" else key.capitalize()
    parts = str(value).split("\n")
    body = ["- **%s:** %s" % (label, parts[0])] + parts[1:]
    at = entry["start"] + 1 if key.lower() == "status" else entry["last_bullet_end"]
    return _replace_range(lines, at, at, body)


def _rename_entry(lines, entry, title, subtitle):
    raw = title.strip()
    if subtitle and subtitle.strip():
        raw = "%s \u2014 %s" % (raw, subtitle.strip())
    return _replace_range(lines, entry["start"], entry["start"] + 1, ["### " + raw])


def _new_entry_lines(title, status, tags, notes, added, subtitle=""):
    raw = title.strip()
    if subtitle and subtitle.strip():
        raw = "%s \u2014 %s" % (raw, subtitle.strip())
    block = ["### " + raw]
    if status:
        block.append("- **Status:** %s" % status)
    if added:
        block.append("- **Added:** %s" % added)
    if tags:
        block.append("- **Tags:** %s" % tags)
    if notes:
        parts = str(notes).split("\n")
        block.append("- **Notes:** %s" % parts[0])
        block.extend(parts[1:])
    return block


# --------------------------------------------------------------- operations

def add_entry(text, section_name, title, status="idea", tags="", notes="",
              added=None, subtitle="", create_section=False):
    doc = parse(text)
    lines = doc["lines"]
    block = _new_entry_lines(title, status, tags, notes, added or _today(), subtitle)
    section = _find_section(doc, section_name)

    if section is None:
        if not create_section:
            raise KeyError("no such section: %s" % section_name)
        at = _strip_trailing_blanks(lines, 0, len(lines))
        addition = [""] + ["## " + section_name.strip(), ""] + block
        lines = _replace_range(lines, at, at, addition)
    else:
        at = _strip_trailing_blanks(lines, section["start"] + 1, section["end"])
        lines = _replace_range(lines, at, at, [""] + block)

    return _join(lines), {"op": "add", "section": section_name, "title": title.strip()}


def edit_entry(text, ident, title=None, status=None, tags=None, notes=None,
               section=None, added=None, subtitle=None):
    doc = parse(text)
    entry, s_index = _find_entry(doc, ident)
    if entry is None:
        raise KeyError("no such entry: %s" % ident)

    original_section = doc["sections"][s_index]["name"]
    anchor = entry["start"]
    lines = doc["lines"]

    if title is not None or subtitle is not None:
        lines = _rename_entry(
            lines, entry,
            entry["title"] if title is None else title,
            entry["subtitle"] if subtitle is None else subtitle,
        )

    # Re-parse before each field write: every write shifts line offsets.
    for key, value in (("status", status), ("tags", tags), ("added", added), ("notes", notes)):
        if value is None:
            continue
        doc = parse(_join(lines))
        entry = _locate_by_start(doc, s_index, anchor)
        lines = _write_bullet(lines, entry, key, value)

    result = {"op": "edit", "id": ident, "section": original_section}

    if section is not None and section.strip().lower() != original_section.strip().lower():
        text2, _ = _move_block(_join(lines), s_index, anchor, to_section=section)
        result["moved_to"] = section
        return text2, result

    return _join(lines), result


def _collapse_blank_run(lines, at):
    """Leave at most one blank line around index `at`.

    Entry blocks own the blank lines that follow them, so removing the last
    entry of a section would otherwise consume the gap before the next
    heading and the document would slowly compact itself.
    """
    start = at
    while start > 0 and BLANK_RE.match(lines[start - 1]):
        start -= 1
    end = at
    while end < len(lines) and BLANK_RE.match(lines[end]):
        end += 1
    if end - start > 1:
        return lines[:start] + [""] + lines[end:]
    return lines


def delete_entry(text, ident):
    doc = parse(text)
    entry, s_index = _find_entry(doc, ident)
    if entry is None:
        raise KeyError("no such entry: %s" % ident)
    lines = _replace_range(doc["lines"], entry["start"], entry["end"], [])
    lines = _collapse_blank_run(lines, entry["start"])
    return _join(lines), {
        "op": "delete",
        "id": ident,
        "section": doc["sections"][s_index]["name"],
        "title": entry["title"],
    }


def _move_block(text, s_index, anchor, direction=None, to_section=None, position=None,
                before_id=None, after_id=None):
    doc = parse(text)
    lines = doc["lines"]
    section = doc["sections"][s_index]
    entry = _locate_by_start(doc, s_index, anchor)
    block = _block_lines(entry)

    if to_section is not None:
        target = _find_section(doc, to_section)
        if target is None:
            raise KeyError("no such section: %s" % to_section)
        if target["name"].strip().lower() == section["name"].strip().lower():
            to_section = None
        else:
            entry_block = entry["_block"]
            ident = entry_id(entry)
            text, _ = delete_entry(text, ident)
            doc2 = parse(text)
            target2 = _find_section(doc2, to_section)
            lines = doc2["lines"]
            if position == "top" and target2["entries"]:
                at = target2["entries"][0]["start"]
                addition = block + [""]
            else:
                at = _strip_trailing_blanks(lines, target2["start"] + 1, target2["end"])
                addition = [""] + block
            lines = _replace_range(lines, at, at, addition)
            return _join(lines), {
                "op": "move", "id": ident, "from": section["name"], "to": to_section,
            }

    entries = section["entries"]
    index = next(i for i, candidate in enumerate(entries) if candidate["start"] == anchor)

    # Anchor-based placement: a filtered or concurrently-edited list makes raw
    # indices unreliable, but "sit next to this entry" survives both.
    if before_id is not None or after_id is not None:
        neighbour_id = before_id if before_id is not None else after_id
        neighbour, neighbour_section = _find_entry(doc, neighbour_id)
        if neighbour is None:
            raise KeyError("no such neighbour entry: %s" % neighbour_id)
        if neighbour_section != s_index:
            raise ValueError("neighbour entry is in another section")
        if neighbour["start"] == anchor:
            return text, {"op": "move", "id": entry_id(entry), "moved": False,
                          "section": section["name"]}
        neighbour_index = next(i for i, candidate in enumerate(entries)
                               if candidate["start"] == neighbour["start"])
        # Removing the dragged entry first shifts the neighbour down when it
        # sits below it, so the insertion point is computed post-removal.
        neighbour_after = neighbour_index - 1 if index < neighbour_index else neighbour_index
        new_index = neighbour_after if before_id is not None else neighbour_after + 1
        if new_index == index:
            return text, {"op": "move", "id": entry_id(entry), "moved": False,
                          "section": section["name"]}
        return _reorder(doc, entries, new_index, entry, index, section)

    if direction == "top":
        new_index = 0
    elif direction == "bottom":
        new_index = len(entries) - 1
    elif direction == "up":
        new_index = max(0, index - 1)
    elif direction == "down":
        new_index = min(len(entries) - 1, index + 1)
    else:
        raise ValueError("direction must be up, down, top or bottom")

    if new_index == index:
        return text, {"op": "move", "id": entry_id(entry), "moved": False,
                      "section": section["name"]}
    return _reorder(doc, entries, new_index, entry, index, section)


def _reorder(doc, entries, new_index, entry, index, section):
    """Rewrite a section's entry block in a new order, preserving spacing."""
    ordered = list(entries)
    ordered.insert(max(0, min(len(ordered), new_index)), ordered.pop(index))

    region_start = entries[0]["start"]
    region_end = entries[-1]["end"]

    # Blank lines that trailed the section's last entry stay trailing, so the
    # gap before the next heading survives the reorder.
    last_block = _lines(entries[-1]["_block"])
    tail_blanks = len(last_block) - _strip_trailing_blanks(last_block, 0, len(last_block))

    rebuilt = []
    for slot, candidate in enumerate(ordered):
        rebuilt.extend(_block_lines(candidate))
        if slot != len(ordered) - 1:
            rebuilt.append("")
    rebuilt.extend([""] * tail_blanks)

    lines = _replace_range(doc["lines"], region_start, region_end, rebuilt)
    return _join(lines), {
        "op": "move", "id": entry_id(entry), "moved": True, "from_index": index,
        "to_index": new_index, "section": section["name"],
    }


def move_entry(text, ident, direction=None, to_section=None, position=None,
               before_id=None, after_id=None):
    """Reorder an entry within its section, or relocate it to another one."""
    doc = parse(text)
    entry, s_index = _find_entry(doc, ident)
    if entry is None:
        raise KeyError("no such entry: %s" % ident)
    return _move_block(text, s_index, entry["start"], direction=direction,
                       to_section=to_section, position=position,
                       before_id=before_id, after_id=after_id)


def add_section(text, name, after=None):
    doc = parse(text)
    lines = doc["lines"]
    if _find_section(doc, name) is not None:
        raise KeyError("section already exists: %s" % name)
    heading = ["## " + name.strip(), ""]
    anchor = _find_section(doc, after) if after else None
    if anchor is not None:
        at = _strip_trailing_blanks(lines, anchor["start"] + 1, anchor["end"])
    else:
        at = _strip_trailing_blanks(lines, 0, len(lines))
    lines = _replace_range(lines, at, at, [""] + heading)
    return _join(lines), {"op": "section-add", "name": name.strip()}


def rename_section(text, name, new_name):
    doc = parse(text)
    section = _find_section(doc, name)
    if section is None:
        raise KeyError("no such section: %s" % name)
    lines = _replace_range(doc["lines"], section["start"], section["start"] + 1,
                           ["## " + new_name.strip()])
    return _join(lines), {"op": "section-rename", "name": name, "new_name": new_name.strip()}


def delete_section(text, name, force=False):
    doc = parse(text)
    section = _find_section(doc, name)
    if section is None:
        raise KeyError("no such section: %s" % name)
    if section["entries"] and not force:
        raise ValueError("section not empty: %s (%d entries)" % (name, len(section["entries"])))
    lines = _replace_range(doc["lines"], section["start"], section["end"], [])
    return _join(lines), {"op": "section-delete", "name": name,
                          "entries_removed": len(section["entries"])}


def cycle_status(text, ident, order):
    """Advance an entry's status through a caller-supplied cycle."""
    doc = parse(text)
    entry, _ = _find_entry(doc, ident)
    if entry is None:
        raise KeyError("no such entry: %s" % ident)
    current = entry["status"].strip().lower()
    lowered = [value.lower() for value in order]
    nxt = order[(lowered.index(current) + 1) % len(order)] if current in lowered else order[0]
    return edit_entry(text, ident, status=nxt)


# -------------------------------------------------------------- op dispatch

OP_HANDLERS = {
    "add": lambda text, op: add_entry(
        text, op["section"], op["title"], status=op.get("status", "idea"),
        tags=op.get("tags", ""), notes=op.get("notes", ""),
        added=op.get("added"), subtitle=op.get("subtitle", ""),
        create_section=bool(op.get("create_section"))),
    "edit": lambda text, op: edit_entry(
        text, op["id"], title=op.get("title"), status=op.get("status"),
        tags=op.get("tags"), notes=op.get("notes"), section=op.get("section"),
        added=op.get("added")),
    "delete": lambda text, op: delete_entry(text, op["id"]),
    "move": lambda text, op: move_entry(
        text, op["id"], direction=op.get("direction"),
        to_section=op.get("to_section"), position=op.get("position"),
        before_id=op.get("before_id"), after_id=op.get("after_id")),
    "section-add": lambda text, op: add_section(text, op["name"], after=op.get("after")),
    "section-rename": lambda text, op: rename_section(text, op["name"], op["new_name"]),
    "section-delete": lambda text, op: delete_section(text, op["name"], force=bool(op.get("force"))),
}


def apply_op(text, op):
    """Apply one operation dict. Raises KeyError/ValueError on bad targets."""
    handler = OP_HANDLERS.get(op.get("op"))
    if handler is None:
        raise ValueError("unknown op: %r" % op.get("op"))
    return handler(text, op)
