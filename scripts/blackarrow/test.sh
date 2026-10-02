#!/bin/sh
# Run the Rust test suite the way upstream's removed `just test` recipe did,
# without touching your real home directory.
#
#   scripts/blackarrow/test.sh                                     # everything
#   scripts/blackarrow/test.sh -p codex-tui
#   scripts/blackarrow/test.sh -p codex-cli --test doctor_path_safety
#   scripts/blackarrow/test.sh -p codex-tui startup_frame          # name filter
#   INSTA_UPDATE=always scripts/blackarrow/test.sh -p codex-tui    # refresh snapshots
#
# With no -p, the whole workspace is tested except codex-voice-host, which
# needs GStreamer installed and is not part of what Black Arrow ships.
#
# The first run downloads upstream's prebuilt V8 (24 MB, checksummed) for the
# code-mode host; see fetch_v8.py. Without it, that crate is left out too.
#
# Always run tests through this script, not bare `cargo test`. It supplies
# five things the suite depends on:
#
# A throwaway HOME. Some upstream tests launch the program without pointing it
#   at a temporary state directory, so on a developer machine they write lock
#   files and helper symlinks into ~/.blackarrow. Here HOME is a scratch
#   directory under target/, so nothing outside the repository is written.
#
# An 8 MiB thread stack. With Rust's 2 MiB default, tests that load
#   configuration in a debug build overflow the stack, and on macOS they spin
#   forever instead of failing.
#
# cargo-nextest, when it is installed. Upstream's suite is written for it: one
#   process per test, per-test timeouts, and the concurrency groups in
#   codex-rs/.config/nextest.toml. Plain `cargo test` is the fallback and is
#   fine for a small crate, but the TUI's unit tests alone take over an hour
#   under it. Install with: cargo install --locked cargo-nextest
#
# No network. Any test that starts the app server would otherwise try to fetch
#   OpenAI's plugin repository from GitHub and ask chatgpt.com for the model
#   list, once per test process: thousands of requests from your address, and
#   enough to exhaust GitHub's unauthenticated rate limit for the hour. The
#   HTTPS proxy variables are pointed at a closed local port so those attempts
#   are refused at once. Loopback is exempt, so the suite's own mock servers
#   work. Only HTTPS is redirected: every such request is HTTPS, and some
#   upstream tests assert that HTTP_PROXY is unset. An outer sandbox would be
#   stricter, but macOS does not allow a sandbox inside a sandbox, and the
#   sandbox tests need to apply their own. Set BLACKARROW_TEST_NETWORK=1 to
#   leave the network alone.
#
# Upstream's defaults. Upstream's tests were written against them: dozens
#   expect analytics events, feedback upload, or the desktop-app command
#   without asking. BLACKARROW_UPSTREAM_DEFAULTS=1 makes a debug build behave
#   that way, so those tests run unmodified. Black Arrow's own tests clear the
#   variable and check the real defaults. Release builds ignore it.
#
# Every test is run even after a failure. Arguments select what to run and are
# passed through unchanged.
#
# Tests must be built with debug assertions (the default): release builds
# ignore CODEX_HOME, which the upstream suite uses to isolate itself.
set -eu

repo_root=$(cd "$(dirname "$0")/../.." && pwd)
real_home=$HOME

export CARGO_HOME="${CARGO_HOME:-$real_home/.cargo}"
export RUSTUP_HOME="${RUSTUP_HOME:-$real_home/.rustup}"
export PATH="$CARGO_HOME/bin:$PATH"

test_home="$repo_root/codex-rs/target/blackarrow-test-home"
rm -rf "$test_home"
mkdir -p "$test_home"
export HOME="$test_home"

# A state directory exported for day-to-day use must not leak into the run:
# it would override the per-test directories the suite sets up.
unset BLACKARROW_HOME BLACKARROW_SQLITE_HOME CODEX_HOME CODEX_SQLITE_HOME

export RUST_MIN_STACK="${RUST_MIN_STACK:-8388608}"
export BLACKARROW_UPSTREAM_DEFAULTS="${BLACKARROW_UPSTREAM_DEFAULTS:-1}"

cd "$repo_root/codex-rs"

if cargo nextest --version >/dev/null 2>&1; then
    # Upstream's configuration, plus Black Arrow's additions as a tool config.
    runner="cargo nextest run --tool-config-file blackarrow:$repo_root/scripts/blackarrow/nextest.toml"
    export NEXTEST_PROFILE="${NEXTEST_PROFILE:-local}"
else
    echo "test.sh: cargo-nextest is not installed; falling back to cargo test" >&2
    runner="cargo test"
fi

# The code-mode host is built against upstream's prebuilt V8.
without_v8=""
if [ -z "${RUSTY_V8_ARCHIVE:-}" ]; then
    if v8=$(python3 "$repo_root/scripts/blackarrow/fetch_v8.py"); then
        RUSTY_V8_ARCHIVE=$(printf '%s\n' "$v8" | sed -n 's/^RUSTY_V8_ARCHIVE=//p')
        RUSTY_V8_SRC_BINDING_PATH=$(printf '%s\n' "$v8" | sed -n 's/^RUSTY_V8_SRC_BINDING_PATH=//p')
        export RUSTY_V8_ARCHIVE RUSTY_V8_SRC_BINDING_PATH
    else
        echo "test.sh: no verified V8 archive; leaving out the code-mode host and the tests that start it" >&2
        without_v8="--exclude codex-code-mode-host --exclude codex-code-mode-runtime --exclude codex-v8-poc"
    fi
fi

# No package named: the whole workspace, minus what cannot be built here.
selected=0
for argument in "$@"; do
    case "$argument" in
        -p | -p* | --package | --package=* | --workspace | --exclude | --exclude=*) selected=1 ;;
    esac
done
if [ "$selected" -eq 0 ]; then
    # shellcheck disable=SC2086  # deliberately split into separate arguments
    set -- --workspace --exclude codex-voice-host $without_v8 "$@"
fi

# Build first, while Cargo can still reach the registry if it needs to.
$runner --no-run "$@"

if [ "${BLACKARROW_TEST_NETWORK:-0}" != "1" ]; then
    refused="http://127.0.0.1:9"
    loopback="127.0.0.1,localhost,::1"
    export HTTPS_PROXY="$refused" https_proxy="$refused"
    export NO_PROXY="$loopback" no_proxy="$loopback"
fi

exec $runner --no-fail-fast "$@"
