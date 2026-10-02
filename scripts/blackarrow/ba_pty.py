"""PTY harness shared by the Black Arrow startup benchmark and terminal checks.

The harness runs a terminal program on a pseudo-terminal and plays the part of
the terminal emulator: it keeps a small screen model, tracks the modes the
program switches on, and (in headless mode) answers the queries a real
terminal would answer. That makes "time to first frame" and "did it leave the
terminal clean" measurable without a human in front of a window.

Two modes:

  headless     The harness is the terminal. Query replies come from a profile
               that mimics Zed's integrated terminal or Terminal.app.
  passthrough  The harness relays between the real terminal it was started in
               and the program. The real emulator renders and answers queries;
               the harness only observes, injects scripted input, and reports.

Standard library only, so it runs on a stock macOS Python 3.
"""

from __future__ import annotations

import codecs
import ctypes
import ctypes.util
import errno
import fcntl
import os
import re
import select
import signal
import struct
import sys
import termios
import time
import tty
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, Optional

ESC = "\x1b"

# Private modes a well-behaved TUI must switch back off before it exits.
MODE_NAMES = {
    1: "application cursor keys (DECCKM)",
    47: "alternate screen (47)",
    1000: "mouse click reporting",
    1002: "mouse drag reporting",
    1003: "mouse motion reporting",
    1004: "focus reporting",
    1005: "mouse UTF-8 encoding",
    1006: "mouse SGR encoding",
    1015: "mouse urxvt encoding",
    1016: "mouse SGR-pixel encoding",
    1047: "alternate screen (1047)",
    1049: "alternate screen (1049)",
    2004: "bracketed paste",
    2026: "synchronized output",
}
ALT_SCREEN_MODES = (47, 1047, 1049)


# ---------------------------------------------------------------------------
# Terminal profiles
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TerminalProfile:
    """How a particular emulator identifies itself and which queries it answers."""

    name: str
    env: dict
    da1: Optional[str]
    da2: Optional[str]
    kitty_keyboard: bool
    osc_colors: bool
    decrqm: bool
    foreground: str = "d0d0/d0d0/d0d0"
    background: str = "1e1e/1e1e/1e1e"


PROFILES = {
    # Zed's terminal is built on alacritty_terminal.
    "zed": TerminalProfile(
        name="zed",
        env={
            "TERM": "xterm-256color",
            "COLORTERM": "truecolor",
            "TERM_PROGRAM": "zed",
            "ZED_TERM": "true",
        },
        da1="\x1b[?6c",
        da2="\x1b[>0;1901;1c",
        kitty_keyboard=True,
        osc_colors=True,
        decrqm=True,
    ),
    # Terminal.app: 256 colours, no kitty keyboard protocol, no DECRQM.
    "apple": TerminalProfile(
        name="apple",
        env={
            "TERM": "xterm-256color",
            "TERM_PROGRAM": "Apple_Terminal",
            "TERM_PROGRAM_VERSION": "455",
        },
        da1="\x1b[?1;2c",
        da2="\x1b[>1;95;0c",
        kitty_keyboard=False,
        osc_colors=True,
        decrqm=False,
    ),
    # A terminal that answers nothing. Exposes every wait-for-reply timeout.
    "mute": TerminalProfile(
        name="mute",
        env={"TERM": "xterm-256color"},
        da1=None,
        da2=None,
        kitty_keyboard=False,
        osc_colors=False,
        decrqm=False,
    ),
}


# ---------------------------------------------------------------------------
# Escape-sequence parser
# ---------------------------------------------------------------------------


