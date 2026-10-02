#!/usr/bin/env python3
"""Check how Black Arrow behaves in a terminal.

Drives the TUI through the situations that most often go wrong in a terminal
program and reports each as PASS or FAIL: startup, typing, Unicode, bracketed
paste, resize, a shell subprocess with long output, cancelling with Ctrl+C,
clean exit, and being killed.

Two modes:

  --mode headless   The script is the terminal. Fast, needs no window, suitable
                    for CI. Imitates Zed or Terminal.app with --profile.

  --mode here       Run this inside the terminal you want to verify. The real
                    emulator draws everything and answers every query; the
                    script relays, injects the test input, and watches. It also
                    times how long the emulator takes to answer each startup
                    query. Do not type while it runs (about 20 seconds).

Every run uses a throwaway HOME, state directory, and workspace. Your real
~/.blackarrow is not touched, and no network request leaves the machine.

    terminal_check.py --bin codex-rs/target/release/blackarrow
    terminal_check.py --bin codex-rs/target/release/blackarrow --mode here
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ba_pty import PROFILES, PtySession, TerminalProfile  # noqa: E402
from bench_startup import REPO_ROOT, build_sandbox, child_env, portable, seed_ready_state  # noqa: E402

PLACEHOLDER = "Describe a task"
PRODUCT = "Black Arrow"

# Replies a terminal sends back, as seen on the input stream in --mode here.
REPLY_PATTERNS = {
    "cursor-position": re.compile(rb"\x1b\[\d+;\d+R"),
    "DA1": re.compile(rb"\x1b\[\?[\d;]*c"),
    "kitty-keyboard": re.compile(rb"\x1b\[\?\d+u"),
    "OSC 10 colour": re.compile(rb"\x1b\]10;[^\x07\x1b]*(?:\x07|\x1b\\)"),
    "OSC 11 colour": re.compile(rb"\x1b\]11;[^\x07\x1b]*(?:\x07|\x1b\\)"),
}


class Checker:
    def __init__(self, args) -> None:
        self.args = args
        self.results = []
        self.session = None
        self.reply_times = {}

    # Bookkeeping -----------------------------------------------------------

    def record(self, name: str, passed: bool, detail: str = "") -> bool:
        self.results.append({"check": name, "passed": bool(passed), "detail": detail})
        return bool(passed)

    def screen(self) -> str:
        return self.session.term.text()

    def wait_text(self, text: str, timeout: float = 8.0) -> bool:
        return self.session.wait_for(lambda: text in self.screen(), timeout)

    # Session ---------------------------------------------------------------

    def start(self, label: str) -> PtySession:
        here = self.args.mode == "here"
        workdir = REPO_ROOT / "codex-rs" / "target" / "blackarrow-bench" / f"terminal-{label}"
        sandbox = build_sandbox(workdir, self.args.home_dir)
        profile = PROFILES[self.args.profile]
        if here:
            # Keep the real terminal's identity so the program sees what a user would.
            real = {
                key: os.environ[key]
                for key in ("TERM", "TERM_PROGRAM", "TERM_PROGRAM_VERSION", "COLORTERM", "ZED_TERM", "LC_TERMINAL")
                if key in os.environ
            }
            profile = TerminalProfile(
                name="here", env=real, da1=None, da2=None, kitty_keyboard=False, osc_colors=False, decrqm=False
            )
        env = child_env(sandbox, self.args.home_env, profile, None)
        # No proxy process here: point at a closed port so every request fails fast.
        for name in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"):
            env[name] = "http://127.0.0.1:9"
        env["NO_PROXY"] = "127.0.0.1,localhost,::1"
        seed_ready_state(self.args.bin, env, sandbox)

        session = PtySession(
            argv=[self.args.bin, *self.args.arg],
            env=env,
            cwd=str(sandbox["workspace"]),
            rows=40,
            cols=120,
            profile=profile,
            passthrough=here,
        )
        if here:
            self._watch_replies(session)
        session.spawn()
        self.session = session
        self.sandbox = sandbox
        return session

    def _watch_replies(self, session: PtySession) -> None:
        """Timestamp the real terminal's replies as they are relayed to the program."""
        original = session._write_master
        seen = bytearray()

        def write(data: bytes) -> None:
            seen.extend(data)
            now = time.perf_counter_ns()
            for kind, pattern in REPLY_PATTERNS.items():
                if kind not in self.reply_times and pattern.search(bytes(seen)):
                    self.reply_times[kind] = now
            original(data)

        session._write_master = write

    # Checks ----------------------------------------------------------------

    def check_startup(self) -> None:
        s = self.session
        painted = s.wait_for(lambda: s.term.first_frame_ns is not None, 15)
        s.wait_quiet(0.4, 15)
        first_frame = s.ms_since_start(s.term.first_frame_ns)
        self.record("first frame drawn", painted, f"{first_frame} ms")
        self.record("identifies as Black Arrow", PRODUCT in self.screen(), "session header")
        self.record("prompt box ready", PLACEHOLDER in self.screen())
        # Upstream draws its logo above the prompt in braille patterns.
        logo_cells = sum(1 for character in self.screen() if "\u2800" <= character <= "\u28ff")
        self.record("no upstream logo drawn", logo_cells == 0, f"{logo_cells} braille cells on screen")
        self.record("uses the alternate screen", s.term.on_alt_screen)
        self.record(
            "bracketed paste enabled",
            2004 in s.term.modes,
            "mode 2004",
        )

    def check_queries(self) -> None:
        s = self.session
        rows = []
        for query in s.term.queries:
            if self.args.mode == "here":
                answered_at = self.reply_times.get(query.kind)
                if answered_at is None:
                    rows.append(f"{query.kind}: no reply")
                else:
                    rows.append(f"{query.kind}: {(answered_at - query.at_ns) / 1e6:.1f} ms")
            else:
                rows.append(f"{query.kind}: {'answered' if query.answered else 'no reply'}")
        self.query_report = rows
        unanswered_da1 = any(row.startswith("DA1: no reply") for row in rows)
        self.record(
            "startup probe not stalled",
            not unanswered_da1,
            "device-attributes reply ends the probe; without it startup waits 250 ms",
        )

    def check_typing(self) -> None:
        s = self.session
        s.type_text("hello")
        self.record("typed text appears", self.wait_text("hello", 3))
        self.clear_prompt()

    def check_unicode(self) -> None:
        s = self.session
        text = "héllo 日本語 ✓"
        s.type_text(text, delay=0.04)
        ok = s.wait_for(lambda: all(part in self.screen() for part in ("héllo", "日本語", "✓")), 4)
        self.record("accented, wide, and symbol characters render", ok, text)
        self.clear_prompt()

    def check_paste(self) -> None:
        s = self.session
        frames_before = s.term.frames
        s.send(b"\x1b[200~first pasted line\nsecond pasted line\x1b[201~")
        ok = s.wait_for(
            lambda: "first pasted line" in self.screen() and "second pasted line" in self.screen(), 4
        )
        s.pump(0.3)
        self.record("multi-line paste stays in the prompt box", ok and s.exit is None, "not submitted")
        self.record("paste triggers a redraw", s.term.frames > frames_before)
        self.clear_prompt()

    def check_resize(self) -> None:
        s = self.session
        if self.args.mode == "here":
            # The real window keeps its size; only the program is told it shrank.
            rows, cols = s.rows, s.cols
            small = (max(12, rows - 10), max(40, cols - 30))
        else:
            rows, cols = 40, 120
            small = (24, 80)
        frames_before = s.term.frames
        s.resize(*small)
        s.wait_quiet(0.3, 4)
        shrunk = s.term.frames > frames_before and PLACEHOLDER in self.screen()
        self.record("redraws after shrinking", shrunk, f"{small[1]}x{small[0]}")
        frames_before = s.term.frames
        s.resize(rows, cols)
        s.wait_quiet(0.3, 4)
        grown = s.term.frames > frames_before and PLACEHOLDER in self.screen() and PRODUCT in self.screen()
        self.record("redraws after growing back", grown, f"{cols}x{rows}")
        self.record("still running after resize", s.exit is None)

    def check_shell(self) -> None:
        s = self.session
        # A `!` line runs a shell command directly; it needs the session to exist.
        s.pump(1.0)
        s.type_text("!printf 'ba-shell-%s\\n' ok && seq 1 400 | tail -n 3")
        s.send(b"\r")
        ok = self.wait_text("ba-shell-ok", 20)
        tail = s.wait_for(lambda: "400" in self.screen(), 10) if ok else False
        self.record("shell subprocess runs and its output is shown", ok and tail, "!printf … && seq 1 400 | tail")
        s.wait_quiet(0.5, 5)

    def clear_prompt(self) -> None:
        """Ctrl+C on a non-empty prompt clears it without quitting."""
        s = self.session
        s.send(b"\x03")
        s.wait_for(lambda: PLACEHOLDER in self.screen(), 3)
        s.pump(0.15)

    def check_cancel_keeps_running(self) -> None:
        s = self.session
        s.type_text("discard me")
        self.wait_text("discard me", 3)
        s.send(b"\x03")
        cleared = s.wait_for(lambda: "discard me" not in self.screen() and PLACEHOLDER in self.screen(), 3)
        self.record("Ctrl+C clears a draft without quitting", cleared and s.exit is None)

    def check_exit(self, what: str) -> None:
        s = self.session
        quit_at = time.perf_counter_ns()
        s.send(b"\x03")
        exited = s.wait_exit(12)
        took = (s.exit.exit_ns - quit_at) / 1e6 if exited else None
        self.record(f"{what}: exits on Ctrl+C", exited, f"{took:.0f} ms" if took is not None else "did not exit")
        s.close()
        self.record(f"{what}: exit status 0", exited and s.exit.status == 0, str(s.exit))
        self.finish_hygiene(what)

    def finish_hygiene(self, what: str) -> None:
        s = self.session
        leaks = s.term.leaked_state()
        self.record(f"{what}: terminal modes restored", not leaks, ", ".join(leaks))
        self.record(f"{what}: left the alternate screen", not s.term.on_alt_screen)
        restored = s.termios_restored()
        self.record(
            f"{what}: line discipline restored",
            restored is True,
            "; ".join(s.termios_diff()) if restored is False else "",
        )

    def check_killed(self) -> None:
        s = self.start("killed")
        s.wait_for(lambda: s.term.first_frame_ns is not None, 15)
        s.wait_quiet(0.4, 15)
        s.signal(signal.SIGTERM)
        exited = s.wait_exit(10)
        self.record("SIGTERM: process ends", exited)
        s.close()
        self.finish_hygiene("SIGTERM")

    def check_state_isolation(self) -> None:
        home_entries = sorted(path.name for path in self.sandbox["home"].iterdir())
        self.record(
            "state written only to the Black Arrow directory",
            self.args.home_dir in home_entries and ".codex" not in home_entries,
            ", ".join(home_entries),
        )

    # Driver ----------------------------------------------------------------

    def run(self) -> int:
        self.start("main")
        try:
            self.check_startup()
            self.check_queries()
            self.check_typing()
            self.check_unicode()
            self.check_paste()
            self.check_resize()
            self.check_cancel_keeps_running()
            self.check_shell()
            self.check_exit("normal exit")
            self.check_state_isolation()
            self.check_killed()
        finally:
            if self.session and self.session.exit is None:
                self.session.close()
        return self.report()

    def report(self) -> int:
        failed = [result for result in self.results if not result["passed"]]
        terminal = (
            os.environ.get("TERM_PROGRAM", "unknown") if self.args.mode == "here" else f"simulated {self.args.profile}"
        )
        lines = [f"Black Arrow terminal check: {terminal}", ""]
        for result in self.results:
            mark = "PASS" if result["passed"] else "FAIL"
            detail = f"  ({result['detail']})" if result["detail"] else ""
            lines.append(f"  {mark}  {result['check']}{detail}")
        lines += ["", "Startup queries:"] + [f"  {row}" for row in getattr(self, "query_report", [])]
        lines += ["", f"{len(self.results) - len(failed)} passed, {len(failed)} failed"]
        text = "\n".join(lines)
        print(text)
        if self.args.report:
            Path(self.args.report).parent.mkdir(parents=True, exist_ok=True)
            Path(self.args.report).write_text(
                portable(json.dumps(
                    {
                        "terminal": terminal,
                        "mode": self.args.mode,
                        "env": {
                            key: os.environ.get(key)
                            for key in ("TERM", "TERM_PROGRAM", "TERM_PROGRAM_VERSION", "COLORTERM", "ZED_TERM")
                        },
                        "results": self.results,
                        "queries": getattr(self, "query_report", []),
                        "passed": len(self.results) - len(failed),
                        "failed": len(failed),
                    },
                    indent=2,
                ))
                + "\n"
            )
        return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bin", required=True, help="blackarrow binary to check")
    parser.add_argument("--mode", choices=("headless", "here"), default="headless")
    parser.add_argument("--profile", choices=("zed", "apple"), default="zed", help="terminal to imitate in headless mode")
    parser.add_argument("--home-env", default="BLACKARROW_HOME")
    parser.add_argument("--home-dir", default=".blackarrow")
    parser.add_argument("--arg", action="append", default=[], help="extra argument for the program (repeatable)")
    parser.add_argument("--report", help="also write the results to this JSON file")
    args = parser.parse_args()
    args.bin = str(Path(args.bin).resolve())
    if not os.access(args.bin, os.X_OK):
        raise SystemExit(f"not an executable: {args.bin}")
    if args.mode == "here" and not sys.stdin.isatty():
        raise SystemExit("--mode here must be run inside the terminal you want to check")
    return Checker(args).run()


if __name__ == "__main__":
    sys.exit(main())
