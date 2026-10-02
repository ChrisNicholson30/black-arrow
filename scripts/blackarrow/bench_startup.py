#!/usr/bin/env python3
"""Startup benchmark for Black Arrow.

Measures what a user feels when launching the program in a terminal:

  * `--version` and `--help` wall time
  * TUI time to first byte, first frame, and a settled screen
  * idle CPU, memory, wakeups, and child processes
  * shutdown time
  * whether the terminal is left clean
  * which hosts the program tried to reach, and when

It works on any binary that takes a state-directory environment variable, so
the same script produced the unmodified-Codex baseline in docs/baseline.md:

    bench_startup.py --bin target/release/codex --home-env CODEX_HOME --home-dir .codex

Every run uses a throwaway HOME, state directory, and git workspace under
--workdir. Nothing is read from or written to your real ~/.blackarrow or
~/.codex.

Network: by default the program is pointed at a local proxy that logs and
refuses every request, so runs are offline and repeatable. Use --online to let
traffic through untouched (nothing is logged in that mode).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ba_pty import PROFILES, PtySession, descendants, sample_process  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
NETLOG = Path(__file__).resolve().parent / "ba_netlog.py"

KEYS = {
    "enter": b"\r",
    "esc": b"\x1b",
    "ctrl-c": b"\x03",
    "ctrl-d": b"\x04",
    "tab": b"\t",
}


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Sandbox
# ---------------------------------------------------------------------------


def build_sandbox(workdir: Path, home_dir_name: str) -> dict:
    """Create a throwaway HOME, state directory, and git workspace."""
    if workdir.exists():
        shutil.rmtree(workdir)
    home = workdir / "home"
    state = home / home_dir_name
    workspace = workdir / "workspace"
    for path in (home, state, workspace / "src"):
        path.mkdir(parents=True)
    (workspace / "README.md").write_text("# bench workspace\n")
    (workspace / "src" / "main.rs").write_text('fn main() {\n    println!("hello");\n}\n')
    git = ["git", "-c", "user.name=bench", "-c", "user.email=bench@example.invalid"]
    quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "check": True, "cwd": workspace}
    subprocess.run(git + ["init", "-q", "-b", "main"], **quiet)
    subprocess.run(git + ["add", "-A"], **quiet)
    subprocess.run(git + ["commit", "-q", "-m", "init"], **quiet)
    return {"home": home, "state": state.resolve(), "workspace": workspace.resolve()}


def child_env(sandbox: dict, home_env: str, profile, proxy_port: int | None) -> dict:
    """A controlled environment: nothing leaks in from the caller's shell."""
    env = {
        "HOME": str(sandbox["home"]),
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "USER": os.environ.get("USER", "bench"),
        "LOGNAME": os.environ.get("LOGNAME", os.environ.get("USER", "bench")),
        "SHELL": "/bin/zsh",
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
        home_env: str(sandbox["state"]),
    }
    env.update(profile.env)
    if proxy_port is not None:
        proxy = f"http://127.0.0.1:{proxy_port}"
        for name in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"):
            env[name] = proxy
        # Loopback stays direct: the TUI talks to its own in-process servers over
        # 127.0.0.1, and refusing those would change what is being measured.
        env["NO_PROXY"] = env["no_proxy"] = "127.0.0.1,localhost,::1"
    return env


def portable(text: str) -> str:
    """`text` with this machine's paths replaced, so results can be committed.

    Results quote the binary's path and the screen, and the screen shows the
    working directory. Neither should carry the name of whoever ran it.
    """
    return text.replace(str(REPO_ROOT), "<repo>").replace(str(Path.home()), "~")


def seed_ready_state(binary: str, env: dict, sandbox: dict) -> None:
    """Log in with a placeholder API key and trust the workspace.

    This is the state a returning user is in: no onboarding, no trust prompt.
    The key is a placeholder; with the default offline proxy it never leaves
    this machine.
    """
    login = subprocess.run(
        [binary, "login", "--with-api-key"],
        input=b"sk-blackarrow-bench-placeholder\n",
        env=env,
        cwd=sandbox["workspace"],
        capture_output=True,
        check=False,
    )
    if login.returncode != 0:
        raise SystemExit(f"could not seed login state:\n{login.stderr.decode(errors='replace')}")
    config = sandbox["state"] / "config.toml"
    with config.open("a") as handle:
        handle.write(f'\n[projects."{sandbox["workspace"]}"]\ntrust_level = "trusted"\n')


