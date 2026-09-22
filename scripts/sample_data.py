#!/usr/bin/env python3
"""Build the local preview from a folder of photos.

Reads items.csv and the photos it lists from a source directory, makes thumb
and full derivatives, and writes site/manifest.json and site/sample-photos/. Both
outputs are gitignored.

    python scripts/sample_data.py                # from example/ (committed)
    python scripts/sample_data.py --source photos  # from your own, pre-upload

    cd site && python -m http.server 8000

Needs no .env, no AWS credentials and no photos of your own.

Keep this file ASCII-only.
"""

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import item_sync as sync  # noqa: E402

REPO_ROOT = sync.REPO_ROOT
SITE_DIR = REPO_ROOT / "site"
SAMPLE_DIR = SITE_DIR / "sample-photos"
MANIFEST = SITE_DIR / "manifest.json"


def build(source):
    csv_path = source / "items.csv"
    rows = sync.read_items_csv(csv_path)
    found = sync.resolve_photos(rows, source)

    if not found:
        raise SystemExit("ERROR: no photos listed in %s were found."
                         % csv_path.relative_to(REPO_ROOT))

    if SAMPLE_DIR.exists():
        shutil.rmtree(SAMPLE_DIR)

    records = []
    for item_id, entries in sorted(found.items()):
        row = rows[item_id]

        photos = []
        for position, path in entries:
            pid = sync.photo_id(position)
            thumb, width, height = sync.derivative(path, sync.THUMB_MAX)
            full, _, _ = sync.derivative(path, sync.FULL_MAX)
            for kind, body in (("thumb", thumb), ("full", full)):
                target = SAMPLE_DIR / item_id / kind / ("%s.jpg" % pid)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(body)
            photos.append({
                "id": pid,
                "thumb": "./sample-photos/%s/thumb/%s.jpg" % (item_id, pid),
                "full": "./sample-photos/%s/full/%s.jpg" % (item_id, pid),
                "w": width,
                "h": height,
            })

        record = dict(row)
        record["photos"] = photos
        record["created"] = "1970-01-01T00:00:00Z"
        record["updated"] = "1970-01-01T00:00:00Z"
        records.append(record)

    if not records:
        raise SystemExit("ERROR: nothing to build.")

    manifest = sync.build_manifest(records)
    manifest["generated"] = datetime.now(timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")
    MANIFEST.write_text(json.dumps(manifest, indent=1), encoding="utf-8")

    print("Built %d item(s), %d photo(s) from %s"
          % (len(records), sum(len(r["photos"]) for r in records),
             source.relative_to(REPO_ROOT)))
    print("Wrote %s and %s" % (MANIFEST.relative_to(REPO_ROOT),
                               SAMPLE_DIR.relative_to(REPO_ROOT)))
    print("Preview with:  cd site && python -m http.server 8000")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default="example",
                        help="folder holding items.csv and the photos it lists (default: example)")
    args = parser.parse_args()

    source = (REPO_ROOT / args.source).resolve()
    if not source.exists():
        raise SystemExit("ERROR: %s does not exist." % args.source)
    build(source)


if __name__ == "__main__":
    main()
