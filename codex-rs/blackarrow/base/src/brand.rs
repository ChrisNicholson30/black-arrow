//! Product identity.
//!
//! Every name the program uses as an identifier lives here: the executable,
//! the alias, keychain services, the OS-level identifier. Running text in the
//! interface spells the product name out where it appears, because most of it
//! is static help text that cannot be assembled from constants.

/// Name shown to users.
pub const PRODUCT_NAME: &str = "Black Arrow";

/// One-line description shown next to the name.
pub const PRODUCT_TAGLINE: &str = "Terminal Coding Harness";

/// Name of the executable users run.
pub const BIN_NAME: &str = "blackarrow";

/// Short alias for [`BIN_NAME`]. Installed as a symlink to the same executable.
pub const BIN_ALIAS: &str = "ba";

/// Reverse-DNS identifier for anything registered with the operating system,
/// such as the macOS managed-preferences domain.
pub const APP_IDENTIFIER: &str = "dev.blackarrow";

/// Keychain service that holds sign-in credentials.
///
/// Service names are what the user sees in Keychain Access and in macOS
/// permission prompts. Black Arrow uses its own so its credentials are never
/// filed under, or confused with, a Codex install on the same machine.
pub const KEYCHAIN_AUTH_SERVICE: &str = "Black Arrow Auth";

/// Keychain service that holds OAuth tokens for MCP servers.
pub const KEYCHAIN_MCP_SERVICE: &str = "Black Arrow MCP Credentials";

/// Keychain service that holds the key protecting the local secrets store.
pub const KEYCHAIN_SECRETS_SERVICE: &str = "blackarrow";

/// Hint shown in the empty prompt box.
pub const COMPOSER_PLACEHOLDER: &str = "Describe a task";

/// Whether an empty conversation is decorated with a large animated mark.
///
/// Upstream draws the OpenAI logo there. Black Arrow does not show another
/// company's trademark, has no mark of its own yet, and keeps the idle screen
/// still so it costs no redraws.
pub const SHOWS_EMPTY_STATE_MARK: bool = false;

/// The project Black Arrow is derived from, for attribution.
pub const UPSTREAM_PRODUCT_NAME: &str = "OpenAI Codex";

/// Where the upstream source lives.
pub const UPSTREAM_REPOSITORY_URL: &str = "https://github.com/openai/codex";

/// Name and tagline on one line, as used in headers and `--help`.
pub fn title() -> String {
    format!("{PRODUCT_NAME} — {PRODUCT_TAGLINE}")
}

#[cfg(test)]
mod tests {
    use super::*;
    use pretty_assertions::assert_eq;

    #[test]
    fn title_joins_name_and_tagline() {
        assert_eq!(title(), "Black Arrow — Terminal Coding Harness");
    }

    #[test]
    fn keychain_services_are_distinct_and_not_upstreams() {
        let services = [
            KEYCHAIN_AUTH_SERVICE,
            KEYCHAIN_MCP_SERVICE,
            KEYCHAIN_SECRETS_SERVICE,
        ];
        for (index, service) in services.iter().enumerate() {
            assert!(
                !service.to_ascii_lowercase().contains("codex"),
                "{service} would collide with an upstream keychain entry"
            );
            assert!(
                !services[..index].contains(service),
                "{service} is used for two different stores"
            );
        }
    }

    #[test]
    fn executable_names_are_shell_safe() {
        for name in [BIN_NAME, BIN_ALIAS] {
            assert!(
                name.chars().all(|c| c.is_ascii_lowercase()),
                "{name} must be lowercase ASCII so it can be typed and symlinked anywhere"
            );
        }
    }
}
