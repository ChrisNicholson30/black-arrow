# Black Arrow

A fast, provider-neutral terminal coding harness, built on the agent runtime of the open-source [OpenAI Codex CLI](https://github.com/openai/codex).

```bash
blackarrow        # or: ba
```

Black Arrow is a deliberately shallow fork. It keeps Codex's sandboxing, approvals, tools, and session machinery, and changes the product around them: its own identity and state, no telemetry by default, startup that is measured instead of assumed, and, in later phases, the ability to move between ChatGPT, API-backed models, and local models without changing how you work.

## Status

**Foundation sprint complete. Not ready for general use.**

| | |
|---|---|
| Works today | Builds and runs as `blackarrow` on Apple Silicon macOS. State isolated in `~/.blackarrow`. Project config in `.blackarrow/`. Sandbox, approvals, and sessions as in Codex. `blackarrow doctor`. Startup tracing and a benchmark. |
| Inherited, not yet Black Arrow's own | Sign-in, provider selection, the model picker, plugins, and slash commands are upstream's. ChatGPT sign-in still presents the program as Codex and must not be relied on in a distributed build. See [docs/authentication.md](docs/authentication.md). |
| Not built yet | Provider switching, `/thinking`, `/provider`, `/flight`, the command registry, packaging, releases. |

The measured starting point is [docs/baseline.md](docs/baseline.md).

## Build

Requires macOS on Apple Silicon and [rustup](https://rustup.rs). The toolchain version is pinned by the repository.

```bash
cd codex-rs
cargo build --release --bin blackarrow     # about 18 minutes from clean
./target/release/blackarrow --version
```

To put `blackarrow` and `ba` on your `PATH`:

```bash
scripts/blackarrow/install.sh
```

It links both names in `~/.local/bin` to the release build, so a rebuild updates them, and it can be run from any directory. `ba` is the same executable under a second name.

Use a release build. A debug build can be made to behave like Codex, in its state directory names and in its defaults, so that upstream's tests can run. It is for development only; [docs/architecture.md](docs/architecture.md) has the details.

## Where things are kept

| | |
|---|---|
| State, credentials, sessions, logs | `~/.blackarrow/`, or wherever `BLACKARROW_HOME` points |
| Per-project configuration | `.blackarrow/config.toml` in the project |
| Machine-wide configuration | `/etc/blackarrow/` |

Black Arrow and Codex can be installed side by side. Black Arrow does not read, write, or migrate anything in `~/.codex`, and ignores `CODEX_HOME`. `blackarrow doctor` reports where state lives and confirms the two are separate.

## What leaves your machine

Off, unless you turn them on: usage analytics, metrics, feedback upload, update checks, and remote announcements. Upstream sends or fetches all five by default.

Still on, inherited from Codex. Each launch contacts:

| Host | What for | To turn it off |
|---|---|---|
| Your model provider, `api.openai.com` by default | The model | |
| `chatgpt.com` | The list of available models | `features.api_key_model_discovery = false` |
| `github.com`, `api.github.com`, `chatgpt.com` | OpenAI's plugin catalogue, re-synced on every launch | `features.plugins = false` |

With both settings off, a launch reaches the model provider and nothing else. Neither request delays the first frame, but the chat screen waits for the model list when it is not cached. Moving model discovery to the provider you chose, and deciding what the plugin catalogue should be, belong to the provider phase; until then this table is the honest state. [docs/performance.md](docs/performance.md) has the measurements.

Whatever a tool does once you approve it is up to that tool.

## Working on it

```bash
cargo install --locked cargo-nextest               # once
scripts/blackarrow/test.sh -p codex-tui            # tests: throwaway HOME, no network
scripts/blackarrow/bench_startup.py --bin codex-rs/target/release/blackarrow
scripts/blackarrow/terminal_check.py --bin codex-rs/target/release/blackarrow
scripts/blackarrow/upstream_sync.py check          # the fork's rules still hold
BLACKARROW_STARTUP_TRACE=/tmp/trace.json blackarrow   # startup timeline
```

Run tests through `test.sh`, not bare `cargo test`; [docs/upstream-sync.md](docs/upstream-sync.md) says why.

| Document | What it covers |
|---|---|
| [architecture.md](docs/architecture.md) | How Black Arrow differs from Codex, and where every difference lives |
| [baseline.md](docs/baseline.md) | Measurements of unmodified Codex, taken before any change |
| [performance.md](docs/performance.md) | Targets, current numbers, how to measure |
| [authentication.md](docs/authentication.md) | Sign-in today and the plan for Black Arrow's own |
| [providers.md](docs/providers.md) | Providers today and the plan for the provider router |
| [commands.md](docs/commands.md) | Slash commands: what exists, what is planned |
| [upstream-sync.md](docs/upstream-sync.md) | Taking changes from upstream Codex, and running the tests |
| [release.md](docs/release.md) | Versioning, packaging, and distribution |

## Licence and attribution

Black Arrow is a modified version of OpenAI Codex and is distributed under the same [Apache-2.0 licence](LICENSE). Upstream's attribution notices are preserved in [NOTICE](NOTICE). Changes made for Black Arrow are recorded in this repository's history and summarised in [docs/architecture.md](docs/architecture.md).

Black Arrow is an independent project. It is not affiliated with, sponsored by, or endorsed by OpenAI. "Codex" and "OpenAI" are used here only to identify the software Black Arrow is derived from.
