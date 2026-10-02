# Security

## Reporting a vulnerability

Report vulnerabilities in Black Arrow privately through this repository's **Security → Report a vulnerability** page on GitHub. Please do not open a public issue for a security problem.

Do not report Black Arrow issues to OpenAI's bug bounty. Black Arrow is an independent fork, and OpenAI does not maintain it.

If the problem is in code Black Arrow inherits unchanged from Codex, it likely affects Codex too. In that case please also report it upstream through [OpenAI's program](https://bugcrowd.com/engagements/openai), so it is fixed at the source.

## What Black Arrow protects

Black Arrow runs model-generated commands on your machine. Its protections are inherited from Codex and are not weakened for any provider, local or hosted:

- **Sandboxing.** Commands run under macOS Seatbelt with filesystem and network restrictions.
- **Approvals.** The program, not the model, decides when a command needs your consent.
- **Protected paths.** Inside a writable workspace, `.git`, `.agents`, `.blackarrow`, `.codex`, and `.aws` stay read-only to the agent, so it cannot rewrite its own configuration, plant hooks, or alter credentials.
- **Credential isolation.** Black Arrow's credentials live under `~/.blackarrow` and its own Keychain service names. It does not read Codex's.

## Known limitations

- **Only macOS is supported.** The Linux and Windows sandbox code is inherited and has not been audited or tested for Black Arrow, including its protection of `.blackarrow`.
- **Debug builds are for development.** So that the upstream test suite can run, they accept `CODEX_HOME` and a project `.codex` directory, and with `BLACKARROW_UPSTREAM_DEFAULTS=1` they use upstream's defaults, which include reporting analytics. Release builds do none of this. Do not use a debug build as your daily driver.
