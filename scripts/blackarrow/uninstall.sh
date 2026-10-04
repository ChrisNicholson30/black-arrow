#!/bin/sh
# Remove Black Arrow completely: the program, its source, your settings,
# sign-in and sessions, and what it keeps in the Keychain.
#
#   curl -fsSL https://raw.githubusercontent.com/ChrisNicholson30/black-arrow/develop/scripts/blackarrow/uninstall.sh | sh
#
# It lists what it found and asks before removing anything. To remove without
# being asked:
#
#   curl -fsSL https://raw.githubusercontent.com/ChrisNicholson30/black-arrow/develop/scripts/blackarrow/uninstall.sh | sh -s -- --yes
#
# It removes:
#
#   ~/.local/bin/blackarrow, ~/.local/bin/ba   if they are links to Black Arrow
#   ~/.local/share/blackarrow                  the program and source get.sh keeps
#   ~/.blackarrow                              settings, sign-in, sessions, logs
#   ~/Library/Application Support/dev.blackarrow
#   the Keychain items Black Arrow keeps sign-in, MCP and other secrets in
#
# It leaves these alone, and says how to remove them when it finds them:
#
#   /etc/blackarrow       machine-wide settings. Removing them needs sudo, and
#                         this script never asks for a password.
#   .blackarrow folders   in your projects, which belong to those projects.
#   the Rust toolchain    the build used, which other projects may share.
#   a checkout            you cloned and built yourself.
#
# Codex is not touched: ~/.codex and Codex's Keychain items stay as they are.
#
# Settings, all optional, the same as get.sh's:
#
#   BLACKARROW_PREFIX     where get.sh put the source and program (default: ~/.local/share/blackarrow)
#   BLACKARROW_BIN_DIR    where the two links are                 (default: ~/.local/bin)
#   BLACKARROW_HOME       settings, sign-in and sessions          (default: ~/.blackarrow)
set -eu

# The Keychain services Black Arrow stores secrets under: the
# KEYCHAIN_*_SERVICE constants in codex-rs/blackarrow/base/src/brand.rs.
KEYCHAIN_SERVICES='Black Arrow Auth
Black Arrow MCP Credentials
blackarrow'

say() {
    printf '%s\n' "$*"
}

fail() {
    printf 'uninstall.sh: %s\n' "$*" >&2
    exit 1
}

# A directory this script may delete: one that exists and is not the root, the
# home directory, or Codex's state, whatever a setting points at.
deletable() {
    resolved=$(cd "$1" 2>/dev/null && pwd -P) || return 1
    [ "$resolved" != / ] && [ "$resolved" != "$home" ] && [ "$resolved" != "$home/.codex" ]
}

# Everything happens in a function called on the last line, so a download that
# is cut short cannot run half a script.
main() {
    yes=0
    for arg in "$@"; do
        case "$arg" in
            -y | --yes) yes=1 ;;
            *) fail "unknown option '$arg'. The only option is --yes." ;;
        esac
    done

    home=$(cd "$HOME" && pwd -P)
    prefix="${BLACKARROW_PREFIX:-$HOME/.local/share/blackarrow}"
    bin_dir="${BLACKARROW_BIN_DIR:-$HOME/.local/bin}"
    state="${BLACKARROW_HOME:-$HOME/.blackarrow}"
    support="$HOME/Library/Application Support/dev.blackarrow"
    is_mac=0
    if [ "$(uname -s)" = Darwin ]; then
        is_mac=1
    fi

    # A running Black Arrow writes its session and logs back after they are gone.
    if pgrep -x blackarrow >/dev/null 2>&1 || pgrep -x ba >/dev/null 2>&1; then
        fail "Black Arrow is running. Quit it in every terminal, then run this again."
    fi

    # Paths to remove, one per line.
    targets=''

    for name in blackarrow ba; do
        link="$bin_dir/$name"
        if [ -L "$link" ]; then
            case "$(readlink "$link")" in
                blackarrow | */blackarrow) targets="$targets$link
