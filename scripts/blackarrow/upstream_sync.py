#!/usr/bin/env python3
"""Keep the Black Arrow fork mergeable with upstream Codex.

Black Arrow differs from upstream in four mechanical ways, and each has a rule
that can be re-applied by a program instead of by hand:

  pruned paths   files Black Arrow does not carry    pruned-paths.txt
  owned paths    files Black Arrow writes itself     owned-paths.txt
  rewritten text `codex ...` advice in messages,     rebrand_command_hints.py
                 and the other rules in that script
  snapshot names test snapshots named after the binary crate

Everything else that differs is a deliberate code change, listed in
docs/architecture.md, and has to be merged by a person.

Commands:

  check      Verify the working tree follows the rules. Exit 1 if it does not.
             Safe to run at any time; changes nothing. It also checks two
             things a merge can undo without a conflict: that hand-made changes
             still carry their note, and that every default in defaults.rs is
             still read by the code it is meant to change.

  footprint  Count how the tree differs from upstream: what is pruned, what a
             script rewrote, what was changed by hand, what is fork-only.

  prune      Delete every file that matches pruned-paths.txt.

  tidy-snapshots
             Run after refreshing snapshots with INSTA_UPDATE=always. Puts
             upstream's header back on every snapshot the refresh touched, and
             restores the ones whose contents did not change at all, so only
             real differences are left to review.

  merge      Merge an upstream ref into the current branch and apply the rules
             to the result. Leaves the merge uncommitted so it can be built,
             tested, and reviewed first.

Typical sync, from a clean tree on the `upstream-sync` branch:

  scripts/blackarrow/upstream_sync.py merge upstream/main
  # resolve anything listed under "needs a person"
  INSTA_UPDATE=always scripts/blackarrow/test.sh -p codex-tui -p codex-cli
  git diff --stat   # review regenerated snapshots
  git commit

See docs/upstream-sync.md for the full procedure.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
PRUNED = HERE / "pruned-paths.txt"
OWNED = HERE / "owned-paths.txt"
REBRAND = HERE / "rebrand_command_hints.py"
DEFAULTS_SOURCE = "codex-rs/blackarrow/base/src/defaults.rs"

sys.path.insert(0, str(HERE))
import rebrand_command_hints as rebrand  # noqa: E402

UPSTREAM_REF = "upstream/main"

# A hand-made change to an upstream file has to say that it is Black Arrow's:
# in a comment, or by naming one of its crates or variables. `check` enforces
# this so that every such change can be found again when upstream moves the code.
CHANGE_MARKERS = ("Black Arrow", "blackarrow", "BLACKARROW")

# Unit-test snapshots inside a binary crate are named after the binary. The
# public binary is `blackarrow`, so snapshots upstream adds as `codex__*` have
# to be renamed before the tests can find them.
BIN_SNAPSHOT_DIRS = ("codex-rs/cli/src/",)
UPSTREAM_SNAPSHOT_PREFIX = "codex__"
SNAPSHOT_PREFIX = "blackarrow__"


def git(*args: str, check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout


def git_paths(*args: str) -> list:
    return [line for line in git(*args, "-z").split("\0") if line]


class PathRules:
    """A list of path patterns where later lines override earlier ones."""

    def __init__(self, path: Path) -> None:
        self.rules = []
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            keep = line.startswith("!")
            self.rules.append((line.lstrip("!"), keep))

    @staticmethod
    def _matches(pattern: str, path: str) -> bool:
        if pattern.startswith("**/"):
            tail = pattern[3:]
            name = path.rsplit("/", 1)[-1]
            return fnmatch.fnmatchcase(name, tail)
        if pattern.endswith("/"):
            return path.startswith(pattern)
        return path == pattern

    def match(self, path: str) -> bool:
        matched = False
        for pattern, keep in self.rules:
            if self._matches(pattern, path):
                matched = not keep
        return matched


def tracked_files() -> list:
    return git_paths("ls-files")


def untracked_files() -> list:
    return git_paths("ls-files", "--others", "--exclude-standard")


def misnamed_snapshots(paths: list) -> list:
    return [
        path
        for path in paths
        if path.endswith(".snap")
        and path.startswith(BIN_SNAPSHOT_DIRS)
        and path.rsplit("/", 1)[-1].startswith(UPSTREAM_SNAPSHOT_PREFIX)
    ]


def renamed_snapshot(path: str) -> str:
    directory, name = path.rsplit("/", 1)
    return f"{directory}/{SNAPSHOT_PREFIX}{name[len(UPSTREAM_SNAPSHOT_PREFIX):]}"


def run_rebrand(check: bool) -> int:
    command = [sys.executable, str(REBRAND)] + (["--check"] if check else [])
    return subprocess.run(command, cwd=REPO_ROOT).returncode


def exists_in(ref: str, path: str) -> bool:
    return subprocess.run(
        ["git", "cat-file", "-e", f"{ref}:{path}"], cwd=REPO_ROOT, capture_output=True
    ).returncode == 0


def text_at(ref: str, path: str):
    """The file's text at `ref`, or None if it is absent there or not UTF-8."""
    result = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=REPO_ROOT, capture_output=True)
    if result.returncode != 0:
        return None
    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None


