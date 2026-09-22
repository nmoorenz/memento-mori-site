#!/usr/bin/env python3
"""Bulk-load mementos into S3 and rebuild the site manifest.

Commands
    check     Match the csv's photo lists against the files in photos/. No AWS.
    sync      Upload new photos, build derivatives, rebuild the manifest.
    export    Write every record in S3 back out to a CSV you can edit.
    download  Pull the original photos back from S3 into ./photos.
    rename    Move an item's record and photos to a new id.
    delete    Forget an item (record and, with --photos, its images).

Local layout -- drop the photos into photos/ under whatever names they
already have, and list them in the csv's "photos" column. Nothing is renamed:

    photos/items.csv
    photos/IMG_4821.JPG
    photos/IMG_4822.JPG
    photos/scan_0007.jpg

    photos,id,title,caption,date,tags
    "IMG_4821.JPG, IMG_4822.JPG",copper-key,Copper Key,...
    scan_0007.jpg,,Anorak's Almanac,...

Leave the id blank and it is derived from the title.

The first filename listed is the cover; the rest follow in that order.

S3 layout:

    images/<id>/orig/<your filename>  untouched upload, never served
    images/<id>/full/<n>.jpg     lightbox size
    images/<id>/thumb/<n>.jpg    grid size
    data/items/<id>.json         the record -- the one source of truth
    data/manifest.json           every record, sorted; derived, never edited

photos/items.csv is an authoring convenience, not the store. `sync` writes
its rows into the records; it never deletes a record that has no row, so
things added through the site's own form survive. `export` goes the other way
when you want to bulk-edit what is already up there.

example/ holds the same shape with invented items and placeholder photos, and
is committed. Copy example/items.csv into photos/ to start; photos/ is
gitignored.

Keep this file ASCII-only.
"""

import argparse
import csv
import io
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from PIL import Image, ImageOps

REPO_ROOT = Path(__file__).resolve().parent.parent
PHOTOS_DIR = REPO_ROOT / "photos"

# Your own photos and the list describing them live together in photos/,
# which is gitignored. example/ holds a committed set in the same shape.
EXAMPLE_DIR = REPO_ROOT / "example"
ITEMS_CSV = PHOTOS_DIR / "items.csv"
EXAMPLE_CSV = EXAMPLE_DIR / "items.csv"

ITEMS_PREFIX = "data/items/"
MANIFEST_KEY = "data/manifest.json"

THUMB_MAX = 600
FULL_MAX = 2000
JPEG_QUALITY = 85
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".heic"}

ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
DATE_PATTERN = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")

QUIET = False


def log(*args):
    if not QUIET:
        print(*args)


def warn(*args):
    print("WARN:", *args, file=sys.stderr)


def die(message):
    print("ERROR:", message, file=sys.stderr)
    raise SystemExit(1)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# The csv's "photos" column is the only thing that maps a file to an item, so
# your own filenames are never touched. Everything that knows about that
# mapping lives in this section.
# ---------------------------------------------------------------------------


def parse_photo_list(raw):
    """Split a photos cell into filenames, in order.

    Commas first, so names may contain spaces; a cell with no comma is split
    on whitespace instead.
    """
    text = str(raw or "").strip()
    if not text:
        return []
    parts = text.split(",") if "," in text else text.split()
    names = []
    for part in parts:
        name = part.strip()
        if name and name not in names:
            names.append(name)
    return names


def photo_id(position):
    return str(position)


SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")


def orig_key(item_id, path, position):
    """Where the untouched upload is kept.

    Under its own filename when that is safe as an S3 key, so `download`
    restores exactly what items.csv lists; otherwise under the position.
    """
    name = path.name if SAFE_NAME.match(path.name) else "%s%s" % (position, path.suffix.lower())
    return "images/%s/orig/%s" % (item_id, name)


