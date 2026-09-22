#!/usr/bin/env python3
"""Assemble the Lambda bundles Terraform zips up.

For each function directory under infrastructure/lambda/, this copies the
handler and installs its requirements into infrastructure/build/<name>/.
Terraform's archive_file then zips that directory.

Dependencies are installed for Lambda's platform (manylinux, cp312), not for
whatever machine this runs on, so building on Windows produces a bundle that
works on Lambda.

    python scripts/build_lambdas.py

Run it before `terraform apply`, and again after changing a handler or its
requirements.txt.
"""

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LAMBDA_DIR = REPO_ROOT / "infrastructure" / "lambda"
BUILD_DIR = REPO_ROOT / "infrastructure" / "build"

PYTHON_VERSION = "3.12"
PLATFORM = "manylinux2014_x86_64"


def build(function_dir):
    name = function_dir.name
    target = BUILD_DIR / name

    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    for path in function_dir.glob("*.py"):
        shutil.copy2(path, target / path.name)

    requirements = function_dir / "requirements.txt"
    if requirements.exists():
        subprocess.run(
            [
                sys.executable, "-m", "pip", "install",
                "--target", str(target),
                "--requirement", str(requirements),
                "--platform", PLATFORM,
                "--python-version", PYTHON_VERSION,
                "--implementation", "cp",
                "--only-binary=:all:",
                "--upgrade",
                "--quiet",
            ],
            check=True,
        )

    # Neither is used at runtime and both make the zip bigger and its hash
    # unstable between builds.
    for junk in list(target.rglob("__pycache__")) + list(target.glob("*.dist-info")):
        shutil.rmtree(junk, ignore_errors=True)

    size = sum(p.stat().st_size for p in target.rglob("*") if p.is_file())
    print("built %-14s %5.1f MB" % (name, size / 1e6))


def main():
    functions = sorted(p for p in LAMBDA_DIR.iterdir() if p.is_dir())
    if not functions:
        raise SystemExit("no function directories under %s" % LAMBDA_DIR)
    for function_dir in functions:
        build(function_dir)


if __name__ == "__main__":
    main()
