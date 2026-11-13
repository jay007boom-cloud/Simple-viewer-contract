#!/usr/bin/env python3
"""Build a contract HTML viewer with structured definitions and clause navigation."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


DEFINITION_TITLE = re.compile(r"\b(?:defined\s+terms?|definitions)\b", re.IGNORECASE)
CLAUSE_NUMBER = re.compile(r"^\d+(?:\.\d+){2,}$")


def section_has_definitions(section: dict[str, Any]) -> bool:
    return bool(DEFINITION_TITLE.search(str(section.get("title") or "")))


def walk_sections(items: list[dict[str, Any]]):
    for item in items:
        if not isinstance(item, dict):
            continue
        yield item
        children = item.get("sub_clauses") or []
        if isinstance(children, list):
            yield from walk_sections(children)


def definitions_from_named_items(data: dict[str, Any]) -> dict[str, str]:
    found: dict[str, str] = {}
    clauses = data.get("clauses") or []
    for clause in clauses:
        if not isinstance(clause, dict):
            continue
        sections = list(walk_sections(clause.get("sub_clauses") or []))
        for section in sections:
            if not section_has_definitions(section):
                continue
            for item in section.get("named_items") or []:
                if not isinstance(item, dict):
                    continue
                term = str(item.get("title") or item.get("label") or "").strip()
                body = item.get("content")
                if not body and isinstance(item.get("paragraphs"), list):
                    body = "\n".join(str(part) for part in item["paragraphs"] if part)
                if term and isinstance(body, str) and body.strip():
                    found.setdefault(term, body.strip())
    return found


def load_definition_map(data: dict[str, Any]) -> dict[str, str]:
    current = data.get("definitions")
    if not isinstance(current, dict):
        current = data.get("preamble_definitions")
    definitions = {
        str(term).strip(): str(body).strip()
        for term, body in (current.items() if isinstance(current, dict) else [])
        if str(term).strip() and isinstance(body, str) and body.strip()
    }
    for term, body in definitions_from_named_items(data).items():
        definitions.setdefault(term, body)
    return definitions


def apply_overrides(data: dict[str, Any], definitions: dict[str, str], overrides_path: Path | None) -> None:
    if overrides_path is None:
        return
    overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
    if not isinstance(overrides, dict):
        raise ValueError("Overrides JSON must contain an object.")

    definition_overrides = overrides.get("definitions") or {}
    if not isinstance(definition_overrides, dict):
        raise ValueError("The 'definitions' override must be an object mapping exact terms to text.")
    for term, body in definition_overrides.items():
        term = str(term).strip()
        if not term or not isinstance(body, str) or not body.strip():
            raise ValueError(f"Invalid definition override for {term!r}.")
        definitions[term] = body.strip()

    page_overrides = overrides.get("definition_sources") or {}
    if not isinstance(page_overrides, dict):
        raise ValueError("The 'definition_sources' override must be an object.")
    sources = data.setdefault("_definition_sources", {})
    if not isinstance(sources, dict):
        sources = {}
        data["_definition_sources"] = sources
    for term, pages in page_overrides.items():
        sources[str(term).strip()] = pages


def _paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()] or ([text] if text else [])


_ALPHA_LIST_MARKER = re.compile(r"(?<![A-Za-z0-9])(?:\(([a-z])\)|([a-z])[.)])[ \t]+", re.IGNORECASE)


def split_inline_alpha_subparagraphs(text: str) -> str:
    """Put each item in an inline, sequential lower-alpha list on its own line."""
    markers = list(_ALPHA_LIST_MARKER.finditer(text))
    if len(markers) < 2:
        return text

    def letter(match: re.Match[str]) -> str:
        return (match.group(1) or match.group(2)).lower()

    breaks: set[int] = set()
    index = 0
    while index < len(markers):
        first = markers[index]
        run = [index]
        previous = index
        cursor = index + 1
        while cursor < len(markers):
            gap = text[markers[previous].end():markers[cursor].start()].rstrip()
            separated = bool(re.search(r"(?:[;,]|\b(?:and|or))\s*$", gap, re.IGNORECASE))
            if ord(letter(markers[cursor])) != ord(letter(markers[previous])) + 1 or not separated:
                break
            run.append(cursor)
            previous = cursor
            cursor += 1

        if len(run) >= 2:
            breaks.update(markers[item].start() for item in run)
            index = cursor
        else:
            index += 1

    normalized = text
    for position in sorted(breaks, reverse=True):
        if position and normalized[position - 1] != "\n":
            normalized = normalized[:position].rstrip(" \t") + "\n" + normalized[position:]
    return normalized


def normalize_inline_alpha_subparagraphs(data: dict[str, Any]) -> int:
    """Normalize inline lettered lists throughout clause and definition JSON."""
    changed = 0

    def visit(value: Any) -> None:
        nonlocal changed
        if isinstance(value, dict):
            content = value.get("content")
            paragraphs = value.get("paragraphs")
            if isinstance(content, str) and content:
                normalized = split_inline_alpha_subparagraphs(content)
                if normalized != content:
                    value["content"] = normalized
                    value["paragraphs"] = _paragraphs(normalized)
                    changed += 1
            elif isinstance(paragraphs, list):
                source = "\n".join(str(part) for part in paragraphs if part)
                normalized = split_inline_alpha_subparagraphs(source)
                if normalized != source:
                    value["content"] = normalized
                    value["paragraphs"] = _paragraphs(normalized)
                    changed += 1
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(data.get("clauses"))
    visit(data.get("nc_index"))
    definitions = data.get("definitions")
    if isinstance(definitions, dict):
        for term, body in list(definitions.items()):
            if isinstance(body, str):
                normalized = split_inline_alpha_subparagraphs(body)
                if normalized != body:
                    definitions[term] = normalized
                    changed += 1
    return changed


def split_sequential_numbered_items(data: dict[str, Any]) -> int:
    """Split embedded sequential subclause headings inside numbered named items."""
    clauses = data.get("clauses") or []
    nc_index = data.setdefault("nc_index", {})
    if not isinstance(nc_index, dict):
        nc_index = {}
        data["nc_index"] = nc_index
    added = 0

    for clause in clauses:
        if not isinstance(clause, dict):
            continue
        for section in walk_sections(clause.get("sub_clauses") or []):
            if section_has_definitions(section):
                continue
            items = section.get("named_items") or []
            if not isinstance(items, list):
                continue
            rebuilt: list[dict[str, Any]] = []

            for item in items:
                if not isinstance(item, dict):
                    continue
                nc = str(item.get("nc") or item.get("display_nc") or "").strip()
                body = str(item.get("content") or "").strip()
                if not CLAUSE_NUMBER.fullmatch(nc) or not body:
                    rebuilt.append(item)
                    continue

                parts = nc.split(".")
                parent_nc = str(section.get("nc") or ".".join(parts[:-1]))
                base = ".".join(parts[:-1])
                expected = int(parts[-1]) + 1
                pattern = re.compile(
                    rf"(?P<boundary>^|\n[ \t]*|[.!?][ \t]+)"
                    rf"(?P<prefix>Clause[ \t]+)?"
                    rf"(?P<nc>{re.escape(base)}\.(?P<ordinal>\d+))(?![\d.])(?=[ \t]+)",
                    re.IGNORECASE,
                )
                matches: list[re.Match[str]] = []
                for match in pattern.finditer(body):
                    boundary = match.group("boundary") or ""
                    # A reference such as ". Clause 4.4.7" is body text; accept
                    # an explicit "Clause" heading only at the start of a line.
                    if match.group("prefix") and "\n" not in boundary:
                        continue
                    ordinal = int(match.group("ordinal"))
                    if ordinal != expected:
                        continue
                    matches.append(match)
                    expected += 1

                if not matches:
                    rebuilt.append(item)
                    continue

                starts = [match.start("prefix") if match.group("prefix") else match.start("nc") for match in matches]
                bodies = [body[:starts[0]].rstrip()]
                for index, match in enumerate(matches):
                    end = starts[index + 1] if index + 1 < len(starts) else len(body)
                    part_body = body[match.end("nc"):end].lstrip(" \t\r\n:-–—")
                    bodies.append(part_body.rstrip())

                all_numbers = [nc] + [match.group("nc") for match in matches]
                for clause_nc, clause_body in zip(all_numbers, bodies):
                    clause_item = dict(item)
                    clause_item["nc"] = clause_nc
                    clause_item["display_nc"] = clause_nc
                    clause_item["content"] = clause_body
                    clause_item["paragraphs"] = _paragraphs(clause_body)
                    rebuilt.append(clause_item)

                    section_level = int(section.get("level") or len(parent_nc.split(".")) + 1)
                    node = nc_index.get(clause_nc)
                    if not isinstance(node, dict):
                        node = {"nc": clause_nc, "id": clause_nc, "title": clause_nc}
                        nc_index[clause_nc] = node
                        if clause_nc != nc:
                            added += 1
                    node.update({
                        "nc": clause_nc,
                        "id": node.get("id") or clause_nc,
                        "title": node.get("title") or clause_nc,
                        "level": node.get("level") or section_level + 1,
                        "content": clause_body,
                        "parent_nc": node.get("parent_nc") or parent_nc,
                        "paragraphs": _paragraphs(clause_body),
                    })

            section["named_items"] = rebuilt

    if added:
        stats = data.get("_stats")
        if isinstance(stats, dict):
            stats["named_items"] = int(stats.get("named_items") or 0) + added
    return added


def split_repeated_sibling_headings(data: dict[str, Any]) -> int:
    """Recover repeated, out-of-sequence sibling clause headings in flattened JSON."""
    nc_index = data.setdefault("nc_index", {})
    if not isinstance(nc_index, dict):
        nc_index = {}
        data["nc_index"] = nc_index

    duplicate_refs = data.setdefault("_duplicate_refs", {})
    if not isinstance(duplicate_refs, dict):
        duplicate_refs = {}
        data["_duplicate_refs"] = duplicate_refs

    added = 0
    duplicate_numbers: set[str] = set()
    for clause in data.get("clauses") or []:
        if not isinstance(clause, dict):
            continue
        for section in walk_sections(clause.get("sub_clauses") or []):
            if section_has_definitions(section):
                continue
            items = section.get("named_items") or []
            if not isinstance(items, list):
                continue

            known_numbers = {
                str(item.get("display_nc") or item.get("nc") or "").split("~", 1)[0].strip()
                for item in items if isinstance(item, dict)
            }
            seen_counts: dict[str, int] = {}
            rebuilt: list[dict[str, Any]] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                internal_nc = str(item.get("nc") or item.get("display_nc") or "").strip()
                printed_nc = str(item.get("display_nc") or internal_nc).split("~", 1)[0].strip()
                body = str(item.get("content") or "").strip()
                if not CLAUSE_NUMBER.fullmatch(printed_nc):
                    rebuilt.append(item)
                    continue

                seen_counts[printed_nc] = seen_counts.get(printed_nc, 0) + 1
                if not body:
                    rebuilt.append(item)
                    continue

                parts = printed_nc.split(".")
                base = ".".join(parts[:-1])
                pattern = re.compile(
                    rf"(?P<boundary>^|\n[ \t]*|[.!?][ \t]+)"
                    rf"(?P<prefix>Clause[ \t]+)?"
                    rf"(?P<nc>{re.escape(base)}\.(?P<ordinal>\d+))(?![\d.])(?=[ \t]+)",
                    re.IGNORECASE,
                )
                candidates: list[re.Match[str]] = []
                for match in pattern.finditer(body):
                    boundary = match.group("boundary") or ""
                    if match.group("prefix") and "\n" not in boundary:
                        continue
                    target = match.group("nc")
                    if target not in known_numbers or seen_counts.get(target, 0) == 0:
                        continue
                    after = body[match.end("nc"):].lstrip()
                    if "\n" not in boundary and not re.match(r"[A-Z][A-Za-z’'-]+\b", after):
                        continue
                    candidates.append(match)

                repeated_run: list[re.Match[str]] = []
                for start in range(len(candidates)):
                    run = [candidates[start]]
                    next_ordinal = int(run[0].group("ordinal")) + 1
                    for candidate in candidates[start + 1:]:
                        if int(candidate.group("ordinal")) != next_ordinal:
                            break
                        run.append(candidate)
                        next_ordinal += 1
                    if len(run) > len(repeated_run):
                        repeated_run = run
                if len(repeated_run) < 2:
                    rebuilt.append(item)
                    continue

                starts = [match.start("prefix") if match.group("prefix") else match.start("nc") for match in repeated_run]
                bodies = [body[:starts[0]].rstrip()]
                for index, match in enumerate(repeated_run):
                    end = starts[index + 1] if index + 1 < len(starts) else len(body)
                    bodies.append(body[match.end("nc"):end].lstrip(" \t\r\n:-–—").rstrip())

                section_nc = str(section.get("nc") or ".".join(parts[:-1]))
                section_level = int(section.get("level") or len(section_nc.split(".")) + 1)
                current_occurrence = seen_counts[printed_nc]
                item["content"] = bodies[0]
                item["paragraphs"] = _paragraphs(bodies[0])
                rebuilt.append(item)
                current_node = nc_index.get(internal_nc) or nc_index.get(printed_nc)
                if isinstance(current_node, dict):
                    current_node["content"] = bodies[0]
                    current_node["paragraphs"] = _paragraphs(bodies[0])

                for match, clause_body in zip(repeated_run, bodies[1:]):
                    target = match.group("nc")
                    occurrence = seen_counts.get(target, 0) + 1
                    seen_counts[target] = occurrence
                    duplicate_nc = f"{target}~{occurrence}"
                    duplicate_title = f"Clause {target} (duplicate #{occurrence})"
                    duplicate_item = dict(item)
                    duplicate_item.update({
                        "nc": duplicate_nc,
                        "display_nc": target,
                        "title": duplicate_title,
                        "content": clause_body,
                        "paragraphs": _paragraphs(clause_body),
                    })
                    rebuilt.append(duplicate_item)

                    node = nc_index.get(duplicate_nc)
                    if not isinstance(node, dict):
                        node = {}
                        nc_index[duplicate_nc] = node
                    node.update({
                        "nc": duplicate_nc,
                        "id": f"{target} (duplicate #{occurrence})",
                        "title": duplicate_title,
                        "level": section_level + 1,
                        "content": clause_body,
                        "parent_nc": section_nc,
                        "paragraphs": _paragraphs(clause_body),
                    })

                    targets = duplicate_refs.setdefault(target, [target])
                    if duplicate_nc not in targets:
                        targets.append(duplicate_nc)
                    duplicate_numbers.add(target)
                    added += 1

            section["named_items"] = rebuilt

    if added:
        stats = data.get("_stats")
        if isinstance(stats, dict):
            stats["named_items"] = int(stats.get("named_items") or 0) + added
    if duplicate_numbers:
        warnings = data.setdefault("_parse_warnings", [])
        warning = "Repeated printed sub-clause numbers: " + ", ".join(sorted(duplicate_numbers))
        if isinstance(warnings, list) and warning not in warnings:
            warnings.append(warning)
        data["_warning_badge"] = data.get("_warning_badge") or "⚠ Source numbering needs review"
    return added


def rebuild_definition_article_text(data: dict[str, Any], definitions: dict[str, str]) -> None:
    if not definitions:
        return
    clauses = data.get("clauses") or []
    for clause in clauses:
        if not isinstance(clause, dict):
            continue
        sections = list(walk_sections(clause.get("sub_clauses") or []))
        if not any(section_has_definitions(section) for section in sections):
            continue
        content = "Term\tDefinition\n" + "\n\n".join(
            f"{term}\t{body}" for term, body in definitions.items()
        )
        clause["content"] = content
        nc_index = data.get("nc_index")
        if isinstance(nc_index, dict):
            node = nc_index.get(str(clause.get("nc")))
            if isinstance(node, dict):
                node["content"] = content


def prepare_data(source: dict[str, Any], overrides_path: Path | None) -> dict[str, Any]:
    data = json.loads(json.dumps(source, ensure_ascii=False))
    definitions = load_definition_map(data)
    apply_overrides(data, definitions, overrides_path)
    data["definitions"] = definitions
    split_sequential_numbered_items(data)
    split_repeated_sibling_headings(data)
    normalize_inline_alpha_subparagraphs(data)
    if "preamble_definitions" in data:
        data["preamble_definitions"] = dict(definitions)
    rebuild_definition_article_text(data, definitions)
    return data


def safe_json_for_script(data: dict[str, Any]) -> str:
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return (
        encoded.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def build(input_json: Path, output_html: Path, template: Path, overrides: Path | None, normalized_json: Path | None) -> None:
    source = json.loads(input_json.read_text(encoding="utf-8"))
    if not isinstance(source, dict):
        raise ValueError("Parsed contract JSON must contain an object at the root.")
    data = prepare_data(source, overrides)

    html = template.read_text(encoding="utf-8")
    marker = "var embeddedData = null;"
    if html.count(marker) != 1:
        raise ValueError(f"Expected exactly one template marker, found {html.count(marker)}: {marker}")
    html = html.replace(marker, "var embeddedData = " + safe_json_for_script(data) + ";", 1)

    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(html, encoding="utf-8")
    if normalized_json is not None:
        normalized_json.parent.mkdir(parents=True, exist_ok=True)
        normalized_json.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    default_template = Path(__file__).resolve().parents[1] / "assets" / "contract_viewer_template.html"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_json", type=Path, help="Parsed contract JSON")
    parser.add_argument("output_html", type=Path, help="Destination HTML viewer")
    parser.add_argument("--template", type=Path, default=default_template, help="HTML template (defaults to this skill's reusable template)")
    parser.add_argument("--overrides", type=Path, help="Optional source-verified definition correction JSON")
    parser.add_argument("--normalized-json", type=Path, help="Optional destination for normalized JSON; input is never overwritten")
    args = parser.parse_args()

    for path, label in ((args.input_json, "input JSON"), (args.template, "template")):
        if not path.is_file():
            parser.error(f"{label} not found: {path}")
    if args.overrides is not None and not args.overrides.is_file():
        parser.error(f"overrides file not found: {args.overrides}")

    build(args.input_json, args.output_html, args.template, args.overrides, args.normalized_json)
    print(f"Built viewer: {args.output_html.resolve()}")
    if args.normalized_json is not None:
        print(f"Normalized JSON: {args.normalized_json.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
