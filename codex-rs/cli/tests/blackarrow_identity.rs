//! Black Arrow: what the executable calls itself and where it keeps state.
//!
//! These run the real binary. Each one gets a throwaway HOME so nothing is
//! read from or written to the developer's own directories.

use anyhow::Result;
use predicates::prelude::PredicateBooleanExt;
use predicates::str::contains;
use std::path::Path;
use tempfile::TempDir;

/// The binary under test, with an environment that names no state directory.
fn blackarrow(home: &Path) -> Result<assert_cmd::Command> {
    let mut command = assert_cmd::Command::new(codex_utils_cargo_bin::cargo_bin("blackarrow")?);
    scrub(&mut command, home);
    Ok(command)
}

fn scrub(command: &mut assert_cmd::Command, home: &Path) {
    command
        .env("HOME", home)
        .env_remove("BLACKARROW_HOME")
        .env_remove("BLACKARROW_SQLITE_HOME")
        .env_remove("CODEX_HOME")
        .env_remove("CODEX_SQLITE_HOME")
        // The test runner asks for upstream's defaults. These tests are about
        // Black Arrow's.
        .env_remove(blackarrow_base::defaults::UPSTREAM_DEFAULTS_ENV_VAR);
}

/// Runs `doctor --json` with its reachability probes kept off the network.
fn doctor_report(command: &mut assert_cmd::Command) -> Result<serde_json::Value> {
    let output = command
        .args(["doctor", "--json"])
        .env("HTTPS_PROXY", "http://127.0.0.1:9")
        .env("HTTP_PROXY", "http://127.0.0.1:9")
        .env("ALL_PROXY", "http://127.0.0.1:9")
        .output()?;
    Ok(serde_json::from_slice(&output.stdout)?)
}

fn entries(dir: &Path) -> Vec<String> {
    let mut names: Vec<String> = std::fs::read_dir(dir)
        .map(|entries| {
            entries
                .flatten()
                .map(|entry| entry.file_name().to_string_lossy().into_owned())
                .collect()
        })
        .unwrap_or_default();
    names.sort();
    names
}

#[test]
fn version_names_the_product() -> Result<()> {
    let home = TempDir::new()?;
    blackarrow(home.path())?
        .arg("--version")
        .assert()
        .success()
        .stdout(format!("blackarrow {}\n", env!("CARGO_PKG_VERSION")));
    Ok(())
}

#[test]
fn help_describes_black_arrow() -> Result<()> {
    let home = TempDir::new()?;
    blackarrow(home.path())?
        .arg("--help")
        .assert()
        .success()
        .stdout(
            contains("Black Arrow: terminal coding harness")
                .and(contains("Usage: blackarrow [OPTIONS] [PROMPT]"))
                .and(contains("~/.blackarrow/config.toml"))
                .and(contains("Codex CLI").not())
                .and(contains("Usage: codex").not())
                .and(contains("~/.codex").not())
                .and(contains("$CODEX_HOME").not()),
        );
    Ok(())
}

#[test]
fn help_omits_commands_that_belong_to_codex() -> Result<()> {
    let home = TempDir::new()?;
    let output = blackarrow(home.path())?.arg("--help").output()?;
    let help = String::from_utf8(output.stdout)?;
    let commands: Vec<&str> = help
        .lines()
        .skip_while(|line| *line != "Commands:")
        .skip(1)
        .take_while(|line| !line.is_empty())
        .filter_map(|line| line.strip_prefix("  "))
        .filter(|line| !line.starts_with(' '))
        .filter_map(|line| line.split_whitespace().next())
        .collect();

    assert!(
        commands.contains(&"doctor") && commands.contains(&"exec"),
        "expected the command list to be parsed, got {commands:?}"
    );
    for hidden in ["update", "app", "cloud", "apply"] {
        assert!(
            !commands.contains(&hidden),
            "`{hidden}` acts on Codex or an OpenAI service and should not be offered: {commands:?}"
        );
    }
    Ok(())
}

#[cfg(unix)]
#[test]
fn ba_alias_is_the_same_program() -> Result<()> {
    let home = TempDir::new()?;
    let bin_dir = TempDir::new()?;
    let alias = bin_dir.path().join("ba");
    std::os::unix::fs::symlink(codex_utils_cargo_bin::cargo_bin("blackarrow")?, &alias)?;

    let mut command = assert_cmd::Command::new(&alias);
    scrub(&mut command, home.path());
    command
        .arg("--version")
        .assert()
        .success()
        .stdout(format!("blackarrow {}\n", env!("CARGO_PKG_VERSION")));
    Ok(())
}

#[test]
fn state_defaults_to_dot_blackarrow_and_never_dot_codex() -> Result<()> {
    let home = TempDir::new()?;
    // Any invocation prepares the state directory before arguments are parsed.
    blackarrow(home.path())?.arg("--version").assert().success();

    assert_eq!(entries(home.path()), vec![".blackarrow".to_string()]);
    Ok(())
}

