//! Where Black Arrow's defaults differ from upstream's.
//!
//! Each default is read at one upstream call site through [`current`].
//! Changing product policy means editing [`Defaults::BLACK_ARROW`], not
//! hunting through the runtime. Users can still override the configurable
//! ones in `config.toml`.
//!
//! # Upstream's defaults, for upstream's tests
//!
//! Upstream's test suite was written against upstream's defaults. Several
//! dozen app-server tests expect analytics events without asking for them, for
//! instance. Editing each of them, and again after every merge, would cost
//! more than the fork is worth.
//!
//! So a debug build started with `BLACKARROW_UPSTREAM_DEFAULTS=1` uses
//! [`Defaults::UPSTREAM`] instead. `scripts/blackarrow/test.sh` sets the
//! variable; Black Arrow's own tests clear it and assert the real defaults.
//! Release builds ignore it, so the shipped program cannot be talked into
//! different defaults by its environment.

use std::sync::OnceLock;

/// Set to `1` to make a debug build use upstream's defaults. See the module
/// documentation.
pub const UPSTREAM_DEFAULTS_ENV_VAR: &str = "BLACKARROW_UPSTREAM_DEFAULTS";

/// Feature flags whose default differs from upstream, as `(key, enabled)`.
///
/// The defaults themselves are set in upstream's feature table, because that
/// is where every consumer reads them, and that table is a constant: it does
/// not follow [`UPSTREAM_DEFAULTS_ENV_VAR`]. This list is the statement of
/// intent: a test in `codex-features` fails if the table stops agreeing with
/// it, which catches an upstream merge quietly restoring a default.
///
/// `daemon_auto_start`: upstream launches a shared background server that
/// outlives the terminal session and requires a packaged install to exist.
/// Black Arrow runs the server in-process, so nothing is left running after
/// exit and a plain source build starts cleanly.
pub const FEATURE_DEFAULTS: &[(&str, bool)] = &[("daemon_auto_start", false)];

/// The defaults one build of the program uses.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Defaults {
    /// What an unset `[analytics] enabled` means. `None` leaves the decision
    /// to each consumer, which is how upstream ends up sending by default.
    pub analytics_enabled: Option<bool>,
    /// Default for `[feedback] enabled`.
    pub feedback_enabled: bool,
    /// Default for `check_for_update_on_startup`.
    pub check_for_update_on_startup: bool,
    /// Whether there is a release channel to check and update from.
    pub has_release_channel: bool,
    /// Whether a desktop application exists for the `app` command to launch.
    pub has_desktop_app: bool,
    /// Whether to fetch announcement text at startup.
    pub fetch_remote_announcements: bool,
}

impl Defaults {
    /// What the shipped program does.
    ///
    /// - Analytics: upstream reports usage analytics and metrics to OpenAI's
    ///   backends unless the user opts out. Black Arrow is a separate product
    ///   and sends nothing unless the user opts in.
    /// - Feedback: upstream's feedback command uploads session logs to
    ///   OpenAI's issue tracker. Those are not Black Arrow's maintainers.
    /// - Updates: upstream's updater reads Codex release feeds and reinstalls
    ///   the Codex package. Until Black Arrow publishes releases, update
    ///   checks and the `update` command are disabled outright, so they can
    ///   never touch a Codex install on the same machine.
    /// - Desktop app: upstream's command opens the Codex desktop app, or
    ///   downloads its installer. Black Arrow is terminal-only.
    /// - Announcements: upstream downloads them from the Codex repository on
    ///   every launch. They describe a different product, and the request is
    ///   startup network work Black Arrow does not need.
    pub const BLACK_ARROW: Self = Self {
        analytics_enabled: Some(false),
        feedback_enabled: false,
        check_for_update_on_startup: false,
        has_release_channel: false,
        has_desktop_app: false,
        fetch_remote_announcements: false,
    };

    /// What upstream does. Used only by debug builds, and only on request.
    pub const UPSTREAM: Self = Self {
        analytics_enabled: None,
        feedback_enabled: true,
        check_for_update_on_startup: true,
        has_release_channel: true,
        has_desktop_app: true,
        fetch_remote_announcements: true,
    };
}

/// Whether debug builds may be asked for upstream's defaults. False in every
/// release build.
pub const HONORS_UPSTREAM_DEFAULTS_REQUEST: bool = cfg!(debug_assertions);

/// The defaults this process uses.
pub fn current() -> &'static Defaults {
    if uses_upstream_defaults() {
        &Defaults::UPSTREAM
    } else {
        &Defaults::BLACK_ARROW
    }
}

/// Whether this process was started with upstream's defaults. Always false in
/// a release build, which does not read the variable at all.
pub fn uses_upstream_defaults() -> bool {
    if !HONORS_UPSTREAM_DEFAULTS_REQUEST {
        return false;
    }
    static REQUESTED: OnceLock<bool> = OnceLock::new();
    *REQUESTED.get_or_init(|| {
        upstream_defaults_requested(
            HONORS_UPSTREAM_DEFAULTS_REQUEST,
            std::env::var(UPSTREAM_DEFAULTS_ENV_VAR).ok().as_deref(),
        )
    })
}

/// The rule behind [`uses_upstream_defaults`], kept pure so the release rule
/// can be tested from a debug build.
fn upstream_defaults_requested(honors_request: bool, value: Option<&str>) -> bool {
    honors_request && value == Some("1")
}

#[cfg(test)]
mod tests {
    use super::*;
    use pretty_assertions::assert_eq;

    #[test]
    fn feature_default_keys_are_unique() {
        let mut keys: Vec<&str> = FEATURE_DEFAULTS.iter().map(|(key, _)| *key).collect();
        keys.sort_unstable();
        let before = keys.len();
        keys.dedup();
        assert_eq!(keys.len(), before, "duplicate key in FEATURE_DEFAULTS");
    }

    /// Pins the privacy policy: turning any of these on is a product decision
    /// that should have to change this test.
    #[test]
    fn nothing_leaves_the_machine_by_default() {
        assert_eq!(
            Defaults::BLACK_ARROW,
            Defaults {
                analytics_enabled: Some(false),
                feedback_enabled: false,
                check_for_update_on_startup: false,
                has_release_channel: false,
                has_desktop_app: false,
                fetch_remote_announcements: false,
            }
        );
    }

    #[test]
    fn release_builds_ignore_the_request() {
        for value in [None, Some(""), Some("0"), Some("1"), Some("true")] {
            assert_eq!(
                upstream_defaults_requested(/*honors_request*/ false, value),
                false,
                "a release build must not change defaults for {value:?}"
            );
        }
    }

    #[test]
    fn debug_builds_need_the_exact_value() {
        assert_eq!(
            upstream_defaults_requested(/*honors_request*/ true, Some("1")),
            true
        );
        for value in [None, Some(""), Some("0"), Some("true"), Some("yes")] {
            assert_eq!(
                upstream_defaults_requested(/*honors_request*/ true, value),
                false,
                "{value:?} should not select upstream's defaults"
            );
        }
    }
}
