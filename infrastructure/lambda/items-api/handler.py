"""Item API for the mementos site.

Reached via the CloudFront behaviour for /api/* whose origin is this
function's Lambda Function URL -- see infrastructure/cloudfront.tf.
CloudFront is the only permitted caller (X-Origin-Verify shared secret).
On top of that, every route verifies the `mm_session` cookie the gate sets at
login: the HMAC is always re-checked here, the cookie's contents are never
trusted as they arrive.

Storage -- one JSON record per item, plus a manifest derived from them:

    data/items/<id>.json    the record. Written here and by item_sync.py.
    data/manifest.json      every record, sorted. Rebuilt from the records
                            after any write; never edited directly.
    images/<id>/orig/<n>.<ext>
    images/<id>/full/<n>.jpg
    images/<id>/thumb/<n>.jpg

The browser resizes its own JPEGs and PUTs all three sizes straight to S3
with the presigned URLs POST /api/upload-url hands out, then posts the record
here. No image processing happens in this function.

Record writes are a read-modify-write guarded by S3 conditional PutObject
(If-Match on the current ETag, If-None-Match: * for a first write).

Routes:
    GET    /api/me
    POST   /api/upload-url      {"itemId": "...", "count": 3}
    POST   /api/items           the whole record
    PATCH  /api/items/{id}      {"title","caption","date","tags"}
    DELETE /api/items/{id}      forgets the record; the images stay in S3

Keep this file ASCII-only.
"""

import hashlib
import hmac
import json
import logging
import os
import re
import time
import urllib.parse
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

log = logging.getLogger()
log.setLevel(logging.INFO)

s3 = boto3.client("s3")
ssm = boto3.client("ssm")

BUCKET = os.environ["BUCKET_NAME"]

ITEMS_PREFIX = "data/items/"
MANIFEST_KEY = "data/manifest.json"

ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
MAX_TITLE_CHARS = 200
MAX_CAPTION_CHARS = 4000
MAX_TAGS = 20
MAX_TAG_CHARS = 40
MAX_PHOTOS = 24
UPLOAD_URL_TTL = 900

_session_secret = None


def get_session_secret():
    global _session_secret
    if _session_secret is None:
        _session_secret = ssm.get_parameter(
            Name=os.environ["SSM_SESSION_SECRET_PARAM"], WithDecryption=True
        )["Parameter"]["Value"]
    return _session_secret


def json_response(status, payload):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"},
        "body": json.dumps(payload),
    }


def read_cookie(event, name):
    for cookie in event.get("cookies") or []:
        key, _, value = cookie.partition("=")
        if key.strip() == name:
            return value.strip()
    return None