def resolve_photos(rows, root=None):
    """Match each row's photo list to real files.

    Returns {item_id: [(position, path)]}. Missing files and files in the
    folder that no row claims are both warned about, so a typo surfaces
    instead of silently going missing.
    """
    root = root or PHOTOS_DIR
    if not root.exists():
        return {}

    # Match case-insensitively: a csv written by hand rarely agrees with what
    # a camera or scanner capitalised.
    on_disk = {}
    for path in sorted(root.iterdir()):
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
            on_disk.setdefault(path.name.lower(), path)

    claimed = set()
    resolved = {}
    for item_id, row in sorted(rows.items()):
        photos = []
        for name in row["photos"]:
            path = on_disk.get(name.lower())
            if path is None:
                warn("%s: '%s' is not in %s" % (item_id, name, root.name))
                continue
            claimed.add(path.name.lower())
            photos.append((len(photos) + 1, path))
        if photos:
            resolved[item_id] = photos

    for name, path in sorted(on_disk.items()):
        if name not in claimed:
            warn("%s: no row in items.csv lists it" % path.name)

    return resolved


# ---------------------------------------------------------------------------
# items.csv
# ---------------------------------------------------------------------------

CSV_COLUMNS = ["photos", "id", "title", "caption", "date", "tags"]


def clean_tags(raw):
    """Tags are freeform -- this only normalises the shape."""
    if isinstance(raw, str):
        raw = raw.replace(",", " ").split()
    seen = []
    for tag in raw or []:
        tag = re.sub(r"[^a-z0-9-]", "", re.sub(r"\s+", "-", str(tag).strip().lower())).strip("-")
        if tag and tag not in seen:
            seen.append(tag)
    return sorted(seen)


def slugify(text):
    """Turn a title into an id: lowercase, hyphens, nothing else.

    Apostrophes are dropped rather than treated as separators, so
    "Anorak's Almanac" becomes "anoraks-almanac".
    """
    value = re.sub(r"['\u2019]", "", str(text or "").strip().lower())
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")[:64]


def clean_date(raw, where):
    value = str(raw or "").strip()
    if value and not DATE_PATTERN.match(value):
        warn("%s: date '%s' is not YYYY, YYYY-MM or YYYY-MM-DD, left blank" % (where, value))
        return ""
    return value


def read_items_csv(path=None):
    path = path or ITEMS_CSV
    if not path.exists():
        die("%s not found -- copy %s there and edit it."
            % (path.relative_to(REPO_ROOT), EXAMPLE_CSV.relative_to(REPO_ROOT)))

    rows = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in CSV_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            die("%s is missing column(s): %s -- compare it with %s."
                % (path.relative_to(REPO_ROOT), ", ".join(missing),
                   EXAMPLE_CSV.relative_to(REPO_ROOT)))
        derived = []
        for row in reader:
            title = (row.get("title") or "").strip()
            item_id = (row.get("id") or "").strip().lower()
            if not item_id:
                # Leave the id column blank and it comes from the title. Once
                # an item is synced its id is fixed, so paste it back in if
                # you ever want to retitle without orphaning the item.
                item_id = slugify(title)
                if item_id:
                    derived.append(item_id)
            if not item_id:
                continue
            if not ID_PATTERN.match(item_id):
                warn("csv id '%s' is not a plain lowercase slug, skipped" % item_id)
                continue
            if item_id in rows:
                warn("two rows share the id '%s', the second is skipped" % item_id)
                continue
            rows[item_id] = {
                "id": item_id,
                "title": title or item_id,
                "caption": (row.get("caption") or "").strip(),
                "date": clean_date(row.get("date"), "row '%s'" % item_id),
                "tags": clean_tags(row.get("tags")),
                "photos": parse_photo_list(row.get("photos")),
            }

        if derived:
            log("Derived %d id(s) from titles: %s" % (len(derived), ", ".join(derived)))
    return rows


# ---------------------------------------------------------------------------
# Local photos
# ---------------------------------------------------------------------------


