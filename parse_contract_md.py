"""Create viewer-ready contract JSON from local Markdown without an external API.

The parser is deliberately conservative: it recognizes printed headings and tables,
keeps all remaining text, and records ambiguities for source review.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from pathlib import Path

TOP = re.compile(r"^(?:#{1,6}\s+)?(ARTICLE|SCHEDULE|ANNEX|APPENDIX|CHAPTER)\s+([IVXLCDM]+|\d+|[A-Z])\s*[-–:.]?\s*(.*)$")
BOLD_TOP = re.compile(r"^\*\*(SCHEDULE|ANNEX|APPENDIX)\s+([IVXLCDM]+|\d+|[A-Z])\*\*$")
SECTION = re.compile(r"^#{1,6}\s+(\d+(?:\.\d+){1,6})\.?\s+(.+)$")
PLAIN_SECTION = re.compile(r"^(\d+\.\d+)\.?\s+(.+)$")
ITEM = re.compile(r"^(\d+(?:\.\d+){1,6})\.?\s+(.+)$")
PAGE_TAG = re.compile(r"\s*\(PDF pp?\.\s*([\d, -]+)\)\s*$", re.I)
PAGE_FOOTER = re.compile(r"(?:\|\s*)?Page\s+(\d+)\s*$", re.I)
GLOSSARY = re.compile(r"\b(?:defined\s+terms|definitions)\b", re.I)
SEPARATOR = re.compile(r"^:?-{3,}:?$")


def roman(value: int) -> str:
    out = ""
    for number, symbol in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"),
                           (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"),
                           (5, "V"), (4, "IV"), (1, "I")):
        while value >= number:
            out += symbol
            value -= number
    return out


def new_node(nc: str, label: str, title: str, level: int, parent: str | None = None) -> dict:
    return {"nc": nc, "id": label, "title": title, "level": level,
            "is_cr": False, "content": "", "paragraphs": [], "references": [],
            "named_items": [], "sub_clauses": [], "parent_nc": parent}


def paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", text.strip()) if part.strip()]


def table_cells(line: str) -> list[str]:
    return [cell.strip().replace("<br>", "\n") for cell in line.strip().strip("|").split("|")]


def table_html(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    count = max(map(len, rows))
    result = ['<table class="schedule-table"><thead><tr>']
    result += [f"<th>{html.escape(cell).replace(chr(10), '<br>')}</th>" for cell in rows[0]]
    result.append("</tr></thead><tbody>")
    for row in rows[1:]:
        result.append("<tr>")
        result += [f"<td>{html.escape(cell).replace(chr(10), '<br>')}</td>" for cell in row + [""] * (count - len(row))]
        result.append("</tr>")
    result.append("</tbody></table>")
    return "".join(result)


def parse_markdown(markdown: str, title: str, source_file: str) -> dict:
    clauses: list[dict] = []
    preamble: list[str] = []
    definitions: dict[str, str] = {}
    preamble_tables: list[str] = []
    warnings: list[str] = []
    current_top: dict | None = None
    current_section: dict | None = None
    current_item: dict | None = None
    table_lines: list[str] = []
    seen: dict[str, int] = {}
    duplicates: dict[str, list[str]] = {}
    page_hint: int | None = 1 if source_file.lower().endswith(".pdf") else None
    waiting_for_schedule_title = False

    def unique(printed: str) -> str:
        seen[printed] = seen.get(printed, 0) + 1
        key = printed if seen[printed] == 1 else f"{printed}~{seen[printed]}"
        if seen[printed] > 1:
            duplicates.setdefault(printed, [printed]).append(key)
            warnings.append(f"Repeated printed clause number {printed}; kept as {key}.")
        return key

    def target() -> dict | None:
        return current_item or current_section or current_top

    def add_text(line: str) -> None:
        node = target()
        if node is None:
            preamble.append(line)
        else:
            if not node["content"] or node["content"].endswith("\n"):
                node["content"] += line
            elif re.match(r"^(?:\(?[a-z]\)|[a-z]\.)\s+", line):
                node["content"] += "\n" + line
            else:
                node["content"] += " " + line
            if page_hint is not None and page_hint not in node.setdefault("source_pages", []):
                node["source_pages"].append(page_hint)

    def flush_table() -> None:
        nonlocal table_lines, current_top, current_section, current_item
        if not table_lines:
            return
        parsed = [table_cells(line) for line in table_lines]
        parsed = [row for row in parsed if not all(SEPARATOR.fullmatch(c.replace(" ", "")) for c in row)]
        table_lines = []
        if not parsed:
            return
        width = len(parsed[0])
        if any(len(row) != width for row in parsed):
            warnings.append(f"Table with {len(parsed)} rows has inconsistent columns near {target().get('id') if target() else 'preamble'}.")
        headers = [re.sub(r"[*_`]", "", cell).strip().lower() for cell in parsed[0]]
        if len(headers) >= 3 and headers[0].startswith("clause no") and "particular" in headers[1] and "description" in headers[2]:
            for row in parsed[1:]:
                if len(row) < 3:
                    continue
                printed = re.sub(r"[*_`]", "", row[0]).strip().rstrip(".")
                if not printed.isdigit():
                    continue
                heading = re.sub(r"[*_`]", "", row[1]).strip()
                body = " | ".join(row[2:]).strip()
                clause = new_node(unique(printed), f"Clause {printed}", heading, 2)
                clauses.append(clause)
                parts = list(re.finditer(r"(?:(?<=  )|(?<=\n)|^)(\d+\.\d+(?:\.\d+)?)(?:\.)?\s+", body))
                for i, match in enumerate(parts):
                    start = match.end()
                    end = parts[i + 1].start() if i + 1 < len(parts) else len(body)
                    item_body = body[start:end].strip()
                    number = match.group(1)
                    key = unique(number)
                    clause["named_items"].append({"nc": key, "title": "Clause", "display_nc": number,
                                                  "content": item_body, "paragraphs": paragraphs(item_body),
                                                  "parent_nc": clause["nc"]})
                if parts:
                    clause["content"] = body[:parts[0].start()].strip()
                else:
                    clause["content"] = body
            current_top = current_section = current_item = None
            return
        node = current_section or current_top
        if node is None:
            preamble_tables.append(table_html(parsed))
            preamble.extend("\t".join(row) for row in parsed)
            return
        glossary = current_section is not None and GLOSSARY.search(current_section.get("title", ""))
        if glossary and width >= 2 and len(parsed) > 1 and "term" in parsed[0][0].lower():
            for row in parsed[1:]:
                term = row[0].strip()
                body = " ".join(row[1:]).strip()
                if term and body:
                    definitions[term] = body
                    item = {"nc": f"def-{len(definitions)}", "title": term,
                            "display_nc": "", "content": body, "paragraphs": paragraphs(body)}
                    node["named_items"].append(item)
            return
        node.setdefault("tables_html", []).append(table_html(parsed))
        # Search can still find table text even when the viewer renders the table as HTML.
        node["table_search_text"] = (node.get("table_search_text", "") + "\n" +
                                     "\n".join("\t".join(row) for row in parsed)).strip()
        if page_hint is not None and page_hint not in node.setdefault("source_pages", []):
            node["source_pages"].append(page_hint)

    for raw in markdown.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            table_lines.append(stripped)
            continue
        flush_table()
        if not stripped:
            if target() is None:
                preamble.append("")
            elif target()["content"] and not target()["content"].endswith("\n\n"):
                target()["content"] += "\n\n"
            continue
        footer = PAGE_FOOTER.search(stripped)
        if footer and ("|" in stripped or stripped.lower().startswith("page ")):
            page_hint = int(footer.group(1)) + 1
            continue
        if stripped.startswith("<!--"):
            add_text(stripped)
            continue
        if waiting_for_schedule_title and stripped.startswith("**") and stripped.endswith("**") and current_top:
            current_top["title"] = stripped.strip("*").strip()
            waiting_for_schedule_title = False
            continue
        match = TOP.fullmatch(stripped)
        bold_match = BOLD_TOP.fullmatch(stripped)
        if not match and bold_match:
            match = bold_match
            waiting_for_schedule_title = True
        if match:
            if bold_match:
                kind, number = match.groups()
                heading = ""
            else:
                kind, number, heading = match.groups()
            heading = heading.strip()
            page = PAGE_TAG.search(heading)
            if page:
                heading = heading[:page.start()].rstrip()
            if kind == "SCHEDULE":
                display = f"Schedule {number}"
                nc = f"Sch-{roman(int(number)) if number.isdigit() else number}"
            else:
                display = f"{kind.title()} {number}"
                nc = number if kind == "ARTICLE" else f"{kind.title()}-{number}"
            nc = unique(nc)
            current_top = new_node(nc, display, heading or display, 2)
            if page:
                current_top["source_pages"] = [int(n) for n in re.findall(r"\d+", page.group(1))]
            elif page_hint is not None:
                current_top["source_pages"] = [page_hint]
            clauses.append(current_top)
            current_section = current_item = None
            continue
        match = SECTION.fullmatch(stripped)
        if not match:
            plain = PLAIN_SECTION.fullmatch(stripped)
            if plain and len(plain.group(2)) <= 110 and not plain.group(2).rstrip().endswith((".", ";")):
                match = plain
        if match:
            printed, heading = match.groups()
            if current_top is None:
                current_top = new_node(unique("Document"), "Document", title, 2)
                clauses.append(current_top)
            nc = unique(printed)
            current_section = new_node(nc, printed, heading.strip(), 3, current_top["nc"])
            if page_hint is not None:
                current_section["source_pages"] = [page_hint]
            if nc != printed:
                current_section["display_nc"] = printed
            current_top["sub_clauses"].append(current_section)
            current_item = None
            continue
        match = ITEM.fullmatch(stripped)
        if match and (current_top is not None):
            printed, body = match.groups()
            nc = unique(printed)
            if current_section is None:
                parent = current_top
            else:
                parent = current_section
            current_item = {"nc": nc, "title": "Clause", "display_nc": printed,
                            "content": body.strip(), "paragraphs": [], "parent_nc": parent["nc"]}
            if page_hint is not None:
                current_item["source_pages"] = [page_hint]
            parent["named_items"].append(current_item)
            continue
        # Unnumbered headings are kept inside the active section instead of lost.
        if stripped.startswith("#"):
            stripped = re.sub(r"^#{1,6}\s*", "", stripped)
        add_text(stripped)
    flush_table()

    if not clauses:
        fallback = new_node("Document", "Document", title, 2)
        fallback["content"] = "\n".join(preamble).strip()
        clauses.append(fallback)
        preamble = []
        warnings.append("No formal numbered heading found; document is available as one reading section.")

    index: dict[str, dict] = {}
    sections = named_items = 0
    def visit(node: dict) -> None:
        nonlocal sections, named_items
        node["content"] = node.get("content", "").strip()
        node["paragraphs"] = paragraphs(node["content"])
        index[node["nc"]] = {k: v for k, v in node.items() if k not in ("sub_clauses", "named_items", "tables_html")}
        if "tables_html" in node:
            index[node["nc"]]["tables_html"] = node["tables_html"]
        for section in node.get("sub_clauses", []):
            sections += 1
            visit(section)
        for item in node.get("named_items", []):
            named_items += 1
            item["content"] = item.get("content", "").strip()
            item["paragraphs"] = paragraphs(item["content"])
            index[item["nc"]] = dict(item)
    for clause in clauses:
        visit(clause)

    return {"title": title, "source_file": source_file, "format": "pdf" if source_file.lower().endswith(".pdf") else "doc",
            "preamble": "\n".join(preamble).strip(), "definitions": definitions,
            "_preamble_tables_html": preamble_tables,
            "clauses": clauses, "nc_index": index, "_duplicate_refs": duplicates,
            "_parse_warnings": warnings, "_warning_badge": "⚠ Check source" if warnings else "",
            "_stats": {"clauses": len(clauses), "sections": sections, "named_items": named_items,
                       "definitions": len(definitions)}}


def extract_pdf_glossary(source_path: Path) -> tuple[dict[str, str], dict[str, int]]:
    """Read a two-column Term/Definition table from a text-based PDF quickly."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(source_path), strict=False)
    except Exception:
        return {}, {}
    found: dict[str, str] = {}
    pages: dict[str, int] = {}
    active = False
    for page_number, page in enumerate(reader.pages, 1):
        lines = (page.extract_text(extraction_mode="layout") or "").splitlines()
        header = next((i for i, line in enumerate(lines)
                       if re.match(r"^\s*Term\s{2,}Definition\s*$", line, re.I)), None)
        if header is None:
            if active:
                break
            continue
        active = True
        split_at = lines[header].lower().find("definition")
        block: list[str] = []

        def commit() -> None:
            nonlocal block
            if not block:
                return
            left: list[str] = []
            right: list[str] = []
            for row in block:
                term_part = re.sub(r"\s+", " ", row[:split_at]).strip()
                body_part = re.sub(r"\s+", " ", row[split_at:]).strip()
                if term_part:
                    left.append(term_part)
                if body_part:
                    right.append(body_part)
            term = " ".join(left).strip()
            body = " ".join(right).strip()
            stray_article = re.match(r"^(.{4,}?)\s+(an|a|the)$", term, re.I)
            if stray_article and body:
                term = stray_article.group(1)
                body = stray_article.group(2) + " " + body
            if term and body:
                found[term] = body
                pages[term] = page_number
            elif body and found:
                last = next(reversed(found))
                found[last] += " " + body
            block = []

        for line in lines[header + 1:]:
            if PAGE_FOOTER.search(line.strip()) and "|" in line:
                commit()
                break
            if re.match(r"^\s*\d+\.\d+\s+[A-Z]", line):
                commit()
                return found, pages
            if not line.strip():
                commit()
            else:
                block.append(line)
        commit()
    return found, pages


