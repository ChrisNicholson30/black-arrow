//! What Black Arrow tells the Codex backend about the client it is.
//!
//! The backend decides which models a client may see and use from the Codex
//! client version it is told, and it is told in two places:
//!
//! - The model catalogue request carries `client_version`. A model the
//!   version is too old for is left out of the reply.
//! - Every model request carries a `version` header. A model that needs a
//!   newer client is refused: "The '...' model is not supported when using
//!   Codex with a ChatGPT account."
//!
//! Neither explains itself. The first hides the model from the picker and the
//! second fails the turn. Upstream's release builds are stamped with a real
//! version. Black Arrow is built from the source tree, whose version is
//! `0.0.0`, and with that the backend treated it as the oldest client there
//! is.
//!
//! What the backend wants to know is which Codex client the code is. That is
//! the newest upstream release whose code this tree contains: a release is
//! cut from upstream `main`, and once the commit it was cut from has been
//! merged, this tree is at least that client. The fork point, `ca466061d6`,
//! contains the commit `rust-v0.160.0` was cut from.
//!
//! The bundled catalogue cannot be the guide. Its `minimal_client_version`
//! values understate what the backend wants: it says GPT-6.1-Sol needs
//! 0.153.0, but told 0.155.0, the newest version the catalogue asks for, the
//! backend left GPT-6.1-Sol out of the list and refused it, while Codex 0.160.0
//! on the same account could use it. The catalogue is still a floor, and a
//! test in `codex-models-manager` checks it.
//!
//! It is not Black Arrow's version number, which is its own and says nothing
//! about Codex compatibility. It is also not the User-Agent, which upstream
//! builds from the package version and which Black Arrow leaves alone.

/// The Codex client version this tree implements, as the backend's model
/// gates understand it: the newest upstream release the merged code contains.
///
/// Raise it after each upstream merge, to the newest release that merge
/// contains; `docs/upstream-sync.md` has the commands. Do not set it ahead of
/// the merged code. A newer version opts in to whatever else the backend gates
/// on it, for code that has not been merged.
pub const CODEX_CLIENT_VERSION: &str = "0.160.0";

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_version_is_three_numbers() {
        let parts: Vec<&str> = CODEX_CLIENT_VERSION.split('.').collect();
        assert_eq!(parts.len(), 3, "{CODEX_CLIENT_VERSION} is not major.minor.patch");
        for part in parts {
            assert!(
                part.parse::<u64>().is_ok(),
                "{CODEX_CLIENT_VERSION} is not major.minor.patch"
            );
        }
    }
}
