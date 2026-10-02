#!/usr/bin/env python3
"""Rewrite command hints so they name the executable Black Arrow ships.

Upstream tells users to run things like `codex resume` in well over a hundred
messages. In Black Arrow that advice is wrong, and on a machine that also has
Codex installed it sends the user to a different program. This script rewrites
those hints to `blackarrow ...`.

It is a codemod rather than a set of hand edits so that it can be re-run after
every upstream merge: take upstream's side of any conflict in a message, then
run this again. Tests and snapshots are rewritten with the same rules, so
expectations keep matching the messages they assert on.

    rebrand_command_hints.py            rewrite in place
    rebrand_command_hints.py --check    list what would change; exit 1 if any

Only command hints are touched: `codex` in backticks or quotes followed by a
subcommand, and "run codex <subcommand>". Crate names, identifiers, environment
variables, URLs, and the product name in running text are left alone.

Messages that name the configuration file to edit are pointed at Black Arrow's:
`~/.codex/config.toml` and `$CODEX_HOME/config.toml`.

The files that define command-line options get one more rewrite: their doc
comments are the `--help` text, so `~/.codex/` and `$CODEX_HOME` there become
the Black Arrow state directory.

A short list of files that make up the screens users see first also has the
product name rewritten in running text. See PRODUCT_NAME_FILES.

Tests that look for the session title or the empty-prompt text on a rendered
screen are pointed at Black Arrow's wording. See PRODUCT_TEXT_TEST_PATHS. A
test that asserts the macOS preferences domain is pointed at Black Arrow's.

In Rust sources, ordinary comments are skipped: nobody running the program sees
them, and rewriting them would only add merge conflicts. Doc comments are
included, because clap turns them into help text. A bare `codex` with nothing
after it is rewritten only outside comments, since in a comment it is as likely
to name an identifier as the command. A line containing `rebrand:keep` is never
rewritten.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO_ROOT / "codex-rs"

SUFFIXES = {".rs", ".snap"}
EXTRA_FILES = {SOURCE_ROOT / "tui" / "assets" / "tooltips.txt"}
SKIP_DIRS = {"target", "vendor", ".git", "blackarrow"}
# Files where `codex` in backticks is sample input, not advice to the user.
SKIP_FILES = {
    # Markdown rendering fixture; the expected output has no backticks to match.
    SOURCE_ROOT / "tui" / "src" / "markdown_render_tests.rs",
}
KEEP_MARKER = "rebrand:keep"

SUBCOMMANDS = (
    "agents|app-server|archive|cloud|completion|debug|delete|doctor|exec|exec-server|"
    "features|fork|login|logout|mcp|plugin|queue|remote-control|resume|review|sandbox|"
    "unarchive"
)

# Applied to every eligible line.
RULES = [
    # `codex resume`, `codex --no-daemon`
    (re.compile(r"`codex(?= )"), "`blackarrow"),
    # 'codex login'
    (re.compile(rf"'codex(?= (?:{SUBCOMMANDS})\b)"), "'blackarrow"),
    # run codex login / Run codex login / re-run codex login / run codex --remote ...
    (re.compile(rf"(?<=[Rr]un )codex(?= (?:(?:{SUBCOMMANDS})\b|--))"), "blackarrow"),
    # "  remove: codex mcp remove <name>"
    (re.compile(rf"(?<=: )codex(?= (?:{SUBCOMMANDS}) )"), "blackarrow"),
    # String literals that open with the command: the shared resume-hint
    # builder, clap usage names, and hints whose opening backtick sits on the
    # previous line. Limited to the subcommands users are told to run, so
    # internal labels such as "codex app-server (WebSockets)" are untouched.
    (re.compile(r'(?<=")codex(?= (?:resume|unarchive|plugin|mcp add)\b)'), "blackarrow"),
    # The exit summary prints the resume command bare, indented or wrapped in
    # an ANSI colour code, and tests assert on that output verbatim. A match at
    # the very start of a line is left alone: there it is a test labelling the
    # argument list it ran, which is built from argv and does not change.
    (re.compile(r"(?:(?<= )|(?<=\[\d\dm))codex(?= (?:resume|unarchive)\b)"), "blackarrow"),
    # The reconnect hint for a remote session: "  codex --remote wss://host ..."
    (re.compile(r"(?<= )codex(?= --remote\b)"), "blackarrow"),
    # "--no-daemon cannot be used with codex agents. ... Use codex --no-daemon ..."
    (re.compile(r"(?<=with )codex(?= agents\b)"), "blackarrow"),
    (re.compile(r"(?<=Use )codex(?= --no-daemon\b)"), "blackarrow"),
]

# Applied only outside comments. Messages that tell the user which file to
# edit: "Set unique keys in `~/.codex/config.toml` and retry." Only the
# configuration file is matched, so fixtures that build other paths under
# `~/.codex` are left alone. Doc comments are left alone too: on configuration
# and protocol types they are copied into generated schema files, which would
# then all differ from upstream's.
CONFIG_FILE_RULES = [
    (re.compile(r"~/\.codex/config\.toml"), "~/.blackarrow/config.toml"),
    (re.compile(r"\$CODEX_HOME/config\.toml"), "$BLACKARROW_HOME/config.toml"),
]

# Applied only outside comments: a bare `codex` naming the command itself.
BARE_RULE = (re.compile(r"`codex`"), "`blackarrow`")

# Files that define command-line options. Their doc comments are the `--help`
# text, so the state directory they name has to be Black Arrow's.
CLI_HELP_FILES = {
    SOURCE_ROOT / "cli" / "src" / "lib.rs",
    SOURCE_ROOT / "cli" / "src" / "main.rs",
    SOURCE_ROOT / "cli" / "src" / "mcp_cmd.rs",
    SOURCE_ROOT / "exec" / "src" / "cli.rs",
    SOURCE_ROOT / "tui" / "src" / "cli.rs",
    SOURCE_ROOT / "utils" / "cli" / "src" / "config_override.rs",
    SOURCE_ROOT / "utils" / "cli" / "src" / "shared_options.rs",
}
STATE_DIR_RULES = [
    (re.compile(r"~/\.codex/"), "~/.blackarrow/"),
    (re.compile(r"\$CODEX_HOME\b"), "$BLACKARROW_HOME"),
    (re.compile(r"`CODEX_HOME`"), "`BLACKARROW_HOME`"),
]

# The doctor prints the state directory under the name of the variable that
# sets it. These files produce, render, and test those rows, so the label is
# renamed in all of them together.
DOCTOR_LABEL_FILES = {
    SOURCE_ROOT / "cli" / "src" / "doctor.rs",
    SOURCE_ROOT / "cli" / "src" / "doctor" / "disk.rs",
    SOURCE_ROOT / "cli" / "src" / "doctor" / "disk_tests.rs",
    SOURCE_ROOT / "cli" / "src" / "doctor" / "output" / "detail.rs",
    SOURCE_ROOT / "cli" / "src" / "doctor" / "thread_inventory.rs",
}
DOCTOR_LABEL_RULE = (re.compile(r"\bCODEX_HOME\b"), "BLACKARROW_HOME")

# Tests that assert where the product *writes* inside a project: imported
# configuration, the external editor's scratch directory. Black Arrow writes
# under `.blackarrow`, so these expectations have to say so. Entries ending in
# `/` cover a directory.
#
# Tests that only *create* a `.codex` fixture for the product to read need no
# entry: debug builds accept upstream's directory name for exactly that reason.
# Do not add tests that assert `.codex` is protected by the sandbox either; it
# still is, and those should keep saying so.
PROJECT_DIR_TEST_PATHS = (
    "external-agent-migration/src/service_tests/",
    "tui/src/external_editor_tests.rs",
    # One test here marks the editor's candidate directories writable and
    # expects the editor to be refused; it has to name the same directories
    # the product tries.
    "tui/src/app/tests.rs",
)
PROJECT_DIR_RULE = (re.compile(r"""(?<=["'])\.codex(?=["'/])"""), ".blackarrow")


# Screens every user meets in the first minute or in everyday use: sign-in,
# permission warnings, the quit menu. In these files the product name in running
# text becomes Black Arrow, in the code and in the tests that sit beside it.
#
# This list is how the remaining "Codex" strings get worked through: add a file
# when its screen becomes part of what Black Arrow presents as its own. Names
# of things that really are Codex's, such as its documentation site, are kept.
PRODUCT_NAME_FILES = {
    SOURCE_ROOT / "tui" / "src" / "onboarding" / "auth.rs",
    SOURCE_ROOT / "tui" / "src" / "app" / "input.rs",
    SOURCE_ROOT / "tui" / "src" / "chatwidget" / "permission_popups.rs",
    # Tests that assert those screens from another file.
    SOURCE_ROOT / "tui" / "src" / "app" / "tests" / "background_exit_tests.rs",
}
PRODUCT_NAME_RULE = (re.compile(r"\bCodex\b(?! (?:docs|Cloud)\b)"), "Black Arrow")

# Tests that look for the session title or the empty-prompt text on a screen the
# product rendered. Both strings come from `blackarrow_base::brand`
# (PRODUCT_NAME, COMPOSER_PLACEHOLDER), so the expectations follow them.
#
# Tests elsewhere that hand a composer its own placeholder text need no entry:
# they render whatever they were given. Snapshot files are not rewritten by
# this rule, because a title of a different length moves what is drawn around
# it; refresh them by running the tests with INSTA_UPDATE=always.
PRODUCT_TEXT_TEST_PATHS = (
    "tui/src/app/tests.rs",
    "tui/src/app/tests/",
    "tui/src/chatwidget/rendering_tests.rs",
    "tui/tests/suite/",
)
PRODUCT_TEXT_RULES = [
    (re.compile(r"OpenAI Codex"), "Black Arrow"),
    (re.compile(r"Ask Codex to do anything"), "Describe a task"),
]


# Tests that read macOS managed preferences through the real loader and then
# assert which preferences domain the value came from. The loader reads Black
# Arrow's domain (`blackarrow_base::brand::APP_IDENTIFIER`).
#
# Tests that build a requirement source by hand and name upstream's domain in
# it need no entry: they get back what they put in.
PREFERENCES_DOMAIN_TEST_PATHS = ("core/src/config/config_loader_tests.rs",)
PREFERENCES_DOMAIN_RULE = (re.compile(r'"com\.openai\.codex"'), '"dev.blackarrow"')


def listed(path: Path, entries) -> bool:
    """Whether `path` is one of `entries`; an entry ending in `/` is a directory."""
    relative = path.relative_to(SOURCE_ROOT).as_posix()
    return any(
        relative.startswith(entry) if entry.endswith("/") else relative == entry
        for entry in entries
    )


@dataclass(frozen=True)
class Traits:
    """Which rule families apply to a file."""

    is_rust: bool = False
    is_cli_help: bool = False
    is_doctor_label: bool = False
    has_project_fixtures: bool = False
    names_product: bool = False
    asserts_product_text: bool = False
    asserts_preferences_domain: bool = False


def traits_for(path: Path) -> Traits:
    return Traits(
        is_rust=path.suffix == ".rs",
        is_cli_help=path in CLI_HELP_FILES,
        is_doctor_label=path in DOCTOR_LABEL_FILES,
        has_project_fixtures=listed(path, PROJECT_DIR_TEST_PATHS),
        names_product=path in PRODUCT_NAME_FILES,
        asserts_product_text=path.suffix == ".rs" and listed(path, PRODUCT_TEXT_TEST_PATHS),
        asserts_preferences_domain=listed(path, PREFERENCES_DOMAIN_TEST_PATHS),
    )


def is_candidate(path: Path) -> bool:
    """Whether this script rewrites `path` at all."""
    try:
        parts = path.relative_to(SOURCE_ROOT).parts
    except ValueError:
        return False
    if any(part in SKIP_DIRS for part in parts[:-1]) or path in SKIP_FILES:
        return False
    return path.suffix in SUFFIXES or path in EXTRA_FILES


def candidate_files():
    for path in sorted(SOURCE_ROOT.rglob("*")):
        if path.is_file() and is_candidate(path):
            yield path


def rewrite_line(line: str, traits: Traits) -> str:
    if KEEP_MARKER in line:
        return line
    stripped = line.lstrip()
    is_doc_comment = traits.is_rust and stripped.startswith("///")
    if traits.is_rust and stripped.startswith("//") and not is_doc_comment:
        return line
    for pattern, replacement in RULES:
        line = pattern.sub(replacement, line)
    if not is_doc_comment:
        line = BARE_RULE[0].sub(BARE_RULE[1], line)
        for pattern, replacement in CONFIG_FILE_RULES:
            line = pattern.sub(replacement, line)
        if traits.is_doctor_label:
            line = DOCTOR_LABEL_RULE[0].sub(DOCTOR_LABEL_RULE[1], line)
        if traits.has_project_fixtures:
            line = PROJECT_DIR_RULE[0].sub(PROJECT_DIR_RULE[1], line)
        if traits.names_product:
            line = PRODUCT_NAME_RULE[0].sub(PRODUCT_NAME_RULE[1], line)
        if traits.asserts_product_text:
            for pattern, replacement in PRODUCT_TEXT_RULES:
                line = pattern.sub(replacement, line)
        if traits.asserts_preferences_domain:
            line = PREFERENCES_DOMAIN_RULE[0].sub(PREFERENCES_DOMAIN_RULE[1], line)
    elif traits.is_cli_help:
        for pattern, replacement in STATE_DIR_RULES:
            line = pattern.sub(replacement, line)
    return line


def rewrite_text(path: Path, text: str) -> str:
    """Apply every rule that concerns `path` to the whole of `text`."""
    traits = traits_for(path)
    return "".join(rewrite_line(line, traits) for line in text.splitlines(keepends=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="report without rewriting; exit 1 if anything would change")
    args = parser.parse_args()

    changed_files = 0
    changed_lines = 0
    for path in candidate_files():
        try:
            original = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        lines = original.splitlines(keepends=True)
        traits = traits_for(path)
        rewritten = [rewrite_line(line, traits) for line in lines]
        if rewritten == lines:
            continue
        changed_files += 1
        for number, (before, after) in enumerate(zip(lines, rewritten), start=1):
            if before != after:
                changed_lines += 1
                if args.check:
                    print(f"{path.relative_to(REPO_ROOT)}:{number}: {before.strip()[:140]}")
        if not args.check:
            path.write_text("".join(rewritten), encoding="utf-8")

    verb = "would change" if args.check else "changed"
    print(f"{verb} {changed_lines} line(s) in {changed_files} file(s)", file=sys.stderr)
    return 1 if args.check and changed_lines else 0


if __name__ == "__main__":
    sys.exit(main())