def refresh_index(data: dict) -> None:
    index: dict[str, dict] = {}
    sections = named = 0
    def add(node: dict) -> None:
        nonlocal sections, named
        index[node["nc"]] = {k: v for k, v in node.items() if k not in ("sub_clauses", "named_items")}
        for child in node.get("sub_clauses", []):
            sections += 1
            add(child)
        for child in node.get("named_items", []):
            named += 1
            add(child)
    for node in data["clauses"]:
        add(node)
    data["nc_index"] = index
    data["_stats"] = {"clauses": len(data["clauses"]), "sections": sections,
                      "named_items": named, "definitions": len(data["definitions"])}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-file", required=True, help="Relative source link from output folder")
    parser.add_argument("--source-path", type=Path, required=True, help="Actual source for SHA-256 identity")
    parser.add_argument("--supplement", type=Path, help="Reviewed schedule Markdown to replace matching schedules")
    args = parser.parse_args()
    markdown = args.markdown.read_text(encoding="utf-8-sig")
    data = parse_markdown(markdown, args.source_path.stem, args.source_file)
    if args.source_path.suffix.lower() == ".pdf" and not data["definitions"]:
        glossary, glossary_pages = extract_pdf_glossary(args.source_path)
        if glossary:
            data["definitions"] = glossary
            definition_article = next((node for node in data["clauses"]
                                       if GLOSSARY.search(node.get("title", "")) and node["id"].lower().startswith("article ")), None)
            if definition_article:
                section = new_node("1.1", "1.1", "Defined Terms", 3, definition_article["nc"])
                section["source_pages"] = sorted(set(glossary_pages.values()))
                section["named_items"] = [
                    {"nc": f"def-{i}", "title": term, "display_nc": f"PDF p. {glossary_pages[term]}",
                     "content": body, "paragraphs": paragraphs(body), "source_pages": [glossary_pages[term]],
                     "parent_nc": section["nc"]}
                    for i, (term, body) in enumerate(glossary.items(), 1)
                ]
                definition_article["sub_clauses"].insert(0, section)
                data["_definition_sources"] = {term: f"PDF p. {number}" for term, number in glossary_pages.items()}
    if args.supplement:
        extra = parse_markdown(args.supplement.read_text(encoding="utf-8-sig"), args.source_path.stem, args.source_file)
        replacements = {node["id"].lower(): node for node in extra["clauses"] if node["id"].lower().startswith("schedule ")}
        if replacements:
            first_schedule = replacements.get("schedule 1")
            if first_schedule and extra.get("_preamble_tables_html"):
                first_schedule["tables_html"] = extra["_preamble_tables_html"] + first_schedule.get("tables_html", [])
            data["clauses"] = [replacements.pop(node["id"].lower(), node) for node in data["clauses"]]
            data["clauses"].extend(replacements.values())
            data["_parse_warnings"].append("Schedule tables use reviewed supplement Markdown.")
    refresh_index(data)
    with args.source_path.open("rb") as source_stream:
        source_hash = hashlib.file_digest(source_stream, "sha256").hexdigest()
    data["_source_metadata"] = {"source_sha256": source_hash,
                                "parser": "Rev2.2 local Markdown parser", "markdown_file": args.markdown.name,
                                "supplement": str(args.supplement) if args.supplement else None}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"JSON={args.output.resolve()}")
    print(f"ARTICLES={len(data['clauses'])} SECTIONS={data['_stats']['sections']} ITEMS={data['_stats']['named_items']}")
    print(f"WARNINGS={len(data['_parse_warnings'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
