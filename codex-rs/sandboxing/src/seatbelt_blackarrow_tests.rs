//! Black Arrow sandbox checks.
//!
//! Black Arrow reads project configuration and hooks from `.blackarrow`. An
//! agent that could write there could change its own sandbox mode or plant a
//! hook, so the directory has to be exactly as protected as upstream's
//! `.codex`. These tests run real commands under `sandbox-exec` to prove it.

use super::*;
use pretty_assertions::assert_eq;

/// The policy a normal session runs with: the workspace is writable, nothing
/// else is.
fn workspace_write() -> SandboxPolicy {
    SandboxPolicy::WorkspaceWrite {
        writable_roots: Vec::new(),
        network_access: false,
        exclude_tmpdir_env_var: true,
        exclude_slash_tmp: true,
    }
}

/// Runs `script` with `$1` set to `target`, sandboxed as an agent command
/// would be in `workspace`.
fn run_sandboxed(workspace: &Path, script: &str, target: &Path) -> std::process::Output {
    let command = ["bash", "-c", script, "bash", &target.to_string_lossy()]
        .iter()
        .map(ToString::to_string)
        .collect();
    let args = create_seatbelt_command_args_for_legacy_policy(
        command,
        &workspace_write(),
        workspace,
        /*enforce_managed_network*/ false,
        /*network*/ None,
    )
    .expect("build seatbelt arguments");
    Command::new(MACOS_PATH_TO_SEATBELT_EXECUTABLE)
        .args(&args)
        .current_dir(workspace)
        .output()
        .expect("run sandbox-exec")
}

fn workspace() -> (TempDir, PathBuf) {
    let tmp = TempDir::new().expect("tempdir");
    let workspace = tmp.path().canonicalize().expect("canonicalize").join("ws");
    fs::create_dir_all(&workspace).expect("create workspace");
    (tmp, workspace)
}

#[test]
fn agent_cannot_rewrite_project_config() {
    let (_tmp, workspace) = workspace();
    let config = workspace.join(".blackarrow").join("config.toml");
    fs::create_dir_all(config.parent().expect("parent")).expect("create project dir");
    fs::write(&config, "sandbox_mode = \"read-only\"\n").expect("write config");

    let output = run_sandboxed(
        &workspace,
        "echo 'sandbox_mode = \"danger-full-access\"' > \"$1\"",
        &config,
    );

    assert!(
        !output.status.success(),
        "overwriting {} should be denied",
        config.display()
    );
    assert_eq!(
        fs::read_to_string(&config).expect("read config"),
        "sandbox_mode = \"read-only\"\n",
        "project config must be unchanged"
    );
    assert_seatbelt_denied(&output.stderr, &config);
}

#[test]
fn agent_cannot_plant_project_hooks() {
    let (_tmp, workspace) = workspace();
    let project_dir = workspace.join(".blackarrow");
    fs::create_dir_all(&project_dir).expect("create project dir");
    let hooks = project_dir.join("hooks.json");

    let output = run_sandboxed(&workspace, "echo '{}' > \"$1\"", &hooks);

    assert!(
        !output.status.success(),
        "creating {} should be denied",
        hooks.display()
    );
    assert!(!hooks.exists(), "{} must not be created", hooks.display());
    assert_seatbelt_denied(&output.stderr, &hooks);
}

#[test]
fn agent_cannot_create_project_directory() {
    let (_tmp, workspace) = workspace();
    let project_dir = workspace.join(".blackarrow");

    let output = run_sandboxed(&workspace, "mkdir \"$1\"", &project_dir);

    assert!(
        !output.status.success(),
        "creating {} should be denied",
        project_dir.display()
    );
    assert!(
        !project_dir.exists(),
        "{} must not be created",
        project_dir.display()
    );
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("Operation not permitted"),
        "expected a sandbox denial, got: {stderr}"
    );
}

#[test]
fn upstream_project_directory_stays_protected() {
    let (_tmp, workspace) = workspace();
    let config = workspace.join(".codex").join("config.toml");
    fs::create_dir_all(config.parent().expect("parent")).expect("create upstream dir");
    fs::write(&config, "model = \"original\"\n").expect("write config");

    let output = run_sandboxed(&workspace, "echo 'model = \"changed\"' > \"$1\"", &config);

    assert!(
        !output.status.success(),
        "a Black Arrow agent must not rewrite Codex's project config"
    );
    assert_eq!(
        fs::read_to_string(&config).expect("read config"),
        "model = \"original\"\n"
    );
}

#[test]
fn agent_can_write_ordinary_workspace_files() {
    let (_tmp, workspace) = workspace();
    let file = workspace.join("notes.txt");

    let output = run_sandboxed(&workspace, "echo ok > \"$1\"", &file);

    // A nested sandbox refuses to apply a second profile. That says nothing
    // about this policy, so only a real run is judged.
    let stderr = String::from_utf8_lossy(&output.stderr);
    if stderr.contains("sandbox_apply: Operation not permitted") {
        return;
    }
    assert!(
        output.status.success(),
        "writing {} should be allowed: {stderr}",
        file.display()
    );
    assert_eq!(fs::read_to_string(&file).expect("read file"), "ok\n");
}