def derivative(path, max_edge):
    """Return (JPEG bytes, width, height), EXIF-rotated and resized to fit."""
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image)
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        image.thumbnail((max_edge, max_edge), Image.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        return buffer.getvalue(), image.width, image.height


# ---------------------------------------------------------------------------
# AWS
# ---------------------------------------------------------------------------


def aws_setup():
    load_dotenv(REPO_ROOT / ".env")
    bucket = os.environ.get("S3_BUCKET")
    region = os.environ.get("AWS_REGION")
    profile = os.environ.get("AWS_PROFILE")
    if not bucket:
        die("S3_BUCKET is not set -- copy env.example to .env and fill it in.")
    session = boto3.Session(profile_name=profile, region_name=region)
    return session.client("s3"), bucket


def list_keys(s3, bucket, prefix):
    keys = {}
    token = None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        page = s3.list_objects_v2(**kwargs)
        for obj in page.get("Contents", []):
            keys[obj["Key"]] = obj["Size"]
        if not page.get("IsTruncated"):
            return keys
        token = page["NextContinuationToken"]


def item_key(item_id):
    return "%s%s.json" % (ITEMS_PREFIX, item_id)


def read_record(s3, bucket, item_id):
    try:
        body = s3.get_object(Bucket=bucket, Key=item_key(item_id))["Body"].read()
    except ClientError as err:
        if err.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise
    return json.loads(body)


def write_record(s3, bucket, record):
    s3.put_object(
        Bucket=bucket,
        Key=item_key(record["id"]),
        Body=json.dumps(record, indent=1).encode("utf-8"),
        ContentType="application/json",
        CacheControl="no-cache",
    )


def read_all_records(s3, bucket):
    records = []
    for key in sorted(list_keys(s3, bucket, ITEMS_PREFIX)):
        if not key.endswith(".json"):
            continue
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        try:
            records.append(json.loads(body))
        except ValueError:
            warn("record %s is not readable JSON, left out" % key)
    return records


# ---------------------------------------------------------------------------
# manifest
#
# Derived, never authored. items-api rebuilds it the same way, so whichever
# wrote last produces the same file.
# ---------------------------------------------------------------------------


def sort_key(record):
    return (record.get("date") or "0000", record.get("created") or "", record.get("id") or "")


def build_manifest(records):
    ordered = sorted(records, key=sort_key, reverse=True)
    return {"generated": now_iso(), "items": ordered}


def write_manifest(s3, bucket, records):
    manifest = build_manifest(records)
    s3.put_object(
        Bucket=bucket,
        Key=MANIFEST_KEY,
        Body=json.dumps(manifest, indent=1).encode("utf-8"),
        ContentType="application/json",
        CacheControl="no-cache",
    )
    return manifest


def photo_entry(item_id, position, width, height):
    pid = photo_id(position)
    return {
        "id": pid,
        "thumb": "/images/%s/thumb/%s.jpg" % (item_id, pid),
        "full": "/images/%s/full/%s.jpg" % (item_id, pid),
        "w": width,
        "h": height,
    }


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def cmd_check(_args):
    rows = read_items_csv()
    resolved = resolve_photos(rows)

    for item_id in sorted(rows):
        row = rows[item_id]
        photos = resolved.get(item_id) or []
        listed = len(row["photos"])
        notes = []
        if not listed:
            notes.append("photos column empty")
        elif len(photos) < listed:
            notes.append("%d of %d file(s) missing" % (listed - len(photos), listed))
        log("%-36s %-10s %2d photo(s)%s"
            % (item_id, row["date"] or "-", len(photos),
               "" if not notes else "   " + ", ".join(notes)))

    log("\n%d item(s) ready to sync, %d photo(s)."
        % (len(resolved), sum(len(p) for p in resolved.values())))


def cmd_sync(args):
    rows = read_items_csv()
    resolved = resolve_photos(rows)
    s3, bucket = aws_setup()

    existing = list_keys(s3, bucket, "images/")
    uploaded = 0
    touched = 0

    for item_id, entries in sorted(resolved.items()):
        photos = []
        for position, path in entries:
            pid = photo_id(position)
            orig = orig_key(item_id, path, position)
            full_key = "images/%s/full/%s.jpg" % (item_id, pid)
            thumb_key = "images/%s/thumb/%s.jpg" % (item_id, pid)

            have_all = all(k in existing for k in (orig, full_key, thumb_key))
            # The thumbnail's dimensions go in the record, so they are needed
            # even when nothing is re-uploaded.
            thumb_bytes, thumb_w, thumb_h = derivative(path, THUMB_MAX)

            if args.force or not have_all:
                log("up %s  (%s)" % (path.name, item_id))
                orig_bytes, _, _ = derivative(path, max(FULL_MAX * 2, 3200))
                full_bytes, _, _ = derivative(path, FULL_MAX)
                for key, body in ((orig, orig_bytes), (full_key, full_bytes), (thumb_key, thumb_bytes)):
                    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="image/jpeg")
                uploaded += 1

            photos.append(photo_entry(item_id, position, thumb_w, thumb_h))

        row = rows[item_id]
        existing_record = read_record(s3, bucket, item_id)
        record = {
            "id": item_id,
            "title": row["title"],
            "caption": row["caption"],
            "date": row["date"],
            "tags": row["tags"],
            "photos": photos,
            "created": (existing_record or {}).get("created") or now_iso(),
            "updated": now_iso(),
        }

        # Only write when something other than the timestamp actually moved,
        # so a re-run of `sync` does not churn every record.
        comparable_old = dict(existing_record or {})
        comparable_new = dict(record)
        for field in ("updated",):
            comparable_old.pop(field, None)
            comparable_new.pop(field, None)

        if comparable_old != comparable_new:
            write_record(s3, bucket, record)
            touched += 1

    if args.prune:
        # Only items that exist on this machine can be pruned -- for any other
        # item this machine has no idea what the full set should be.
        expected = set()
        for item_id, entries in resolved.items():
            for position, path in entries:
                pid = photo_id(position)
                expected.add(orig_key(item_id, path, position))
                for size in ("full", "thumb"):
                    expected.add("images/%s/%s/%s.jpg" % (item_id, size, pid))

        for key in sorted(list_keys(s3, bucket, "images/")):
            parts = key.split("/")
            if len(parts) != 4 or parts[1] not in resolved or key in expected:
                continue
            log("rm %s" % key)
            s3.delete_object(Bucket=bucket, Key=key)

    records = read_all_records(s3, bucket)
    manifest = write_manifest(s3, bucket, records)

    log("\nuploaded %d photo(s), wrote %d record(s); the site now has %d item(s), %d photo(s)."
        % (uploaded, touched, len(manifest["items"]),
           sum(len(i.get("photos") or []) for i in manifest["items"])))
    log("Invalidate CloudFront if you want the change visible immediately.")


