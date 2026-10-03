# Release

**Status: there is no release process yet. Packaging is Phase 18 and release automation is Phase 19.** This page records the decisions already made and what the later phases have to settle.

## The executable

The public executable is `blackarrow`. It is the `[[bin]]` target of the `codex-cli` package; the package and its library keep their upstream names so merges stay mechanical.

`ba` is not a second binary. It is a symlink to `blackarrow`, created by whatever installs the program. Help and version output say `blackarrow` under either name, because the name is fixed in the argument parser rather than taken from `argv[0]`.

For a build from source:

```bash
(cd codex-rs && cargo build --release --bin blackarrow)
scripts/blackarrow/install.sh
```

The script links both names in `~/.local/bin` to the build. It finds the binary from its own location, because a link made by hand from the wrong directory points at nothing and the shell only says "command not found".

A Homebrew formula would do the same with `bin.install` and `bin.install_symlink`.

`scripts/blackarrow/get.sh` is the same thing for someone without a checkout, as a `curl … | sh` command: it fetches the source, builds it, keeps the program outside the build directory, and links the two names. It builds from source because there is nothing else to install yet. Publishing a binary is a decision for later: a build that signs in to ChatGPT as the Codex CLI should not be handed out as a product, and a download needs signing and notarising to run without warnings. See [authentication.md](authentication.md).

## Versioning

The workspace version is `0.0.0`, as upstream keeps it on `main`, and `blackarrow --version` prints `blackarrow 0.0.0` for any source build.

Upstream treats `0.0.0` as "development build" in several places: update checks are skipped, and Keychain credential storage is replaced by a file. Black Arrow keeps that convention. A release will stamp a real version at build time, as upstream's does, instead of committing one.

Before the first versioned build, check each place that tests for `0.0.0` (`LOCAL_DEV_BUILD_VERSION` in `core/src/config/mod.rs`, `is_source_build_version` in the TUI) and decide whether the released behaviour is what Black Arrow wants.

Black Arrow's version numbers are its own and are unrelated to Codex's. A Codex version is stated in two requests to the Codex backend, the model catalogue and the `version` header, which have to say which Codex client the code is; see [providers.md](providers.md).

## Updates

Black Arrow has no release channel. Until it does:

- `blackarrow update` is refused, with a message saying so.
- Startup update checks are disabled in code, not only by default, so a config setting cannot turn them back on.
- `blackarrow doctor` reports "no release channel yet".

These are controlled by `HAS_RELEASE_CHANNEL` in `codex-rs/blackarrow/base/src/defaults.rs`. Upstream's updater must not be re-enabled as it stands: it reads Codex's release feeds and reinstalls the Codex package through npm, Homebrew, or OpenAI's installer.

## Size

A release build is 328 MB, or 242 MB stripped, the same as upstream. The first run of a freshly installed binary costs about 1.7 s while macOS validates it, and that cost scales with size. Reducing it is tracked in [performance.md](performance.md).

Upstream's release profile leaves symbols in so its packaging can archive them separately. A Black Arrow distribution build should strip.

## Helper programs

`cargo build --bin blackarrow` builds one executable, and that is all Black Arrow needs today. Upstream's packages carry more, and two of them cannot be built with a plain `cargo build`:

| Program | What it is for | What it needs |
|---|---|---|
| `codex-code-mode-host` | Runs model-written JavaScript for "code mode", which is off by default and marked under development | V8 built with pointer compression and its sandbox. The `v8` crate publishes no such prebuilt library; upstream builds its own and publishes it on the Codex GitHub releases. `scripts/blackarrow/fetch_v8.py` downloads it and checks it against the manifest in `third_party/v8/`. |
| `codex-voice-host` | Voice input and output | GStreamer installed on the build machine |

Black Arrow builds the code-mode host only to run upstream's tests of it. Shipping it means either depending on OpenAI's V8 build or producing one, and that is a decision for the packaging phase, together with whether code mode and voice are features Black Arrow keeps.

## What Phase 18 and 19 have to decide

- Targets: `aarch64-apple-darwin` first, then `x86_64-apple-darwin`.
- A distribution profile: stripped, and whichever of fat LTO, a single codegen unit, and size optimisation the measurements justify.
- Code signing and notarisation. An unsigned binary downloaded through a browser is quarantined by Gatekeeper.
- Homebrew: a tap first. The name `blackarrow` in homebrew-core is not guaranteed to be free.
- Checksums and release notes.
- An uninstall procedure: remove the binary and the `ba` symlink, then `~/.blackarrow` if the user wants their state gone.
- CI. Upstream's workflows were removed because they target OpenAI's infrastructure. Black Arrow needs its own: format, lint, test, the fork-rule check (`scripts/blackarrow/upstream_sync.py check`), the terminal check, and the startup benchmark with budgets.

## Licence obligations

Black Arrow is distributed under Apache-2.0, as Codex is. Every distribution must include `LICENSE` and `NOTICE`. `NOTICE` carries upstream's attribution notices unchanged below Black Arrow's own. Licence texts for third-party code the workspace is derived from are kept under `third_party/`.

Have the attribution reviewed before the first public release. The licence asks that modified files carry notices of change; Black Arrow marks hand-made changes with `Black Arrow:` comments and states the fork relationship in `NOTICE` and the README, but that has not had legal review.
