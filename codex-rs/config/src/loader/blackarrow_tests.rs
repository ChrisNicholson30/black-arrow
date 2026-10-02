//! Black Arrow: project configuration is read from `.blackarrow`.
//!
//! Upstream's tests build their fixture projects with a `.codex` directory and
//! pass because debug builds accept that name. These tests cover the name the
//! product actually uses, and the order of preference between the two.

use super::*;
use crate::loader::tests::TestFileSystem;
use pretty_assertions::assert_eq;
use tempfile::TempDir;
use tempfile::tempdir;

struct Fixture {
    _tmp: TempDir,
    state_dir: std::path::PathBuf,
    project: std::path::PathBuf,
    overrides: LoaderOverrides,
}

/// A trusted project next to an empty state directory, with every
/// machine-wide source pointed at files that do not exist.
fn trusted_project() -> Fixture {
    let tmp = tempdir().expect("tempdir");
    let root = tmp.path().canonicalize().expect("canonicalize tempdir");
    let state_dir = root.join("state");
    let project = root.join("project");
    for dir in [&state_dir, &project] {
        std::fs::create_dir_all(dir).expect("create fixture directory");
    }
    std::fs::write(project.join(".project-root"), "").expect("write project marker");

    let project_key = TomlValue::String(project_trust_key(&project)).to_string();
    std::fs::write(
        state_dir.join(CONFIG_TOML_FILE),
        format!(
            "project_root_markers=[\".project-root\"]\n[projects.{project_key}]\ntrust_level=\"trusted\"\n"
        ),
    )
    .expect("write user config");

    let mut overrides =
        LoaderOverrides::with_managed_config_path_for_tests(root.join("managed_config.toml"));
    overrides.system_config_path = Some(root.join("system-config.toml"));
    overrides.system_requirements_path = Some(root.join("system-requirements.toml"));

    Fixture {
        _tmp: tmp,
        state_dir,
        project,
        overrides,
    }
}

fn write_project_config(project: &Path, dir_name: &str, model: &str) {
    let dir = project.join(dir_name);
    std::fs::create_dir_all(&dir).expect("create project config directory");
    std::fs::write(dir.join(CONFIG_TOML_FILE), format!("model = \"{model}\"\n"))
        .expect("write project config");
}

/// The project layers found for the fixture, as `(directory, model)`.
async fn project_layers(fixture: &Fixture) -> Vec<(std::path::PathBuf, Option<String>)> {
    let cwd = AbsolutePathBuf::from_absolute_path(&fixture.project).expect("absolute cwd");
    let layers = local::load_local_config_layers_with_overrides(
        &TestFileSystem,
        &fixture.state_dir,
        &cwd,
        &fixture.overrides,
    )
    .await
    .expect("load local layers");

    layers
        .config
        .layers
        .into_iter()
        .filter(|layer| matches!(layer.source, ConfigLayerSource::Project { .. }))
        .map(|layer| {
            let model = layer
                .toml
                .get("model")
                .and_then(TomlValue::as_str)
                .map(str::to_string);
            (layer.base_dir.to_path_buf(), model)
        })
        .collect()
}

#[tokio::test]
async fn project_config_is_read_from_the_black_arrow_directory() {
    let fixture = trusted_project();
    write_project_config(&fixture.project, ".blackarrow", "from-blackarrow");

    assert_eq!(
        project_layers(&fixture).await,
        vec![(
            fixture.project.join(".blackarrow"),
            Some("from-blackarrow".to_string())
        )]
    );
}

#[tokio::test]
async fn black_arrow_directory_wins_over_upstream_directory() {
    let fixture = trusted_project();
    write_project_config(&fixture.project, ".codex", "from-codex");
    write_project_config(&fixture.project, ".blackarrow", "from-blackarrow");

    assert_eq!(
        project_layers(&fixture).await,
        vec![(
            fixture.project.join(".blackarrow"),
            Some("from-blackarrow".to_string())
        )],
        "a project carrying both directories must use Black Arrow's, and only that one"
    );
}

#[tokio::test]
async fn upstream_directory_alone_is_read_only_by_builds_that_honor_upstream_names() {
    let fixture = trusted_project();
    write_project_config(&fixture.project, ".codex", "from-codex");

    let expected = if blackarrow_base::paths::HONORS_UPSTREAM_NAMES {
        vec![(
            fixture.project.join(".codex"),
            Some("from-codex".to_string()),
        )]
    } else {
        Vec::new()
    };
    assert_eq!(project_layers(&fixture).await, expected);
}

#[tokio::test]
async fn a_project_without_either_directory_has_no_project_layer() {
    let fixture = trusted_project();

    assert_eq!(project_layers(&fixture).await, Vec::new());
}