def cmd_export(args):
    s3, bucket = aws_setup()
    records = sorted(read_all_records(s3, bucket), key=sort_key, reverse=True)

    target = Path(args.out) if args.out else ITEMS_CSV
    if target.exists() and not args.force:
        die("%s already exists -- pass --force to overwrite, or --out somewhere else." % target)

    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for record in records:
            writer.writerow({
                "id": record.get("id", ""),
                "title": record.get("title", ""),
                "caption": record.get("caption", ""),
                "date": record.get("date", ""),
                "tags": " ".join(record.get("tags") or []),
            })
    log("Wrote %d record(s) to %s." % (len(records), target))


def cmd_download(args):
    s3, bucket = aws_setup()
    keys = list_keys(s3, bucket, "images/")
    origs = {k: size for k, size in keys.items() if k.split("/")[2:3] == ["orig"]}
    total = sum(origs.values())
    log("%d original(s), %.1f MB in s3://%s/images/" % (len(origs), total / 1e6, bucket))
    if not args.yes:
        log("Re-run with --yes to download them into ./photos.")
        return
    for key in sorted(origs):
        _, item_id, _, filename = key.split("/", 3)
        if args.item and item_id != args.item:
            continue
        # Originals are stored under the name they were uploaded with, so
        # they come back matching what items.csv already lists.
        target = PHOTOS_DIR / filename
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        log("dl %s" % key)
        s3.download_file(bucket, key, str(target))


