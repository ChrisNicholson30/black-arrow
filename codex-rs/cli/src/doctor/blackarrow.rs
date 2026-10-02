//! Black Arrow's own doctor checks.
//!
//! Upstream's checks cover the runtime. This module covers what is specific to
//! the fork: that Black Arrow's state is kept apart from a Codex install on the
//! same machine, and that nothing is reported to anyone unless the user asked.

use std::path::Path;
use std::path::PathBuf;

use blackarrow_base::defaults;
use blackarrow_base::defaults::Defaults;
use blackarrow_base::paths;
use blackarrow_base::paths::EnvSource;
use blackarrow_base::startup;
use codex_core::config::Config;

use super::CheckStatus;
use super::DoctorCheck;
use super::DoctorIssue;

/// What the isolation check needs to know about the machine.
struct IsolationFacts {
    /// The state directory in use, or why it could not be resolved.
    state_dir: Result<PathBuf, String>,
    /// The override that chose the state directory, if one did.
    state_dir_override: Option<paths::EnvOverride>,
    /// The upstream variable's value, whether or not this build reads it.
    upstream_home_env: Option<String>,
    /// Where Codex keeps its state by default.
    upstream_default_dir: Option<PathBuf>,
    /// Whether that default Codex directory exists.
    upstream_default_dir_exists: bool,
    /// Whether this build falls back to upstream's variables.
    honors_upstream_env: bool,
    /// Where a startup timeline is being written, if tracing is on.
    startup_trace: Option<String>,
}

impl IsolationFacts {
    fn gather() -> Self {
        let upstream_default_dir = dirs_home().map(|home| home.join(paths::UPSTREAM_HOME_DIR_NAME));
        Self {
            state_dir: codex_core::config::find_codex_home()
                .map(|dir| dir.to_path_buf())
                .map_err(|err| err.to_string()),
            state_dir_override: paths::home_override(),
            upstream_home_env: std::env::var(paths::UPSTREAM_HOME_ENV_VAR)
                .ok()
                .filter(|value| !value.is_empty()),
            upstream_default_dir_exists: upstream_default_dir.as_deref().is_some_and(Path::is_dir),
            upstream_default_dir,
            honors_upstream_env: paths::HONORS_UPSTREAM_NAMES,
            startup_trace: std::env::var(startup::TRACE_ENV_VAR)
                .ok()
                .filter(|value| !value.is_empty()),
        }
    }
}

fn dirs_home() -> Option<PathBuf> {
    std::env::var_os("HOME")
        .filter(|home| !home.is_empty())
        .map(PathBuf::from)
}

/// Reports where state lives and whether it is separate from Codex.
pub(super) fn isolation_check() -> DoctorCheck {
    isolation_check_from(IsolationFacts::gather())
}

