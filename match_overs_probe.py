"""
match_overs_probe.py

Probe Play Cricket public match payloads for match over limit / innings over limit / DLS fields.

Usage:

python match_overs_probe.py --match-id b4fb9c97-22c2-43e3-adbd-e4d2d0062d87 --save-prefix test_30_start

This saves:
- test_30_start_match_basic.json
- test_30_start_match_with_scorecard.json
- test_30_start_balls.json

It also prints any paths whose key or value mentions:
- over
- limit
- target
- dls
- duckworth
- par
- revised
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import requests


BASE_URL = "https://grassrootsapiproxy.cricket.com.au"

SEARCH_TERMS = [
    "over",
    "overs",
    "limit",
    "target",
    "dls",
    "duckworth",
    "par",
    "revised",
    "innings",
    "maximum",
    "max",
    "reduced",
]


def fetch_json(path: str, params: dict[str, str] | None = None) -> Any:
    final_params = {"jsconfig": "eccn:true"}
    if params:
        final_params.update(params)

    headers = {
        "accept": "*/*",
        "origin": "https://play.cricket.com.au",
        "referer": "https://play.cricket.com.au/",
        "user-agent": "MatchOversProbe/1.0",
        "cache-control": "no-cache",
        "pragma": "no-cache",
    }

    url = BASE_URL + path
    response = requests.get(url, params=final_params, headers=headers, timeout=30)

    print(f"GET {response.url}")
    print(f"Status: {response.status_code}")

    response.raise_for_status()
    return response.json()


def save_json(filename: str, data: Any) -> None:
    Path(filename).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved: {filename}")


def is_interesting_key(key: str) -> bool:
    k = key.lower()
    return any(term in k for term in SEARCH_TERMS)


def is_interesting_value(value: Any) -> bool:
    if isinstance(value, str):
        v = value.lower()
        return any(term in v for term in SEARCH_TERMS)

    return False


def walk(data: Any, path: str = "") -> list[tuple[str, Any]]:
    hits: list[tuple[str, Any]] = []

    if isinstance(data, dict):
        for key, value in data.items():
            child_path = f"{path}.{key}" if path else str(key)

            if is_interesting_key(str(key)) or is_interesting_value(value):
                hits.append((child_path, value))

            hits.extend(walk(value, child_path))

    elif isinstance(data, list):
        for index, item in enumerate(data):
            child_path = f"{path}[{index}]"
            hits.extend(walk(item, child_path))

    return hits


def short_value(value: Any, max_len: int = 180) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = repr(value)

    if len(text) > max_len:
        return text[:max_len] + "..."

    return text


def print_interesting(title: str, data: Any) -> None:
    print()
    print("=" * 100)
    print(title)
    print("=" * 100)

    hits = walk(data)

    if not hits:
        print("No interesting paths found.")
        return

    seen = set()
    for path, value in hits:
        if path in seen:
            continue
        seen.add(path)
        print(f"{path}: {short_value(value)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--save-prefix", default="match_probe")
    args = parser.parse_args()

    match_id = args.match_id.strip()
    prefix = args.save_prefix.strip()

    endpoints = [
        (
            "match_basic",
            f"/scores/matches/{match_id}",
            None,
            f"{prefix}_match_basic.json",
        ),
        (
            "match_with_scorecard",
            f"/scores/matches/{match_id}",
            {"responseModifier": "includeScorecard"},
            f"{prefix}_match_with_scorecard.json",
        ),
        (
            "balls",
            f"/scores/matches/{match_id}/balls",
            None,
            f"{prefix}_balls.json",
        ),
    ]

    results: dict[str, Any] = {}

    for name, path, params, filename in endpoints:
        print()
        print("-" * 100)
        print(name)
        print("-" * 100)

        try:
            data = fetch_json(path, params=params)
        except Exception as exc:
            print(f"FAILED {name}: {exc}")
            continue

        save_json(filename, data)
        results[name] = data

    for name, data in results.items():
        print_interesting(name, data)

    print()
    print("Done.")
    print()
    print("Next useful tests:")
    print("1. Keep this as baseline: over limit 30, innings started.")
    print("2. Change over limit to 20 or 40 if allowed, run again with a new save prefix.")
    print("3. Compare JSON files for fields that changed from 30 to 20/40.")
    print("4. If public payload does not show the limit, inspect scorer Network/XHR calls.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())