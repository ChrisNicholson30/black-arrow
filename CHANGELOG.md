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
- `scripts/blackarrow/`: startup benchmark, terminal behaviour check, hermetic test runner, and upstream sync tooling.
- Engineering documentation under `docs/`, including a measured baseline of unmodified Codex.

### Changed

- Product name, session header, onboarding copy, `--help`, and command hints say Black Arrow and `blackarrow`.
- The background app-server daemon is off by default. The server runs in-process.
- Usage analytics and metrics are off unless enabled in `config.toml`.
- Feedback upload is off: it sends logs to OpenAI, not to Black Arrow.
- The animated OpenAI logo on empty conversations is not shown.
- Keychain entries, device-key labels, and the macOS preferences domain use Black Arrow's names.

### Removed

- `update` and `app` are refused: they would reinstall or launch Codex.
- Update checks and remote announcements, which read Codex's feeds.
- Upstream's SDKs, npm packaging, Bazel build, Nix packaging, CI workflows, and release scripts. See `scripts/blackarrow/pruned-paths.txt`.

### Known gaps

- ChatGPT sign-in still authenticates as the Codex CLI. See `docs/authentication.md`.
- Each launch still asks chatgpt.com for the model list and syncs OpenAI's plugin catalogue from GitHub. Both can be switched off; see the README.
- Linux and Windows are untested. Their sandbox code has not been audited for `.blackarrow`.
