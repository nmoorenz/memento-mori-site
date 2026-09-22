#!/usr/bin/env python3
"""Run terraform with the deployment's variables taken from .env.

    python scripts/tf.py init
    python scripts/tf.py cert     stage one: the certificate, then its DNS record
    python scripts/tf.py plan
    python scripts/tf.py apply
    python scripts/tf.py output cloudfront_domain_name

Everything after the script name is passed straight through, so any terraform
command works. `-chdir=infrastructure` is added for you.

`cert` is the exception: it runs the first-stage targeted apply and then
prints the validation record, so there is no -target=type.name argument to
get mangled by the shell (PowerShell drops the part after the dot).

.env is the one place a deployment's own names live, and it is gitignored.
A terraform.tfvars or *.auto.tfvars file would override it without saying so,
so this script refuses to run while one exists.
This maps it to the TF_VAR_* variables terraform looks for:

    S3_BUCKET              -> TF_VAR_bucket_name
    DOMAIN_NAME            -> TF_VAR_domain_name
    AWS_PROFILE            -> TF_VAR_aws_profile
    SITE_PASSWORD          -> TF_VAR_site_password
    AWS_REGION             -> TF_VAR_aws_region
    PROJECT_NAME           -> TF_VAR_project_name
    SESSION_HOURS          -> TF_VAR_session_hours

Any missing Lambda bundle is built first, since terraform reads the
archive_file data sources during plan.

Set TERRAFORM to use a binary other than `terraform` on PATH.

Keep this file ASCII-only.
"""

import os
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"
TF_DIR = REPO_ROOT / "infrastructure"
LAMBDA_DIR = TF_DIR / "lambda"
BUILD_DIR = TF_DIR / "build"

# env var -> terraform variable, and whether the deployment needs it set
MAPPING = [
    ("S3_BUCKET", "bucket_name", True),
    ("DOMAIN_NAME", "domain_name", True),
    ("AWS_PROFILE", "aws_profile", True),
    ("SITE_PASSWORD", "site_password", True),
    ("AWS_REGION", "aws_region", False),
    ("PROJECT_NAME", "project_name", False),
    ("SESSION_HOURS", "session_hours", False),
]


def ensure_lambda_bundles():
    """Build any Lambda bundle that is missing.

    Terraform reads the archive_file data sources during plan, so a missing
    build directory stops even a targeted apply.
    """
    missing = [d.name for d in sorted(LAMBDA_DIR.iterdir())
               if d.is_dir() and not (BUILD_DIR / d.name).is_dir()]
    if not missing:
        return True

    print("building Lambda bundle(s): %s" % ", ".join(missing))
    result = subprocess.call([sys.executable, str(Path(__file__).with_name("build_lambdas.py"))])
    if result != 0:
        print("ERROR: scripts/build_lambdas.py failed -- fix that before running terraform.",
              file=sys.stderr)
        return False
    return True


CERT_RESOURCE = "aws_acm_certificate.site"

# terraform.tfvars and *.auto.tfvars are loaded automatically and OUTRANK the
# TF_VAR_* environment variables this script sets, so one of them can
# silently override .env. There should not be one.
TFVARS_GLOBS = ["terraform.tfvars", "terraform.tfvars.json", "*.auto.tfvars",
                "*.auto.tfvars.json"]


def check_no_tfvars():
    found = sorted({p for glob in TFVARS_GLOBS for p in TF_DIR.glob(glob)})
    if not found:
        return True
    print("ERROR: %s in %s." % (", ".join(p.name for p in found), TF_DIR),
          file=sys.stderr)
    print("Terraform loads these automatically and they override the values "
          "this script\npasses from .env, silently. Delete them and set "
          "everything in .env instead.", file=sys.stderr)
    return False


def run(terraform, env, args):
    return subprocess.call([terraform, "-chdir=%s" % TF_DIR] + args, env=env)


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2

    if not ENV_FILE.exists():
        print("ERROR: no .env -- copy env.example to .env and fill it in.", file=sys.stderr)
        return 1

    values = dotenv_values(ENV_FILE)
    env = os.environ.copy()
    missing = []

    for key, tf_name, required in MAPPING:
        value = (values.get(key) or os.environ.get(key) or "").strip()
        if value:
            env["TF_VAR_" + tf_name] = value
        elif required:
            missing.append(key)

    if missing:
        print("ERROR: .env is missing %s -- see env.example." % ", ".join(missing),
              file=sys.stderr)
        return 1

    if not check_no_tfvars():
        return 1

    if not ensure_lambda_bundles():
        return 1

    terraform = env.get("TERRAFORM", "terraform")

    if args == ["cert"]:
        result = run(terraform, env, ["apply", "-target=" + CERT_RESOURCE])
        if result != 0:
            return result
        print("\nAdd this CNAME at your registrar, then run: python scripts/tf.py apply\n")
        return run(terraform, env, ["output", "acm_validation_records"])

    return run(terraform, env, args)


if __name__ == "__main__":
    raise SystemExit(main())