# ---------------------------------------------------------------------------
# Measurements
# ---------------------------------------------------------------------------


def time_cli(binary: str, args: list, env: dict, cwd: Path, runs: int) -> dict:
    """Wall time of a one-shot invocation. The first run is reported separately."""
    samples = []
    output = ""
    for _ in range(runs + 1):
        start = time.perf_counter_ns()
        result = subprocess.run([binary, *args], env=env, cwd=cwd, capture_output=True, check=False)
        samples.append((time.perf_counter_ns() - start) / 1e6)
        output = result.stdout.decode(errors="replace")
        if result.returncode != 0:
            raise SystemExit(f"{binary} {' '.join(args)} exited {result.returncode}:\n{result.stderr.decode(errors='replace')}")
    return {"first_ms": round(samples[0], 2), **summarize(samples[1:]), "output_first_line": output.splitlines()[0] if output else ""}


def summarize(samples: list) -> dict:
    samples = [s for s in samples if s is not None]
    if not samples:
        return {"n": 0}
    ordered = sorted(samples)
    p95 = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
    return {
        "n": len(ordered),
        "min_ms": round(ordered[0], 2),
        "median_ms": round(statistics.median(ordered), 2),
        "p95_ms": round(p95, 2),
        "max_ms": round(ordered[-1], 2),
    }


def parse_keys(spec: str) -> list:
    """Parse 'text:/exit,wait:0.2,enter' into steps."""
    steps = []
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        if token.startswith("text:"):
            steps.append(("text", token[5:]))
        elif token.startswith("wait:"):
            steps.append(("wait", float(token[5:])))
        elif token in KEYS:
            steps.append(("key", KEYS[token]))
        else:
            raise SystemExit(f"unknown key token {token!r}; known: {', '.join(KEYS)}, text:…, wait:…")
    return steps


def play(session: PtySession, steps: list) -> None:
    for kind, value in steps:
        if kind == "text":
            session.type_text(value)
        elif kind == "wait":
            session.pump(value)
        else:
            session.send(value)
            session.pump(0.03)


def open_sockets(pid: int) -> list:
    """Internet sockets the process holds open, as reported by lsof."""
    result = subprocess.run(
        ["lsof", "-nP", "-a", "-p", str(pid), "-i"], capture_output=True, text=True, check=False
    )
    return [line.split(None, 8)[-1] for line in result.stdout.splitlines()[1:]]


