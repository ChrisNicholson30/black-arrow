# Performance

Black Arrow's numbers at the end of the foundation sprint, measured the same way and on the same machine as [baseline.md](baseline.md), with unmodified Codex's figures beside them. The raw results are in `docs/performance-data/`.

| | |
|---|---|
| Build | `cargo build --release --bin blackarrow`, upstream's release profile |
| Machine | Apple M5, 10 cores, 32 GB, macOS 27.0 |
| Date | 2 October 2026 |
| Conditions | Other applications were running, as they were for the baseline. Differences of a few milliseconds are noise. |

## Summary

The foundation sprint did not set out to make startup faster, and the baseline's first frame was already 23 ms. What the numbers show:

- **Nothing got slower.** First frame, one-shot commands, memory, and binary size are where the baseline was, or slightly better.
- **Two hosts are no longer contacted**: the announcement file on GitHub and the telemetry endpoint. Four remain.
- **The screen settles sooner**, in 55 ms instead of 69 ms offline and 53 ms instead of 476 ms online, because the animated logo is gone and nothing redraws when replies arrive.
- **What the baseline did badly, Black Arrow still does badly.** The binary is 328 MB. Offline, quitting takes 2.7 s and the process does not go idle. The chat screen waits for the model list.

## Against the targets

| Measurement | Target | Codex | Black Arrow | |
|---|---|---:|---:|---|
| `blackarrow --help` | effectively instant | 11.7 ms | 9.3 ms | met |
| First TUI frame | under 150 ms | 23.4 ms | 20.9 ms | met |
| First TUI frame, first-ever launch | under 150 ms | 19.5 ms | 60.2 ms | met; see below |
| Config load | under 20 ms | not traced | about 3 ms for the configuration the first frame needs, and 3 ms more for the rest | met |
| Cached model list | immediate | not traced | immediate when cached; otherwise the chat screen waits 0.3 s online and 3.0 s offline | **not met** |
| Idle CPU | about zero | 0.003% online, 0.98% offline | 0.04% online, 0.88% offline | **not met offline** |
| Idle network | zero | retries while offline | retries while offline | **not met offline** |
| Optional MCP blocking the first frame | never | | never: the first frame is drawn before the app server starts | met |

## Launch

120×40, median of 10 launches, milliseconds from process spawn. Codex's figure is in brackets.

| | Ready, zed | Ready, apple | Fresh, zed | Ready, zed, online |
|---|---:|---:|---:|---:|
| First byte | 19.8 (18.7) | 23.3 (18.4) | 17.1 (15.5) | 19.4 (14.6) |
| First frame | 20.9 (23.4) | 24.6 (22.0) | 60.2 (19.5) | 20.2 (18.4) |
| Settled | 55.0 (69.1) | 58.9 (70.2) | 60.0 (73.0) | 52.7 (475.5) |
| Quit, right after launch | 2719 (2742) | 2662 (2681) | 5.0 (4.2) | 216 (8.9) |
| Quit, after idling | 4.0 (9.3) | 4.6 (10.0) | 2.2 (4.0) | 4.2 (10.2) |

Two cells need explaining.

**First-ever launch, first frame 60 ms.** With no saved login there is no prompt to draw early. Codex filled that gap with its logo at 20 ms and showed the sign-in screen at 73 ms. Black Arrow draws nothing until the sign-in screen is ready, at 60 ms. The useful screen arrives sooner; the first paint arrives later.

**Online, quit right after launch 216 ms.** The benchmark presses quit as soon as the screen settles. Black Arrow settles at 53 ms, while the startup requests are still in flight, and the process waits for them. Codex settled at 476 ms, after they had finished, so its quit was instant. Pressed at the same moment, both wait.

## One-shot commands

Median of 20 runs, milliseconds.

| Command | Codex | Black Arrow |
|---|---:|---:|
| `--version` | 14.8 | 8.9 |
| `--help` | 11.7 | 9.3 |
| `--version`, first run of a new copy of the binary | 1686 | 1667 |

The first run of a newly installed binary costs 1.7 s while macOS validates it. That cost follows the binary's size.

## Startup timeline

From `BLACKARROW_STARTUP_TRACE`, one launch each, returning user, milliseconds since the process started executing. A single launch varies by several milliseconds; the two columns differ early on for that reason, not because of the network.

| Point | Offline | Online |
|---|---:|---:|
| `main` | 7.5 | 7.8 |
| arguments parsed | 22.0 | 10.8 |
| bootstrap config loaded | 24.7 | 13.0 |
| terminal ready | 25.1 | 13.2 |
| **first frame** | **25.5** | **13.6** |
| full config loaded | 28.5 | 15.4 |
| state databases ready | 47.4 | 43.1 |
| app server ready | 65.9 | 62.4 |
| sign-in state loaded | 67.0 | 63.6 |
| model list loaded | 2975 | 315 |
| **chat screen** | **2985** | **323** |
| session ready | 9066 | 812 |
| MCP ready | 9066 | 812 |

