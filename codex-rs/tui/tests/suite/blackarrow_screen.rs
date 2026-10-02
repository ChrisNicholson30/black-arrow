//! Black Arrow: what the first screen of a new session shows.
//!
//! Upstream fills the space above the prompt with its animated logo. Black
//! Arrow does not draw it. This crate's unit tests keep the logo switched on
//! (see `empty_state_animation::is_shown`), so this is the test of what the
//! program itself puts on a terminal.

use super::focus_palette::PtyCodex;
use super::focus_palette::write_test_config;
use anyhow::Context;
use anyhow::Result;
use pretty_assertions::assert_eq;
use std::time::Duration;
use std::time::Instant;

/// The logo is drawn in braille patterns, one per terminal cell.
fn is_braille(character: char) -> bool {
    ('\u{2800}'..='\u{28FF}').contains(&character)
}

#[test]
fn new_session_names_black_arrow_and_draws_no_logo() -> Result<()> {
    let repo_root = codex_utils_cargo_bin::repo_root()?;
    let home = tempfile::tempdir()?;
    write_test_config(home.path(), &repo_root)?;
    // The helper's terminal is 120 columns by 32 rows, large enough that
    // upstream centres its logo above the prompt.
    let mut terminal = PtyCodex::start(&repo_root, home, &[])?;
    terminal.wait_for_startup()?;
    terminal.wait_for_screen(blackarrow_base::brand::COMPOSER_PLACEHOLDER)?;
    // Upstream paints the logo with the first frame and animates it for a few
    // seconds; keep reading so a late paint would be seen.
    let settled = Instant::now() + Duration::from_secs(/*secs*/ 1);
    while Instant::now() < settled {
        terminal.read_output(Duration::from_millis(/*millis*/ 50))?;
    }

    let screen = terminal.screen_contents();
    assert!(
        screen.contains(blackarrow_base::brand::PRODUCT_NAME),
        "the session header should name the product:\n{screen}"
    );
    assert!(
        !screen.contains(blackarrow_base::brand::UPSTREAM_PRODUCT_NAME),
        "the session header should not name upstream's product:\n{screen}"
    );

    let prompt_row = screen
        .lines()
        .position(|line| line.contains(blackarrow_base::brand::COMPOSER_PLACEHOLDER))
        .context("no empty prompt on screen")?;
    let logo_cells = screen
        .lines()
        .take(prompt_row)
        .flat_map(str::chars)
        .filter(|character| is_braille(*character))
        .count();
    assert_eq!(
        logo_cells, 0,
        "nothing should be drawn above the prompt except the header:\n{screen}"
    );
    Ok(())
}