def run_tui_once(args, env: dict, sandbox: dict, quit_steps: list, index: int, measure_idle: bool, dump_dir: Path | None) -> dict:
    session = PtySession(
        argv=[args.bin, *args.arg],
        env=env,
        cwd=str(sandbox["workspace"]),
        rows=args.rows,
        cols=args.cols,
        profile=PROFILES[args.profile],
        transcript=str(dump_dir / f"run-{index:02d}.raw") if dump_dir else None,
    )
    session.spawn()
    record: dict = {"run": index}
    try:
        painted = session.wait_for(lambda: session.term.first_frame_ns is not None, args.timeout)
        if not painted:
            # Renderers that do not bracket frames still count once they draw.
            painted = session.wait_for(lambda: session.first_paint_ns is not None, 1.0)
        session.wait_quiet(args.quiet, args.timeout)
        record["first_byte_ms"] = session.ms_since_start(session.first_byte_ns)
        record["first_paint_ms"] = session.ms_since_start(session.first_paint_ns)
        record["first_frame_ms"] = session.ms_since_start(session.term.first_frame_ns)
        record["settled_ms"] = session.ms_since_start(session.last_byte_ns)
        record["frames_until_settled"] = session.term.frames
        record["alt_screen"] = session.term.on_alt_screen
        record["exited_early"] = session.exit is not None
        screen = session.term.text()
        record["screen"] = screen
        if dump_dir:
            (dump_dir / f"run-{index:02d}.screen.txt").write_text(screen + "\n")

        if args.ready:
            record["ready_ms"] = None
            if session.wait_for(lambda: session.term.contains(args.ready), args.timeout):
                record["ready_ms"] = session.ms_since_start(time.perf_counter_ns())

        if measure_idle and session.exit is None:
            session.pump(args.settle_seconds)
            before = sample_process(session.pid)
            frames_before = session.term.frames
            bytes_before = session.bytes_out
            session.pump(args.idle_seconds)
            after = sample_process(session.pid)
            if before and after:
                window = (after.at_ns - before.at_ns) / 1e9
                record["idle"] = {
                    "window_s": round(window, 2),
                    "cpu_percent": round((after.cpu_ns - before.cpu_ns) / (after.at_ns - before.at_ns) * 100, 3),
                    "cpu_ms": round((after.cpu_ns - before.cpu_ns) / 1e6, 2),
                    "rss_mb": round(after.rss_bytes / 1048576, 1),
                    "footprint_mb": round(after.footprint_bytes / 1048576, 1),
                    "idle_wakeups_per_s": round((after.idle_wakeups - before.idle_wakeups) / window, 1),
                    "interrupt_wakeups_per_s": round((after.interrupt_wakeups - before.interrupt_wakeups) / window, 1),
                    "frames_drawn": session.term.frames - frames_before,
                    "bytes_written": session.bytes_out - bytes_before,
                    "child_processes": [name for _, name in descendants(session.pid)],
                    "open_sockets": open_sockets(session.pid),
                }

        record["queries"] = [
            {"at_ms": session.ms_since_start(q.at_ns), "kind": q.kind, "answered": q.answered}
            for q in session.term.queries
        ]

        if session.exit is None:
            quit_at = time.perf_counter_ns()
            play(session, quit_steps)
            if session.wait_exit(args.timeout):
                record["shutdown_ms"] = round((session.exit.exit_ns - quit_at) / 1e6, 2)
                record["exit_status"] = session.exit.status
                record["exit_signal"] = session.exit.signal
            else:
                record["shutdown_ms"] = None
                record["quit_failed"] = True
                record["screen_at_quit_failure"] = session.term.text()
    finally:
        leftovers = descendants(session.pid) if session.exit is None else []
        session.close()
        for pid, _ in leftovers:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    record["leaked_terminal_state"] = session.term.leaked_state()
    record["termios_restored"] = session.termios_restored()
    if not record["termios_restored"]:
        record["termios_diff"] = session.termios_diff()
    record["start_wall_ns"] = session.start_wall_ns
    return record


def read_netlog(path: Path, runs: list) -> list:
    """Attribute each logged request to the run it happened in."""
    if not path.exists():
        return []
    starts = sorted((run["start_wall_ns"], run["run"]) for run in runs)
    events = []
    for line in path.read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        owner = None
        for start, index in starts:
            if event["t_ns"] >= start:
                owner = (start, index)
        if owner is None:
            continue
        events.append(
            {
                "run": owner[1],
                "at_ms": round((event["t_ns"] - owner[0]) / 1e6, 1),
                "method": event["method"],
                "target": event["target"],
            }
        )
    return events


