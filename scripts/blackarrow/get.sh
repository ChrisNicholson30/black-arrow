#!/bin/sh
# Install Black Arrow by building it from source.
#
#   curl -fsSL https://raw.githubusercontent.com/ChrisNicholson30/black-arrow/develop/scripts/blackarrow/get.sh | sh
#
# There are no prebuilt binaries yet. This fetches the source, builds the
# release binary with the toolchain the repository pins, and links `blackarrow`
# and `ba` into ~/.local/bin. On an Apple Silicon Mac with memory to spare the
# build takes about 20 minutes. Short of memory it takes far longer: well over
# an hour on a 32 GB machine that was already swapping. It needs about 15 GB of
# disk while it runs. The build output is deleted afterwards; what stays is the
# program (330 MB) and the source (about 120 MB).
#
# It needs macOS on Apple Silicon, git, the Xcode command line tools, and
# rustup. It installs none of them: it says what is missing and stops. It never
# asks for a password and writes nothing outside your home directory.
#
# Run it again to update. To remove Black Arrow completely, including your
# settings, sign-in, and sessions, use uninstall.sh beside this script:
#
#   curl -fsSL https://raw.githubusercontent.com/ChrisNicholson30/black-arrow/develop/scripts/blackarrow/uninstall.sh | sh
#
# Your settings, sign-in, and sessions are in ~/.blackarrow. Installing and
# updating leave that directory alone.
#
# Settings, all optional:
#
#   BLACKARROW_REF           branch or tag to build     (default: develop)
#   BLACKARROW_PREFIX        source and program go here (default: ~/.local/share/blackarrow)
#   BLACKARROW_BIN_DIR       the two links go here      (default: ~/.local/bin)
#   BLACKARROW_REPO          repository to fetch from
#   BLACKARROW_KEEP_BUILD=1  keep the build output, so the next update takes
#                            minutes instead of building everything again
set -eu

say() {
    printf '%s\n' "$*"
}

fail() {
    printf 'get.sh: %s\n' "$*" >&2
    exit 1
}

# Everything happens in a function called on the last line, so a download that
# is cut short cannot run half a script.
main() {
    repo="${BLACKARROW_REPO:-https://github.com/ChrisNicholson30/black-arrow.git}"
    ref="${BLACKARROW_REF:-develop}"
    prefix="${BLACKARROW_PREFIX:-$HOME/.local/share/blackarrow}"
    bin_dir="${BLACKARROW_BIN_DIR:-$HOME/.local/bin}"
    src="$prefix/src"

    if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
        fail "Black Arrow supports macOS on Apple Silicon only, for now."
    fi
    command -v git >/dev/null 2>&1 ||
        fail "git is not installed. Install the Xcode command line tools: xcode-select --install"
    xcode-select -p >/dev/null 2>&1 ||
        fail "the Xcode command line tools are not installed. Run: xcode-select --install"

    # rustup installs into ~/.cargo/bin and does not always put it on PATH.
    if ! command -v cargo >/dev/null 2>&1 && [ -x "$HOME/.cargo/bin/cargo" ]; then
        PATH="$HOME/.cargo/bin:$PATH"
        export PATH
    fi
    command -v cargo >/dev/null 2>&1 ||
        fail "Rust is not installed. Install rustup from https://rustup.rs and run this again."
    # The repository pins its toolchain, and only rustup's cargo honours the pin.
    command -v rustup >/dev/null 2>&1 ||
        fail "cargo is installed without rustup, which is needed to fetch the pinned toolchain: https://rustup.rs"

    mkdir -p "$prefix"
    free_kb=$(df -k "$prefix" | awk 'NR == 2 { print $4 }')
    if [ "${free_kb:-0}" -lt 20000000 ]; then
        fail "the build needs about 15 GB of free disk, and $prefix has $((free_kb / 1000000)) GB."
    fi

    if [ -d "$src/.git" ]; then
        [ -z "$(git -C "$src" status --porcelain)" ] ||
            fail "$src has local changes. Move it aside or delete it, then run this again."
        say "Updating the source in $src"
        git -C "$src" fetch --quiet --depth 1 origin "$ref"
        git -C "$src" checkout --quiet --detach FETCH_HEAD
    elif [ -e "$src" ]; then
        fail "$src exists and is not a checkout of Black Arrow."
    else
        say "Fetching the source into $src"
        git clone --quiet --depth 1 --branch "$ref" "$repo" "$src"
    fi
    [ -f "$src/scripts/blackarrow/install.sh" ] ||
        fail "'$ref' does not contain Black Arrow. Is BLACKARROW_REF right?"

    say "Building. About 20 minutes, longer if the Mac is short of memory; the first run also downloads the Rust toolchain."
    (cd "$src/codex-rs" && cargo build --release --locked --bin blackarrow)

    # Keep the program outside the build directory, so that deleting the build
    # output does not delete it. Copy and rename, so a blackarrow that is
    # running keeps the file it started from.
    mkdir -p "$prefix/bin"
    cp "$src/codex-rs/target/release/blackarrow" "$prefix/bin/blackarrow.new"
    mv -f "$prefix/bin/blackarrow.new" "$prefix/bin/blackarrow"
    BLACKARROW_BINARY="$prefix/bin/blackarrow" sh "$src/scripts/blackarrow/install.sh" "$bin_dir"

    if [ "${BLACKARROW_KEEP_BUILD:-0}" != "1" ]; then
        rm -rf "$src/codex-rs/target"
    fi

    say ""
    say "Black Arrow is installed, built from $(git -C "$src" rev-parse --short HEAD) on '$ref'."
    say "  start it:   blackarrow        (or: ba)"
    say "  check it:   blackarrow doctor"
    say "  update it:  run this installer again"
}

main "$@"
