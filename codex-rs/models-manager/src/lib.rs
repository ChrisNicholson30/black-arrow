pub mod cache;
pub mod collaboration_mode_presets;
pub(crate) mod config;
pub mod manager;
pub mod model_info;
pub mod model_presets;
pub mod test_support;

pub use codex_protocol::auth::AuthMode;
pub use config::ModelsManagerConfig;

/// Load the bundled model catalog shipped with `codex-models-manager`.
pub fn bundled_models_response()
-> std::result::Result<codex_protocol::openai_models::ModelsResponse, serde_json::Error> {
    serde_json::from_str(include_str!("../models.json"))
}

/// Convert the client version string to a whole version string (e.g. "1.2.3-alpha.4" -> "1.2.3").
pub fn client_version_to_whole() -> String {
    // Black Arrow: upstream sends the package version, which is 0.0.0 in a
    // source build, and the backend leaves out every model that needs a newer
    // client than it is told. Say which Codex client this tree is instead;
    // see blackarrow_base::upstream.
    blackarrow_base::upstream::CODEX_CLIENT_VERSION.to_string()
}

#[cfg(test)]
#[path = "blackarrow_client_version_tests.rs"]
mod blackarrow_client_version_tests;