def stray_daemons(state_dir: Path) -> list:
    """Processes still running that mention this run's state directory."""
    listing = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, check=False).stdout
    found = []
    for line in listing.splitlines():
        pid, _, command = line.strip().partition(" ")
        if str(state_dir) in command and pid.isdigit() and int(pid) != os.getpid():
            found.append((int(pid), command.strip()))
    return found


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bin", required=True, help="binary to measure")
    parser.add_argument("--label", help="name for this measurement (default: binary file name)")
    parser.add_argument("--home-env", default="BLACKARROW_HOME", help="state directory environment variable")
    parser.add_argument("--home-dir", default=".blackarrow", help="state directory name under the sandbox HOME")
    parser.add_argument("--state", choices=("ready", "fresh"), default="ready",
                        help="ready: logged in and workspace trusted; fresh: first ever launch")
    parser.add_argument("--runs", type=int, default=10, help="TUI launches to time")
    parser.add_argument("--cli-runs", type=int, default=20, help="--version/--help launches to time")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="zed", help="terminal to imitate")
    parser.add_argument("--rows", type=int, default=40)
    parser.add_argument("--cols", type=int, default=120)
    parser.add_argument("--arg", action="append", default=[], help="extra argument for TUI launches (repeatable)")
    parser.add_argument("--ready", help="also time until this text is on screen")
    parser.add_argument("--expect", action="append", default=[], help="fail unless the settled screen contains this text")
    parser.add_argument("--quit", default="ctrl-c", help="keys that exit the TUI")
    parser.add_argument("--quiet", type=float, default=0.3, help="seconds without output that count as settled")
    parser.add_argument("--settle-seconds", type=float, default=4.0, help="pause before the idle window")
    parser.add_argument("--idle-seconds", type=float, default=10.0, help="length of the idle window")
    parser.add_argument("--timeout", type=float, default=20.0, help="seconds to wait for any single step")
    parser.add_argument("--online", action="store_true", help="do not route traffic through the refusing proxy")
    parser.add_argument("--skip-cli", action="store_true")
    parser.add_argument("--skip-tui", action="store_true")
    parser.add_argument("--workdir", help="sandbox location (default: codex-rs/target/blackarrow-bench/<label>)")
    parser.add_argument("--json", help="write full results to this file")
    parser.add_argument("--dump", action="store_true", help="keep raw output and screen text per run")
    parser.add_argument("--budget", action="append", default=[], metavar="METRIC=MS",
                        help="fail if a median exceeds this many ms, e.g. first_frame_ms=150")
    args = parser.parse_args()

    args.bin = str(Path(args.bin).resolve())
    if not os.access(args.bin, os.X_OK):
        raise SystemExit(f"not an executable: {args.bin}")
    label = args.label or Path(args.bin).name
    workdir = Path(args.workdir) if args.workdir else REPO_ROOT / "codex-rs" / "target" / "blackarrow-bench" / label
    sandbox = build_sandbox(workdir, args.home_dir)
    dump_dir = workdir / "dump" if args.dump else None
    if dump_dir:
        dump_dir.mkdir()

    proxy = None
    proxy_port = None
    netlog_path = workdir / "net.jsonl"
    if not args.online:
        port_file = workdir / "proxy.port"
        proxy = subprocess.Popen([sys.executable, str(NETLOG), "--log", str(netlog_path), "--port-file", str(port_file)])
        deadline = time.monotonic() + 5
        while not port_file.exists() or not port_file.read_text().strip():
            if time.monotonic() > deadline:
                proxy.kill()
                raise SystemExit("logging proxy did not start")
            time.sleep(0.01)
        proxy_port = int(port_file.read_text())

    results: dict = {
        "label": label,
        "binary": args.bin,
        "binary_bytes": os.path.getsize(args.bin),
        "state": args.state,
        "profile": args.profile,
        "size": f"{args.cols}x{args.rows}",
        "network": "online" if args.online else "refused by logging proxy",
        "home_env": args.home_env,
    }
    failures = []
    try:
        env = child_env(sandbox, args.home_env, PROFILES[args.profile], proxy_port)
        if not args.skip_cli:
            log(f"[{label}] timing --version and --help ({args.cli_runs} runs each)")
            results["version"] = time_cli(args.bin, ["--version"], env, sandbox["workspace"], args.cli_runs)
            results["help"] = time_cli(args.bin, ["--help"], env, sandbox["workspace"], args.cli_runs)

        if not args.skip_tui:
            if args.state == "ready":
                seed_ready_state(args.bin, env, sandbox)
            quit_steps = parse_keys(args.quit)
            runs = []
            for index in range(args.runs):
                log(f"[{label}] TUI launch {index + 1}/{args.runs}")
                runs.append(run_tui_once(args, env, sandbox, quit_steps, index, measure_idle=index == 0, dump_dir=dump_dir))
                if args.state == "fresh":
                    # Keep every launch a first launch.
                    shutil.rmtree(sandbox["state"])
                    sandbox["state"].mkdir()
            results["tui"] = {
                metric: summarize([run.get(metric) for run in runs])
                for metric in ("first_byte_ms", "first_paint_ms", "first_frame_ms", "settled_ms", "ready_ms", "shutdown_ms")
            }
            # The first launch pays one-time setup; report it apart from the rest.
            results["tui_first_launch"] = {
                metric: runs[0].get(metric)
                for metric in ("first_byte_ms", "first_frame_ms", "settled_ms", "shutdown_ms")
            }
            results["idle"] = runs[0].get("idle")
            results["queries"] = runs[-1].get("queries", [])
            results["screen"] = runs[-1].get("screen", "")
            results["network_requests"] = read_netlog(netlog_path, runs)
            results["runs"] = [{k: v for k, v in run.items() if k != "screen"} for run in runs]

            for run in runs:
                if run.get("quit_failed"):
                    failures.append(f"run {run['run']}: did not exit after the quit keys")
                if run["leaked_terminal_state"]:
                    failures.append(f"run {run['run']}: terminal state leaked: {', '.join(run['leaked_terminal_state'])}")
                if run["termios_restored"] is False:
                    failures.append(f"run {run['run']}: line discipline not restored: {'; '.join(run['termios_diff'])}")
                if run.get("exited_early"):
                    failures.append(f"run {run['run']}: exited before it settled")
            for text in args.expect:
                if text not in results["screen"]:
                    failures.append(f"settled screen does not contain {text!r}")

        strays = stray_daemons(sandbox["state"])
        results["stray_processes"] = [command for _, command in strays]
        for pid, _ in strays:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

        results["state_dir_entries"] = sorted(p.name for p in sandbox["state"].iterdir())
        results["home_entries"] = sorted(p.name for p in sandbox["home"].iterdir())
    finally:
        if proxy:
            proxy.terminate()
            proxy.wait()

    for budget in args.budget:
        metric, _, limit = budget.partition("=")
        section = results.get("tui", {}).get(metric) or results.get(metric.removesuffix("_ms"), {})
        median = section.get("median_ms") if isinstance(section, dict) else None
        if median is None:
            failures.append(f"budget {budget}: no measurement for {metric}")
        elif median > float(limit):
            failures.append(f"budget exceeded: {metric} median {median} ms > {limit} ms")

    results["failures"] = failures
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(portable(json.dumps(results, indent=2)) + "\n")
    print_report(results)
    return 1 if failures else 0


