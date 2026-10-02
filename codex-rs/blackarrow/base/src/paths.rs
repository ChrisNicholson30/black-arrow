//! Where Black Arrow keeps its state, and how that location is chosen.
//!
//! Black Arrow and Codex must be able to live on the same machine without
//! touching each other's files. Every name that decides a state location is
//! defined here, alongside the upstream name it replaces.
//!
//! # Upstream names
//!
//! Release builds use only Black Arrow's names. They read `BLACKARROW_*`
//! variables and look for project configuration in `.blackarrow`. A user who
//! has `CODEX_HOME` exported for Codex, or a repository that carries a `.codex`
//! directory for Codex, gets no surprise: Black Arrow ignores both.
//!
//! Debug builds also accept upstream's names where Black Arrow's are absent.
//! The upstream test suite sets `CODEX_HOME` on the processes it spawns and
//! builds fixture projects with a `.codex` directory, in a few hundred places
//! across about seventy files. Rewriting those would make every upstream merge
//! harder for no product benefit. See [`HONORS_UPSTREAM_NAMES`].

/// Environment variable that overrides the state directory.
pub const HOME_ENV_VAR: &str = "BLACKARROW_HOME";

/// State directory name under the user's home directory.
pub const HOME_DIR_NAME: &str = ".blackarrow";

/// Per-project configuration directory name.
pub const PROJECT_DIR_NAME: &str = ".blackarrow";

/// Environment variable that overrides where SQLite state is stored.
pub const SQLITE_HOME_ENV_VAR: &str = "BLACKARROW_SQLITE_HOME";

/// Machine-wide configuration directory on Unix.
pub const SYSTEM_CONFIG_DIR_UNIX: &str = "/etc/blackarrow";

/// Machine-wide defaults, lowest-precedence config layer.
pub const SYSTEM_CONFIG_TOML_UNIX: &str = "/etc/blackarrow/config.toml";

/// Machine-wide requirements that users cannot override.
pub const SYSTEM_REQUIREMENTS_TOML_UNIX: &str = "/etc/blackarrow/requirements.toml";

/// Legacy machine-wide managed config, read as requirements.
pub const SYSTEM_MANAGED_CONFIG_TOML_UNIX: &str = "/etc/blackarrow/managed_config.toml";

/// Prefix reserved for Black Arrow's own environment variables.
pub const ENV_VAR_PREFIX: &str = "BLACKARROW_";

/// Upstream's state directory variable. See the module docs for when it is read.
pub const UPSTREAM_HOME_ENV_VAR: &str = "CODEX_HOME";

/// Upstream's state directory name. Never used as a Black Arrow state location.
pub const UPSTREAM_HOME_DIR_NAME: &str = ".codex";

/// Upstream's per-project directory name. Release builds do not load
/// configuration from it, but the sandbox always protects it from agent writes.
pub const UPSTREAM_PROJECT_DIR_NAME: &str = ".codex";

/// Upstream's SQLite location variable. See the module docs for when it is read.
pub const UPSTREAM_SQLITE_HOME_ENV_VAR: &str = "CODEX_SQLITE_HOME";

/// Prefix of upstream's environment variables, which the runtime still uses
/// internally to talk to its own child processes.
pub const UPSTREAM_ENV_VAR_PREFIX: &str = "CODEX_";

/// Whether this build falls back to upstream's names for state locations.
///
/// True only for builds with debug assertions, which is what `cargo test` and
/// `cargo build` produce. Anything shipped to users is built without them.
pub const HONORS_UPSTREAM_NAMES: bool = cfg!(debug_assertions);

/// Directory names searched for project configuration, most preferred first.
///
/// A directory that has both uses `.blackarrow`.
pub fn project_dir_names() -> &'static [&'static str] {
    project_dir_names_for(HONORS_UPSTREAM_NAMES)
}

fn project_dir_names_for(honor_upstream: bool) -> &'static [&'static str] {
    if honor_upstream {
        &[PROJECT_DIR_NAME, UPSTREAM_PROJECT_DIR_NAME]
    } else {
        &[PROJECT_DIR_NAME]
    }
}

/// Which variable an override came from.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EnvSource {
    /// A `BLACKARROW_*` variable.
    BlackArrow,
    /// An upstream `CODEX_*` variable, accepted for test-suite compatibility.
    UpstreamTestCompat,
}

/// A state location taken from the environment.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EnvOverride {
    /// The raw value of the variable.
    pub value: String,
    /// The name of the variable the value was read from.
    pub variable: &'static str,
    pub source: EnvSource,
}

/// Returns the state directory override from the environment, if any.
pub fn home_override() -> Option<EnvOverride> {
    select_override(
        HOME_ENV_VAR,
        UPSTREAM_HOME_ENV_VAR,
        HONORS_UPSTREAM_NAMES,
        read_env,
    )
}

/// Returns the SQLite directory override from the environment, if any.
pub fn sqlite_home_override() -> Option<EnvOverride> {
    select_override(
        SQLITE_HOME_ENV_VAR,
        UPSTREAM_SQLITE_HOME_ENV_VAR,
        HONORS_UPSTREAM_NAMES,
        read_env,
    )
}

/// Returns true for variable names that a user-editable `.env` file must not
/// be able to set.
///
/// The state directory holds a `.env` file that is loaded at startup. Letting
/// it set `BLACKARROW_HOME` or any internal `CODEX_*` control variable would
/// let a file inside the state directory redirect or reconfigure the process
/// that is reading it.
pub fn is_reserved_env_var(name: &str) -> bool {
    let name = name.to_ascii_uppercase();
    name.starts_with(ENV_VAR_PREFIX) || name.starts_with(UPSTREAM_ENV_VAR_PREFIX)
}

