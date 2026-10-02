//! Startup timeline.
//!
//! Startup speed is a product feature, so it has to be measurable from inside
//! the process as well as from outside. Setting `BLACKARROW_STARTUP_TRACE` to
//! a file path makes the process record when it reaches each named point and
//! write the timeline to that file as JSON.
//!
//! The output goes to a file because the TUI owns the terminal while it runs,
//! and on macOS it points stderr at `/dev/null` for that whole time.
//!
//! With the variable unset, [`mark`] is a single atomic load and a branch.
//!
//! ```text
//! BLACKARROW_STARTUP_TRACE=/tmp/trace.json blackarrow
//! ```

use std::path::PathBuf;
use std::sync::Mutex;
use std::sync::OnceLock;
use std::time::Duration;
use std::time::Instant;

/// Environment variable holding the file the timeline is written to.
pub const TRACE_ENV_VAR: &str = "BLACKARROW_STARTUP_TRACE";

/// The named points in the timeline, in the order a normal launch reaches them.
pub mod point {
    /// `main` has been entered.
    pub const MAIN: &str = "main";
    /// Helper aliases are on `PATH` and `.env` has been loaded.
    pub const ARG0_READY: &str = "arg0_ready";
    /// The async runtime is running.
    pub const RUNTIME_READY: &str = "runtime_ready";
    /// Command-line arguments have been parsed.
    pub const CLI_PARSED: &str = "cli_parsed";
    /// The configuration needed to draw the first frame has been loaded.
    pub const BOOTSTRAP_CONFIG_LOADED: &str = "bootstrap_config_loaded";
    /// Raw mode is on and the terminal has answered the capability probe.
    pub const TERMINAL_READY: &str = "terminal_ready";
    /// The first frame has been drawn. The user can see and type.
    pub const FIRST_FRAME: &str = "first_frame";
    /// The full configuration, including every layer, has been resolved.
    pub const CONFIG_LOADED: &str = "config_loaded";
    /// Local state databases are open.
    pub const STATE_READY: &str = "state_ready";
    /// The in-process app server is accepting requests.
    pub const APP_SERVER_READY: &str = "app_server_ready";
    /// Stored credentials have been read and login status is known.
    pub const AUTH_LOADED: &str = "auth_loaded";
    /// The model catalogue is available to the UI.
    pub const MODELS_LOADED: &str = "models_loaded";
    /// The chat interface has replaced the provisional first frame.
    pub const CHAT_FRAME: &str = "chat_frame";
    /// The session exists and can accept a prompt.
    pub const SESSION_READY: &str = "session_ready";
    /// Every configured MCP server has finished starting, or failed.
    pub const MCP_READY: &str = "mcp_ready";
}

/// The point after which a written timeline is worth having on disk even if
/// the process is later killed.
const FLUSH_ON: &str = point::FIRST_FRAME;

static TRACE: OnceLock<Option<Trace>> = OnceLock::new();

/// Starts the timeline. Call this first thing in `main`.
///
/// Does nothing unless [`TRACE_ENV_VAR`] names a file. Safe to call more than
/// once; only the first call has any effect.
pub fn init() {
    let mut started_now = false;
    let trace = TRACE.get_or_init(|| {
        let path = std::env::var_os(TRACE_ENV_VAR).filter(|value| !value.is_empty())?;
        started_now = true;
        Some(Trace::new(PathBuf::from(path), time_since_exec()))
    });
    if let Some(trace) = trace
        && started_now
    {
        trace.mark(point::MAIN);
        register_exit_flush();
    }
}

/// Records that the process has reached `name`.
///
/// Only the first time a name is reached is kept, so this can sit on a path
/// that runs repeatedly.
#[inline]
pub fn mark(name: &'static str) {
    if let Some(Some(trace)) = TRACE.get() {
        trace.mark(name);
        if name == FLUSH_ON {
            trace.flush();
        }
    }
}

/// Writes the timeline recorded so far.
///
/// Called automatically after the first frame and at normal process exit.
pub fn flush() {
    if let Some(Some(trace)) = TRACE.get() {
        trace.flush();
    }
}