def text_now(path: str):
    """The file's text in the working tree, or None if it is absent or not UTF-8."""
    try:
        return (REPO_ROOT / path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def upstream_base():
    """The newest commit shared with upstream, or None if upstream is unknown here."""
    result = subprocess.run(
        ["git", "merge-base", "HEAD", UPSTREAM_REF], cwd=REPO_ROOT, capture_output=True, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else None


def cargo_tool(name: str):
    """Path of a rustup-managed tool, whether or not ~/.cargo/bin is on PATH."""
    found = shutil.which(name)
    if found:
        return found
    cargo_home = Path(os.environ.get("CARGO_HOME", Path.home() / ".cargo"))
    candidate = cargo_home / "bin" / name
    return str(candidate) if candidate.exists() else None


def formatted(path: str, text: str) -> str:
    """`text` laid out by rustfmt. Unchanged if it is not Rust or rustfmt is missing.

    Rewriting `codex` to `blackarrow` makes lines longer, so the rewrite is
    always followed by rustfmt, and the pair is what counts as mechanical.
    """
    rustfmt = cargo_tool("rustfmt") if path.endswith(".rs") else None
    if rustfmt is None:
        return text
    workspace = REPO_ROOT / "codex-rs"
    result = subprocess.run(
        [rustfmt, "--config-path", str(workspace / "rustfmt.toml")],
        input=text,
        capture_output=True,
        text=True,
        cwd=workspace,
    )
    return result.stdout if result.returncode == 0 and result.stdout else text


def differs_only_by_rewrite(base: str, path: str, ours, upstream_path=None) -> bool:
    """Whether `ours` is upstream's copy at `base` with the codemod applied.

    If so, the difference carries no decision: upstream's newer copy, rewritten
    again, is the right answer. `upstream_path` is the file's name upstream when
    Black Arrow renamed it.
    """
    absolute = REPO_ROOT / path
    if ours is None or not rebrand.is_candidate(absolute):
        return False
    before = text_at(base, upstream_path or path)
    if before is None:
        return False
    rewritten = rebrand.rewrite_text(absolute, before)
    return rewritten == ours or formatted(path, rewritten) == ours


def added_lines(base: str, path: str) -> list:
    diff = git("diff", "-U0", base, "--", path)
    return [line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]


class Footprint:
    """How the working tree differs from upstream at `base`."""

    def __init__(self, base: str) -> None:
        owned = PathRules(OWNED)
        pruned = PathRules(PRUNED)
        self.base = base
        self.pruned = []        # upstream files not carried
        self.owned = []         # upstream files replaced wholesale
        self.rewritten = []     # changed only by the codemod
        self.regenerated = []   # snapshots refreshed by the tests
        self.by_hand = []       # deliberate changes
        self.undocumented = []  # deliberate changes with no marker
        self.fork_only = []     # files upstream does not have

        changes = git("diff", "--name-status", "--no-renames", "-z", base).split("\0")
        changes = list(zip(changes[0::2], changes[1::2]))
        # A snapshot renamed after the binary shows up as a deletion and an
        # addition. Treat the pair as one changed file under its new name.
        renames = {
            renamed_snapshot(path): path
            for status, path in changes
            if status == "D" and path in misnamed_snapshots([path])
        }
        for status, path in changes:
            if status == "D":
                if path in renames.values():
                    continue
                (self.pruned if pruned.match(path) else self.owned).append(path)
            elif status == "A" and path not in renames:
                self.fork_only.append(path)
            elif owned.match(path):
                self.owned.append(path)
            elif differs_only_by_rewrite(base, path, text_now(path), renames.get(path, path)):
                self.rewritten.append(path)
            elif path.endswith(".snap"):
                self.regenerated.append(path)
            else:
                self.by_hand.append(path)
                added = added_lines(base, path)
                if added and not any(marker in line for line in added for marker in CHANGE_MARKERS):
                    self.undocumented.append(path)
        self.fork_only.extend(untracked_files())


def is_test_path(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return "/tests/" in path or name.endswith("_tests.rs") or name == "tests.rs" or "/service_tests/" in path


def unread_defaults() -> list:
    """Fields of `Defaults` that no upstream file reads any more.

    Each default Black Arrow changes takes effect at one call site inside an
    upstream file, written `defaults::current().<field>`. A merge that rewrites
    the code around it can drop the call without breaking the build or a test,
    and the default goes back to upstream's with nothing to show for it.

    Fork-only files do not count: they report the defaults, they do not apply
    them.
    """
    text = (REPO_ROOT / DEFAULTS_SOURCE).read_text(encoding="utf-8")
    body = re.search(r"pub struct Defaults \{(.*?)\n\}", text, re.DOTALL)
    fields = re.findall(r"^\s*pub (\w+):", body.group(1), re.MULTILINE) if body else []
    unread = set(fields)
    for path in tracked_files() + untracked_files():
        if not path.endswith(".rs") or "blackarrow" in path or not unread:
            continue
        try:
            source = (REPO_ROOT / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "defaults::current()" not in source:
            continue
        for field in sorted(unread):
            if re.search(rf"defaults::current\(\)\s*\.\s*{field}\b", source):
                unread.discard(field)
    return [field for field in fields if field in unread]


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------


def command_check(_args) -> int:
    pruned = PathRules(PRUNED)
    problems = 0

    leftovers = [path for path in tracked_files() if pruned.match(path)]
    if leftovers:
        problems += 1
        print(f"{len(leftovers)} tracked file(s) match pruned-paths.txt:")
        for path in leftovers[:20]:
            print(f"  {path}")
        if len(leftovers) > 20:
            print(f"  ... and {len(leftovers) - 20} more")
        print("  fix: scripts/blackarrow/upstream_sync.py prune\n")

    snapshots = misnamed_snapshots(tracked_files())
    if snapshots:
        problems += 1
        print(f"{len(snapshots)} snapshot(s) still use the upstream binary name:")
        for path in snapshots:
            print(f"  {path}")
        print("  fix: scripts/blackarrow/upstream_sync.py merge renames these; or git mv by hand\n")

    if run_rebrand(check=True) != 0:
        problems += 1
        print("  fix: scripts/blackarrow/rebrand_command_hints.py\n")

    base = upstream_base()
    if base is None:
        print(f"note: {UPSTREAM_REF} is not available, so hand-made changes were not checked for notes.")
        print("  fix: git remote add upstream https://github.com/openai/codex.git && git fetch upstream main\n")
    else:
        undocumented = Footprint(base).undocumented
        if undocumented:
            problems += 1
            print(f"{len(undocumented)} upstream file(s) changed by hand without a note saying why:")
            for path in undocumented:
                print(f"  {path}")
            print("  fix: add a `Black Arrow:` comment beside the change\n")

    unread = unread_defaults()
    if unread:
        problems += 1
        print(f"{len(unread)} default(s) in {DEFAULTS_SOURCE} are no longer read by any upstream file:")
        for field in unread:
            print(f"  {field}")
        print(
            "  fix: put back the `defaults::current().<name>` call that a merge removed; "
            "docs/architecture.md says where each belongs\n"
        )

    if problems:
        print(f"{problems} rule(s) violated.")
        return 1
    print(
        "Fork rules hold: nothing pruned is tracked, snapshots are named correctly, "
        "text is rewritten, hand-made changes are marked, and every default is read."
    )
    return 0


# ---------------------------------------------------------------------------
# footprint
# ---------------------------------------------------------------------------


def command_footprint(args) -> int:
    base = upstream_base()
    if base is None:
        print(f"{UPSTREAM_REF} is not available; fetch it first.")
        return 1
    footprint = Footprint(base)
    by_hand_tests = [path for path in footprint.by_hand if is_test_path(path)]
    by_hand_manifests = [path for path in footprint.by_hand if path.endswith(("Cargo.toml", "Cargo.lock"))]
    by_hand_source = [
        path for path in footprint.by_hand if path not in by_hand_tests and path not in by_hand_manifests
    ]
    rewritten_tests = [path for path in footprint.rewritten if is_test_path(path) or path.endswith(".snap")]
    rows = [
        ("upstream files not carried", len(footprint.pruned)),
        ("upstream files replaced wholesale", len(footprint.owned)),
        ("changed only by the codemod", len(footprint.rewritten)),
        ("  of which tests and snapshots", len(rewritten_tests)),
        ("snapshots refreshed by the tests", len(footprint.regenerated)),
        ("changed by hand", len(footprint.by_hand)),
        ("  source", len(by_hand_source)),
        ("  tests", len(by_hand_tests)),
        ("  manifests", len(by_hand_manifests)),
        ("fork-only files", len(footprint.fork_only)),
    ]
    print(f"Against upstream at {base[:10]}:")
    for label, count in rows:
        print(f"  {label:36} {count:5}")
    if args.list:
        for title, paths in (
            ("changed by hand: source", by_hand_source),
            ("changed by hand: tests", by_hand_tests),
            ("changed by hand: manifests", by_hand_manifests),
        ):
            print(f"\n{title}")
            for path in paths:
                print(f"  {path}")
    return 0


# ---------------------------------------------------------------------------
# prune
# ---------------------------------------------------------------------------


def prune(quiet: bool = False) -> int:
    pruned = PathRules(PRUNED)
    tracked = [path for path in tracked_files() if pruned.match(path)]
    for start in range(0, len(tracked), 200):
        git("rm", "-r", "-f", "-q", "--ignore-unmatch", "--", *tracked[start : start + 200])
    stray = [path for path in untracked_files() if pruned.match(path)]
    for path in stray:
        (REPO_ROOT / path).unlink(missing_ok=True)
    if not quiet:
        print(f"removed {len(tracked)} tracked and {len(stray)} untracked file(s)")
    return len(tracked) + len(stray)


def command_prune(_args) -> int:
    prune()
    return 0


# ---------------------------------------------------------------------------
# tidy-snapshots
# ---------------------------------------------------------------------------


def split_snapshot(text: str):
    """Split a snapshot file into its header (both `---` lines included) and its contents."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end == -1:
        return None
    return text[: end + 5], text[end + 5 :]


def without_clock(line: str) -> str:
    """The line with elapsed-time counters and the spinner frame blanked out."""
    return re.sub(r"\(\d+s\b", "(Ns", line).replace("◦", "•")


def clock_artifacts(before: str, now: str) -> list:
    """Lines that differ from upstream only by a timer or a spinner frame.

    Some snapshots render "Working (0s" a moment after a task starts. On a
    busy machine the moment is longer, the snapshot says "(2s", and a refresh
    writes that down as if the code had changed.
    """
    old_lines, new_lines = before.splitlines(), now.splitlines()
    if len(old_lines) != len(new_lines):
        return []
    return [
        (old, new)
        for old, new in zip(old_lines, new_lines)
        if old != new and without_clock(old) == without_clock(new)
    ]


def command_tidy_snapshots(_args) -> int:
    """Undo the parts of a snapshot refresh that carry no information.

    A refresh rewrites the header of every snapshot it touches: the line number
    of the assertion, and the expression as currently written. Upstream does
    not keep those current, so rewriting them only makes merges conflict.
    """
    base = upstream_base()
    if base is None:
        print(f"{UPSTREAM_REF} is not available; fetch it first.")
        return 1
    changes = git("diff", "--name-status", "--no-renames", "-z", base).split("\0")
    changes = list(zip(changes[0::2], changes[1::2]))
    renames = {
        renamed_snapshot(path): path
        for status, path in changes
        if status == "D" and path in misnamed_snapshots([path])
    }
    restored = reheaded = 0
    suspicious = []
    for status, path in changes:
        if status == "D" or not path.endswith(".snap"):
            continue
        before = text_at(base, renames.get(path, path))
        now = text_now(path)
        if before is None or now is None or before == now:
            continue
        if clock_artifacts(before, now):
            suspicious.append(path)
        upstream = split_snapshot(before)
        ours = split_snapshot(now)
        if upstream is None or ours is None:
            continue
        # insta ignores blank lines at either end when it compares.
        if upstream[1].strip("\r\n") == ours[1].strip("\r\n"):
            (REPO_ROOT / path).write_text(before, encoding="utf-8")
            restored += 1
        elif upstream[0] != ours[0]:
            (REPO_ROOT / path).write_text(upstream[0] + ours[1], encoding="utf-8")
            reheaded += 1
    print(f"restored {restored} snapshot(s) whose contents had not changed")
    print(f"put upstream's header back on {reheaded} snapshot(s) whose contents did")
    if suspicious:
        print(f"\n{len(suspicious)} snapshot(s) differ from upstream only in a timer or spinner frame:")
        for path in suspicious:
            print(f"  {path}")
        print(
            "That is what a refresh on a busy machine looks like, not a code change.\n"
            "Restore each with `git checkout <upstream ref> -- <path>` and re-run its test on its own."
        )
        return 1
    return 0


# ---------------------------------------------------------------------------
# merge
# ---------------------------------------------------------------------------


def unmerged_paths() -> list:
    return sorted(set(git_paths("diff", "--name-only", "--diff-filter=U")))


def command_merge(args) -> int:
    if git("status", "--porcelain").strip():
        print("The working tree has uncommitted changes. Commit or stash them first.")
        return 1

    ref = args.ref
    base = git("merge-base", "HEAD", ref).strip()
    incoming = git("rev-list", "--count", f"HEAD..{ref}").strip()
    if incoming == "0":
        print(f"Already up to date with {ref}.")
        return 0
    print(f"Merging {incoming} upstream commit(s) from {ref} (common ancestor {base[:10]}).")

    merge = subprocess.run(
        ["git", "merge", "--no-commit", "--no-ff", ref], cwd=REPO_ROOT, capture_output=True, text=True
    )
    if merge.returncode != 0 and "CONFLICT" not in merge.stdout:
        print(merge.stdout + merge.stderr)
        return 1

    pruned = PathRules(PRUNED)
    owned = PathRules(OWNED)

    # 1. Pruned paths: gone, whatever upstream did to them.
    removed = prune(quiet=True)
    for path in unmerged_paths():
        if pruned.match(path):
            git("rm", "-f", "-q", "--ignore-unmatch", "--", path)
            removed += 1

    # 2. Owned paths: Black Arrow's version, or nothing if Black Arrow has none.
    restored = dropped = 0
    candidates = set(unmerged_paths()) | set(git_paths("diff", "--cached", "--name-only", "HEAD"))
    for path in sorted(candidates):
        if not owned.match(path):
            continue
        if exists_in("HEAD", path):
            git("checkout", "HEAD", "--", path)
            restored += 1
        else:
            git("rm", "-f", "-q", "--ignore-unmatch", "--", path)
            dropped += 1

    # 3. Snapshots: take upstream's rendering, then let the tests re-brand it.
    snapshots_taken = 0
    for path in unmerged_paths():
        if path.endswith(".snap") and exists_in(ref, path):
            git("checkout", "--theirs", "--", path)
            git("add", "--", path)
            snapshots_taken += 1

    # 4. Files Black Arrow changed only through the codemod: take upstream's
    #    new text and let the codemod rewrite it again in step 6.
    rewritten_again = 0
    for path in unmerged_paths():
        if exists_in(ref, path) and differs_only_by_rewrite(base, path, text_at("HEAD", path)):
            git("checkout", "--theirs", "--", path)
            git("add", "--", path)
            rewritten_again += 1

    # 5. Snapshots named after the binary crate.
    renamed = 0
    for path in misnamed_snapshots(tracked_files()):
        target = renamed_snapshot(path)
        if (REPO_ROOT / target).exists():
            # Upstream changed a snapshot Black Arrow already renamed.
            (REPO_ROOT / target).write_bytes((REPO_ROOT / path).read_bytes())
            git("rm", "-f", "-q", "--", path)
            git("add", "--", target)
        else:
            git("mv", path, target)
        renamed += 1

    # 6. The codemod, over anything upstream added or rewrote, then rustfmt,
    #    because the rewritten text is longer than what it replaced.
    run_rebrand(check=False)
    cargo = cargo_tool("cargo")
    if cargo is None:
        print("cargo was not found, so rewritten files were not reformatted; run `cargo fmt --all`.")
    else:
        subprocess.run([cargo, "fmt", "--all"], cwd=REPO_ROOT / "codex-rs", capture_output=True)

    remaining = unmerged_paths()
    print()
    print(f"  pruned paths removed          {removed}")
    print(f"  owned paths kept              {restored} (plus {dropped} upstream addition(s) dropped)")
    print(f"  snapshots taken from upstream {snapshots_taken}")
    print(f"  rewritten files re-taken      {rewritten_again}")
    print(f"  snapshots renamed             {renamed}")
    print()
    if remaining:
        print(f"{len(remaining)} file(s) need a person:")
        for path in remaining:
            print(f"  {path}")
        print("\nResolve them, `git add` each one, then continue below.")
    else:
        print("No conflicts left.")
    print(
        "\nNext:\n"
        "  (cd codex-rs && cargo build --bin blackarrow)\n"
        "  INSTA_UPDATE=always scripts/blackarrow/test.sh -p codex-tui -p codex-cli   # re-brand snapshots\n"
        "  scripts/blackarrow/upstream_sync.py check\n"
        "  git commit"
    )
    return 2 if remaining else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="verify the tree follows the fork rules").set_defaults(run=command_check)
    footprint = commands.add_parser("footprint", help="count how the tree differs from upstream")
    footprint.add_argument("--list", action="store_true", help="also list the files changed by hand")
    footprint.set_defaults(run=command_footprint)
    commands.add_parser("prune", help="delete files matching pruned-paths.txt").set_defaults(run=command_prune)
    commands.add_parser(
        "tidy-snapshots", help="drop header-only changes left by a snapshot refresh"
    ).set_defaults(run=command_tidy_snapshots)
    merge = commands.add_parser("merge", help="merge an upstream ref and re-apply the fork rules")
    merge.add_argument("ref", nargs="?", default="upstream/main", help="ref to merge (default: upstream/main)")
    merge.set_defaults(run=command_merge)
    args = parser.parse_args()
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
