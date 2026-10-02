# Baseline: unmodified Codex

Black Arrow is a fork of the Codex CLI. Before anything was changed, the upstream source was built and measured as it stood, so that later work can be judged against numbers instead of impressions. This document is that record. It does not change; current Black Arrow numbers live in [performance.md](performance.md).

| | |
|---|---|
| Upstream commit | `ca466061d6` (openai/codex `main`, 2 October 2026) |
| Machine | Apple M5, 10 cores, 32 GB, macOS 27.0 (26A428) |
| Toolchain | Rust 1.95.0 (pinned by `codex-rs/rust-toolchain.toml`) |
| Build | `cargo build --release --bin codex`, upstream's release profile (thin LTO, 4 codegen units) |
| Binary measured | SHA-256 `8dfcd344…f444bd`, kept at `codex-rs/target/blackarrow-baseline/codex` |

## Summary

The baseline is already quick to draw its first frame, about 23 ms, a sixth of Black Arrow's 150 ms budget. The cost is elsewhere:

1. **The binary is 328 MB.** 184 MB of that is machine code. The first run of a freshly installed copy takes about 1.7 s while macOS validates the file; later runs take 14 ms.
2. **A source build cannot start its own TUI.** By default the TUI wants a background daemon, the daemon wants a packaged install, and the program exits with an error. Every interactive number below was taken with `--no-daemon`.
3. **Launching it contacts five hosts before the user types anything**, including a telemetry endpoint and a file fetched from the Codex repository.
4. **Offline, it does not go idle and is slow to quit.** Refused connections are retried, costing about 1% CPU, and quitting during startup takes 2.7 s. Online it idles at 0.003% CPU and quits in 9 ms.
5. **`--version` and `--help` write to the state directory** on every run and leave a temporary directory behind.

## How it was measured

`scripts/blackarrow/bench_startup.py` runs the binary on a pseudo-terminal and plays the terminal's part: it keeps a screen model, answers the queries a terminal answers, and timestamps every byte. The same script measures Black Arrow, so the two sets of numbers are comparable.

- **Isolation.** Each suite gets a throwaway `HOME`, state directory, and git workspace under `codex-rs/target/blackarrow-bench/`. The real `~/.codex` on the measuring machine was never read or written.
- **States.** *Ready* is a returning user: logged in with a placeholder API key, workspace trusted. *Fresh* is a first launch with no state at all.
- **Terminal profiles.** *zed* answers every query, as Zed's terminal does. *apple* answers everything except the kitty keyboard query, as Terminal.app does. *mute* answers only the cursor-position report.
- **Network.** Unless stated, the program's proxy variables point at a local proxy that logs each request and refuses it. Runs are therefore offline and repeatable, and nothing is sent to a third party. One suite was run online, with telemetry disabled, for comparison.
- **First frame** is the end of the first synchronized-update bracket that put at least 16 cells on screen. **Settled** is the last byte before output stays quiet for 300 ms.
- **Idle** is a 10 s window starting 4 s after the screen settles, read from the kernel's per-process counters.

These are simulated terminals. Timings in a real emulator include its rendering and its own latency in answering queries; see [performance.md](performance.md) for runs inside Zed and Terminal.app.

## Results

### Build

| | |
|---|---:|
| Wall time, clean release build | 18 min 19 s |
| CPU time | 107 min |
| Peak compiler memory | 12.2 GB |
| `target/` after the build | 6.8 GB |
| Binary | 328.0 MB |
| Binary, stripped | 242.4 MB |

Where the 328 MB goes:

| Section | Size |
|---|---:|
| `__text` (machine code) | 184.5 MB |
| `__LINKEDIT` (symbols and line tables; strippable) | 89.8 MB |
| `__eh_frame` + `__gcc_except_tab` (unwinding) | 32.7 MB |
| `__const` | 16.2 MB |

### One-shot commands

Median of 20 runs, milliseconds.

| Command | Median | Min | p95 |
|---|---:|---:|---:|
| `codex --version` | 14.8 | 12.2 | 21.5 |
| `codex --help` | 11.7 | 10.8 | 20.2 |
| `codex --version`, first run of a new copy of the binary | 1686 | 1677 | 1832 |

