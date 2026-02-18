from __future__ import annotations

import argparse
import json

from app.services.hash_manifest import verify_range_against_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify series episode hashes against manifest")
    parser.add_argument("--show", required=True, help="Canonical show title")
    parser.add_argument("--season", required=True, type=int, help="Season number")
    parser.add_argument("--start", required=True, type=int, help="Start episode number")
    parser.add_argument("--end", required=True, type=int, help="End episode number")
    args = parser.parse_args()

    mismatches = verify_range_against_manifest(args.show, args.season, args.start, args.end)
    if not mismatches:
        print("OK: no mismatches")
        return 0

    print(json.dumps({"mismatches": mismatches}, ensure_ascii=False, indent=2))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
