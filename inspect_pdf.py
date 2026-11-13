"""Emit a small local PDF profile for the PowerShell workflow."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pypdf import PdfReader


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: inspect_pdf.py <pdf-file>")

    source = Path(sys.argv[1])
    reader = PdfReader(str(source), strict=False)
    encrypted = bool(reader.is_encrypted)
    page_count = 0 if encrypted else len(reader.pages)
    sample_text = "" if encrypted else "".join(
        page.extract_text() or "" for page in reader.pages[: min(5, page_count)]
    )
    print(
        json.dumps(
            {
                "encrypted": encrypted,
                "pages": page_count,
                "characters": len(sample_text),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
