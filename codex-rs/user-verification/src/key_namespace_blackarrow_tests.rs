//! Black Arrow: device keys are labelled as Black Arrow's, not Codex's.

use super::*;

#[test]
fn label_belongs_to_black_arrow() {
    let namespace = UserVerificationKeyNamespace::new("account-user-one");

    assert!(
        namespace
            .label
            .starts_with("dev.blackarrow.user-verification."),
        "unexpected label: {}",
        namespace.label
    );
    assert!(
        !namespace.label.contains("openai"),
        "a key labelled for Codex would be shared with a Codex install: {}",
        namespace.label
    );
}
