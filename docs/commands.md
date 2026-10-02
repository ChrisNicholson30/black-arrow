# Slash commands

**Status: inherited from upstream. Black Arrow's command registry is Phase 8 and has not been built.**

Commands typed after `/` in the prompt box are parsed and run inside the TUI. None of them needs a round trip to the model unless the command itself starts agent work, such as `/review`.

## The 1.0 set, and where it stands

| Command | Today | Notes |
|---|---|---|
| `/model` | exists | Picks the model and, in a second step, reasoning effort. |
| `/thinking` | missing | Reasoning effort is only reachable through `/model` and two keyboard shortcuts. |
| `/provider` | missing | Providers cannot be switched at runtime. See [providers.md](providers.md). |
| `/flight` | missing | Black Arrow's own feature. Phase 7. |
| `/status` | exists | |
| `/context` | missing | `/status` shows context-window use but not what fills it. |
| `/compact` | exists | No `aggressive` mode. |
| `/new` | exists | |
| `/resume` | exists | |
| `/clear` | exists | Also starts a new session. |
| `/permissions` | exists | |
| `/review` | exists | |
| `/diff` | exists | |
| `/test` | missing | |
| `/fix` | missing | |
| `/git` | missing | |
| `/mcp` | exists | Lists tools; `/mcp verbose`; `/mcp login <name>`. No start, stop, or restart. |
| `/skills` | exists | |
| `/usage` | exists | Only with ChatGPT sign-in. |
| `/config` | missing | A hidden read-only `/debug-config` exists. |
| `/theme` | exists | Syntax highlighting theme only. |
| `/doctor` | missing | `blackarrow doctor` exists as a subcommand. |
| `/help` | missing | `?` on an empty prompt opens the shortcut overlay. |
| `/exit` | exists | `/quit` is an alias. |

Fourteen exist, ten do not.

Upstream has 63 commands in all. Many concern features Black Arrow has not yet decided to keep, such as `/voice`, `/pets`, `/plugins`, `/apps`, and `/daemon`. Two are already changed: `/app` is hidden because there is no desktop app, and `/feedback` reports that feedback is disabled because its upload goes to OpenAI.

## How commands work today

Paths relative to `codex-rs/tui/src/`.

- **Definition.** One enum, `SlashCommand` in `slash_command.rs`. Names come from the variant names through `strum`. Descriptions and per-command flags (takes arguments, allowed during a task, allowed in a side conversation, visible) are each a separate hand-written `match` in the same file.
- **Parsing.** `bottom_pane/prompt_args.rs` and `bottom_pane/chat_composer/slash_input.rs`.
- **Dispatch.** Two `match` statements in `chatwidget/slash_dispatch.rs`: about 460 lines for bare commands and 310 for commands with arguments. Adding a command means editing the enum, each flag list, and both dispatch functions.
- **Popup.** `bottom_pane/command_popup.rs`. Filtering is an exact-then-prefix match on the name, recomputed on every key. It is synchronous and has no perceptible delay.
- **Aliases.** Hard-coded only: `/quit` for `/exit`, `/btw` for `/side`, and three alternate spellings.
- **Argument completion.** None. The popup closes when the cursor leaves the command name.
- **User-defined commands.** None. Skills are invoked with `$`, not `/`.

## What Phase 8 has to build

The plan asks for a registry where each command declares its name, aliases, description, category, handler, completion provider, and capability requirements, so that adding one does not mean editing a central `match`.

Design constraints from the audit:

- The existing enum is read in many places and by a large test suite. Replacing it outright would be a deep change to a file upstream edits constantly. A registry that sits in front of the enum, owning Black Arrow's new commands and metadata and delegating the upstream ones, keeps the fork shallow.
- Capability requirements need the provider and model capability records from Phase 4. `/thinking` cannot refuse an unsupported level until those exist.
- Argument completion is new behaviour in the prompt box, which currently closes the popup after the command name.
- Help text should be generated from the registry, which is what makes `/help` cheap.