fn read_env(name: &str) -> Option<String> {
    std::env::var(name).ok()
}

fn select_override(
    variable: &'static str,
    upstream_variable: &'static str,
    honor_upstream: bool,
    lookup: impl Fn(&str) -> Option<String>,
) -> Option<EnvOverride> {
    let non_empty = |name: &str| lookup(name).filter(|value| !value.is_empty());

    if let Some(value) = non_empty(variable) {
        return Some(EnvOverride {
            value,
            variable,
            source: EnvSource::BlackArrow,
        });
    }
    if !honor_upstream {
        return None;
    }
    non_empty(upstream_variable).map(|value| EnvOverride {
        value,
        variable: upstream_variable,
        source: EnvSource::UpstreamTestCompat,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use pretty_assertions::assert_eq;
    use std::collections::HashMap;

    fn env(pairs: &[(&str, &str)]) -> impl Fn(&str) -> Option<String> {
        let map: HashMap<String, String> = pairs
            .iter()
            .map(|(name, value)| ((*name).to_string(), (*value).to_string()))
            .collect();
        move |name| map.get(name).cloned()
    }

    fn select(honor_upstream: bool, pairs: &[(&str, &str)]) -> Option<EnvOverride> {
        select_override(
            HOME_ENV_VAR,
            UPSTREAM_HOME_ENV_VAR,
            honor_upstream,
            env(pairs),
        )
    }

    #[test]
    fn black_arrow_variable_wins_over_upstream() {
        let pairs = [("BLACKARROW_HOME", "/ba"), ("CODEX_HOME", "/codex")];
        for honor_upstream in [false, true] {
            assert_eq!(
                select(honor_upstream, &pairs),
                Some(EnvOverride {
                    value: "/ba".to_string(),
                    variable: "BLACKARROW_HOME",
                    source: EnvSource::BlackArrow,
                })
            );
        }
    }

    #[test]
    fn release_builds_ignore_upstream_variable() {
        assert_eq!(
            select(/*honor_upstream*/ false, &[("CODEX_HOME", "/codex")]),
            None
        );
    }

    #[test]
    fn debug_builds_accept_upstream_variable_for_tests() {
        assert_eq!(
            select(/*honor_upstream*/ true, &[("CODEX_HOME", "/codex")]),
            Some(EnvOverride {
                value: "/codex".to_string(),
                variable: "CODEX_HOME",
                source: EnvSource::UpstreamTestCompat,
            })
        );
    }

    #[test]
    fn empty_values_count_as_unset() {
        assert_eq!(
            select(/*honor_upstream*/ true, &[("BLACKARROW_HOME", "")]),
            None
        );
        assert_eq!(
            select(
                /*honor_upstream*/ true,
                &[("BLACKARROW_HOME", ""), ("CODEX_HOME", "/codex")]
            )
            .map(|found| found.source),
            Some(EnvSource::UpstreamTestCompat)
        );
    }

    #[test]
    fn nothing_set_means_no_override() {
        assert_eq!(select(/*honor_upstream*/ true, &[]), None);
    }

    #[test]
    fn dotenv_cannot_set_reserved_variables() {
        for name in [
            "BLACKARROW_HOME",
            "blackarrow_home",
            "BLACKARROW_SQLITE_HOME",
            "CODEX_HOME",
            "codex_sandbox",
        ] {
            assert!(is_reserved_env_var(name), "{name} should be reserved");
        }
        for name in ["OPENAI_API_KEY", "PATH", "MY_BLACKARROW_TOKEN"] {
            assert!(!is_reserved_env_var(name), "{name} should be allowed");
        }
    }

    #[test]
    fn release_builds_search_only_the_black_arrow_project_directory() {
        assert_eq!(
            project_dir_names_for(/*honor_upstream*/ false),
            [".blackarrow"]
        );
    }

    #[test]
    fn debug_builds_prefer_the_black_arrow_project_directory() {
        assert_eq!(
            project_dir_names_for(/*honor_upstream*/ true),
            [".blackarrow", ".codex"]
        );
    }

    #[test]
    fn system_files_live_in_the_system_config_directory() {
        for file in [
            SYSTEM_CONFIG_TOML_UNIX,
            SYSTEM_REQUIREMENTS_TOML_UNIX,
            SYSTEM_MANAGED_CONFIG_TOML_UNIX,
        ] {
            assert_eq!(
                std::path::Path::new(file).parent(),
                Some(std::path::Path::new(SYSTEM_CONFIG_DIR_UNIX)),
                "{file}"
            );
        }
        assert!(!SYSTEM_CONFIG_DIR_UNIX.contains("codex"));
    }

    #[test]
    fn state_and_project_directories_do_not_collide_with_upstream() {
        assert_ne!(HOME_DIR_NAME, UPSTREAM_HOME_DIR_NAME);
        assert_ne!(PROJECT_DIR_NAME, UPSTREAM_PROJECT_DIR_NAME);
        assert_ne!(HOME_ENV_VAR, UPSTREAM_HOME_ENV_VAR);
        assert_ne!(SQLITE_HOME_ENV_VAR, UPSTREAM_SQLITE_HOME_ENV_VAR);
    }
}