/// Returns true when a timeline is being recorded.
pub fn is_enabled() -> bool {
    matches!(TRACE.get(), Some(Some(_)))
}

struct Trace {
    path: PathBuf,
    origin: Instant,
    /// Time between the kernel creating the process and [`init`] running:
    /// loading the executable, dynamic linking, and static initialisers.
    before_main: Option<Duration>,
    marks: Mutex<Vec<(&'static str, Duration)>>,
}

impl Trace {
    fn new(path: PathBuf, before_main: Option<Duration>) -> Self {
        Self {
            path,
            origin: Instant::now(),
            before_main,
            marks: Mutex::new(Vec::with_capacity(16)),
        }
    }

    fn mark(&self, name: &'static str) {
        let elapsed = self.origin.elapsed();
        let Ok(mut marks) = self.marks.lock() else {
            return;
        };
        if !marks.iter().any(|(existing, _)| *existing == name) {
            marks.push((name, elapsed));
        }
    }

    fn render(&self) -> String {
        let marks = match self.marks.lock() {
            Ok(marks) => marks.clone(),
            Err(_) => Vec::new(),
        };
        let before_main_ms = self.before_main.map(as_ms);

        let mut out = String::from("{\n");
        out.push_str(&format!("  \"pid\": {},\n", std::process::id()));
        match before_main_ms {
            Some(ms) => out.push_str(&format!("  \"exec_to_main_ms\": {ms:.3},\n")),
            None => out.push_str("  \"exec_to_main_ms\": null,\n"),
        }
        out.push_str("  \"marks\": [");
        for (index, (name, elapsed)) in marks.iter().enumerate() {
            let since_main = as_ms(*elapsed);
            out.push_str(if index == 0 { "\n" } else { ",\n" });
            out.push_str(&format!(
                "    {{\"name\": \"{name}\", \"since_main_ms\": {since_main:.3}"
            ));
            if let Some(before_main_ms) = before_main_ms {
                let since_exec = before_main_ms + since_main;
                out.push_str(&format!(", \"since_exec_ms\": {since_exec:.3}"));
            }
            out.push('}');
        }
        out.push_str(if marks.is_empty() { "]\n" } else { "\n  ]\n" });
        out.push_str("}\n");
        out
    }

    fn flush(&self) {
        // A diagnostic must never take the program down or print over the TUI,
        // so a failed write is dropped.
        let _ = std::fs::write(&self.path, self.render());
    }
}

fn as_ms(duration: Duration) -> f64 {
    duration.as_secs_f64() * 1000.0
}

#[cfg(unix)]
fn register_exit_flush() {
    extern "C" fn flush_at_exit() {
        flush();
    }
    // `--help`, `--version`, and error paths leave through `exit` without
    // returning from `main`, so the final write hangs off the C runtime.
    //
    // SAFETY: `flush_at_exit` is a plain function with C linkage that takes no
    // arguments and does not unwind.
    unsafe {
        libc::atexit(flush_at_exit);
    }
}

#[cfg(not(unix))]
fn register_exit_flush() {}

/// How long ago the kernel created this process.
#[cfg(target_os = "macos")]
fn time_since_exec() -> Option<Duration> {
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    let size = libc::c_int::try_from(std::mem::size_of::<libc::proc_bsdinfo>()).ok()?;
    // SAFETY: `proc_bsdinfo` is plain data for which all-zero bytes are valid.
    let mut info: libc::proc_bsdinfo = unsafe { std::mem::zeroed() };
    // SAFETY: `info` is a writable buffer of exactly `size` bytes, and
    // `proc_pidinfo` writes at most `size` bytes into it.
    let written = unsafe {
        libc::proc_pidinfo(
            libc::getpid(),
            libc::PROC_PIDTBSDINFO,
            0,
            (&raw mut info).cast::<libc::c_void>(),
            size,
        )
    };
    if written != size {
        return None;
    }
    let micros = u32::try_from(info.pbi_start_tvusec).ok()?;
    let started = Duration::new(info.pbi_start_tvsec, micros.checked_mul(1000)?);
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .ok()?
        .checked_sub(started)
}

#[cfg(not(target_os = "macos"))]
fn time_since_exec() -> Option<Duration> {
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use pretty_assertions::assert_eq;

    fn trace_in(dir: &tempfile::TempDir, before_main: Option<Duration>) -> Trace {
        Trace::new(dir.path().join("trace.json"), before_main)
    }

    fn names(trace: &Trace) -> Vec<&'static str> {
        trace
            .marks
            .lock()
            .expect("marks lock")
            .iter()
            .map(|(name, _)| *name)
            .collect()
    }

