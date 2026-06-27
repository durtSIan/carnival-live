"""
compare_probe_json.py

Compare two JSON files and print differences that are likely to matter for:
- over limits
- innings limits
- targets
- DLS / Duckworth-Lewis
- revised targets
- innings data

Usage:

python compare_probe_json.py old_file.json new_file.json

Examples:

python compare_probe_json.py test_30_start_match_with_scorecard.json test_20_start_match_with_scorecard.json

python compare_probe_json.py test_30_start_match_basic.json test_20_start_match_basic.json

python compare_probe_json.py test_30_start_balls.json test_20_start_balls.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


KEYWORDS = [
    "over",
    "overs",
    "limit",
    "target",
    "dls",
    "duckworth",
    "par",
    "revised",
    "maximum",
    "max",
    "reduced",
    "innings",
    "balls",
    "rain",
]


def flatten(data: Any, path: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}

    if isinstance(data, dict):
        for key, value in data.items():
            child = f"{path}.{key}" if path else str(key)
            out.update(flatten(value, child))

    elif isinstance(data, list):
        for i, value in enumerate(data):
            child = f"{path}[{i}]"
            out.update(flatten(value, child))

    else:
        out[path] = data

    return out


def interesting(path: str, old_value: Any, new_value: Any) -> bool:
    text = f"{path} {old_value} {new_value}".lower()
    return any(keyword in text for keyword in KEYWORDS)


def short(value: Any, max_len: int = 220) -> str:
    text = repr(value)
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def load_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare two JSON files and print interesting cricket-related differences."
    )
    parser.add_argument("old_file", help="First JSON file, e.g. test_30_start_match_with_scorecard.json")
    parser.add_argument("new_file", help="Second JSON file, e.g. test_20_start_match_with_scorecard.json")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Print all differences, not just cricket-related ones.",
    )
    args = parser.parse_args()

    old_data = load_json(args.old_file)
    new_data = load_json(args.new_file)

    old_flat = flatten(old_data)
    new_flat = flatten(new_data)

    all_paths = sorted(set(old_flat) | set(new_flat))

    printed = 0

    print()
    print("=" * 100)
    print("Comparing JSON files")
    print("=" * 100)
    print(f"OLD: {args.old_file}")
    print(f"NEW: {args.new_file}")
    print()

    for path in all_paths:
        old_value = old_flat.get(path, "<missing>")
        new_value = new_flat.get(path, "<missing>")

        if old_value == new_value:
            continue

        if args.all or interesting(path, old_value, new_value):
            print(path)
            print(f"  OLD: {short(old_value)}")
            print(f"  NEW: {short(new_value)}")
            print()
            printed += 1

    if printed == 0:
        if args.all:
            print("No differences found.")
        else:
            print("No interesting cricket-related differences found.")
            print()
            print("Try again with --all to see every difference:")
            print(f"python compare_probe_json.py {args.old_file} {args.new_file} --all")

    print()
    print(f"Differences printed: {printed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())