class VtParser:
    """Incremental parser for the subset of ECMA-48 a TUI emits.

    Subclasses override the ``on_*`` hooks. Input may be split anywhere, even
    in the middle of a sequence or a UTF-8 code point.
    """

    def __init__(self) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._state = "ground"
        self._buf = ""
        self._string_kind = ""

    def feed(self, data: bytes) -> None:
        for ch in self._decoder.decode(data):
            self._step(ch)

    def _step(self, ch: str) -> None:
        state = self._state
        if state == "ground":
            if ch == ESC:
                self._state = "esc"
                self._buf = ""
            elif ch < " " or ch == "\x7f":
                self.on_control(ch)
            else:
                self.on_print(ch)
        elif state == "esc":
            if ch == "[":
                self._state = "csi"
                self._buf = ""
            elif ch == "]":
                self._state = "string"
                self._string_kind = "osc"
                self._buf = ""
            elif ch in "P_^X":
                self._state = "string"
                self._string_kind = {"P": "dcs", "_": "apc", "^": "pm", "X": "sos"}[ch]
                self._buf = ""
            elif " " <= ch <= "/":
                self._buf += ch
            elif ch == ESC:
                self._buf = ""
            else:
                self._state = "ground"
                self.on_esc(self._buf, ch)
        elif state == "csi":
            if "@" <= ch <= "~":
                self._state = "ground"
                self._dispatch_csi(self._buf, ch)
            elif ch == ESC:
                self._state = "esc"
                self._buf = ""
            elif ch < " ":
                self.on_control(ch)
            else:
                self._buf += ch
        elif state == "string":
            if ch == "\x07":
                self._state = "ground"
                self.on_string(self._string_kind, self._buf, "\x07")
            elif ch == ESC:
                self._state = "string_esc"
            else:
                self._buf += ch
        elif state == "string_esc":
            if ch == "\\":
                self._state = "ground"
                self.on_string(self._string_kind, self._buf, ESC + "\\")
            else:
                # Not a terminator after all: the string was aborted by a new escape.
                self._state = "esc"
                self._buf = ""
                self._step(ch)

    def _dispatch_csi(self, body: str, final: str) -> None:
        prefix = ""
        while body and body[0] in "<=>?":
            prefix += body[0]
            body = body[1:]
        intermediates = ""
        while body and " " <= body[-1] <= "/":
            intermediates = body[-1] + intermediates
            body = body[:-1]
        self.on_csi(prefix, body, intermediates, final)

    # Hooks -----------------------------------------------------------------

    def on_print(self, ch: str) -> None:
        pass

    def on_control(self, ch: str) -> None:
        pass

    def on_esc(self, intermediates: str, final: str) -> None:
        pass

    def on_csi(self, prefix: str, params: str, intermediates: str, final: str) -> None:
        pass

    def on_string(self, kind: str, payload: str, terminator: str) -> None:
        pass


def _ints(params: str, default: int) -> list:
    """Split CSI parameters, mapping empty and zero fields to ``default``."""
    out = []
    for part in params.split(";") if params else [""]:
        head = part.split(":", 1)[0]
        try:
            value = int(head) if head else 0
        except ValueError:
            value = 0
        out.append(value or default)
    return out


def _char_width(ch: str) -> int:
    if unicodedata.combining(ch) or unicodedata.category(ch) in ("Mn", "Me", "Cf"):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


# ---------------------------------------------------------------------------
# Screen model, mode tracking, query answering
# ---------------------------------------------------------------------------


@dataclass
class Query:
    """A request the program sent that expects the terminal to reply."""

    at_ns: int
    kind: str
    raw: str
    answered: bool


