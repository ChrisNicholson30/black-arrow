//! Black Arrow checks on the upstream feature table.
//!
//! Feature defaults live in upstream's `FEATURES` table, because every consumer
//! reads them from there. Black Arrow's policy is declared separately in
//! `blackarrow_base::defaults`. These tests fail if the two drift apart, which
//! is what happens when an upstream merge rewrites an entry Black Arrow changed.

use crate::FEATURES;
use crate::Features;
use blackarrow_base::defaults::FEATURE_DEFAULTS;
use pretty_assertions::assert_eq;

#[test]
fn feature_table_matches_black_arrow_policy() {
    for (key, expected) in FEATURE_DEFAULTS {
        let spec = FEATURES
            .iter()
            .find(|spec| spec.key == *key)
            .unwrap_or_else(|| panic!("policy names unknown feature `{key}`"));
        assert_eq!(
            spec.default_enabled, *expected,
            "feature `{key}` default drifted from Black Arrow policy"
        );
    }
}

#[test]
fn default_feature_set_honours_black_arrow_policy() {
    let features = Features::with_defaults();
    for (key, expected) in FEATURE_DEFAULTS {
        let spec = FEATURES
            .iter()
            .find(|spec| spec.key == *key)
            .unwrap_or_else(|| panic!("policy names unknown feature `{key}`"));
        assert_eq!(features.enabled(spec.id), *expected, "feature `{key}`");
    }
}
