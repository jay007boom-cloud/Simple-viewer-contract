"""Apply reviewed Schedule Markdown to an existing parsed contract without reparsing Articles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from parse_contract_md import parse_markdown, refresh_index


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parsed", type=Path, required=True)
    parser.add_argument("--supplement", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.parsed.read_text(encoding="utf-8-sig"))
    supplement = parse_markdown(args.supplement.read_text(encoding="utf-8-sig"),
                                str(data.get("title") or "Contract"), str(data.get("source_file") or ""))
    reviewed = {node["id"].lower(): node for node in supplement["clauses"]
                if node["id"].lower().startswith("schedule ")}
    if not reviewed:
        raise ValueError("The supplement has no Schedule headings to merge.")
    first_schedule = reviewed.get("schedule 1")
    if first_schedule and supplement.get("_preamble_tables_html"):
        first_schedule["tables_html"] = supplement["_preamble_tables_html"] + first_schedule.get("tables_html", [])
    replaced: list[str] = []
    for node in data.get("clauses", []):
        replacement = reviewed.pop(str(node.get("id", "")).lower(), None)
        if replacement is None:
            continue
        node["content"] = replacement.get("content", "")
        node["paragraphs"] = replacement.get("paragraphs", [])
        node["tables_html"] = replacement.get("tables_html", [])
        node["table_search_text"] = replacement.get("table_search_text", "")
        node["source_pages"] = replacement.get("source_pages", node.get("source_pages", []))
        node["title"] = replacement.get("title", node.get("title", ""))
        replaced.append(node["id"])
    data["clauses"].extend(reviewed.values())
    replaced.extend(node["id"] for node in reviewed.values())
    refresh_index(data)
    data.setdefault("_parse_warnings", [])
    data["_parse_warnings"].append("Reviewed Schedule Markdown applied; Articles and definitions retained from existing JSON.")
    data.setdefault("_source_metadata", {})["schedule_supplement"] = str(args.supplement)
    args.parsed.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"MERGED={','.join(replaced)}")
    print(f"JSON={args.parsed.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
