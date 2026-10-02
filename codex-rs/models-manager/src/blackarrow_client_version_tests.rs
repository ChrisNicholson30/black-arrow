//! The Codex client version Black Arrow states, against the catalogue it ships.
//!
//! The backend leaves a model out of the catalogue, and refuses requests for
//! it, when the client version it is told is below the model's
//! `minimal_client_version`. The version stated is a constant in
//! `blackarrow_base::upstream`, because the crates that send it sit below
//! this one. These tests are what keep the constant true: it has to be exactly
//! what the bundled catalogue needs.

use blackarrow_base::upstream::CODEX_CLIENT_VERSION;
use pretty_assertions::assert_eq;
use serde_json::Value;

const BUNDLED: &str = include_str!("../models.json");

/// `(major, minor, patch)`, so that comparison is numeric: 0.98.0 is older
/// than 0.153.0.
type Version = (u64, u64, u64);

/// The backend writes the field as `"0.155.0"`. Upstream's test fixtures also
/// write it as `[0, 155, 0]`.
fn parse_version(value: &Value) -> Option<Version> {
    let parts: Vec<u64> = match value {
        Value::String(text) => {
            // A pre-release or build suffix does not change which models the
            // version can see.
            let whole = text.split(['-', '+']).next()?;
            whole
                .split('.')
                .map(|part| part.parse().ok())
                .collect::<Option<_>>()?
        }
        Value::Array(parts) => parts.iter().map(Value::as_u64).collect::<Option<_>>()?,
        _ => return None,
    };
    match parts.as_slice() {
        [major, minor, patch] => Some((*major, *minor, *patch)),
        _ => None,
    }
}

/// Every `minimal_client_version` in a catalogue, with the model that asks for
/// it. Panics on one it cannot read, so a change of format is noticed.
fn minimal_client_versions(catalog_json: &str) -> Vec<(String, Version)> {
    let catalog: Value = serde_json::from_str(catalog_json).expect("catalogue parses");
    catalog["models"]
        .as_array()
        .expect("models is a list")
        .iter()
        .filter_map(|model| {
            let minimum = model.get("minimal_client_version")?;
            let slug = model["slug"].as_str().unwrap_or("?").to_string();
            let version = parse_version(minimum).unwrap_or_else(|| {
                panic!("{slug} has a minimal_client_version that cannot be read: {minimum}")
            });
            Some((slug, version))
        })
        .collect()
}

/// With a lower version the newest bundled models are hidden and refused.
/// With a higher one Black Arrow claims to be a client it has not merged.
#[test]
fn the_stated_client_is_exactly_what_the_bundled_catalogue_needs() {
    let gated = minimal_client_versions(BUNDLED);
    let (slug, (major, minor, patch)) = gated
        .iter()
        .max_by_key(|(_, version)| *version)
        .expect("no bundled model names a minimal_client_version; has upstream renamed the field?");

    assert_eq!(
        CODEX_CLIENT_VERSION,
        format!("{major}.{minor}.{patch}"),
        "the bundled catalogue's newest requirement is {slug}'s; set CODEX_CLIENT_VERSION in \
         blackarrow/base/src/upstream.rs to it"
    );
}

#[test]
fn catalogue_requests_state_it() {
    assert_eq!(crate::client_version_to_whole(), CODEX_CLIENT_VERSION);
}

#[test]
fn versions_are_compared_as_numbers_in_either_spelling() {
    let catalog = r#"{"models": [
        {"slug": "old", "minimal_client_version": "0.98.0"},
        {"slug": "newest", "minimal_client_version": "0.153.0"},
        {"slug": "fixture-style", "minimal_client_version": [0, 124, 0]},
        {"slug": "pre-release", "minimal_client_version": "0.150.0-alpha.9"},
        {"slug": "ungated"}
    ]}"#;

    assert_eq!(
        minimal_client_versions(catalog),
        vec![
            ("old".to_string(), (0, 98, 0)),
            ("newest".to_string(), (0, 153, 0)),
            ("fixture-style".to_string(), (0, 124, 0)),
            ("pre-release".to_string(), (0, 150, 0)),
        ]
    );
    for unreadable in [
        serde_json::json!("0.155"),
        serde_json::json!("latest"),
        serde_json::json!([0, 155]),
        serde_json::json!([0, -1, 0]),
        serde_json::json!(155),
    ] {
        assert_eq!(parse_version(&unreadable), None, "{unreadable}");
    }
}
