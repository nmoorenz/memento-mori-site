"""The password gate.

Everything on the site except /login.html and /style.css sits behind a
CloudFront behaviour with a trusted key group, so a viewer with no valid
signed cookies gets a 403, which CloudFront turns into the login page.

login.html posts the shared password here. On a match this function:

  1. issues CloudFront signed cookies scoped to the whole site
  2. sets a session cookie scoped to /api/*, an HMAC over the expiry, which
     items-api verifies before it will write anything
  3. tells the browser to reload

Routes:
    POST /auth/login     {"password": "..."}
    GET  /auth/logout

Reached via the CloudFront behaviour for /auth/* whose origin is this
function's Lambda Function URL -- see infrastructure/cloudfront.tf.

Keep this file ASCII-only.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import time

import boto3
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

log = logging.getLogger()
log.setLevel(logging.INFO)

ssm = boto3.client("ssm")

SESSION_SECONDS = int(float(os.environ.get("SESSION_HOURS", "720")) * 3600)

# A wrong password costs the caller this much wall-clock time. The gate is
# behind CloudFront with one password and no usernames, so a slow "no" is the
# whole of the brute-force defence.
WRONG_PASSWORD_DELAY = 1.0

_secrets = None


def get_secrets():
    global _secrets
    if _secrets is None:
        _secrets = {
            "private_key": ssm.get_parameter(
                Name=os.environ["SSM_PRIVATE_KEY_PARAM"], WithDecryption=True
            )["Parameter"]["Value"],
            "password": ssm.get_parameter(
                Name=os.environ["SSM_PASSWORD_PARAM"], WithDecryption=True
            )["Parameter"]["Value"],
            "session_secret": ssm.get_parameter(
                Name=os.environ["SSM_SESSION_SECRET_PARAM"], WithDecryption=True
            )["Parameter"]["Value"],
        }
    return _secrets


# ---------------------------------------------------------------------------
# CloudFront signed cookies
# ---------------------------------------------------------------------------

CF_TRANSLATION = str.maketrans("+=/", "-_~")


def cf_b64(raw):
    """base64 in CloudFront's URL-safe alphabet."""
    return base64.b64encode(raw).decode("ascii").translate(CF_TRANSLATION)


def signed_cookies(private_key_pem, key_pair_id, resource, expires_at):
    policy = json.dumps(
        {
            "Statement": [
                {
                    "Resource": resource,
                    "Condition": {"DateLessThan": {"AWS:EpochTime": expires_at}},
                }
            ]
        },
        separators=(",", ":"),
    ).encode("utf-8")

    key = serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
    signature = key.sign(policy, padding.PKCS1v15(), hashes.SHA1())

    return {
        "CloudFront-Policy": cf_b64(policy),
        "CloudFront-Signature": cf_b64(signature),
        "CloudFront-Key-Pair-Id": key_pair_id,
    }


# ---------------------------------------------------------------------------
# session cookie for /api/*
#
# Signed cookies gate what CloudFront serves, but items-api sits behind a
# Lambda Function URL and has to decide for itself. This is the smallest thing
# that lets it: "<expiry>.<hmac of expiry>".
# ---------------------------------------------------------------------------


def make_session(secret, expires_at):
    payload = str(expires_at)
    mac = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return "%s.%s" % (payload, mac)


# ---------------------------------------------------------------------------
# responses
# ---------------------------------------------------------------------------


def cookie_attrs(max_age=None, path="/"):
    base = "Domain=%s; Path=%s; Secure; HttpOnly; SameSite=Lax" % (
        os.environ["COOKIE_DOMAIN"],
        path,
    )
    return base if max_age is None else "%s; Max-Age=%d" % (base, max_age)


def json_response(status, payload, cookies=None):
    response = {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"},
        "body": json.dumps(payload),
    }
    if cookies:
        response["cookies"] = cookies
    return response


def expired_cookies():
    return [
        "CloudFront-Policy=deleted; " + cookie_attrs(0),
        "CloudFront-Signature=deleted; " + cookie_attrs(0),
        "CloudFront-Key-Pair-Id=deleted; " + cookie_attrs(0),
        "mm_session=deleted; " + cookie_attrs(0, "/api"),
    ]


def handle_login(event):
    try:
        body = json.loads(event.get("body") or "{}")
    except ValueError:
        return json_response(400, {"error": "Invalid JSON body."})

    supplied = str(body.get("password") or "")
    secrets = get_secrets()

    if not hmac.compare_digest(supplied, secrets["password"]):
        time.sleep(WRONG_PASSWORD_DELAY)
        return json_response(401, {"error": "That's not it."})

    expires_at = int(time.time()) + SESSION_SECONDS
    cookies = [
        "%s=%s; %s" % (name, value, cookie_attrs(SESSION_SECONDS))
        for name, value in signed_cookies(
            secrets["private_key"],
            os.environ["CLOUDFRONT_KEY_PAIR_ID"],
            os.environ["COOKIE_RESOURCE"],
            expires_at,
        ).items()
    ]
    cookies.append(
        "mm_session=%s; %s"
        % (make_session(secrets["session_secret"], expires_at), cookie_attrs(SESSION_SECONDS, "/api"))
    )
    return json_response(200, {"ok": True}, cookies)


def handler(event, _context):
    # Only CloudFront should ever be able to invoke this function.
    if (event.get("headers") or {}).get("x-origin-verify") != os.environ["ORIGIN_VERIFY_SECRET"]:
        return {"statusCode": 403, "body": "Forbidden"}

    method = ((event.get("requestContext") or {}).get("http") or {}).get("method", "GET")
    path = event.get("rawPath") or "/"

    try:
        if path.endswith("/logout"):
            return {
                "statusCode": 302,
                "headers": {"Location": "/login.html", "Cache-Control": "no-store"},
                "cookies": expired_cookies(),
                "body": "",
            }

        if method == "POST" and path.endswith("/login"):
            return handle_login(event)

        return json_response(404, {"error": "Not found."})
    except Exception:
        log.exception("gate error")
        return json_response(500, {"error": "Something went wrong -- try again."})