fn isolation_check_from(facts: IsolationFacts) -> DoctorCheck {
    let state_dir = match &facts.state_dir {
        Ok(state_dir) => state_dir,
        Err(error) => {
            return DoctorCheck::new(
                "isolation.state",
                "isolation",
                CheckStatus::Fail,
                "state directory could not be resolved",
            )
            .detail(format!("error: {error}"))
            .remediation(format!(
                "Point {} at an existing directory, or unset it to use ~/{}.",
                paths::HOME_ENV_VAR,
                paths::HOME_DIR_NAME
            ));
        }
    };

    let source = match &facts.state_dir_override {
        Some(found) => format!("{} environment variable", found.variable),
        None => format!("default (~/{})", paths::HOME_DIR_NAME),
    };
    let mut details = vec![
        format!("state directory: {}", state_dir.display()),
        format!("chosen by: {source}"),
        format!("project directory: {}", paths::PROJECT_DIR_NAME),
    ];
    details.push(
        match (&facts.upstream_home_env, facts.honors_upstream_env) {
            (None, _) => format!("{}: not set", paths::UPSTREAM_HOME_ENV_VAR),
            (Some(_), false) => format!("{}: set, ignored", paths::UPSTREAM_HOME_ENV_VAR),
            (Some(_), true) => format!(
                "{}: set, read by this debug build",
                paths::UPSTREAM_HOME_ENV_VAR
            ),
        },
    );
    if let Some(upstream_dir) = &facts.upstream_default_dir {
        details.push(format!(
            "Codex state: {}",
            if facts.upstream_default_dir_exists {
                format!("found at {}, not used", upstream_dir.display())
            } else {
                "none found".to_string()
            }
        ));
    }
    details.push(format!(
        "startup trace: {}",
        match &facts.startup_trace {
            Some(path) => format!("writing to {path}"),
            None => format!("off (set {} to a file path)", startup::TRACE_ENV_VAR),
        }
    ));

    if shares_upstream_state(state_dir, &facts) {
        return DoctorCheck::new(
            "isolation.state",
            "isolation",
            CheckStatus::Fail,
            "state directory is shared with Codex",
        )
        .details(details)
        .issue(
            DoctorIssue::new(
                CheckStatus::Fail,
                "Black Arrow and Codex are reading and writing the same state directory",
            )
            .measured(state_dir.display().to_string())
            .expected("a directory used only by Black Arrow")
            .remedy(format!(
                "Set {} to a directory of its own, or unset it.",
                paths::HOME_ENV_VAR
            )),
        );
    }

    let uses_upstream_env = facts
        .state_dir_override
        .as_ref()
        .is_some_and(|found| found.source == EnvSource::UpstreamTestCompat);
    if uses_upstream_env {
        return DoctorCheck::new(
            "isolation.state",
            "isolation",
            CheckStatus::Warning,
            format!(
                "state directory comes from {}",
                paths::UPSTREAM_HOME_ENV_VAR
            ),
        )
        .details(details)
        .issue(
            DoctorIssue::new(
                CheckStatus::Warning,
                format!(
                    "this debug build reads {} so the upstream test suite can isolate itself",
                    paths::UPSTREAM_HOME_ENV_VAR
                ),
            )
            .expected(format!(
                "{} unset outside tests",
                paths::UPSTREAM_HOME_ENV_VAR
            ))
            .remedy(format!(
                "Unset {}, or set {} to choose the directory explicitly. Release builds ignore {}.",
                paths::UPSTREAM_HOME_ENV_VAR,
                paths::HOME_ENV_VAR,
                paths::UPSTREAM_HOME_ENV_VAR
            )),
        );
    }

    DoctorCheck::new(
        "isolation.state",
        "isolation",
        CheckStatus::Ok,
        "state is separate from Codex",
    )
    .details(details)
}

/// True when the state directory is the one Codex uses by default.
///
/// Paths are compared after resolving symlinks where possible, so a symlink
/// from one directory to the other is caught too.
fn shares_upstream_state(state_dir: &Path, facts: &IsolationFacts) -> bool {
    let Some(upstream_dir) = facts.upstream_default_dir.as_deref() else {
        return false;
    };
    same_location(state_dir, upstream_dir)
}

fn same_location(left: &Path, right: &Path) -> bool {
    let resolve = |path: &Path| path.canonicalize().unwrap_or_else(|_| path.to_path_buf());
    resolve(left) == resolve(right)
}

/// What the privacy check needs to know.
struct PrivacyFacts {
    /// `[analytics] enabled` as resolved, or the default if configuration did
    /// not load. `None` leaves the decision to each consumer, which sends.
    analytics_enabled: Option<bool>,
    /// `[feedback] enabled` as resolved.
    feedback_enabled: bool,
    /// `check_for_update_on_startup` as resolved.
    check_for_update_on_startup: bool,
    /// The defaults this process runs with.
    defaults: Defaults,
    /// Whether those are upstream's, requested through the environment.
    uses_upstream_defaults: bool,
}

impl PrivacyFacts {
    fn gather(config: Option<&Config>) -> Self {
        let defaults = *defaults::current();
        Self {
            analytics_enabled: config.map_or(defaults.analytics_enabled, |config| {
                config.analytics_enabled
            }),
            feedback_enabled: config
                .map_or(defaults.feedback_enabled, |config| config.feedback_enabled),
            check_for_update_on_startup: config
                .map_or(defaults.check_for_update_on_startup, |config| {
                    config.check_for_update_on_startup
                }),
            defaults,
            uses_upstream_defaults: defaults::uses_upstream_defaults(),
        }
    }
}

/// Reports what is sent anywhere other than the model provider.
pub(super) fn privacy_check(config: Option<&Config>) -> DoctorCheck {
    privacy_check_from(PrivacyFacts::gather(config))
}