class Terminal(VtParser):
    """Screen model plus the bookkeeping needed to judge terminal hygiene."""

    # A frame counts as the first real one once this many cells have been drawn.
    FRAME_THRESHOLD = 16

    def __init__(
        self,
        rows: int,
        cols: int,
        profile: Optional[TerminalProfile] = None,
        reply: Optional[Callable[[bytes], None]] = None,
        clock: Callable[[], int] = time.perf_counter_ns,
    ) -> None:
        super().__init__()
        self.rows = rows
        self.cols = cols
        self.profile = profile
        self._reply = reply
        self._clock = clock

        self._primary = self._blank()
        self._alternate = self._blank()
        self.grid = self._primary
        self.row = 0
        self.col = 0
        self._saved = (0, 0)
        self._top = 0
        self._bottom = rows - 1
        self._wrap_pending = False

        self.modes: set = set()
        self.cursor_visible = True
        self.kitty_stack: list = []
        self.modify_other_keys = 0
        self.keypad_application = False
        self.title: Optional[str] = None
        self.title_stack_depth = 0

        self.queries: list = []
        self.printed_cells = 0
        self.alt_screen_entries = 0
        # Frames are counted by synchronized-update brackets (mode 2026), which
        # ratatui-style renderers wrap around every draw.
        self.frames = 0
        self.first_frame_ns: Optional[int] = None

    # Geometry --------------------------------------------------------------

    def _blank(self) -> list:
        return [[" "] * self.cols for _ in range(self.rows)]

    def resize(self, rows: int, cols: int) -> None:
        def fit(grid: list) -> list:
            grid = [line[:cols] + [" "] * max(0, cols - len(line)) for line in grid[:rows]]
            while len(grid) < rows:
                grid.append([" "] * cols)
            return grid

        on_alternate = self.grid is self._alternate
        self.rows, self.cols = rows, cols
        self._primary = fit(self._primary)
        self._alternate = fit(self._alternate)
        self.grid = self._alternate if on_alternate else self._primary
        self._top, self._bottom = 0, rows - 1
        self.row = min(self.row, rows - 1)
        self.col = min(self.col, cols - 1)
        self._wrap_pending = False

    @property
    def on_alt_screen(self) -> bool:
        return self.grid is self._alternate

    def text(self) -> str:
        return "\n".join("".join(line).rstrip() for line in self.grid)

    def contains(self, needle: str) -> bool:
        return needle in self.text()

    def visible_cells(self) -> int:
        return sum(1 for line in self.grid for cell in line if cell not in (" ", ""))

    # Printing --------------------------------------------------------------

    def on_print(self, ch: str) -> None:
        width = _char_width(ch)
        if width == 0:
            return
        if self._wrap_pending:
            self._wrap_pending = False
            self.col = 0
            self._line_feed()
        if self.col + width > self.cols:
            self.col = 0
            self._line_feed()
        self.grid[self.row][self.col] = ch
        if width == 2 and self.col + 1 < self.cols:
            self.grid[self.row][self.col + 1] = ""
        self.printed_cells += 1
        if self.col + width >= self.cols:
            self.col = self.cols - 1
            self._wrap_pending = True
        else:
            self.col += width

    def on_control(self, ch: str) -> None:
        if ch == "\r":
            self.col = 0
            self._wrap_pending = False
        elif ch in "\n\x0b\x0c":
            self._wrap_pending = False
            self._line_feed()
        elif ch == "\b":
            self.col = max(0, self.col - 1)
            self._wrap_pending = False
        elif ch == "\t":
            self.col = min(self.cols - 1, (self.col // 8 + 1) * 8)

    def _line_feed(self) -> None:
        if self.row == self._bottom:
            self._scroll_up(1)
        elif self.row < self.rows - 1:
            self.row += 1

    def _scroll_up(self, count: int) -> None:
        for _ in range(count):
            del self.grid[self._top]
            self.grid.insert(self._bottom, [" "] * self.cols)

    def _scroll_down(self, count: int) -> None:
        for _ in range(count):
            del self.grid[self._bottom]
            self.grid.insert(self._top, [" "] * self.cols)

    # Escape sequences ------------------------------------------------------

    def on_esc(self, intermediates: str, final: str) -> None:
        if intermediates:
            return
        if final == "7":
            self._saved = (self.row, self.col)
        elif final == "8":
            self.row, self.col = self._saved
            self._wrap_pending = False
        elif final == "M":
            if self.row == self._top:
                self._scroll_down(1)
            elif self.row > 0:
                self.row -= 1
        elif final == "D":
            self._line_feed()
        elif final == "E":
            self.col = 0
            self._line_feed()
        elif final == "=":
            self.keypad_application = True
        elif final == ">":
            self.keypad_application = False
        elif final == "c":
            self._hard_reset()

    def _hard_reset(self) -> None:
        self._primary = self._blank()
        self._alternate = self._blank()
        self.grid = self._primary
        self.row = self.col = 0
        self._top, self._bottom = 0, self.rows - 1
        self.modes.clear()
        self.cursor_visible = True
        self.kitty_stack.clear()
        self.modify_other_keys = 0
        self.keypad_application = False

    def on_csi(self, prefix: str, params: str, intermediates: str, final: str) -> None:
        if prefix == "?" and final in "hl" and not intermediates:
            for mode in _ints(params, 0):
                self._set_private_mode(mode, final == "h")
            return
        if prefix == "?" and final == "p" and intermediates == "$":
            self._query_decrqm(params)
            return
        if final == "u" and prefix:
            self._kitty_keyboard(prefix, params)
            return
        if final == "m" and prefix == ">":
            values = _ints(params, 0)
            if values and values[0] == 4:
                self.modify_other_keys = values[1] if len(values) > 1 else 0
            return
        if final == "c" and not intermediates:
            self._query_device_attributes(prefix, params)
            return
        if final == "n" and not prefix:
            self._query_status(params)
            return
        if final == "t" and not prefix:
            self._window_op(params)
            return
        if final == "q" and prefix == ">":
            self._note_query("xtversion", f"\x1b[>{params}q", answered=False)
            return
        if prefix or intermediates:
            return

        self._wrap_pending = False
        n = _ints(params, 1)
        if final in "Hf":
            self.row = min(self.rows - 1, n[0] - 1)
            self.col = min(self.cols - 1, (n[1] if len(n) > 1 else 1) - 1)
        elif final == "A":
            self.row = max(0, self.row - n[0])
        elif final == "B":
            self.row = min(self.rows - 1, self.row + n[0])
        elif final == "C":
            self.col = min(self.cols - 1, self.col + n[0])
        elif final == "D":
            self.col = max(0, self.col - n[0])
        elif final == "E":
            self.row = min(self.rows - 1, self.row + n[0])
            self.col = 0
        elif final == "F":
            self.row = max(0, self.row - n[0])
            self.col = 0
        elif final == "G":
            self.col = min(self.cols - 1, n[0] - 1)
        elif final == "d":
            self.row = min(self.rows - 1, n[0] - 1)
        elif final == "J":
            self._erase_display(_ints(params, 0)[0])
        elif final == "K":
            self._erase_line(_ints(params, 0)[0])
        elif final == "X":
            for col in range(self.col, min(self.cols, self.col + n[0])):
                self.grid[self.row][col] = " "
        elif final == "P":
            line = self.grid[self.row]
            del line[self.col : self.col + n[0]]
            line.extend([" "] * (self.cols - len(line)))
        elif final == "@":
            line = self.grid[self.row]
            for _ in range(n[0]):
                line.insert(self.col, " ")
            del line[self.cols :]
        elif final == "L":
            if self._top <= self.row <= self._bottom:
                for _ in range(n[0]):
                    del self.grid[self._bottom]
                    self.grid.insert(self.row, [" "] * self.cols)
        elif final == "M":
            if self._top <= self.row <= self._bottom:
                for _ in range(n[0]):
                    del self.grid[self.row]
                    self.grid.insert(self._bottom, [" "] * self.cols)
        elif final == "S":
            self._scroll_up(n[0])
        elif final == "T":
            self._scroll_down(n[0])
        elif final == "r":
            top = n[0] - 1
            bottom = (n[1] if len(n) > 1 else self.rows) - 1
            if 0 <= top < bottom < self.rows:
                self._top, self._bottom = top, bottom
            else:
                self._top, self._bottom = 0, self.rows - 1
            self.row = self.col = 0
        elif final == "s":
            self._saved = (self.row, self.col)
        elif final == "u":
            self.row, self.col = self._saved

    def _erase_display(self, mode: int) -> None:
        if mode == 0:
            self._erase_line(0)
            for row in range(self.row + 1, self.rows):
                self.grid[row] = [" "] * self.cols
        elif mode == 1:
            self._erase_line(1)
            for row in range(0, self.row):
                self.grid[row] = [" "] * self.cols
        elif mode in (2, 3):
            for row in range(self.rows):
                self.grid[row] = [" "] * self.cols

    def _erase_line(self, mode: int) -> None:
        line = self.grid[self.row]
        if mode == 0:
            start, end = self.col, self.cols
        elif mode == 1:
            start, end = 0, self.col + 1
        else:
            start, end = 0, self.cols
        for col in range(start, min(end, self.cols)):
            line[col] = " "

    # Modes -----------------------------------------------------------------

    def _set_private_mode(self, mode: int, enabled: bool) -> None:
        if mode == 25:
            self.cursor_visible = enabled
            return
        if mode in ALT_SCREEN_MODES:
            if enabled and not self.on_alt_screen:
                self.alt_screen_entries += 1
                if mode == 1049:
                    self._saved = (self.row, self.col)
                self._alternate = self._blank()
                self.grid = self._alternate
            elif not enabled and self.on_alt_screen:
                self.grid = self._primary
                if mode == 1049:
                    self.row, self.col = self._saved
        if mode == 6 or mode == 7:
            return
        if mode == 2026 and not enabled and 2026 in self.modes:
            self.frames += 1
            if self.first_frame_ns is None and self.printed_cells >= self.FRAME_THRESHOLD:
                self.first_frame_ns = self._clock()
        if enabled:
            self.modes.add(mode)
        else:
            self.modes.discard(mode)

    def _kitty_keyboard(self, prefix: str, params: str) -> None:
        values = _ints(params, 0)
        if prefix == ">":
            self.kitty_stack.append(values[0])
        elif prefix == "<":
            for _ in range(max(1, values[0])):
                if self.kitty_stack:
                    self.kitty_stack.pop()
        elif prefix == "=":
            if self.kitty_stack:
                self.kitty_stack[-1] = values[0]
            else:
                self.kitty_stack.append(values[0])
        elif prefix == "?":
            supported = bool(self.profile and self.profile.kitty_keyboard)
            flags = self.kitty_stack[-1] if self.kitty_stack else 0
            self._note_query("kitty-keyboard", "\x1b[?u", supported, f"\x1b[?{flags}u")

    def leaked_state(self) -> list:
        """Everything the program switched on and never switched back off."""
        leaks = [MODE_NAMES.get(mode, f"private mode {mode}") for mode in sorted(self.modes)]
        if not self.cursor_visible:
            leaks.append("cursor left hidden")
        if self.kitty_stack:
            leaks.append(f"kitty keyboard flags still pushed ({len(self.kitty_stack)})")
        if self.modify_other_keys:
            leaks.append(f"modifyOtherKeys left at {self.modify_other_keys}")
        if self.keypad_application:
            leaks.append("keypad left in application mode")
        if self.on_alt_screen and not any(m in self.modes for m in ALT_SCREEN_MODES):
            leaks.append("alternate screen still active")
        return leaks

    # Queries ---------------------------------------------------------------

    def _note_query(self, kind: str, raw: str, answered: bool, response: str = "") -> None:
        send = answered and self._reply is not None and self.profile is not None
        self.queries.append(Query(self._clock(), kind, raw, send))
        if send:
            self._reply(response.encode())

    def _query_device_attributes(self, prefix: str, params: str) -> None:
        if params not in ("", "0"):
            return
        profile = self.profile
        if prefix == "":
            reply = profile.da1 if profile else None
            self._note_query("DA1", "\x1b[c", reply is not None, reply or "")
        elif prefix == ">":
            reply = profile.da2 if profile else None
            self._note_query("DA2", "\x1b[>c", reply is not None, reply or "")

    def _query_status(self, params: str) -> None:
        if params == "6":
            # Cursor position report. Every emulator answers this one.
            self._note_query("cursor-position", "\x1b[6n", True, f"\x1b[{self.row + 1};{self.col + 1}R")
        elif params == "5":
            self._note_query("device-status", "\x1b[5n", True, "\x1b[0n")

    def _query_decrqm(self, params: str) -> None:
        mode = _ints(params, 0)[0]
        supported = bool(self.profile and self.profile.decrqm)
        if mode == 25:
            state = 1 if self.cursor_visible else 2
        elif mode in MODE_NAMES:
            state = 1 if mode in self.modes else 2
        else:
            state = 0
        self._note_query(f"DECRQM {mode}", f"\x1b[?{mode}$p", supported, f"\x1b[?{mode};{state}$y")

    def _window_op(self, params: str) -> None:
        values = _ints(params, 0)
        op = values[0]
        if op == 14:
            self._note_query("window-pixels", "\x1b[14t", True, f"\x1b[4;{self.rows * 18};{self.cols * 9}t")
        elif op == 16:
            self._note_query("cell-pixels", "\x1b[16t", True, "\x1b[6;18;9t")
        elif op == 18:
            self._note_query("window-cells", "\x1b[18t", True, f"\x1b[8;{self.rows};{self.cols}t")
        elif op == 22:
            self.title_stack_depth += 1
        elif op == 23:
            self.title_stack_depth = max(0, self.title_stack_depth - 1)

    def on_string(self, kind: str, payload: str, terminator: str) -> None:
        if kind != "osc":
            if kind == "apc" and payload.startswith("G"):
                self._note_query("kitty-graphics", "\x1b_G…", answered=False)
            return
        code, _, rest = payload.partition(";")
        if code in ("0", "2"):
            self.title = rest
        elif code in ("10", "11", "12") and rest == "?":
            profile = self.profile
            supported = bool(profile and profile.osc_colors)
            colour = ""
            if profile:
                colour = profile.background if code == "11" else profile.foreground
            self._note_query(
                f"OSC {code} colour",
                f"\x1b]{code};?",
                supported,
                f"\x1b]{code};rgb:{colour}{terminator}",
            )
        elif code == "4" and rest.endswith(";?"):
            self._note_query("OSC 4 palette", f"\x1b]4;{rest}", answered=False)


# ---------------------------------------------------------------------------
# Process accounting (macOS)
# ---------------------------------------------------------------------------


class _RusageInfoV2(ctypes.Structure):
    _fields_ = [
        ("ri_uuid", ctypes.c_uint8 * 16),
        ("ri_user_time", ctypes.c_uint64),
        ("ri_system_time", ctypes.c_uint64),
        ("ri_pkg_idle_wkups", ctypes.c_uint64),
        ("ri_interrupt_wkups", ctypes.c_uint64),
        ("ri_pageins", ctypes.c_uint64),
        ("ri_wired_size", ctypes.c_uint64),
        ("ri_resident_size", ctypes.c_uint64),
        ("ri_phys_footprint", ctypes.c_uint64),
        ("ri_proc_start_abstime", ctypes.c_uint64),
        ("ri_proc_exit_abstime", ctypes.c_uint64),
        ("ri_child_user_time", ctypes.c_uint64),
        ("ri_child_system_time", ctypes.c_uint64),
        ("ri_child_pkg_idle_wkups", ctypes.c_uint64),
        ("ri_child_interrupt_wkups", ctypes.c_uint64),
        ("ri_child_pageins", ctypes.c_uint64),
        ("ri_child_elapsed_abstime", ctypes.c_uint64),
        ("ri_diskio_bytesread", ctypes.c_uint64),
        ("ri_diskio_byteswritten", ctypes.c_uint64),
    ]


class _MachTimebase(ctypes.Structure):
    _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]


@dataclass
class ProcSample:
    """One reading of a process's cumulative resource counters."""

    at_ns: int
    cpu_ns: int
    rss_bytes: int
    footprint_bytes: int
    idle_wakeups: int
    interrupt_wakeups: int


_libproc = None
_timebase = (1, 1)


def _load_libproc():
    global _libproc, _timebase
    if _libproc is None:
        lib = ctypes.CDLL(ctypes.util.find_library("proc") or "/usr/lib/libproc.dylib", use_errno=True)
        lib.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
        lib.proc_pid_rusage.restype = ctypes.c_int
        libc = ctypes.CDLL(ctypes.util.find_library("c"))
        info = _MachTimebase()
        libc.mach_timebase_info(ctypes.byref(info))
        _timebase = (info.numer or 1, info.denom or 1)
        _libproc = lib
    return _libproc


def sample_process(pid: int) -> Optional[ProcSample]:
    """Read CPU time, memory, and wakeup counters for ``pid`` via libproc."""
    if sys.platform != "darwin":
        return None
    info = _RusageInfoV2()
    if _load_libproc().proc_pid_rusage(pid, 2, ctypes.byref(info)) != 0:
        return None
    numer, denom = _timebase
    return ProcSample(
        at_ns=time.perf_counter_ns(),
        cpu_ns=(info.ri_user_time + info.ri_system_time) * numer // denom,
        rss_bytes=info.ri_resident_size,
        footprint_bytes=info.ri_phys_footprint,
        idle_wakeups=info.ri_pkg_idle_wkups,
        interrupt_wakeups=info.ri_interrupt_wkups,
    )


def descendants(pid: int) -> list:
    """Return ``(pid, command)`` for every live descendant of ``pid``."""
    import subprocess

    listing = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,comm="], capture_output=True, text=True, check=False
    ).stdout
    children: dict = {}
    names: dict = {}
    for line in listing.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        child, parent = int(parts[0]), int(parts[1])
        children.setdefault(parent, []).append(child)
        names[child] = parts[2]
    found = []
    stack = list(children.get(pid, []))
    while stack:
        current = stack.pop()
        found.append((current, names.get(current, "?")))
        stack.extend(children.get(current, []))
    return found