" ;;
                *) say "Leaving $link alone: it points at another program." ;;
            esac
        elif [ -e "$link" ]; then
            say "Leaving $link alone: it is not a link to Black Arrow."
        fi
    done

    # Only a directory get.sh made, so a mistaken BLACKARROW_PREFIX deletes nothing.
    toolchain=''
    if [ -d "$prefix" ]; then
        if [ -x "$prefix/bin/blackarrow" ] || [ -f "$prefix/src/scripts/blackarrow/get.sh" ] ||
            [ -z "$(ls -A "$prefix")" ]; then
            deletable "$prefix" || fail "refusing to delete $prefix"
            targets="$targets$prefix
"
            toolchain=$(sed -n 's/^channel *= *"\(.*\)"/\1/p' "$prefix/src/codex-rs/rust-toolchain.toml" 2>/dev/null || true)
        else
            say "Leaving $prefix alone: it is not where get.sh installs."
        fi
    fi

    if [ -d "$state" ]; then
        deletable "$state" || fail "refusing to delete $state, which BLACKARROW_HOME names"
        targets="$targets$state
"
    fi

    if [ "$is_mac" = 1 ] && [ -d "$support" ]; then
        targets="$targets$support
"
    fi

    keychain=''
    if [ "$is_mac" = 1 ]; then
        keychain=$(printf '%s\n' "$KEYCHAIN_SERVICES" | while IFS= read -r service; do
            if security find-generic-password -s "$service" >/dev/null 2>&1; then
                printf '%s\n' "$service"
            fi
        done)
    fi

    if [ -z "$targets" ] && [ -z "$keychain" ]; then
        say "Black Arrow is not installed here. Nothing was removed."
    else
        say "This removes:"
        printf '%s' "$targets" | while IFS= read -r path; do
            size=''
            if [ ! -L "$path" ]; then
                size=$(du -sh "$path" 2>/dev/null | cut -f1)
            fi
            say "  $path${size:+  ($size)}"
        done
        if [ -n "$keychain" ]; then
            printf '%s\n' "$keychain" | while IFS= read -r service; do
                say "  Keychain items for \"$service\""
            done
        fi

        if [ "$yes" != 1 ]; then
            # The script itself arrives on standard input, so ask the terminal.
            if ! (: </dev/tty) 2>/dev/null; then
                fail "there is no terminal to ask on. Run again with --yes to remove without asking."
            fi
            printf 'Remove all of this? [y/N] ' >/dev/tty
            answer=''
            read -r answer </dev/tty || true
            case "$answer" in
                y | Y | yes | Yes | YES) ;;
                *)
                    say "Nothing was removed."
                    exit 0
                    ;;
            esac
        fi

        printf '%s' "$targets" | while IFS= read -r path; do
            rm -rf "$path"
            say "Removed $path"
        done
        if [ -n "$keychain" ]; then
            printf '%s\n' "$keychain" | while IFS= read -r service; do
                # Each call deletes one item; the bound stops a call that keeps
                # succeeding without deleting anything.
                count=0
                while [ "$count" -lt 100 ] && security delete-generic-password -s "$service" >/dev/null 2>&1; do
                    count=$((count + 1))
                done
                if security find-generic-password -s "$service" >/dev/null 2>&1; then
                    say "Could not remove every Keychain item for \"$service\". Open Keychain Access and search for it."
                else
                    say "Removed the Keychain items for \"$service\""
                fi
            done
        fi
    fi

    if [ -e /etc/blackarrow ]; then
        say ""
        say "Machine-wide settings remain in /etc/blackarrow. To remove them:"
        say "  sudo rm -rf /etc/blackarrow"
    fi
    if [ -n "$toolchain" ] && rustup toolchain list 2>/dev/null | grep -q "^$toolchain"; then
        say ""
        say "The Rust toolchain the build used is still installed, for other projects. To remove it:"
        say "  rustup toolchain uninstall $toolchain"
    fi
    say ""
    say "Projects you used Black Arrow in may have a .blackarrow folder of their own. To list them:"
    say "  find ~ -name .blackarrow -type d -not -path '*/Library/*' 2>/dev/null"
}

main "$@"