def session_valid(event):
    token = read_cookie(event, "mm_session")
    if not token or "." not in token:
        return False
    payload, _, mac = token.rpartition(".")
    expected = hmac.new(
        get_session_secret().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(mac, expected):
        return False
    try:
        return int(payload) > time.time()
    except ValueError:
        return False


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


def clean_tags(raw):
    """Tags are freeform; this only trims, lowercases and dedupes them."""
    if isinstance(raw, str):
        raw = raw.replace(",", " ").split()
    if not isinstance(raw, list):
        return []
    seen = []
    for tag in raw:
        tag = re.sub(r"\s+", "-", str(tag).strip().lower())[:MAX_TAG_CHARS]
        tag = re.sub(r"[^a-z0-9-]", "", tag).strip("-")
        if tag and tag not in seen:
            seen.append(tag)
    return sorted(seen)[:MAX_TAGS]


def clean_date(raw):
    """Accepts a year, a year-month or a full date. Anything else is dropped."""
    value = str(raw or "").strip()
    return value if re.match(r"^\d{4}(-\d{2}(-\d{2})?)?$", value) else ""


def clean_fields(body, required_title):
    """Returns (fields, error). Only the keys present in `body` come back."""
    fields = {}

    if "title" in body or required_title:
        title = str(body.get("title") or "").strip()
        if not title:
            return None, "Give it a name."
        if len(title) > MAX_TITLE_CHARS:
            return None, "That name is too long -- keep it under %d characters." % MAX_TITLE_CHARS
        fields["title"] = title

    if "caption" in body:
        caption = str(body.get("caption") or "").strip()
        if len(caption) > MAX_CAPTION_CHARS:
            return None, "That's a lot of words -- keep it under %d characters." % MAX_CAPTION_CHARS
        fields["caption"] = caption

    if "date" in body:
        fields["date"] = clean_date(body.get("date"))
    if "tags" in body:
        fields["tags"] = clean_tags(body.get("tags"))

    return fields, None


def clean_photos(raw, item_id):
    """Validates the photo list the browser reports after uploading."""
    if not isinstance(raw, list) or not raw:
        return None, "No photos on that one."
    if len(raw) > MAX_PHOTOS:
        return None, "That's more than %d photos -- split it into two items." % MAX_PHOTOS

    photos = []
    for index, photo in enumerate(raw, start=1):
        if not isinstance(photo, dict):
            return None, "Bad photo record."
        photo_id = str(photo.get("id") or index)
        if not re.match(r"^\d{1,3}$", photo_id):
            return None, "Bad photo id."
        try:
            width = int(photo.get("w") or 0)
            height = int(photo.get("h") or 0)
        except (TypeError, ValueError):
            return None, "Bad photo dimensions."
        if width <= 0 or height <= 0:
            return None, "Bad photo dimensions."
        photos.append({
            "id": photo_id,
            "thumb": "/images/%s/thumb/%s.jpg" % (item_id, photo_id),
            "full": "/images/%s/full/%s.jpg" % (item_id, photo_id),
            "w": width,
            "h": height,
        })
    return photos, None


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------


def item_key(item_id):
    return "%s%s.json" % (ITEMS_PREFIX, item_id)


def read_item(item_id):
    """Returns (record, etag). Both None when the item does not exist."""
    try:
        got = s3.get_object(Bucket=BUCKET, Key=item_key(item_id))
    except ClientError as err:
        if err.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None, None
        raise
    return json.loads(got["Body"].read()), got["ETag"]


def write_item(record, etag):
    """Conditional write: fails if somebody else wrote since `etag` was read."""
    condition = {"IfMatch": etag} if etag else {"IfNoneMatch": "*"}
    s3.put_object(
        Bucket=BUCKET,
        Key=item_key(record["id"]),
        Body=json.dumps(record, indent=1).encode("utf-8"),
        ContentType="application/json",
        CacheControl="no-cache",
        **condition,
    )


def sort_key(record):
    """Newest first, by whatever part of a date the record actually has."""
    return (record.get("date") or "0000", record.get("created") or "", record.get("id") or "")


def rebuild_manifest():
    """Reads every record back and writes the file the frontend loads.

    The manifest is derived, never authored -- item_sync.py rebuilds it the
    same way, so whichever wrote last produces the same thing.
    """
    records = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=ITEMS_PREFIX):
        for obj in page.get("Contents", []):
            if not obj["Key"].endswith(".json"):
                continue
            body = s3.get_object(Bucket=BUCKET, Key=obj["Key"])["Body"].read()
            try:
                records.append(json.loads(body))
            except ValueError:
                log.warning("skipping unreadable record %s", obj["Key"])

    records.sort(key=sort_key, reverse=True)
    manifest = {"generated": now_iso(), "items": records}
    s3.put_object(
        Bucket=BUCKET,
        Key=MANIFEST_KEY,
        Body=json.dumps(manifest, indent=1).encode("utf-8"),
        ContentType="application/json",
        CacheControl="no-cache",
    )
    return len(records)


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------

SIZE_PREFIXES = ("orig", "full", "thumb")


def handle_upload_url(event):
    try:
        body = json.loads(event.get("body") or "{}")
    except ValueError:
        return json_response(400, {"error": "Invalid JSON body."})

    item_id = str(body.get("itemId") or "").strip().lower()
    if not ID_PATTERN.match(item_id):
        return json_response(400, {"error": "Bad item id."})

    try:
        count = int(body.get("count") or 0)
    except (TypeError, ValueError):
        return json_response(400, {"error": "Bad photo count."})
    if count < 1 or count > MAX_PHOTOS:
        return json_response(400, {"error": "Ask for between 1 and %d photos." % MAX_PHOTOS})

    urls = []
    for photo_id in range(1, count + 1):
        entry = {"id": str(photo_id)}
        for size in SIZE_PREFIXES:
            key = "images/%s/%s/%d.jpg" % (item_id, size, photo_id)
            entry[size] = s3.generate_presigned_url(
                "put_object",
                Params={"Bucket": BUCKET, "Key": key, "ContentType": "image/jpeg"},
                ExpiresIn=UPLOAD_URL_TTL,
            )
        urls.append(entry)

    return json_response(200, {"itemId": item_id, "uploads": urls})