# ---------------------------------------------------------------------------
# PTY session
# ---------------------------------------------------------------------------


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _get_winsize(fd: int) -> tuple:
    rows, cols, _, _ = struct.unpack("HHHH", fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\0" * 8))
    return rows, cols


@dataclass
class ExitInfo:
    status: Optional[int]
    signal: Optional[int]
    exit_ns: int


@dataclass
class PtySession:
    """A program running on a PTY, with the harness acting as its terminal."""

    argv: list
    env: dict
    cwd: str
    rows: int = 40
    cols: int = 120
    profile: Optional[TerminalProfile] = None
    passthrough: bool = False
    transcript: Optional[str] = None

    pid: int = field(default=0, init=False)
    start_ns: int = field(default=0, init=False)
    start_wall_ns: int = field(default=0, init=False)
    first_byte_ns: Optional[int] = field(default=None, init=False)
    first_paint_ns: Optional[int] = field(default=None, init=False)
    last_byte_ns: Optional[int] = field(default=None, init=False)
    bytes_out: int = field(default=0, init=False)
    term: Terminal = field(default=None, init=False)  # type: ignore[assignment]
    exit: Optional[ExitInfo] = field(default=None, init=False)
    termios_before: Optional[list] = field(default=None, init=False)
    termios_after: Optional[list] = field(default=None, init=False)

    # A frame counts as painted once this many cells have been written.
    PAINT_THRESHOLD = 16

    def spawn(self) -> None:
        self._master, self._slave = os.openpty()
        if self.passthrough:
            self.rows, self.cols = _get_winsize(sys.stdin.fileno())
            self._real_termios = termios.tcgetattr(sys.stdin.fileno())
        _set_winsize(self._master, self.rows, self.cols)
        # Read attributes through the master: once the program (a session leader)
        # exits, the kernel revokes the slave side and it can no longer be queried.
        self.termios_before = termios.tcgetattr(self._master)
        self.term = Terminal(
            self.rows,
            self.cols,
            profile=None if self.passthrough else self.profile,
            reply=None if self.passthrough else self._write_master,
        )
        self._log = open(self.transcript, "wb") if self.transcript else None

        self.start_wall_ns = time.time_ns()
        self.start_ns = time.perf_counter_ns()
        pid = os.fork()
        if pid == 0:
            try:
                os.setsid()
                fcntl.ioctl(self._slave, termios.TIOCSCTTY, 0)
                for fd in (0, 1, 2):
                    os.dup2(self._slave, fd)
                os.close(self._master)
                if self._slave > 2:
                    os.close(self._slave)
                os.chdir(self.cwd)
                os.execve(self.argv[0], self.argv, self.env)
            except BaseException as error:  # noqa: BLE001 - the child must never return
                os.write(2, f"ba_pty: exec failed: {error}\n".encode())
            os._exit(127)
        self.pid = pid
        os.set_blocking(self._master, False)
        if self.passthrough:
            tty.setraw(sys.stdin.fileno())
            self._previous_winch = signal.signal(signal.SIGWINCH, self._forward_winch)

    # IO --------------------------------------------------------------------

    def _write_master(self, data: bytes) -> None:
        view = memoryview(data)
        while view:
            try:
                written = os.write(self._master, view)
                view = view[written:]
            except BlockingIOError:
                select.select([], [self._master], [], 0.05)
            except OSError:
                return

    def _forward_winch(self, *_args) -> None:
        rows, cols = _get_winsize(sys.stdin.fileno())
        self.resize(rows, cols)

    def pump(self, timeout: float) -> bool:
        """Process output for up to ``timeout`` seconds. Returns False once the program has exited."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = max(0.0, deadline - time.monotonic())
            watch = [self._master]
            if self.passthrough:
                watch.append(sys.stdin.fileno())
            try:
                readable, _, _ = select.select(watch, [], [], remaining)
            except InterruptedError:
                continue
            if self.passthrough and sys.stdin.fileno() in readable:
                try:
                    self._write_master(os.read(sys.stdin.fileno(), 65536))
                except OSError:
                    pass
            if self._master in readable and not self._drain():
                self._reap(block=True)
                return False
            if self._reap(block=False):
                self._drain()
                return False
            if time.monotonic() >= deadline:
                return True

    def _drain(self) -> bool:
        """Read everything currently available. Returns False at end of stream."""
        while True:
            try:
                data = os.read(self._master, 65536)
            except BlockingIOError:
                return True
            except OSError as error:
                if error.errno in (errno.EIO, errno.EBADF):
                    return False
                raise
            if not data:
                return False
            now = time.perf_counter_ns()
            if self.first_byte_ns is None:
                self.first_byte_ns = now
            self.last_byte_ns = now
            self.bytes_out += len(data)
            if self._log:
                self._log.write(data)
            if self.passthrough:
                os.write(sys.stdout.fileno(), data)
            self.term.feed(data)
            if self.first_paint_ns is None and self.term.printed_cells >= self.PAINT_THRESHOLD:
                self.first_paint_ns = now

    def _reap(self, block: bool) -> bool:
        if self.exit is not None:
            return True
        try:
            pid, status = os.waitpid(self.pid, 0 if block else os.WNOHANG)
        except ChildProcessError:
            self.exit = ExitInfo(None, None, time.perf_counter_ns())
            return True
        if pid == 0:
            return False
        self.exit = ExitInfo(
            status=os.WEXITSTATUS(status) if os.WIFEXITED(status) else None,
            signal=os.WTERMSIG(status) if os.WIFSIGNALED(status) else None,
            exit_ns=time.perf_counter_ns(),
        )
        return True

    def wait_for(self, predicate: Callable[[], bool], timeout: float, step: float = 0.005) -> bool:
        """Pump until ``predicate`` holds. False on timeout or if the program exits first."""
        deadline = time.monotonic() + timeout
        while True:
            if predicate():
                return True
            if self.exit is not None or time.monotonic() >= deadline:
                return predicate()
            if not self.pump(step):
                return predicate()

    def wait_quiet(self, quiet: float, timeout: float) -> bool:
        """Pump until no output has arrived for ``quiet`` seconds."""
        deadline = time.monotonic() + timeout
        last_bytes = self.bytes_out
        last_change = time.monotonic()
        while time.monotonic() < deadline:
            if not self.pump(min(quiet / 4, 0.02)):
                return False
            if self.bytes_out != last_bytes:
                last_bytes = self.bytes_out
                last_change = time.monotonic()
            elif time.monotonic() - last_change >= quiet:
                return True
        return False

    def send(self, data: bytes) -> None:
        self._write_master(data)

    def type_text(self, text: str, delay: float = 0.02) -> None:
        """Send text one key at a time so paste-burst heuristics do not kick in."""
        for ch in text:
            self.send(ch.encode())
            self.pump(delay)

    def resize(self, rows: int, cols: int) -> None:
        self.rows, self.cols = rows, cols
        self.term.resize(rows, cols)
        _set_winsize(self._master, rows, cols)

    def signal(self, signum: int) -> None:
        try:
            os.kill(self.pid, signum)
        except ProcessLookupError:
            pass

    def wait_exit(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while self.exit is None and time.monotonic() < deadline:
            self.pump(0.01)
        return self.exit is not None

    def close(self) -> None:
        """Stop the program if it is still running and release the PTY."""
        if self.exit is None:
            self.signal(signal.SIGTERM)
            if not self.wait_exit(3.0):
                self.signal(signal.SIGKILL)
                self.wait_exit(3.0)
        try:
            self._drain()
        except OSError:
            pass
        try:
            self.termios_after = termios.tcgetattr(self._master)
        except termios.error:
            self.termios_after = None
        if self.passthrough:
            signal.signal(signal.SIGWINCH, self._previous_winch)
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self._real_termios)
        for fd in (self._master, self._slave):
            try:
                os.close(fd)
            except OSError:
                pass
        if self._log:
            self._log.close()

    # Reporting -------------------------------------------------------------

    def ms_since_start(self, at_ns: Optional[int]) -> Optional[float]:
        return None if at_ns is None else round((at_ns - self.start_ns) / 1e6, 2)

    def termios_restored(self) -> Optional[bool]:
        """True when the line discipline matches what it was before launch."""
        if self.termios_before is None or self.termios_after is None:
            return None
        return self.termios_before[:4] == self.termios_after[:4]

    def termios_diff(self) -> list:
        if self.termios_before is None or self.termios_after is None:
            return ["could not read terminal attributes"]
        names = ["iflag", "oflag", "cflag", "lflag"]
        return [
            f"{names[i]}: {self.termios_before[i]:#x} -> {self.termios_after[i]:#x}"
            for i in range(4)
            if self.termios_before[i] != self.termios_after[i]
        ]


def strip_ansi(text: str) -> str:
    """Remove escape sequences from captured output for plain-text assertions."""
    text = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", text)
    text = re.sub(r"\x1b[P_^X][^\x1b]*\x1b\\", "", text)
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    return re.sub(r"\x1b[ -/]*[0-~]", "", text)