#[test]
fn existing_codex_state_is_left_untouched() -> Result<()> {
    let home = TempDir::new()?;
    let codex_state = home.path().join(".codex");
    std::fs::create_dir(&codex_state)?;
    std::fs::write(codex_state.join("config.toml"), "model = \"codex-only\"\n")?;
    std::fs::write(codex_state.join("auth.json"), "{\"marker\":true}\n")?;

    blackarrow(home.path())?
        .args(["features", "list"])
        .assert()
        .success();

    assert_eq!(
        entries(&codex_state),
        vec!["auth.json".to_string(), "config.toml".to_string()],
        "Black Arrow must not create anything inside Codex's state directory"
    );
    assert_eq!(
        std::fs::read_to_string(codex_state.join("config.toml"))?,
        "model = \"codex-only\"\n"
    );
    assert_eq!(
        std::fs::read_to_string(codex_state.join("auth.json"))?,
        "{\"marker\":true}\n"
    );
    Ok(())
}

#[test]
fn blackarrow_home_takes_precedence_over_codex_home() -> Result<()> {
    let home = TempDir::new()?;
    let chosen = TempDir::new()?;
    let upstream = TempDir::new()?;

    blackarrow(home.path())?
        .env("BLACKARROW_HOME", chosen.path())
        .env("CODEX_HOME", upstream.path())
        .arg("--version")
        .assert()
        .success();

    assert!(
        !entries(chosen.path()).is_empty(),
        "state should be prepared under BLACKARROW_HOME"
    );
    assert_eq!(
        entries(upstream.path()),
        Vec::<String>::new(),
        "CODEX_HOME must be ignored when BLACKARROW_HOME is set"
    );
    assert_eq!(
        entries(home.path()),
        Vec::<String>::new(),
        "the default directory must not be created when an override is set"
    );
    Ok(())
}

#[test]
fn missing_blackarrow_home_is_reported_by_name() -> Result<()> {
    let home = TempDir::new()?;
    blackarrow(home.path())?
        .env("BLACKARROW_HOME", home.path().join("does-not-exist"))
        .args(["features", "list"])
        .assert()
        .failure()
        .stderr(contains("BLACKARROW_HOME"));
    Ok(())
}

#[test]
fn update_is_refused() -> Result<()> {
    let home = TempDir::new()?;
    blackarrow(home.path())?
        .arg("update")
        .assert()
        .failure()
        .stderr(contains("does not publish releases yet"));
    Ok(())
}

#[cfg(target_os = "macos")]
#[test]
fn app_is_refused() -> Result<()> {
    let home = TempDir::new()?;
    blackarrow(home.path())?
        .arg("app")
        .assert()
        .failure()
        .stderr(contains("no desktop app"));
    Ok(())
}

#[test]
fn doctor_reports_isolation() -> Result<()> {
    let home = TempDir::new()?;
    std::fs::create_dir(home.path().join(".codex"))?;

    let report = doctor_report(&mut blackarrow(home.path())?)?;
    // The JSON report keys its checks by id.
    let isolation = &report["checks"]["isolation.state"];
    assert!(
        isolation.is_object(),
        "no isolation check in doctor output: {}",
        report["checks"]
    );

    assert_eq!(isolation["status"], "ok", "{isolation}");
    assert_eq!(isolation["summary"], "state is separate from Codex");
    assert_eq!(
        isolation["details"]["Codex state"]
            .as_str()
            .map(|detail| detail.ends_with(".codex, not used")),
        Some(true),
        "{isolation}"
    );
    Ok(())
}

#[test]
fn nothing_is_reported_or_uploaded_by_default() -> Result<()> {
    let home = TempDir::new()?;

    let report = doctor_report(&mut blackarrow(home.path())?)?;
    let privacy = &report["checks"]["privacy.defaults"];

    assert_eq!(privacy["status"], "ok", "{privacy}");
    assert_eq!(
        privacy["summary"],
        "analytics, feedback upload, and update checks are off"
    );
    for switch in [
        "usage analytics",
        "feedback upload",
        "update check",
        "remote announcements",
    ] {
        assert_eq!(privacy["details"][switch], "off", "{privacy}");
    }
    Ok(())
}

#[test]
fn analytics_follow_the_users_configuration() -> Result<()> {
    let home = TempDir::new()?;
    let state = home.path().join(".blackarrow");
    std::fs::create_dir(&state)?;
    std::fs::write(state.join("config.toml"), "[analytics]\nenabled = true\n")?;

    let report = doctor_report(&mut blackarrow(home.path())?)?;
    let privacy = &report["checks"]["privacy.defaults"];

    assert_eq!(privacy["status"], "ok", "{privacy}");
    assert_eq!(privacy["summary"], "on, as configured: usage analytics");
    assert_eq!(privacy["details"]["feedback upload"], "off", "{privacy}");
    Ok(())
}

/// The switch the test runner uses. It exists only in debug builds, which is
/// what tests run, so this also shows the doctor warning a developer would see.
#[test]
fn debug_build_can_be_asked_for_upstream_defaults() -> Result<()> {
    let home = TempDir::new()?;

    let mut command = blackarrow(home.path())?;
    command.env(blackarrow_base::defaults::UPSTREAM_DEFAULTS_ENV_VAR, "1");
    let report = doctor_report(&mut command)?;
    let privacy = &report["checks"]["privacy.defaults"];

    assert_eq!(privacy["status"], "warning", "{privacy}");
    assert_eq!(privacy["summary"], "running with upstream's defaults");
    assert_eq!(privacy["details"]["usage analytics"], "on", "{privacy}");
    Ok(())
}
