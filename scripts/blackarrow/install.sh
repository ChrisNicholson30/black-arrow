#!/bin/sh
# Put `blackarrow` and `ba` on your PATH, as links to the release build in this
# checkout. Nothing is copied, so rebuilding updates both.
#
#   scripts/blackarrow/install.sh              # into ~/.local/bin
#   scripts/blackarrow/install.sh /some/dir    # into another directory
#
# It can be run from any directory: the binary is found from where this script
# is, not from where you are. A link made by hand with a relative path, or from
# the wrong directory, points at nothing and the shell then reports "command
# not found"; this is what that mistake looks like, and running this fixes it.
#
# A link that already points at a `blackarrow` binary, or at nothing, is
# repointed. Anything else with one of the two names is left alone.
#
# BLACKARROW_BINARY names a different binary to link to. get.sh uses it for the
# copy it keeps outside the build directory.
set -eu

repo_root=$(cd "$(dirname "$0")/../.." && pwd)
binary="${BLACKARROW_BINARY:-$repo_root/codex-rs/target/release/blackarrow}"
bin_dir="${1:-$HOME/.local/bin}"

if [ ! -x "$binary" ]; then
    if [ -n "${BLACKARROW_BINARY:-}" ]; then
        echo "install.sh: there is no program at $binary" >&2
    else
        echo "install.sh: there is no release build at $binary" >&2
        echo "  build it first: (cd \"$repo_root/codex-rs\" && cargo build --release --bin blackarrow)" >&2
    fi
    exit 1
fi

mkdir -p "$bin_dir"

# Check both names before changing either.
for name in blackarrow ba; do
    link="$bin_dir/$name"
    if [ -L "$link" ]; then
        case "$(readlink "$link")" in
            blackarrow | */blackarrow) ;;
            *)
                if [ -e "$link" ]; then
                    echo "install.sh: $link points at another program; leaving it alone" >&2
                    exit 1
                fi
                ;;
        esac
    elif [ -e "$link" ]; then
        echo "install.sh: $link exists and is not a link; leaving it alone" >&2
        exit 1
    fi
done

for name in blackarrow ba; do
    ln -sfn "$binary" "$bin_dir/$name"
    echo "$bin_dir/$name -> $binary"
done

case ":$PATH:" in
    *":$bin_dir:"*) ;;
    *) echo "install.sh: $bin_dir is not on your PATH; add it to run blackarrow by name" >&2 ;;
esac
