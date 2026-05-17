from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from extract.extractor import compact_json, extract_structured_posts
else:
    from .extractor import compact_json, extract_structured_posts


def _load_payload(input_path: str | None) -> dict[str, Any]:
    if input_path:
        return json.loads(Path(input_path).read_text(encoding="utf-8"))
    return json.load(sys.stdin)


def _write_output(text: str, output_path: str | None = None) -> None:
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
        return

    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build deterministic structured_posts from a WF-FETCH-03 aggregate payload."
    )
    parser.add_argument(
        "--input-path",
        help="Path to a JSON file that contains the aggregate payload. Reads stdin when omitted.",
    )
    parser.add_argument(
        "--output-path",
        help="Optional path to write the structured_posts JSON instead of stdout.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Print indented UTF-8 JSON instead of ASCII-safe compact JSON.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = _load_payload(args.input_path)
    result = extract_structured_posts(payload)
    _write_output(compact_json(result, pretty=args.pretty), args.output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