def print_report(results: dict) -> None:
    def row(name: str, stats: dict) -> str:
        if not stats or not stats.get("n"):
            return f"  {name:<22} (no data)"
        first = f"  first {stats['first_ms']:>8.2f}" if "first_ms" in stats else ""
        return (
            f"  {name:<22} median {stats['median_ms']:>8.2f}   min {stats['min_ms']:>8.2f}"
            f"   p95 {stats['p95_ms']:>8.2f}   max {stats['max_ms']:>8.2f}   n={stats['n']}{first}"
        )

    print(f"\n{results['label']}  ({results['binary_bytes'] / 1048576:.1f} MB)")
    print(f"  state={results['state']}  terminal={results['profile']} {results['size']}  network={results['network']}")
    print("\nOne-shot commands (ms)")
    for key, name in (("version", "--version"), ("help", "--help")):
        if key in results:
            print(row(name, results[key]))
    if "tui" in results:
        print("\nTUI launch (ms from spawn)")
        for key, name in (
            ("first_byte_ms", "first byte"),
            ("first_paint_ms", "first paint"),
            ("first_frame_ms", "first frame"),
            ("settled_ms", "settled"),
            ("ready_ms", "ready text"),
            ("shutdown_ms", "shutdown"),
        ):
            stats = results["tui"].get(key)
            if stats and stats.get("n"):
                print(row(name, stats))
        idle = results.get("idle")
        if idle:
            print(f"\nIdle ({idle['window_s']} s window)")
            print(f"  cpu                    {idle['cpu_percent']} %  ({idle['cpu_ms']} ms)")
            print(f"  memory                 {idle['footprint_mb']} MB footprint, {idle['rss_mb']} MB resident")
            print(f"  wakeups                {idle['idle_wakeups_per_s']}/s idle, {idle['interrupt_wakeups_per_s']}/s interrupt")
            print(f"  redraws                {idle['frames_drawn']} frames, {idle['bytes_written']} bytes")
            print(f"  child processes        {', '.join(idle['child_processes']) or 'none'}")
            print(f"  open sockets           {', '.join(idle['open_sockets']) or 'none'}")
        requests = results.get("network_requests", [])
        print(f"\nNetwork attempts: {len(requests)}")
        seen = set()
        for request in requests:
            key = (request["method"], request["target"])
            if key in seen:
                continue
            seen.add(key)
            print(f"  +{request['at_ms']:>8.1f} ms  {request['method']} {request['target']}")
        if results.get("stray_processes"):
            print("\nProcesses left running after exit:")
            for command in results["stray_processes"]:
                print(f"  {command[:150]}")
    if results["failures"]:
        print("\nFAILURES")
        for failure in results["failures"]:
            print(f"  - {failure}")
    else:
        print("\nAll checks passed.")


if __name__ == "__main__":
    sys.exit(main())
