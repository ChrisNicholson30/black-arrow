#!/usr/bin/env python3
"""Fetch the prebuilt V8 that the code-mode host is built against.

`codex-code-mode-host` embeds V8 with pointer compression and the V8 sandbox
switched on. The `v8` crate publishes no prebuilt library for that
combination, so a plain `cargo build` of the workspace fails in its build
script. Upstream builds its own and publishes it on the Codex GitHub releases;
its CI downloads that, checks it against a manifest committed in the
repository, and points the build at it. This script does the same.

    fetch_v8.py            download if needed, verify, print the two variables
    fetch_v8.py --check    verify what is already downloaded; never download

It prints shell assignments for the variables the `v8` build script reads:

    RUSTY_V8_ARCHIVE=/.../librusty_v8_ptrcomp_sandbox_release_<target>.a.gz
    RUSTY_V8_SRC_BINDING_PATH=/.../src_binding_ptrcomp_sandbox_release_<target>.rs

Trust: the per-target checksum list is downloaded, and must itself match the
SHA-256 recorded in third_party/v8/rusty_v8_<version>_release_manifests.sha256,
which comes from upstream's repository at the commit Black Arrow is based on.
The library and binding must then match that list. Nothing unverified is ever
handed to the build.

The `blackarrow` executable does not link V8. Only the code-mode host does,
along with the tests that start it.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = REPO_ROOT / "codex-rs"
PROFILE = "ptrcomp_sandbox_release"
RELEASES = "https://github.com/openai/codex/releases/download"


def v8_version() -> str:
    """The version of the `v8` crate the workspace is locked to."""
    lock = (WORKSPACE / "Cargo.lock").read_text(encoding="utf-8")
    match = re.search(r'\[\[package\]\]\nname = "v8"\nversion = "([^"]+)"', lock)
    if not match:
        raise SystemExit("could not find the v8 crate in codex-rs/Cargo.lock")
    return match.group(1)


def host_target() -> str:
    try:
        output = subprocess.run(
            ["rustc", "-vV"], cwd=WORKSPACE, capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return "aarch64-apple-darwin"
    match = re.search(r"^host: (\S+)$", output, re.MULTILINE)
    return match.group(1) if match else "aarch64-apple-darwin"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_checksums(text: str) -> dict:
    """`<sha256>  <name>` lines, as sha256sum writes them. CRLF tolerated."""
    entries = {}
    for line in text.replace("\r", "").splitlines():
        parts = line.split()
        if len(parts) == 2:
            entries[parts[1].lstrip("*")] = parts[0].lower()
    return entries


def download(url: str, destination: Path) -> None:
    partial = destination.with_suffix(destination.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as response, partial.open("wb") as handle:
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            handle.write(chunk)
    partial.replace(destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="verify existing files; do not download")
    parser.add_argument("--target", default=None, help="Rust target triple (default: this machine's)")
    args = parser.parse_args()

    version = v8_version()
    target = args.target or host_target()
    trusted_path = REPO_ROOT / "third_party" / "v8" / f"rusty_v8_{version.replace('.', '_')}_release_manifests.sha256"
    if not trusted_path.exists():
        print(
            f"no trusted checksums for v8 {version}: {trusted_path.relative_to(REPO_ROOT)} is missing.\n"
            "Upstream adds one when it changes the v8 version; take it from upstream with the merge.",
            file=sys.stderr,
        )
        return 1
    trusted = parse_checksums(trusted_path.read_text(encoding="utf-8"))

    suffix = "lib.gz" if target.endswith("-pc-windows-msvc") else "a.gz"
    prefix = "" if target.endswith("-pc-windows-msvc") else "lib"
    archive_name = f"{prefix}rusty_v8_{PROFILE}_{target}.{suffix}"
    binding_name = f"src_binding_{PROFILE}_{target}.rs"
    manifest_name = f"rusty_v8_{PROFILE}_{target}.sha256"
    if manifest_name not in trusted:
        print(f"upstream publishes no V8 build for {target}", file=sys.stderr)
        return 1

    directory = WORKSPACE / "target" / "rusty_v8" / version
    directory.mkdir(parents=True, exist_ok=True)
    base_url = f"{RELEASES}/rusty-v8-v{version}"
    manifest_path = directory / manifest_name
    archive_path = directory / archive_name
    binding_path = directory / binding_name

    def verified() -> bool:
        if not (manifest_path.exists() and archive_path.exists() and binding_path.exists()):
            return False
        if sha256(manifest_path) != trusted[manifest_name]:
            return False
        expected = parse_checksums(manifest_path.read_text(encoding="utf-8"))
        return (
            expected.get(archive_name) == sha256(archive_path)
            and expected.get(binding_name) == sha256(binding_path)
        )

    if not verified():
        if args.check:
            print("the V8 archive is missing or does not match its checksums", file=sys.stderr)
            return 1
        try:
            for name, path in ((manifest_name, manifest_path), (archive_name, archive_path), (binding_name, binding_path)):
                print(f"downloading {name}", file=sys.stderr)
                download(f"{base_url}/{name}", path)
        except OSError as error:
            print(f"could not download the V8 archive: {error}", file=sys.stderr)
            return 1
        if not verified():
            for path in (manifest_path, archive_path, binding_path):
                path.unlink(missing_ok=True)
            print(
                "the downloaded V8 files do not match the checksums in "
                f"{trusted_path.relative_to(REPO_ROOT)}; they were deleted",
                file=sys.stderr,
            )
            return 1

    print(f"RUSTY_V8_ARCHIVE={archive_path}")
    print(f"RUSTY_V8_SRC_BINDING_PATH={binding_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
