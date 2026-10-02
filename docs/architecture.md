# Architecture

Black Arrow is a shallow fork of the Codex CLI. This page says what "shallow" means in practice: where Black Arrow's code lives, exactly what was changed inside upstream's files and why, and what was deliberately left alone. It is the document to read before changing anything upstream owns, and before merging from upstream.

## Shape of the fork

```text
black-arrow/
├── codex-rs/                 upstream's Rust workspace
│   ├── blackarrow/           fork-only crates
│   │   └── base/             names, paths, default policy, startup trace
│   └── …                     upstream crates, with small marked changes
├── scripts/blackarrow/       fork-only tooling
├── docs/                     fork-only documentation
└── third_party/              licence texts kept from upstream
```

The agent runtime, tools, sandbox, protocol, session storage, and TUI are upstream's. Internal names stay as upstream wrote them: crates are still `codex-*`, the state-directory function is still `find_codex_home`, and the environment variables the runtime uses to talk to its own child processes are still `CODEX_*`. Renaming those would touch thousands of lines and buy nothing a user can see.

Black Arrow changes the product boundary: what the program is called, where it keeps state, what it does by default, and what it tells the user.

## How much differs

`scripts/blackarrow/upstream_sync.py footprint` counts it. At the foundation commit, against upstream at `ca466061d6`:

| | Files |
|---|---|
| Upstream files not carried | 645 |
| Upstream files replaced wholesale (README, docs, startup tips) | 19 |
| Changed only by the codemod | 105, of which 54 are tests and snapshots |
| Snapshots refreshed by running the tests | 146 |
| Changed by hand | 73: 48 source, 6 tests, 19 manifests |
| Fork-only files | 49 |

Only the "changed by hand" row costs anything at merge time. The rest is re-applied by script; see [upstream-sync.md](upstream-sync.md).

**Fork-only files.** Upstream never touches these, so they never conflict.

| Path | Contents |
|---|---|
| `codex-rs/blackarrow/base/` | `brand` (names and identifiers), `paths` (state locations and the rules for choosing them), `defaults` (policy that differs from upstream), `startup` (the startup timeline). No workspace dependencies. |
| `codex-rs/cli/src/doctor/blackarrow.rs` | The doctor's isolation check. |
| `codex-rs/tui/src/blackarrow_signals.rs` | Terminal restoration on termination signals. |
| `blackarrow_tests.rs` and `seatbelt_blackarrow_tests.rs` beside the code they test; `cli/tests/blackarrow_identity.rs`; `tui/tests/suite/blackarrow_*.rs` | Black Arrow's own tests. |
| `scripts/blackarrow/`, `docs/` | Tooling and documentation. |

**Mechanical differences.** Pruned paths are listed in `scripts/blackarrow/pruned-paths.txt`: SDKs, npm packaging, Bazel, Nix, CI workflows, release scripts. A few files under pruned directories are kept: licence texts, and the checksum manifest for upstream's prebuilt V8. The codemod is `scripts/blackarrow/rebrand_command_hints.py`; its header describes each rule. Eleven snapshot files are renamed from `codex__*` to `blackarrow__*`, because unit-test snapshots take the name of the binary crate.

**Deliberate changes inside upstream files.** Most are a line or two. Every one either carries a `Black Arrow:` comment or calls into `blackarrow_base`, and `upstream_sync.py check` fails if a hand-changed file has neither. `grep -rn "Black Arrow:\|blackarrow_base" codex-rs` finds them all. They are described below by purpose.

## State isolation

Black Arrow and Codex must be able to share a machine without touching each other's files.