The last row is the nearest thing to a cold start that can be measured without root: the binary is copied to a new path, so the kernel has never validated it. A fully cold start, with the file evicted from the page cache as well, needs `sudo purge` and was not measured.

### Interactive launch

`codex --no-daemon`, 120×40, median of 10 launches, milliseconds from process spawn.

| | Ready, zed | Ready, apple | Fresh, zed | Ready, mute | Ready, zed, online |
|---|---:|---:|---:|---:|---:|
| First byte | 18.7 | 18.4 | 15.5 | 18.3 | 14.6 |
| First frame | 23.4 | 22.0 | 19.5 | 272.4 | 18.5 |
| Settled | 69.1 | 70.2 | 73.0 | 318.6 | 475.5 |
| Quit, right after launch | 2742 | 2681 | 4.2 | 2745 | 8.9 |
| Quit, after idling | 9.3 | 10.0 | 4.0 | 5009 | 10.2 |

- The *mute* column shows a fixed 250 ms penalty. The startup probe waits for the terminal's device-attributes reply and gives up after 250 ms. Any terminal that answers that query, which includes both of Black Arrow's target terminals, avoids it.
- Online, the screen takes longer to settle because it is waiting on real replies, but the first frame is unaffected.
- The slow quit is the TUI giving the session two seconds to shut down (`SHUTDOWN_FIRST_EXIT_TIMEOUT`, `tui/src/app/event_dispatch.rs:25`) while the session is busy retrying refused connections. The idle wait before the second quit row was 14 s, except in the *mute* column, where it was 3 s and the session had not finished starting.

### Idle

One launch per suite, 10 s window.

| | Ready, offline | Fresh, offline | Ready, online |
|---|---:|---:|---:|
| CPU | 0.98% | 0.02% | 0.003% |
| Memory footprint | 33.4 MB | 22.0 MB | 31.8 MB |
| Resident memory | 119.7 MB | 70.4 MB | 120.7 MB |
| Interrupt wakeups per second | 2.5 | 1.8 | 0.5 |
| Frames redrawn | 2 | 0 | 0 |
| Child processes | none | none | none |

### Terminal hygiene

Across all 39 launches that reached the TUI, the program restored the line discipline exactly and left no mode switched on: no alternate screen, bracketed paste, mouse or focus reporting, hidden cursor, or pushed keyboard flags.

### Network activity with nothing typed

Requests seen by the logging proxy during one 14 s session in the *ready* state:

| First seen | Host | Count | What it is |
|---:|---|---:|---|
| +54 ms | `raw.githubusercontent.com` | 1 | announcement text from the Codex repository |
| +65 ms | `chatgpt.com` | 22 | model list, plugin catalogue, and retries |
| +78 ms | `github.com` | 1 | `git ls-remote` of the curated plugin repository |
| +168 ms | `api.github.com` | 1 | fallback for the plugin sync |
| +9.5 s | `api.openai.com` | 1 | connection prewarm |
| +14.5 s | `ab.chatgpt.com` | 1 | metrics, flushed at exit |

A launch that is quit after one second makes 15 requests. A *fresh* launch, not logged in, still makes 6. The proxy only sees clients that honour the proxy variables, so this list is a floor.

### The default launch

`codex` with no flags, as built from source:

```text
Error: this CLI has no complete local package; install a packaged Codex CLI or use the standalone installer
To work without the background server, rerun the same command with --no-daemon
```

It exits in 33 ms, having already tried to reach `ab.chatgpt.com`.

## Where things live upstream

This is the map used to decide what Black Arrow changes and what it leaves alone. Paths are relative to `codex-rs/`. Entries marked *(read)* come from reading the source and were not exercised.

### Branding

710 string literals in non-test code contain "Codex": 360 in `tui`, 85 in `cli`, the rest spread over 36 crates. 333 of 1,518 snapshot files mention it. About 110 messages tell the user to run a `codex …` command.

### State locations

Everything resolves through one function, `find_codex_home()` in `utils/home-dir/src/lib.rs`, which reads `CODEX_HOME` and defaults to `~/.codex`. Other names that decide where state goes:

