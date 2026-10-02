//! What Black Arrow tells the Codex backend about the client it is.
//!
//! The backend decides which models a client may see and use from the Codex
//! client version it is told, and it is told in two places:
//!
//! - The model catalogue request carries `client_version`. A model whose
//!   `minimal_client_version` is higher is left out of the reply.
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
//! the upstream code this tree is built from, and the tree records what that
//! code can run in the bundled model catalogue: upstream adds a model to
//! `models-manager/models.json`, with the client version it needs, when the
//! client can use it. So the version stated is the highest one the bundled
//! catalogue asks for, and no higher.
//!
//! It is not Black Arrow's version number, which is its own and says nothing
//! about Codex compatibility. It is also not the User-Agent, which upstream
//! builds from the package version and which Black Arrow leaves alone.

/// The Codex client version this tree implements, as the backend's model
/// gates understand it.
///
/// Raise it when an upstream merge brings a catalogue that needs a newer
/// client: a test in `codex-models-manager` fails until the two agree, and
/// names the value to use. Do not set it ahead of the catalogue. A newer
/// version opts in to whatever else the backend gates on it, for code that
/// has not been merged.
pub const CODEX_CLIENT_VERSION: &str = "0.155.0";

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