def handle_create(event):
    try:
        body = json.loads(event.get("body") or "{}")
    except ValueError:
        return json_response(400, {"error": "Invalid JSON body."})

    item_id = str(body.get("id") or "").strip().lower()
    if not ID_PATTERN.match(item_id):
        return json_response(400, {"error": "Bad item id."})

    fields, error = clean_fields(body, required_title=True)
    if error:
        return json_response(400, {"error": error})

    photos, error = clean_photos(body.get("photos"), item_id)
    if error:
        return json_response(400, {"error": error})

    existing, etag = read_item(item_id)
    if existing is not None:
        return json_response(409, {"error": "Something is already filed under that name."})

    record = {
        "id": item_id,
        "title": fields["title"],
        "caption": fields.get("caption", ""),
        "date": fields.get("date", ""),
        "tags": fields.get("tags", []),
        "photos": photos,
        "created": now_iso(),
        "updated": now_iso(),
    }

    try:
        write_item(record, etag)
    except ClientError as err:
        if err.response["Error"]["Code"] in ("PreconditionFailed", "412"):
            return json_response(409, {"error": "Something is already filed under that name."})
        raise

    rebuild_manifest()
    return json_response(201, {"item": record})


def handle_patch(event, item_id):
    try:
        body = json.loads(event.get("body") or "{}")
    except ValueError:
        return json_response(400, {"error": "Invalid JSON body."})

    fields, error = clean_fields(body, required_title=False)
    if error:
        return json_response(400, {"error": error})
    if not fields:
        return json_response(400, {"error": "Nothing to change."})

    record, etag = read_item(item_id)
    if record is None:
        return json_response(404, {"error": "No item with that name."})

    record.update(fields)
    record["updated"] = now_iso()

    try:
        write_item(record, etag)
    except ClientError as err:
        if err.response["Error"]["Code"] in ("PreconditionFailed", "412"):
            return json_response(409, {"error": "Somebody else just changed that -- reload and retry."})
        raise

    rebuild_manifest()
    return json_response(200, {"item": record})


def handle_delete(item_id):
    record, _etag = read_item(item_id)
    if record is None:
        return json_response(404, {"error": "No item with that name."})

    s3.delete_object(Bucket=BUCKET, Key=item_key(item_id))
    rebuild_manifest()
    return json_response(200, {"deleted": item_id})


def handler(event, _context):
    if (event.get("headers") or {}).get("x-origin-verify") != os.environ["ORIGIN_VERIFY_SECRET"]:
        return {"statusCode": 403, "body": "Forbidden"}

    method = ((event.get("requestContext") or {}).get("http") or {}).get("method", "GET")
    path = event.get("rawPath") or "/"

    if not session_valid(event):
        return json_response(401, {"error": "Please enter the password again."})

    try:
        if method == "GET" and path == "/api/me":
            return json_response(200, {"ok": True})

        if method == "POST" and path == "/api/upload-url":
            return handle_upload_url(event)

        if method == "POST" and path in ("/api/items", "/api/items/"):
            return handle_create(event)

        tail = re.sub(r"^/api/items/?", "", path)
        parts = [urllib.parse.unquote(p) for p in tail.split("/") if p]

        if len(parts) == 1 and method in ("PATCH", "DELETE"):
            if not ID_PATTERN.match(parts[0]):
                return json_response(400, {"error": "Bad item id."})
            if method == "PATCH":
                return handle_patch(event, parts[0])
            return handle_delete(parts[0])

        return json_response(404, {"error": "Not found."})
    except Exception:
        log.exception("items-api error")
        return json_response(500, {"error": "Something went wrong -- try again."})
