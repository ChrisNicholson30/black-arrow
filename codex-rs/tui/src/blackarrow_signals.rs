//! Black Arrow: put the terminal back when the process is told to stop.
//!
//! Upstream restores the terminal on normal exit and on panic. A termination
//! signal gets neither: the process dies at once and the user's shell inherits
//! a terminal in raw mode, on the alternate screen, with mouse, focus, and
//! paste reporting still on. That happens whenever something other than the
//! user ends the session, such as `kill`, a task runner stopping its child, or
//! the system shutting down.
//!
//! This watches for those signals, restores the terminal, and then lets the
//! signal do what it would have done, so the parent still sees the process as
//! killed by that signal.

#[cfg(unix)]
pub(crate) fn restore_terminal_on_termination() {
    use tokio::signal::unix::SignalKind;
    use tokio::signal::unix::signal;

    for kind in [
        SignalKind::terminate(),
        SignalKind::hangup(),
        SignalKind::interrupt(),
    ] {
        // Registration replaces the default action for the rest of the
        // process's life, so the task below must always end it.
        let Ok(mut stream) = signal(kind) else {
            continue;
        };
        tokio::spawn(async move {
            if stream.recv().await.is_some() {
                // The terminal may already be gone, as after a hangup. There
                // is nobody left to tell, and nothing more to restore.
                let _ = crate::tui::restore_after_exit();
                die_from(kind.as_raw_value());
            }
        });
    }
}

#[cfg(not(unix))]
pub(crate) fn restore_terminal_on_termination() {}

/// Ends the process the way `signal` would have if nothing had caught it.
#[cfg(unix)]
fn die_from(signal: libc::c_int) -> ! {
    // SAFETY: restoring the default disposition and raising a signal on the
    // current process are both async-signal-safe and take no pointers.
    unsafe {
        libc::signal(signal, libc::SIG_DFL);
        libc::raise(signal);
    }
    // Only reached if the signal is blocked. Use the shell's convention for
    // "killed by signal" so callers can still tell what happened.
    std::process::exit(128 + signal);
}
