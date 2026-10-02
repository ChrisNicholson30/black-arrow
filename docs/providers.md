# Providers

**Status: inherited from upstream. Black Arrow's provider router is Phase 4 and has not been built.**

Provider neutrality is the main thing Black Arrow adds to Codex, so this page separates what exists from what is planned.

## What exists today

Built-in providers, defined in `codex-rs/model-provider-info/src/lib.rs`:

| Id | Base URL | Notes |
|---|---|---|
| `openai` | `https://chatgpt.com/backend-api/codex` with ChatGPT sign-in, `https://api.openai.com/v1` with an API key | The only provider that requires OpenAI authentication, and the only one using WebSockets. |
| `ollama` | `http://localhost:11434/v1` | Used with `--oss --local-provider ollama`. Requires Ollama 0.13.4 or later. |
| `lmstudio` | `http://localhost:1234/v1` | Used with `--oss --local-provider lmstudio`. |
| `amazon-bedrock` | Derived from the AWS region | |

A custom provider can be added in `config.toml`:

```toml
[model_providers.lab]
name = "Lab Server"
base_url = "http://192.168.1.20:8000/v1"
wire_api = "responses"
```

Limits of the current design:

- **One wire protocol.** Only the Responses API. `wire_api = "chat"` is rejected, so a server that speaks only Chat Completions cannot be used.
- **The provider is fixed when a session starts.** There is no way to switch during a session and no `/provider` command.
- **Built-in ids are reserved.** A `model_providers.ollama` entry in config is ignored; it cannot change the built-in's URL.
- **Local providers are not discovered.** They are only contacted when `--oss` is passed.
- **The model list is per process.** It comes from a bundled catalogue, refreshed at startup and cached for five minutes in `models_cache.json`.
- **Model discovery goes to chatgpt.com.** For the built-in OpenAI provider the refresh is `GET https://chatgpt.com/backend-api/codex/models`, with an API key as much as with ChatGPT sign-in (`features.api_key_model_discovery`, on by default). A provider-neutral harness should ask the provider the user chose, and should not ask anyone when the cache is fresh.
- **Capabilities are known only for catalogued models.** A model the catalogue does not know gets fallback metadata with no reasoning levels.

## What Black Arrow needs

From the plan, to be designed in Phase 4:

- Provider, model, thinking effort, flight profile, and permissions as five separate things the user can change independently.
- Switching provider inside a running session.
- A capability record per provider and model: configurable reasoning and which levels, tool support, streaming, context window, local or hosted, authentication method.
- Settings a model cannot honour are refused with a clear message. Nothing is silently ignored.
- Local providers probed from cache first and refreshed in the background, never before the first frame.
- The same sandbox and approval rules for local models as for hosted ones.

## What the audit says about the work

- **Runtime switching is the hard part.** A session holds its provider for life, and the TUI restarts its in-process server if the provider changes during startup. The nearest existing mechanism is that `thread/start`, `thread/resume`, and `thread/fork` accept a provider, so switching probably means starting a new thread on the new provider and carrying the conversation across. Whether that works end to end has not been tested.
- **Capability data already exists for hosted models.** `ModelInfo` in `protocol/src/openai_models.rs` carries supported reasoning levels, context window, tool types, and input modalities. Local models need the same record filled in from somewhere: probing, a table, or user config.
- **Chat Completions support is a separate decision.** Upstream's built-in local providers already rely on Ollama and LM Studio serving the Responses API. An adapter for servers that only speak Chat Completions is in the plan's post-1.0 backlog.
- **ChatGPT plan access changes the provider picture.** The supported sign-in route for independent tools sends requests to the public Responses API, not the Codex backend. See [authentication.md](authentication.md). That may make "ChatGPT" and "OpenAI API" the same endpoint with different credentials.