The first frame is the prompt, and it accepts typing straight away. The chat screen replaces it only when the model list has arrived, and with a cold cache that is a request to chatgpt.com: a quarter of a second online, three seconds of waiting for it to fail offline. This is the largest gap between what the plan asks for and what the program does.

## Idle

One launch per column, 10 s window.

| | Ready, offline | Fresh, offline | Ready, online |
|---|---:|---:|---:|
| CPU | 0.88% (0.98%) | 0.02% (0.02%) | 0.04% (0.003%) |
| Memory footprint | 32.0 MB (33.4) | 21.2 MB (22.0) | 31.8 MB (31.8) |
| Resident memory | 117.7 MB | 67.3 MB | 120.8 MB |
| Interrupt wakeups per second | 2.2 (2.5) | 1.6 (1.8) | 2.3 (0.5) |
| Frames redrawn | 2 | 0 | 0 |
| Child processes | none | none | none |

Offline, refused connections are retried, which is what keeps the CPU from going idle.

## Network activity with nothing typed

One 14 s session, returning user, seen by the logging proxy.

| First seen | Host | Count | What it is | Codex |
|---:|---|---:|---|---|
| +46 ms | `chatgpt.com` | 22 | model list, featured plugins, and retries | same |
| +58 ms | `github.com` | 1 | `git ls-remote` of OpenAI's plugin repository | same |
| +156 ms | `api.github.com` | 1 | fallback for the plugin sync | same |
| +9.5 s | `api.openai.com` | 1 | connection prewarm for the model provider | same |
| | `raw.githubusercontent.com` | 0 | announcement text | 1 |
| | `ab.chatgpt.com` | 0 | metrics, flushed at exit | 1 |

A first-ever launch, not signed in, makes 4 requests where Codex made 6.

`features.plugins = false` removes the GitHub requests and two of the chatgpt.com ones. `features.api_key_model_discovery = false` removes the rest of chatgpt.com. With both off, a launch contacts the model provider and nothing else. Whether they should be off by default belongs to the provider phase.

## Size

| | Codex | Black Arrow |
|---|---:|---:|
| Binary | 328.0 MB | 327.9 MB |
| Stripped | 242.4 MB | 242.4 MB |
| `__text` (machine code) | 184.5 MB | 184.5 MB |

## Terminal behaviour

`scripts/blackarrow/terminal_check.py` drives the program through startup, terminal queries, typing, Unicode, bracketed paste, resize, cancelling with Ctrl+C, a shell command with long output, clean exit, state isolation, and being killed by SIGTERM.

| Terminal | Result |
|---|---|
| Simulated Zed terminal | 26 of 26 |
| Simulated Terminal.app | 26 of 26 |
| Terminal.app 488, the real one | 26 of 26 |
| Zed's integrated terminal, the real one | not yet run |

Run against unmodified Codex, the same script fails all three checks about the terminal's state after SIGTERM: it is left in raw mode, on the alternate screen, with mouse reporting on.

To check a real terminal, run this inside it and do not type for about 20 seconds:

```bash
scripts/blackarrow/terminal_check.py --bin codex-rs/target/release/blackarrow --mode here
```

## Measuring

```bash
scripts/blackarrow/bench_startup.py --bin codex-rs/target/release/blackarrow
scripts/blackarrow/bench_startup.py --bin codex-rs/target/release/blackarrow --profile apple
scripts/blackarrow/bench_startup.py --bin codex-rs/target/release/blackarrow --state fresh
scripts/blackarrow/bench_startup.py --bin codex-rs/target/release/blackarrow --online
BLACKARROW_STARTUP_TRACE=/tmp/trace.json codex-rs/target/release/blackarrow
```

Every run uses a throwaway home directory. Without `--online`, requests go to a local proxy that logs and refuses them.

To fail when a number regresses, give the benchmark a budget. This is the check a CI job should run:

```bash
scripts/blackarrow/bench_startup.py --bin codex-rs/target/release/blackarrow \
    --budget first_frame_ms=150
```

## What Phase 2 should do

In order of what the measurements say matters:

1. **Stop the chat screen waiting for the model list.** Show the cached or bundled catalogue at once and refresh behind it. Ask the provider the user chose, not chatgpt.com.
2. **Decide what runs at startup at all.** The plugin sync and the featured-plugin request happen on every launch whether or not plugins are used.
3. **Behave when offline.** Bound the retries so the process goes idle, and do not make quitting wait two seconds for a session that is only retrying.
4. **Make the binary smaller.** 184 MB of machine code is the cost of the first run and of every download. Strip distribution builds, then find out what the code is.
5. **Keep `--version` and `--help` off the disk.** Both prepare the state directory before parsing arguments.
6. **Put the budget in CI**, once there is CI.