    #[test]
    fn marks_keep_first_occurrence_in_order() {
        let dir = tempfile::tempdir().expect("tempdir");
        let trace = trace_in(&dir, None);
        trace.mark(point::MAIN);
        trace.mark(point::FIRST_FRAME);
        trace.mark(point::MAIN);
        trace.mark(point::CHAT_FRAME);
        trace.mark(point::FIRST_FRAME);

        assert_eq!(
            names(&trace),
            vec![point::MAIN, point::FIRST_FRAME, point::CHAT_FRAME]
        );
    }

    #[test]
    fn marks_are_monotonic() {
        let dir = tempfile::tempdir().expect("tempdir");
        let trace = trace_in(&dir, None);
        trace.mark(point::MAIN);
        std::thread::sleep(Duration::from_millis(2));
        trace.mark(point::FIRST_FRAME);

        let marks = trace.marks.lock().expect("marks lock").clone();
        assert!(marks[1].1 > marks[0].1);
        assert!(marks[1].1 - marks[0].1 >= Duration::from_millis(2));
    }

    #[test]
    fn render_reports_time_since_exec_when_known() {
        let dir = tempfile::tempdir().expect("tempdir");
        let trace = trace_in(&dir, Some(Duration::from_millis(10)));
        trace
            .marks
            .lock()
            .expect("marks lock")
            .push((point::FIRST_FRAME, Duration::from_micros(2500)));

        let rendered = trace.render();
        assert!(
            rendered.contains("\"exec_to_main_ms\": 10.000"),
            "{rendered}"
        );
        assert!(
            rendered.contains(
                "{\"name\": \"first_frame\", \"since_main_ms\": 2.500, \"since_exec_ms\": 12.500}"
            ),
            "{rendered}"
        );
    }

    #[test]
    fn render_omits_time_since_exec_when_unknown() {
        let dir = tempfile::tempdir().expect("tempdir");
        let trace = trace_in(&dir, None);
        trace
            .marks
            .lock()
            .expect("marks lock")
            .push((point::MAIN, Duration::ZERO));

        let rendered = trace.render();
        assert!(rendered.contains("\"exec_to_main_ms\": null"), "{rendered}");
        assert!(
            rendered.contains("{\"name\": \"main\", \"since_main_ms\": 0.000}"),
            "{rendered}"
        );
    }

    #[test]
    fn render_is_valid_with_no_marks() {
        let dir = tempfile::tempdir().expect("tempdir");
        let rendered = trace_in(&dir, None).render();
        assert!(rendered.contains("\"marks\": []"), "{rendered}");
    }

    #[test]
    fn flush_writes_the_rendered_timeline() {
        let dir = tempfile::tempdir().expect("tempdir");
        let trace = trace_in(&dir, None);
        trace.mark(point::MAIN);
        trace.flush();

        let written = std::fs::read_to_string(dir.path().join("trace.json")).expect("trace file");
        assert_eq!(written, trace.render());
    }

    #[test]
    fn flush_to_an_unwritable_path_is_silent() {
        let dir = tempfile::tempdir().expect("tempdir");
        let trace = Trace::new(dir.path().join("missing").join("trace.json"), None);
        trace.mark(point::MAIN);
        trace.flush();
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn process_start_time_is_readable_and_recent() {
        let elapsed = time_since_exec().expect("kernel reports process start");
        assert!(
            elapsed < Duration::from_secs(600),
            "test process should be minutes old at most, got {elapsed:?}"
        );
    }
}
