//! Black Arrow: a terminated session must hand the terminal back clean.
//!
//! Each test starts the TUI on a pseudo-terminal, sends it a signal, and reads
//! what it wrote on the way out. The process has to undo every mode it turned
//! on and still report that the signal killed it.

use super::focus_palette::PtyCodex;
use super::focus_palette::write_test_config;
use anyhow::Result;
use pretty_assertions::assert_eq;
use std::os::unix::process::ExitStatusExt;
use std::time::Duration;

const LEAVE_ALTERNATE_SCREEN: &[u8] = b"\x1b[?1049l";
const DISABLE_BRACKETED_PASTE: &[u8] = b"\x1b[?2004l";
const DISABLE_FOCUS_REPORTING: &[u8] = b"\x1b[?1004l";
const SHOW_CURSOR: &[u8] = b"\x1b[?25h";

fn contains(haystack: &[u8], needle: &[u8]) -> bool {
    haystack
        .windows(needle.len())
        .any(|window| window == needle)
}

fn terminated_session_restores_terminal(signal: libc::c_int) -> Result<()> {
    let repo_root = codex_utils_cargo_bin::repo_root()?;
    let home = tempfile::tempdir()?;
    write_test_config(home.path(), &repo_root)?;
    let mut terminal = PtyCodex::start(&repo_root, home, &[])?;
    terminal.wait_for_startup()?;
    let written_before = terminal.raw_output().len();

    let pid = libc::pid_t::try_from(terminal.pid())?;
    // SAFETY: `pid` is the child this test started and still owns.
    let sent = unsafe { libc::kill(pid, signal) };
    assert_eq!(sent, 0, "failed to signal the session");

    let status = terminal.wait_for_exit(Duration::from_secs(/*secs*/ 15))?;
    assert_eq!(
        status.signal(),
        Some(signal),
        "the parent should still see the process as killed by the signal"
    );

    let farewell = &terminal.raw_output()[written_before..];
    for (what, sequence) in [
        ("leave the alternate screen", LEAVE_ALTERNATE_SCREEN),
        ("turn off bracketed paste", DISABLE_BRACKETED_PASTE),
        ("turn off focus reporting", DISABLE_FOCUS_REPORTING),
        ("show the cursor", SHOW_CURSOR),
    ] {
        assert!(
            contains(farewell, sequence),
            "the session did not {what} before dying; wrote {:?}",
            String::from_utf8_lossy(farewell)
        );
    }
    Ok(())
}

#[test]
fn sigterm_restores_terminal() -> Result<()> {
    terminated_session_restores_terminal(libc::SIGTERM)
}

#[test]
fn sighup_restores_terminal() -> Result<()> {
    terminated_session_restores_terminal(libc::SIGHUP)
}

#[test]
fn sigint_restores_terminal() -> Result<()> {
    terminated_session_restores_terminal(libc::SIGINT)
}