| What | Upstream | Black Arrow | Changed in |
|---|---|---|---|
| State directory | `~/.codex` | `~/.blackarrow` | `utils/home-dir/src/lib.rs` |
| Override variable | `CODEX_HOME` | `BLACKARROW_HOME` | same |
| SQLite location variable | `CODEX_SQLITE_HOME` | `BLACKARROW_SQLITE_HOME` | `state/src/lib.rs`, `core/src/config/mod.rs` |
| Project directory | `.codex/` | `.blackarrow/` | `config/src/loader/mod.rs` |
| Machine-wide config | `/etc/codex/` | `/etc/blackarrow/` | `config/src/loader/mod.rs`, `layer_io.rs` |
| macOS managed preferences | `com.openai.codex` | `dev.blackarrow` | `config/src/loader/macos.rs` |
| Keychain services | `Codex Auth`, `Codex MCP Credentials`, `codex` | `Black Arrow Auth`, `Black Arrow MCP Credentials`, `blackarrow` | `login/src/auth/storage.rs`, `rmcp-client/src/oauth.rs`, `secrets/src/lib.rs` |
| `.env` cannot set | `CODEX_*` | `CODEX_*` and `BLACKARROW_*` | `arg0/src/lib.rs` |
| Symlinked state directory alias | reads `CODEX_HOME` | reads the resolved override | `config/src/codex_home_symlink.rs` |
| Import from other agents writes to | `.codex/` | `.blackarrow/` | `external-agent-migration/src/` |
| External editor scratch directory | under `~/.codex` or `.codex/` | under `~/.blackarrow` or `.blackarrow/` | `tui/src/external_editor.rs` |
| Device-key label and its lock file | `com.openai.codex.…`, locked under `~/Library/Application Support/com.openai.codex/` | `dev.blackarrow.…`, locked under `~/Library/Application Support/dev.blackarrow/` | `user-verification/src/` |

Everything resolves through `find_codex_home()`, which upstream already used everywhere, so the directory change is one function.

### What debug builds do for upstream's tests

Upstream's test suite assumes it is testing Codex: Codex's names for where state lives, and Codex's defaults. Rewriting the tests to assume Black Arrow would mean editing several hundred places across about a hundred files, and editing them again after every merge. Instead, a **debug build** can behave like upstream in two ways. A release build can do neither.

**Upstream's names, when Black Arrow's are absent.** A debug build also accepts `CODEX_HOME`, `CODEX_SQLITE_HOME`, and a project `.codex/` directory. Upstream's tests isolate themselves by setting `CODEX_HOME` on the processes they spawn and by building fixture projects with `.codex/` directories. The rule is one constant, `HONORS_UPSTREAM_NAMES` in `blackarrow/base/src/paths.rs`.

