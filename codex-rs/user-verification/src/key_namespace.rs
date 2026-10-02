//! Keychain labels isolate account-user identities within the fixed plugin-service scope.

use base64::Engine as _;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use sha2::Digest as _;
use sha2::Sha256;

/// An opaque account-user namespace. App-server authenticates and selects the identity.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct UserVerificationKeyNamespace {
    pub(crate) label: String,
}

impl UserVerificationKeyNamespace {
    pub fn new(account_user_id: &str) -> Self {
        let identity = URL_SAFE_NO_PAD.encode(Sha256::digest(account_user_id.as_bytes()));
        Self {
            // Black Arrow: its own label, so it never finds or replaces a key
            // that Codex created for the same account.
            label: format!(
                "{}.user-verification.plugin-service.v1.{identity}",
                blackarrow_base::brand::APP_IDENTIFIER
            ),
        }
    }
}

#[cfg(test)]
#[path = "key_namespace_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "key_namespace_blackarrow_tests.rs"]
mod blackarrow_tests;