fn privacy_check_from(facts: PrivacyFacts) -> DoctorCheck {
    let update_check = facts.defaults.has_release_channel && facts.check_for_update_on_startup;
    let switches = [
        ("usage analytics", facts.analytics_enabled != Some(false)),
        ("feedback upload", facts.feedback_enabled),
        ("update check", update_check),
        (
            "remote announcements",
            facts.defaults.fetch_remote_announcements,
        ),
    ];
    let details: Vec<String> = switches
        .iter()
        .map(|(name, on)| format!("{name}: {}", if *on { "on" } else { "off" }))
        .collect();
    let sending: Vec<&str> = switches
        .iter()
        .filter(|(_, on)| *on)
        .map(|(name, _)| *name)
        .collect();

    if facts.uses_upstream_defaults {
        return DoctorCheck::new(
            "privacy.defaults",
            "privacy",
            CheckStatus::Warning,
            "running with upstream's defaults",
        )
        .details(details)
        .issue(
            DoctorIssue::new(
                CheckStatus::Warning,
                format!(
                    "this debug build was started with {}=1, which the test suite uses",
                    defaults::UPSTREAM_DEFAULTS_ENV_VAR
                ),
            )
            .expected(format!(
                "{} unset outside tests",
                defaults::UPSTREAM_DEFAULTS_ENV_VAR
            ))
            .remedy(format!(
                "Unset {}. Release builds ignore it.",
                defaults::UPSTREAM_DEFAULTS_ENV_VAR
            )),
        );
    }

    let summary = if sending.is_empty() {
        "analytics, feedback upload, and update checks are off".to_string()
    } else {
        format!("on, as configured: {}", sending.join(", "))
    };
    DoctorCheck::new("privacy.defaults", "privacy", CheckStatus::Ok, summary).details(details)
}

#[cfg(test)]
mod tests {
    use super::*;
    use pretty_assertions::assert_eq;

    fn privacy_facts() -> PrivacyFacts {
        PrivacyFacts {
            analytics_enabled: Defaults::BLACK_ARROW.analytics_enabled,
            feedback_enabled: Defaults::BLACK_ARROW.feedback_enabled,
            check_for_update_on_startup: Defaults::BLACK_ARROW.check_for_update_on_startup,
            defaults: Defaults::BLACK_ARROW,
            uses_upstream_defaults: false,
        }
    }

    #[test]
    fn black_arrow_defaults_send_nothing() {
        let check = privacy_check_from(privacy_facts());

        assert_eq!(check.status, CheckStatus::Ok);
        assert_eq!(
            check.summary,
            "analytics, feedback upload, and update checks are off"
        );
        assert_eq!(
            check.details,
            vec![
                "usage analytics: off".to_string(),
                "feedback upload: off".to_string(),
                "update check: off".to_string(),
                "remote announcements: off".to_string(),
            ]
        );
    }

    #[test]
    fn settings_the_user_turned_on_are_named() {
        let mut facts = privacy_facts();
        facts.analytics_enabled = Some(true);
        facts.feedback_enabled = true;
        let check = privacy_check_from(facts);

        assert_eq!(check.status, CheckStatus::Ok);
        assert_eq!(
            check.summary,
            "on, as configured: usage analytics, feedback upload"
        );
    }

    #[test]
    fn update_check_needs_a_release_channel() {
        let mut facts = privacy_facts();
        facts.check_for_update_on_startup = true;
        let check = privacy_check_from(facts);

        assert_eq!(detail(&check, "update check"), "off");
    }

    #[test]
    fn upstream_defaults_warn() {
        let check = privacy_check_from(PrivacyFacts {
            analytics_enabled: Defaults::UPSTREAM.analytics_enabled,
            feedback_enabled: Defaults::UPSTREAM.feedback_enabled,
            check_for_update_on_startup: Defaults::UPSTREAM.check_for_update_on_startup,
            defaults: Defaults::UPSTREAM,
            uses_upstream_defaults: true,
        });

        assert_eq!(check.status, CheckStatus::Warning);
        assert_eq!(check.summary, "running with upstream's defaults");
        assert_eq!(detail(&check, "usage analytics"), "on");
        assert_eq!(check.issues.len(), 1);
    }

    fn facts(state_dir: &Path, home: &Path) -> IsolationFacts {
        IsolationFacts {
            state_dir: Ok(state_dir.to_path_buf()),
            state_dir_override: None,
            upstream_home_env: None,
            upstream_default_dir: Some(home.join(".codex")),
            upstream_default_dir_exists: false,
            honors_upstream_env: false,
            startup_trace: None,
        }
    }