**Upstream's defaults, on request.** A debug build started with `BLACKARROW_UPSTREAM_DEFAULTS=1` uses upstream's defaults for the settings listed under [Defaults that differ](#defaults-that-differ): analytics, feedback upload, update checks, the desktop-app command, and announcements. Dozens of upstream tests expect those without asking for them. The rule is `uses_upstream_defaults` in `blackarrow/base/src/defaults.rs`, and `scripts/blackarrow/test.sh` sets the variable.

Consequences:

- Tests must run in a profile with debug assertions, which is Cargo's default. The test helper that locates the binary refuses to run otherwise, instead of letting tests write to a real state directory.
- A debug build must not be used as a daily driver. With `CODEX_HOME` exported it would use that directory, and with the defaults variable exported it would report analytics. `blackarrow doctor` warns about each.
- Where the product *writes* a path, it always writes Black Arrow's name. Only reading falls back.
- Upstream's tests therefore exercise upstream's defaults, not Black Arrow's. Black Arrow's defaults are tested in fork-only tests that clear the variable: `cli/tests/blackarrow_identity.rs` runs the real program and reads its doctor report.

Both release rules are pure functions and are tested from a debug build.

## Sandbox

`.codex` is one of the paths upstream keeps read-only inside a writable workspace, so that an agent cannot edit its own configuration or plant a hook. Moving project configuration to `.blackarrow` without protecting that directory would have opened exactly that hole.

`protocol/src/permissions.rs` adds `.blackarrow` to `PROTECTED_METADATA_PATH_NAMES` and to the two places that build default read-only carve-outs. As with `.codex`, the workspace's own `.blackarrow` is protected even before it exists, so creating it goes through approval. The macOS Seatbelt profile is generated from that list, so it follows.

`.codex` stays protected. A Black Arrow agent must not be able to rewrite the project configuration of a Codex install working in the same repository.

`sandboxing/src/seatbelt_blackarrow_tests.rs` runs real commands under `sandbox-exec` and checks that an agent cannot rewrite `.blackarrow/config.toml`, plant `.blackarrow/hooks.json`, or create the directory, and that ordinary files remain writable.

**Not done:** the Linux (`linux-sandbox/src/bwrap.rs`) and Windows (`windows-sandbox-rs/`) sandboxes each name `.codex` in their own code. They inherit the shared list, but their special cases were not changed, compiled, or tested. See [Platform support](#platform-support).

## Identity

| Surface | Change | Changed in |
|---|---|---|
| Executable | `[[bin]] name = "blackarrow"` | `cli/Cargo.toml` |
| `--help`, `--version`, completions | Name, usage, and subcommand descriptions | `cli/src/main.rs` |
| Session header and status card | "Black Arrow" | `tui/src/history_cell/session.rs` |
| Empty prompt | "Describe a task" | `tui/src/chatwidget.rs`, `startup_draft.rs` |
| Onboarding and sign-in copy | Product name | `tui/src/onboarding/` |
| Slash command descriptions | Five that named Codex | `tui/src/slash_command.rs` |
| Startup tips | Rewritten; Codex-specific tips removed | `tui/assets/tooltips.txt` |
| Exit summary | `blackarrow resume …` | `tui/src/app/exit_summary.rs` |
| Terminal title app name | `blackarrow` | `tui/src/chatwidget/status_surfaces.rs` |
| `exec` banner | "Black Arrow v…" | `exec/src/event_processor_with_human_output.rs` |
| Doctor | Title, state-directory labels | `cli/src/doctor/` |
| Command hints, the quit menu, permission warnings | `codex …` to `blackarrow …`; product name on the listed screens | codemod |

### The logo

Upstream draws its animated logo in the empty space above the prompt, and on the welcome screen. Black Arrow does not display another company's mark, and a still screen costs no redraws.

The switch is one function, `empty_state_animation::is_shown`, checked in the two places the animation starts or paints. In the shipped program it is always false. In this crate's own unit tests it is true (`cfg!(test)`), which leaves upstream's animation tests and their snapshots exactly as upstream wrote them, so they never conflict.

That means the unit tests do not show what the program draws. `tui/tests/suite/blackarrow_screen.rs` does: it starts the real program on a pseudo-terminal and fails if anything is drawn above the prompt except the header. `scripts/blackarrow/terminal_check.py` makes the same check, and reports 380 logo cells when pointed at unmodified Codex.

### What still says Codex

Several hundred lower-traffic strings: error messages on rare paths, settings descriptions, and features Black Arrow has not decided to keep. They are a backlog, not an oversight. The way to work through them is the codemod's `PRODUCT_NAME_FILES` list: add a file when its screen becomes part of what Black Arrow presents as its own.

## Defaults that differ

All in `blackarrow/base/src/defaults.rs`, as `Defaults::BLACK_ARROW`. Each is read at one upstream call site through `defaults::current()`.

| Behaviour | Upstream | Black Arrow | Why |
|---|---|---|---|
| Background app-server daemon | Started automatically | Off; server runs in-process | Nothing should outlive the session. A source build cannot start it anyway. |
| Usage analytics and metrics | On, sent to OpenAI | Off unless `[analytics] enabled = true` | Black Arrow is not OpenAI's product. |
| Feedback upload | On, sends logs to OpenAI | Off | Those are not Black Arrow's maintainers. |
| Update check | Reads Codex release feeds | Disabled in code | Black Arrow has no release channel. |
| `update` command | Reinstalls Codex via npm, Homebrew, or installer | Refused | It would modify a Codex install. |
| `app` command, `/app` | Launches or installs the Codex desktop app | Refused, hidden | There is no desktop app. |
| Remote announcements | Fetched from the Codex repository at each launch | Not fetched | Different product; needless startup request. |
| Doctor's desktop and update probes | Inspect the Codex desktop app and update CDN | Skipped | Not this program's business. |
| `cloud`, `apply` commands | Listed in help | Hidden | Codex Cloud is an OpenAI service. They still work. |

The daemon default is a feature flag, and feature defaults live in upstream's feature table, because every consumer reads them there. That table is a constant, so it does not follow `BLACKARROW_UPSTREAM_DEFAULTS`; the few upstream tests about daemon auto-start turn it on in their own configuration. `features/src/blackarrow_tests.rs` fails if the table stops agreeing with Black Arrow's policy, which is how a merge that restores a default gets caught.

`blackarrow doctor` reports the result under "privacy": which of analytics, feedback upload, update checks, and announcements are on, and why.

Two startup requests are **not** changed and still go to OpenAI and GitHub on every launch: the model list and the plugin catalogue. They are listed in the README and measured in [performance.md](performance.md). Changing them is provider and plugin work, not foundation work.

## Startup trace

Setting `BLACKARROW_STARTUP_TRACE=/path/to/file.json` records when the process reaches each named point and writes the timeline to that file. The points are single-line calls to `blackarrow_base::startup::mark` at the places upstream's startup already has natural boundaries. With the variable unset, a mark is one atomic load.

The first frame is marked in `tui/src/custom_terminal.rs`, where every draw path ends, so it is correct whichever screen is drawn first. See [performance.md](performance.md).

## Terminal restoration on signals

Upstream restores the terminal on normal exit and on panic. A SIGTERM, SIGHUP, or SIGINT killed the process outright and left the user's shell in raw mode on the alternate screen with mouse reporting on. `tui/src/blackarrow_signals.rs` restores the terminal and then re-raises the signal, so the parent still sees the process as killed by it.

## Tests

Upstream's tests are kept as upstream wrote them wherever possible, because every edited test is a future conflict. Four mechanisms make that work:

- **Debug builds honour upstream's names**, so fixtures that set `CODEX_HOME` or create `.codex/` still work.
- **Debug builds use upstream's defaults when the test runner asks**, so tests that expect analytics, feedback upload, or the desktop-app command still pass.
- **The codemod rewrites expectations** together with the messages they assert on: command hints everywhere, and in listed test files the session title, the prompt text, the directory the product writes to, and the preferences domain.
- **The logo stays on in unit tests**, as described above.

What is left is a short list of upstream tests edited by hand, each with a `Black Arrow:` comment: the tests about daemon auto-start, which turn it on; and the sandbox tests, whose expected profiles gain `.blackarrow`.

Supporting changes:

- `utils/cargo-bin`: a lookup for the binary named `codex` returns `blackarrow`.
- `test-binary-support`: sets `BLACKARROW_HOME` instead of `CODEX_HOME` for in-process setup.
- `tui/tests/suite/focus_palette.rs`: the shared pseudo-terminal helper waits for Black Arrow's header, and gains three accessors used by the signal tests.

The suite has to be run through `scripts/blackarrow/test.sh`. It replaces upstream's `just test` recipe, which Black Arrow does not carry, and adds two protections for a developer's machine: a throwaway home directory and no network. [upstream-sync.md](upstream-sync.md) has the details and the known-flaky tests.

## Deliberately unchanged

| Thing | Why it was left |
|---|---|
| OAuth client id, `codex_cli_rs` originator, User-Agent | Replacing them is the whole of Phase 3, and changing one in isolation breaks sign-in. See [authentication.md](authentication.md). **This is the main remaining way the build presents itself as Codex.** |
| Model list fetched from `chatgpt.com`; OpenAI's plugin repository synced from GitHub | Provider and plugin decisions. Both can be switched off today with a feature flag; see the README. |
| The model's system prompt, which names Codex | It affects model behaviour and needs evaluating, not a search and replace. |
| Internal `CODEX_*` variables (`CODEX_SANDBOX`, `CODEX_THREAD_ID`, …) | A private contract between the runtime and its child processes. |
| Rate-limit and metric identifiers named `codex` | Server-side identifiers. |
| Helper names on `PATH` (`apply_patch`, `codex-execve-wrapper`) | Internal; the model is trained to call `apply_patch`. |
| Connectors, cloud tasks, voice, pets, code mode | Product decisions for later phases. Code mode and voice need helper programs that Black Arrow does not ship; see [release.md](release.md). |
| The `codex-tui` and other secondary binaries | Development tools, not shipped. |
| `codex-rs/.config/nextest.toml` | Upstream's test configuration. Black Arrow's additions are in `scripts/blackarrow/nextest.toml`. |

## Platform support

**macOS on Apple Silicon is the only supported platform.** Everything on this page was built and tested there.

The Linux and Windows code is still in the tree, because the shared crates depend on it under `cfg`, but for Black Arrow it is unaudited. Before supporting either:

- Linux: `linux-sandbox/src/bwrap.rs` treats `.git`, `.agents`, and `.codex` specially when masking missing paths. Decide whether `.blackarrow` belongs in that list and test it.
- Windows: `windows-sandbox-rs/` protects a workspace `.codex` by ACL in four places. `.blackarrow` needs the same. `config/src/loader/windows.rs` still reads machine-wide config from `%ProgramData%\OpenAI\Codex`.

## Decisions

Short records of choices that shape maintenance.

1. **One dependency-free base crate.** Low-level crates such as `codex-utils-home-dir` need Black Arrow's names, so the crate holding them cannot depend on anything in the workspace. Later Black Arrow features that need protocol types get their own crates under `codex-rs/blackarrow/`.
2. **Rename the binary target, not the package.** A binary called `codex` in `target/` on a machine that also has Codex installed is a hazard. The package name `codex-cli` stays so `Cargo.toml` diffs stay small. The cost is eleven renamed snapshot files.
3. **Debug builds honour upstream names.** Chosen over rewriting about seventy test files. The risk is confined to development builds and documented above.
4. **Rewrite command hints by script.** Well over a hundred messages told the user to run `codex …`. That is a functional bug, not cosmetics, so they are all fixed, but by a codemod that can be re-run after each merge.
5. **Prune by manifest.** Removing upstream files would normally make every merge conflict. A manifest plus a script that re-deletes makes it free.
6. **Policy in one place, not scattered edits.** Each default Black Arrow changes is one field of `Defaults::BLACK_ARROW` read at one call site, with a test pinning the whole set.
7. **Keep upstream's tests upstream's.** Black Arrow behaviour is tested in fork-only files. Upstream test files are edited only where they assert something Black Arrow changed on purpose.
8. **Gate the logo in one place, and leave it on for unit tests.** The first version switched it off at seven call sites and would have needed upstream's animation tests and snapshots rewritten. One gate inside the module, with a test of the real program, is a smaller patch and no conflicts.
9. **Tests run offline, with a scratch home.** Upstream's suite reaches GitHub and the model provider from any test that starts the app server, and writes into the home directory from a few. Neither belongs on a developer's machine, so the wrapper prevents both instead of trusting each test.
10. **Add to upstream's test configuration from outside it.** Concurrency limits for this platform live in a nextest tool config, so upstream's file is never edited.
11. **Upstream's defaults on request, in debug builds only.** The alternative was to opt each affected upstream test back in to the default it assumes: thirty-odd analytics tests across twenty files, whose configuration is written in more than one order. One switch that release builds cannot see is smaller and does not grow with upstream. The cost is that upstream's suite no longer exercises Black Arrow's defaults, so those have their own tests.
