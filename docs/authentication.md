# Authentication

**Status: inherited from upstream. Black Arrow's own authentication is Phase 3 and has not been built.**

This page records what the current build does, why that has to change before Black Arrow is distributed, and the route OpenAI provides for doing it properly.

## What the current build does

The login code is upstream's, unchanged apart from where credentials are stored.

| | |
|---|---|
| `blackarrow login` | Opens a browser and signs in through OpenAI's OAuth server **as the Codex CLI**: Codex's client id, the `codex_cli_rs` originator, and a callback on `127.0.0.1:1455`. |
| `blackarrow login --device-auth` | The same, using a device code. |
| `blackarrow login --with-api-key` | Reads an API key from stdin and stores it. |
| `blackarrow logout` | Removes stored credentials. |
| Storage | `auth.json` in the state directory by default. Keychain storage exists upstream but is disabled in source builds. |

What Black Arrow has already changed:

- Credentials live under `~/.blackarrow`, never `~/.codex`. A Codex login on the same machine is neither read nor affected.
- Keychain entries, when used, are filed under `Black Arrow Auth`, `Black Arrow MCP Credentials`, and `blackarrow` instead of Codex's service names.
- A `.env` file in the state directory cannot set `BLACKARROW_*` or `CODEX_*` variables.
- Device-bound keys used for user verification are labelled `dev.blackarrow.…`, and their lock file sits under `~/Library/Application Support/dev.blackarrow/`, so Black Arrow neither finds nor replaces a key Codex created. An unsigned source build cannot use these keys at all; they need Keychain entitlements.

## Why this must change

Signing in with ChatGPT today presents Black Arrow to OpenAI as Codex. That is the one place where the build still impersonates the upstream product, and it conflicts with a stated requirement: Black Arrow has its own identity.

Until Phase 3 lands:

- Treat ChatGPT sign-in in this build as development scaffolding. Do not distribute a build that relies on it.
- API-key login does not use Codex's OAuth client, but requests still carry the `codex_cli_rs` originator and User-Agent.

## The supported route

OpenAI publishes a sign-in flow for exactly this case: [Sign in with ChatGPT](https://developers.openai.com/siwc), with a variant for open-source tools that run locally. It was checked against the published documentation on 2 October 2026; none of it has been implemented or tested here yet.

How it works, from [Registration and sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in):

1. The app generates a stable, opaque host id once per installation (`urn:uuid:…` or a JWK thumbprint) and keeps it.
2. First sign-in sends `client_id=dynamic_agent_client`, `agent_name_hint=Black Arrow`, and the host id to `https://auth.openai.com/api/accounts/authorize`, with PKCE and a loopback callback on `127.0.0.1`.
3. The user approves, and the callback returns a **client id issued to Black Arrow** for that account and workspace. Black Arrow saves it and uses it for later sign-ins. No client secret or partner key is involved.
4. Scopes: `openid profile email` for identity, plus `offline_access resource.invoke chatgpt.tokens.use.direct` to use the ChatGPT plan. The app must check that `chatgpt.tokens.use.direct` was actually granted.
5. Requests go to the Responses API at `https://api.openai.com/v1` with the access token as a bearer token.

OpenAI also documents this for programs that embed the Codex app server, which Black Arrow does ([Codex app-server](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server)): configure a Responses provider at `https://api.openai.com/v1` that takes its token from the environment, with `requires_openai_auth = false` and `supports_websockets = false`, and identify the app in `initialize` with a name that matches `agent_name_hint`. Token renewal is the app's job.

Conditions worth knowing before design starts:

- Plan usage this way is offered to open-source tools and personal projects that run locally. Paid or hosted apps need separate approval.
- The interface guidelines ask for the action to be labelled **Continue with ChatGPT**, which is what the Black Arrow plan already specifies.
- OpenAI lists [preview limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations) for the Responses API and the app server. Read them first; they may constrain features such as WebSocket streaming.

## Phase 3 scope

Planned, not started:

- `blackarrow login chatgpt`, `blackarrow login api`, `blackarrow logout [chatgpt|api]`, and `/login`.
- An authentication router that keeps provider-specific logic out of the TUI.
- Sign in with ChatGPT through dynamic registration, replacing Codex's client id and originator.
- API keys in the macOS Keychain by default. Never in `config.toml`.
- A Black Arrow originator and User-Agent on every request.

Open questions for that phase:

- Which upstream features depend on the Codex-specific ChatGPT backend (`chatgpt.com/backend-api/codex`) rather than the public Responses API, and what Black Arrow does about each: usage display, cloud configuration, connectors, plugin catalogues.
- Whether an existing upstream login can be migrated, or whether users sign in afresh. Signing in afresh is the safe default.

## Where the code is

Paths relative to `codex-rs/`.

| | |
|---|---|
| CLI commands | `cli/src/login.rs` |
| OAuth flow and callback server | `login/src/server.rs`, `login/src/oauth/pkce.rs`, `login/src/device_code_auth.rs` |
| Client id, token refresh | `login/src/auth/manager.rs` |
| Originator and User-Agent | `login/src/auth/default_client.rs` |
| Credential storage | `login/src/auth/storage.rs`, `keyring-store/`, `secrets/` |
| Sign-in screen | `tui/src/onboarding/auth.rs` |