    fn detail<'a>(check: &'a DoctorCheck, label: &str) -> &'a str {
        check
            .details
            .iter()
            .find_map(|line| line.strip_prefix(&format!("{label}: ")))
            .unwrap_or_else(|| panic!("no `{label}` detail in {:?}", check.details))
    }

    #[test]
    fn default_state_directory_is_ok() {
        let home = tempfile::tempdir().expect("tempdir");
        let state_dir = home.path().join(".blackarrow");
        let check = isolation_check_from(facts(&state_dir, home.path()));

        assert_eq!(check.status, CheckStatus::Ok);
        assert_eq!(check.summary, "state is separate from Codex");
        assert_eq!(detail(&check, "chosen by"), "default (~/.blackarrow)");
        assert_eq!(detail(&check, "CODEX_HOME"), "not set");
        assert_eq!(detail(&check, "Codex state"), "none found");
    }

    #[test]
    fn existing_codex_install_is_reported_but_not_a_problem() {
        let home = tempfile::tempdir().expect("tempdir");
        std::fs::create_dir(home.path().join(".codex")).expect("create upstream dir");
        let mut facts = facts(&home.path().join(".blackarrow"), home.path());
        facts.upstream_default_dir_exists = true;
        let check = isolation_check_from(facts);

        assert_eq!(check.status, CheckStatus::Ok);
        assert!(
            detail(&check, "Codex state").ends_with(".codex, not used"),
            "{:?}",
            check.details
        );
    }

    #[test]
    fn release_build_reports_upstream_variable_as_ignored() {
        let home = tempfile::tempdir().expect("tempdir");
        let mut facts = facts(&home.path().join(".blackarrow"), home.path());
        facts.upstream_home_env = Some("/somewhere/else".to_string());
        let check = isolation_check_from(facts);

        assert_eq!(check.status, CheckStatus::Ok);
        assert_eq!(detail(&check, "CODEX_HOME"), "set, ignored");
    }

    #[test]
    fn debug_build_following_upstream_variable_warns() {
        let home = tempfile::tempdir().expect("tempdir");
        let state_dir = home.path().join("elsewhere");
        let mut facts = facts(&state_dir, home.path());
        facts.honors_upstream_env = true;
        facts.upstream_home_env = Some(state_dir.display().to_string());
        facts.state_dir_override = Some(paths::EnvOverride {
            value: state_dir.display().to_string(),
            variable: paths::UPSTREAM_HOME_ENV_VAR,
            source: EnvSource::UpstreamTestCompat,
        });
        let check = isolation_check_from(facts);

        assert_eq!(check.status, CheckStatus::Warning);
        assert_eq!(check.summary, "state directory comes from CODEX_HOME");
        assert_eq!(
            detail(&check, "CODEX_HOME"),
            "set, read by this debug build"
        );
        assert_eq!(check.issues.len(), 1);
    }

    #[test]
    fn sharing_the_codex_directory_fails() {
        let home = tempfile::tempdir().expect("tempdir");
        let upstream = home.path().join(".codex");
        std::fs::create_dir(&upstream).expect("create upstream dir");
        let mut facts = facts(&upstream, home.path());
        facts.upstream_default_dir_exists = true;
        facts.state_dir_override = Some(paths::EnvOverride {
            value: upstream.display().to_string(),
            variable: paths::HOME_ENV_VAR,
            source: EnvSource::BlackArrow,
        });
        let check = isolation_check_from(facts);

        assert_eq!(check.status, CheckStatus::Fail);
        assert_eq!(check.summary, "state directory is shared with Codex");
    }

    #[cfg(unix)]
    #[test]
    fn symlink_to_the_codex_directory_fails() {
        let home = tempfile::tempdir().expect("tempdir");
        let upstream = home.path().join(".codex");
        std::fs::create_dir(&upstream).expect("create upstream dir");
        let link = home.path().join(".blackarrow");
        std::os::unix::fs::symlink(&upstream, &link).expect("symlink");
        let mut facts = facts(&link, home.path());
        facts.upstream_default_dir_exists = true;
        let check = isolation_check_from(facts);

        assert_eq!(check.status, CheckStatus::Fail);
    }

    #[test]
    fn unresolvable_state_directory_fails_with_guidance() {
        let home = tempfile::tempdir().expect("tempdir");
        let mut facts = facts(&home.path().join(".blackarrow"), home.path());
        facts.state_dir =
            Err("BLACKARROW_HOME points to \"/nope\", but that path does not exist".into());
        let check = isolation_check_from(facts);

        assert_eq!(check.status, CheckStatus::Fail);
        assert_eq!(check.summary, "state directory could not be resolved");
        assert!(
            check
                .remediation
                .as_deref()
                .is_some_and(|text| text.contains("BLACKARROW_HOME")),
            "{:?}",
            check.remediation
        );
    }

    #[test]
    fn startup_trace_destination_is_shown_when_enabled() {
        let home = tempfile::tempdir().expect("tempdir");
        let mut facts = facts(&home.path().join(".blackarrow"), home.path());
        facts.startup_trace = Some("/tmp/trace.json".to_string());
        let check = isolation_check_from(facts);

        assert_eq!(
            detail(&check, "startup trace"),
            "writing to /tmp/trace.json"
        );
    }
}