def cmd_rename(args):
    s3, bucket = aws_setup()

    if not ID_PATTERN.match(args.to):
        die("'%s' is not a plain lowercase slug." % args.to)

    record = read_record(s3, bucket, args.item)
    if record is None:
        die("No item '%s'." % args.item)
    if read_record(s3, bucket, args.to) is not None:
        die("'%s' already exists." % args.to)

    for key in sorted(list_keys(s3, bucket, "images/%s/" % args.item)):
        new_key = key.replace("images/%s/" % args.item, "images/%s/" % args.to, 1)
        log("mv %s -> %s" % (key, new_key))
        s3.copy_object(Bucket=bucket, Key=new_key, CopySource={"Bucket": bucket, "Key": key})
        s3.delete_object(Bucket=bucket, Key=key)

    record["id"] = args.to
    for photo in record.get("photos") or []:
        photo["thumb"] = "/images/%s/thumb/%s.jpg" % (args.to, photo["id"])
        photo["full"] = "/images/%s/full/%s.jpg" % (args.to, photo["id"])
    record["updated"] = now_iso()

    write_record(s3, bucket, record)
    s3.delete_object(Bucket=bucket, Key=item_key(args.item))
    write_manifest(s3, bucket, read_all_records(s3, bucket))
    log("Renamed '%s' to '%s'. Update the id in items.csv too." % (args.item, args.to))


def cmd_delete(args):
    s3, bucket = aws_setup()

    record = read_record(s3, bucket, args.item)
    if record is None:
        die("No item '%s'." % args.item)
    if not args.yes:
        log("Would forget '%s' (%s)%s. Re-run with --yes."
            % (args.item, record.get("title", ""), " and delete its images" if args.photos else ""))
        return

    s3.delete_object(Bucket=bucket, Key=item_key(args.item))
    if args.photos:
        for key in sorted(list_keys(s3, bucket, "images/%s/" % args.item)):
            log("rm %s" % key)
            s3.delete_object(Bucket=bucket, Key=key)

    write_manifest(s3, bucket, read_all_records(s3, bucket))
    log("Forgot '%s'." % args.item)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-q", "--quiet", action="store_true", help="only print warnings and errors")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="match the csv photo lists against photos/, no AWS").set_defaults(func=cmd_check)

    p_sync = sub.add_parser("sync", help="upload new photos and rebuild the manifest")
    p_sync.add_argument("--force", action="store_true", help="re-upload photos already in S3")
    p_sync.add_argument("--prune", action="store_true",
                        help="delete S3 images for photos no longer present locally")
    p_sync.set_defaults(func=cmd_sync)

    p_ex = sub.add_parser("export", help="write every record in S3 back out to CSV")
    p_ex.add_argument("--out", help="write here instead of photos/items.csv")
    p_ex.add_argument("--force", action="store_true", help="overwrite an existing file")
    p_ex.set_defaults(func=cmd_export)

    p_dl = sub.add_parser("download", help="pull the original photos back from S3")
    p_dl.add_argument("--yes", action="store_true", help="actually download (otherwise just reports)")
    p_dl.add_argument("--item", help="limit to one item id")
    p_dl.set_defaults(func=cmd_download)

    p_rn = sub.add_parser("rename", help="move an item's record and photos to a new id")
    p_rn.add_argument("--item", required=True, help="current item id")
    p_rn.add_argument("--to", required=True, help="new item id")
    p_rn.set_defaults(func=cmd_rename)

    p_del = sub.add_parser("delete", help="forget an item")
    p_del.add_argument("--item", required=True, help="item id")
    p_del.add_argument("--photos", action="store_true", help="delete its images too")
    p_del.add_argument("--yes", action="store_true", help="actually delete")
    p_del.set_defaults(func=cmd_delete)

    args = parser.parse_args()

    global QUIET
    QUIET = args.quiet
    args.func(args)


if __name__ == "__main__":
    main()