| Name | Defined in |
|---|---|
| `CODEX_SQLITE_HOME` | `state/src/lib.rs:131`, read in `core/src/config/mod.rs:273` |
| `.codex/` project directory | `config/src/loader/mod.rs` |
| `.codex` as a sandbox-protected path | `protocol/src/permissions.rs:42` |
| `/etc/codex/` | `config/src/loader/mod.rs:79`, `layer_io.rs:22` |
| macOS managed preferences domain `com.openai.codex` | `config/src/loader/macos.rs:27` |
| Keychain services `Codex Auth`, `Codex MCP Credentials`, `codex` | `login/src/auth/storage.rs:243`, `rmcp-client/src/oauth.rs:100`, `secrets/src/lib.rs:23` |
| `.env` filter for `CODEX_*` | `arg0/src/lib.rs` |

The upstream test suite sets `CODEX_HOME` on spawned processes in 146 places and locates the binary by the name `codex` in 75.

### Authentication *(read)*

- CLI: `login` (browser, `--device-auth`, `--with-api-key`, `--with-access-token`, `status`) and `logout`, in `cli/src/login.rs`.
- OAuth with PKCE in `login/src/server.rs`. Issuer `https://auth.openai.com`, callback on `127.0.0.1:1455` (fallback 1457). A comment notes the ports must match an allow-list on OpenAI's side.
- Client id `app_EMoamEEZ73f0CkXaXp7hrann` (`login/src/auth/manager.rs:1718`). Originator `codex_cli_rs` (`login/src/auth/default_client.rs:42`), sent in the authorize request and the User-Agent.
- Credentials default to `auth.json` in the state directory. Keychain storage exists but is ignored when the package version is `0.0.0`, which it is for every source build.
- `OPENAI_API_KEY` is not read when loading auth; it only pre-fills the key entry screen.

### Providers *(read)*

- Built in: `openai`, `amazon-bedrock`, `ollama` (`localhost:11434/v1`), `lmstudio` (`localhost:1234/v1`), in `model-provider-info/src/lib.rs`. User entries under `model_providers.*` can add providers but not override these.
- One wire protocol, Responses. `"chat"` is rejected.
- Local providers are only probed with `--oss`.
- The provider is fixed when a session starts. Nothing changes it at runtime, and there is no provider command.
- Model list: bundled JSON, refreshed from the provider, cached in `models_cache.json` for five minutes.
- Reasoning effort has ten levels in `protocol/src/openai_models.rs`, with per-model supported levels. It is set through the `/model` picker.

### Slash commands *(read)*

63 commands in one enum, `tui/src/slash_command.rs`, with names derived by strum. Parsing is local to the TUI. Dispatch is two `match` statements in `tui/src/chatwidget/slash_dispatch.rs`, about 460 and 310 lines. There is no registry, no user-defined alias, and no completion of arguments.

Of the 24 commands planned for Black Arrow 1.0, 14 exist. Missing: `/thinking`, `/provider`, `/flight`, `/context`, `/test`, `/fix`, `/git`, `/config`, `/doctor`, `/help`.

### Startup order

Confirmed with Black Arrow's startup trace, which records the same points:

1. `main`, then `arg0`: loads `.env`, creates a locked temporary directory of helper symlinks under the state directory, and puts it on `PATH`. This happens before arguments are parsed, so `--help` pays for it too.
2. The async runtime starts and arguments are parsed.
3. A minimal configuration is loaded from disk.
4. The terminal enters raw mode and is probed (cursor position, colours, keyboard protocol, device attributes) with a shared 250 ms deadline.
5. **A provisional prompt box is drawn.** The user can type from here.
6. The full configuration, the state databases, and the in-process app server are brought up.
7. Login status is read, then the model list is requested. This step can wait on the network.
8. The chat interface replaces the provisional frame, and the session starts in the background.

Upstream's only startup timing is one log line whose clock starts at step 7.

### MCP *(read)*

Servers are configured under `mcp_servers.*` and started concurrently when a session starts. Only servers marked `required` block. The first turn waits up to one second for the rest. There is no lazy or manual start option and no way to start, stop, or restart one server.

## Reproducing

```bash
# Build upstream at the baseline commit, then:
B=codex-rs/target/blackarrow-baseline/codex
scripts/blackarrow/bench_startup.py --bin $B --home-env CODEX_HOME --home-dir .codex \
    --arg=--no-daemon --state ready --profile zed --runs 10 --json out.json
```

Raw results for every suite are in [`baseline-data/`](baseline-data/).
