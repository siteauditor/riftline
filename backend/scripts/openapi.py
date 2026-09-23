"""Write the API's OpenAPI document to a file, without starting a server.

    python -m scripts.openapi ../frontend/openapi.json

The frontend generates its response types from this file (`pnpm api:types`),
and CI runs both steps again and fails on any difference, so a field added or
renamed here reaches the pages as a type error rather than as `undefined`.
Written with LF line endings and a trailing newline on every platform, so the
file is the same bytes on a Windows workstation and a Linux runner.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.main import app


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python -m scripts.openapi <output.json>")
    out = Path(sys.argv[1])
    text = json.dumps(app.openapi(), indent=1) + "\n"
    with out.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    # On stderr, so `/dev/stdout` as the output path gives the document alone.
    print(f"wrote {out} ({len(text):,} bytes)", file=sys.stderr)


if __name__ == "__main__":
    main()
