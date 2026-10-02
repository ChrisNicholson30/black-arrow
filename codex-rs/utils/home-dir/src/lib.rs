use blackarrow_base::paths::HOME_DIR_NAME;
use blackarrow_base::paths::HOME_ENV_VAR;
use codex_utils_absolute_path::AbsolutePathBuf;
use dirs::home_dir;
use std::path::PathBuf;

/// Returns the path to the Black Arrow state directory, which can be
/// specified by the `BLACKARROW_HOME` environment variable. If not set,
/// defaults to `~/.blackarrow`.
///
/// The function keeps its upstream name so the rest of the workspace compiles
/// unchanged. It never resolves to Codex's `~/.codex`; see
/// [`blackarrow_base::paths`] for when upstream's `CODEX_HOME` is read.
///
/// - If `BLACKARROW_HOME` is set, the value must exist and be a directory. The
///   value will be canonicalized and this function will Err otherwise.
/// - If `BLACKARROW_HOME` is not set, this function does not verify that the
///   directory exists.
pub fn find_codex_home() -> std::io::Result<AbsolutePathBuf> {
    match blackarrow_base::paths::home_override() {
        Some(found) => find_codex_home_from_env(found.variable, Some(&found.value)),
        None => find_codex_home_from_env(HOME_ENV_VAR, /*codex_home_env*/ None),
    }
}

fn find_codex_home_from_env(
    variable: &str,
    codex_home_env: Option<&str>,
) -> std::io::Result<AbsolutePathBuf> {
    // Honor the override when it is set to allow users (and tests) to move the
    // state directory away from the default location.
    match codex_home_env {
        Some(val) => {
            let path = PathBuf::from(val);
            let metadata = std::fs::metadata(&path).map_err(|err| match err.kind() {
                std::io::ErrorKind::NotFound => std::io::Error::new(
                    std::io::ErrorKind::NotFound,
                    format!("{variable} points to {val:?}, but that path does not exist"),
                ),
                _ => std::io::Error::new(
                    err.kind(),
                    format!("failed to read {variable} {val:?}: {err}"),
                ),
            })?;

            if !metadata.is_dir() {
                Err(std::io::Error::new(
                    std::io::ErrorKind::InvalidInput,
                    format!("{variable} points to {val:?}, but that path is not a directory"),
                ))
            } else {
                let canonical = path.canonicalize().map_err(|err| {
                    std::io::Error::new(
                        err.kind(),
                        format!("failed to canonicalize {variable} {val:?}: {err}"),
                    )
                })?;
                AbsolutePathBuf::from_absolute_path(canonical)
            }
        }
        None => {
            let mut p = home_dir().ok_or_else(|| {
                std::io::Error::new(
                    std::io::ErrorKind::NotFound,
                    "Could not find home directory",
                )
            })?;
            p.push(HOME_DIR_NAME);
            AbsolutePathBuf::from_absolute_path(p)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::find_codex_home_from_env;
    use blackarrow_base::paths::HOME_ENV_VAR;
    use codex_utils_absolute_path::AbsolutePathBuf;
    use dirs::home_dir;
    use pretty_assertions::assert_eq;
    use std::fs;
    use std::io::ErrorKind;
    use tempfile::TempDir;

    #[test]
    fn find_codex_home_env_missing_path_is_fatal() {
        let temp_home = TempDir::new().expect("temp home");
        let missing = temp_home.path().join("missing-codex-home");
        let missing_str = missing
            .to_str()
            .expect("missing codex home path should be valid utf-8");

        let err = find_codex_home_from_env(HOME_ENV_VAR, Some(missing_str))
            .expect_err("missing BLACKARROW_HOME");
        assert_eq!(err.kind(), ErrorKind::NotFound);
        assert!(
            err.to_string().contains("BLACKARROW_HOME"),
            "unexpected error: {err}"
        );
    }

    #[test]
    fn find_codex_home_env_file_path_is_fatal() {
        let temp_home = TempDir::new().expect("temp home");
        let file_path = temp_home.path().join("codex-home.txt");
        fs::write(&file_path, "not a directory").expect("write temp file");
        let file_str = file_path
            .to_str()
            .expect("file codex home path should be valid utf-8");

        let err = find_codex_home_from_env(HOME_ENV_VAR, Some(file_str))
            .expect_err("file BLACKARROW_HOME");
        assert_eq!(err.kind(), ErrorKind::InvalidInput);
        assert!(
            err.to_string().contains("not a directory"),
            "unexpected error: {err}"
        );
    }

    #[test]
    fn find_codex_home_env_valid_directory_canonicalizes() {
        let temp_home = TempDir::new().expect("temp home");
        let temp_str = temp_home
            .path()
            .to_str()
            .expect("temp codex home path should be valid utf-8");

        let resolved =
            find_codex_home_from_env(HOME_ENV_VAR, Some(temp_str)).expect("valid BLACKARROW_HOME");
        let expected = temp_home
            .path()
            .canonicalize()
            .expect("canonicalize temp home");
        let expected = AbsolutePathBuf::from_absolute_path(expected).expect("absolute home");
        assert_eq!(resolved, expected);
    }

    #[test]
    fn find_codex_home_without_env_uses_default_home_dir() {
        let resolved = find_codex_home_from_env(HOME_ENV_VAR, /*codex_home_env*/ None)
            .expect("default BLACKARROW_HOME");
        let mut expected = home_dir().expect("home dir");
        expected.push(".blackarrow");
        let expected = AbsolutePathBuf::from_absolute_path(expected).expect("absolute home");
        assert_eq!(resolved, expected);
    }

    #[test]
    fn find_codex_home_default_never_points_at_upstream_state() {
        let resolved = find_codex_home_from_env(HOME_ENV_VAR, /*codex_home_env*/ None)
            .expect("default BLACKARROW_HOME");
        assert_ne!(
            resolved.as_path().file_name(),
            Some(std::ffi::OsStr::new(".codex")),
            "Black Arrow must not share Codex's state directory"
        );
    }

    #[test]
    fn find_codex_home_error_names_the_variable_that_was_read() {
        let err = find_codex_home_from_env("CODEX_HOME", Some("/nonexistent/black-arrow-test"))
            .expect_err("missing override");
        assert!(
            err.to_string().starts_with("CODEX_HOME points to"),
            "unexpected error: {err}"
        );
    }
}
