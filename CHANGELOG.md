# Changelog

Changes to Black Arrow. Changes inherited from upstream Codex are not repeated here; see the [upstream releases](https://github.com/openai/codex/releases).

## Unreleased

Foundation sprint, forked from openai/codex at `ca466061d6`.

### Added

- `blackarrow` executable, with `ba` as a symlink alias.
- State in `~/.blackarrow`, overridable with `BLACKARROW_HOME`. Project configuration in `.blackarrow/`. Machine-wide configuration in `/etc/blackarrow/`.
- `.blackarrow` is a sandbox-protected path: an agent cannot rewrite or create its own project configuration or hooks. `.codex` stays protected as well.
- Startup timeline, written to the file named by `BLACKARROW_STARTUP_TRACE`.
- Two checks in `blackarrow doctor`: that state is separate from Codex, and which of analytics, feedback upload, update checks, and announcements are on.
- The terminal is restored when the process is ended by SIGTERM, SIGHUP, or SIGINT.
- `scripts/blackarrow/`: startup benchmark, terminal behaviour check, hermetic test runner, upstream sync tooling, and `install.sh`, which links `blackarrow` and `ba` into `~/.local/bin`.
- Engineering documentation under `docs/`, including a measured baseline of unmodified Codex.

### Changed

- Product name, session header, onboarding copy, `--help`, and command hints say Black Arrow and `blackarrow`.
- The background app-server daemon is off by default. The server runs in-process.
- Usage analytics and metrics are off unless enabled in `config.toml`.
- Feedback upload is off: it sends logs to OpenAI, not to Black Arrow.
- The animated OpenAI logo on empty conversations is not shown.
- Keychain entries, device-key labels, and the macOS preferences domain use Black Arrow's names.
- The status line at the bottom shows how much of the weekly usage limit is left, after the model, directory, and thread name. It is omitted when the provider reports no weekly limit.
- Requests to the Codex backend state the Codex client version that the bundled catalogue needs, `0.155.0` at this fork point, not the source tree's `0.0.0`. With `0.0.0` the backend left the newest models, GPT-6-Luna, GPT-6-Sol and GPT-6.1-Sol among them, out of the model list, and refused them when asked for by name.

### Removed

- `update` and `app` are refused: they would reinstall or launch Codex.
- Update checks and remote announcements, which read Codex's feeds.
- Upstream's SDKs, npm packaging, Bazel build, Nix packaging, CI workflows, and release scripts. See `scripts/blackarrow/pruned-paths.txt`.

### Known gaps

- ChatGPT sign-in still authenticates as the Codex CLI. See `docs/authentication.md`.
- Each launch still asks chatgpt.com for the model list and syncs OpenAI's plugin catalogue from GitHub. Both can be switched off; see the README.
- Linux and Windows are untested. Their sandbox code has not been audited for `.blackarrow`.
