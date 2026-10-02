//! The `version` header on requests to the built-in OpenAI provider.
//!
//! The Codex backend refuses a model when this header names a client older
//! than the model needs. Upstream fills it from the package version, which is
//! `0.0.0` in a source build, so every recent model was refused. See
//! `blackarrow_base::upstream`.

use super::*;
use blackarrow_base::upstream::CODEX_CLIENT_VERSION;
use pretty_assertions::assert_eq;

#[test]
fn the_openai_provider_states_the_codex_client_version() {
    let provider = ModelProviderInfo::create_openai_provider(/*base_url*/ None);
    let api_provider = provider
        .to_api_provider(/*auth_mode*/ None)
        .expect("the built-in provider builds");

    assert_eq!(
        api_provider
            .headers
            .get("version")
            .and_then(|value| value.to_str().ok()),
        Some(CODEX_CLIENT_VERSION)
    );
}

/// The header belongs to the Codex backend's protocol. Other providers were
/// never sent it and still are not.
#[test]
fn other_built_in_providers_do_not_send_it() {
    for (id, provider) in built_in_model_providers(/*openai_base_url*/ None) {
        if id == OPENAI_PROVIDER_ID {
            continue;
        }
        let has_version = provider
            .http_headers
            .as_ref()
            .is_some_and(|headers| headers.contains_key("version"));
        assert!(!has_version, "{id} sends a version header");
    }
}
