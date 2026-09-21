#!/usr/bin/env python3
"""PixelPresence companion: a small always-on-top window showing what the agent is doing.

Run it from a terminal:

    python3 companion/pixel_presence.py

Only the standard library is used, so there is nothing to install. The window is
deliberately plain: opaque, decorated, and ordinary. No transparency, no
click-through, no global keyboard hook -- nothing that resembles the behaviour
antivirus software flags.
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Where the state lives. The Hermes hook and the CLI write the same directory.
# ---------------------------------------------------------------------------


def windows_profile() -> Path | None:
    """Resolve the Windows profile from either side of the WSL boundary."""
    if os.environ.get("USERPROFILE"):
        return Path(os.environ["USERPROFILE"])
    users = Path("/mnt/c/Users")
    if os.name == "nt" or not users.is_dir():
        return None
    with_state = [p for p in sorted(users.iterdir()) if (p / ".pixelpresence").is_dir()]
    return with_state[0] if len(with_state) == 1 else None


def state_dir() -> Path:
    override = os.environ.get("PIXELPRESENCE_DIR")
    if override:
        return Path(override)
    profile = windows_profile()
    return (profile / ".pixelpresence") if profile else Path.home() / ".pixelpresence"


# ---------------------------------------------------------------------------
# Timing and appearance
# ---------------------------------------------------------------------------

HEARTBEAT_SECONDS = 5   # how often the companion says it is still alive
FRAME_MS = 120          # animation and state-poll tick
SUCCESS_HOLD_MS = 5000  # `success` settles back to `idle` after this long
DETAIL_LIMIT = 22
SCREEN_INSET = 24

BACKGROUND = "#f4f1ea"  # caption card, and the window when transparency is unavailable
INK = "#1c1c1c"
CAPTION_FONT = ("Segoe UI", 10)

# The window colour that Windows hides (see `blank`). Deliberately a value the
# art does not contain, so no sprite pixel is punched out with it.
KEY = "#0a0b0c"

# ---------------------------------------------------------------------------
# The protocol. The hook and the CLI write these; this order is the contract.
# ---------------------------------------------------------------------------

STATES = ("idle", "thinking", "working", "waiting", "success", "error")
PROTOCOL_VERSION = 1

# Most urgent first: a session waiting on the user outranks one that is merely
# busy, and recency breaks a tie.
PRIORITY = {"waiting": 0, "error": 1, "working": 2, "success": 3, "thinking": 4, "idle": 5}

# idle and thinking are legible from the character alone, so they carry no text.
TEXT_STATES = {"working", "waiting", "success", "error"}
ACTIVITY_TEXT = {
    "idle": "resting",
    "thinking": "thinking",
    "working": "working",
    "waiting": "waiting for you",
    "success": "finished",
    "error": "something went wrong",
}

# ---------------------------------------------------------------------------
# Sprite sheets: one descriptor per known art file.
# ---------------------------------------------------------------------------

UEI_LAYOUT = {
    "frame": 192,
    "col_pitch": 192,
    "row_pitch": 192,
    "frames": 8,
    "rows": {"idle": 0, "thinking": 1, "working": 2, "waiting": 3, "success": 4, "error": 5},
}

# The shipped fallback is a single six-frame strip shared by every state.
WISP_LAYOUT = {
    "frame": 192,
    "col_pitch": 216,
    "row_pitch": 0,
    "frames": 6,
    "rows": {state: 0 for state in STATES},
}

LAYOUTS = {"uei": UEI_LAYOUT, "wisp": WISP_LAYOUT}
DEFAULT_ART = REPO_ROOT / "assets" / "enso-wisp-strip.png"


def art_choice() -> tuple[Path, dict]:
    """Pick the sheet and its layout, preferring an explicit override.

    A personal sheet kept in assets/ as `*.local.*` is used on its own, so
    nobody has to set an environment variable to see their own art.
    """
    override = os.environ.get("PIXELPRESENCE_ART")
    if not override:
        personal = sorted((REPO_ROOT / "assets").glob("*.local.*"))
        if personal:
            override = str(personal[0])
    if not override:
        return DEFAULT_ART, WISP_LAYOUT
    path = Path(override)
    kind = os.environ.get("PIXELPRESENCE_ART_LAYOUT") or (
        "uei" if "uei" in path.name.lower() else "wisp"
    )
    return path, LAYOUTS.get(kind, WISP_LAYOUT)


# ---------------------------------------------------------------------------
# Reading the sessions the agents write
# ---------------------------------------------------------------------------


def session_ttl_seconds() -> int:
    try:
        return int(os.environ.get("PIXELPRESENCE_SESSION_TTL_SECONDS", "600"))
    except ValueError:
        return 600


def parse_session(text: str) -> dict | None:
    """Return a validated event, or None when the body is not one we speak."""
    try:
        event = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(event, dict):
        return None
    if event.get("version") != PROTOCOL_VERSION:
        return None
    if event.get("state") not in PRIORITY:
        return None
    return event


def winning_session() -> dict | None:
    """The most urgent live session, or None when nothing is running.

    A session that stopped writing is ignored, so an agent that died mid-turn
    cannot leave the companion stuck on `working`.
    """
    ttl = session_ttl_seconds()
    now = time.time()
    events = []
    for path in sorted((state_dir() / "sessions").glob("*.json")):
        try:
            if now - path.stat().st_mtime > ttl:
                continue
            event = parse_session(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        if event is not None:
            events.append(event)

    if not events:
        return None

    best_rank = min(PRIORITY[event["state"]] for event in events)
    urgent = [e for e in events if PRIORITY[e["state"]] == best_rank]
    return max(urgent, key=lambda e: str(e.get("timestamp", "")))


def caption_for(event: dict | None) -> str:
    if not event:
        return ""
    state = event["state"]
    detail = event.get("label")
    detail = str(detail)[:DETAIL_LIMIT] if detail else ""
    if detail and state == "working":
        return f"using {detail}"
    if detail and state == "error":
        return f"{detail} failed"
    return ACTIVITY_TEXT[state]


# ---------------------------------------------------------------------------
# Window placement, remembered between runs
# ---------------------------------------------------------------------------


def window_state_file() -> Path:
    return state_dir() / "window.json"


def remember_position(x: int, y: int) -> None:
    try:
        target = window_state_file()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"x": x, "y": y}), encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Global shortcuts. Windows only, and not a keyboard hook: RegisterHotKey is
# the system's own way to claim a combination, so it watches no other input.
# ---------------------------------------------------------------------------

TOGGLE_KEYS = "Ctrl+Shift+Space"
QUIT_KEYS = "Ctrl+Shift+Q"

HOTKEY_TOGGLE = 1
HOTKEY_QUIT = 2
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
WM_HOTKEY = 0x0312
VK_SPACE = 0x20
VK_Q = 0x51


def start_hotkeys(events: "queue.Queue[int]") -> bool:
    """Claim the shortcuts, reporting whether they were actually registered.

    The worker thread owns its own message queue, so Tk's message pump is never
    touched -- draining the main thread's queue would eat Tk's own messages.
    """
    if sys.platform != "win32":
        return False

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    ready = threading.Event()

    def pump() -> None:
        if not user32.RegisterHotKey(None, HOTKEY_TOGGLE, MOD_CONTROL | MOD_SHIFT, VK_SPACE):
            return
        if not user32.RegisterHotKey(None, HOTKEY_QUIT, MOD_CONTROL | MOD_SHIFT, VK_Q):
            user32.UnregisterHotKey(None, HOTKEY_TOGGLE)
            return

        ready.set()
        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            if message.message == WM_HOTKEY:
                events.put(int(message.wParam))
        user32.UnregisterHotKey(None, HOTKEY_TOGGLE)
        user32.UnregisterHotKey(None, HOTKEY_QUIT)

    threading.Thread(target=pump, daemon=True).start()
    # Another program may already own the combination, so wait for the verdict
    # rather than claiming success.
    return ready.wait(timeout=2.0)


# ---------------------------------------------------------------------------
# The companion
# ---------------------------------------------------------------------------


class Companion:
    def __init__(self, sheet: Path, layout: dict) -> None:
        self.layout = layout
        self.state = "idle"
        self.frame = 0
        self.drag_origin = (0, 0)
        self.success_since: float | None = None

        self.root = tk.Tk()
        self.root.title("PixelPresence")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        # No title bar and no border: the sprite is the window.
        self.root.overrideredirect(True)

        # On Windows one attribute makes a single colour see-through, so the
        # sprite floats on the desktop instead of sitting in a box. Anywhere
        # else the window keeps an opaque background.
        self.transparent = False
        try:
            self.root.attributes("-transparentcolor", KEY)
        except tk.TclError:
            pass
        else:
            self.transparent = True

        self.root.configure(bg=self.blank)
        frame = layout["frame"]
        self.caption = tk.Label(
            self.root, text="", bg=self.blank, fg=INK, font=CAPTION_FONT, pady=4
        )
        self.canvas = tk.Canvas(
            self.root, width=frame, height=frame, bg=self.blank, highlightthickness=0
        )
        self.caption.pack(fill="x")
        self.canvas.pack()

        try:
            self.sheet = tk.PhotoImage(file=str(sheet))
        except tk.TclError as error:
            raise SystemExit(f"pixelpresence: cannot read sprite sheet {sheet}: {error}")

        # The canvas clips its items, so a sheet pushed up and left by whole
        # frames shows exactly one frame -- no image library needed.
        self.sprite = self.canvas.create_image(0, 0, anchor="nw", image=self.sheet)

        self.place()
        for widget in (self.canvas, self.caption):
            widget.bind("<ButtonPress-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.drag)
            # Remember where it was put, the moment the drag ends.
            widget.bind("<ButtonRelease-1>", lambda _event: self.save_position())
            # A borderless window has no close button, so offer a menu instead.
            widget.bind("<ButtonPress-3>", self.popup)

        self.hidden = False
        self.hotkeys: queue.Queue[int] = queue.Queue()
        self.hotkeys_ok = start_hotkeys(self.hotkeys)
        self.last_beat = 0.0
        self.write_heartbeat()
        if not self.hotkeys_ok and sys.platform == "win32":
            # Silently dead shortcuts are worse than none: say why.
            print(
                f"pixelpresence: {TOGGLE_KEYS} and {QUIT_KEYS} could not be claimed "
                "(another program holds them); use right-click to quit",
                file=sys.stderr,
            )

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Hide", command=self.toggle)
        self.menu.add_separator()
        self.menu.add_command(label="Quit", command=self.close)

    def popup(self, event: tk.Event) -> None:
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def reapply(self) -> None:
        """Restore what Tk drops when a borderless window is re-mapped.

        Without this, showing the window again after hiding it loses the
        see-through background.
        """
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        if self.transparent:
            self.root.attributes("-transparentcolor", KEY)

    def toggle(self) -> None:
        self.hidden = not self.hidden
        if self.hidden:
            self.root.withdraw()
            return
        self.root.deiconify()
        self.reapply()

    @property
    def blank(self) -> str:
        """The colour that disappears, or the plain background without it."""
        return KEY if self.transparent else BACKGROUND

    # -- placement ---------------------------------------------------------

    def place(self) -> None:
        frame = self.layout["frame"]
        width = frame
        height = frame + 28
        self.root.update_idletasks()

        x = y = None
        try:
            remembered = json.loads(window_state_file().read_text(encoding="utf-8"))
            x, y = int(remembered["x"]), int(remembered["y"])
        except (OSError, ValueError, KeyError, TypeError):
            pass

        vroot_w = self.root.winfo_vrootwidth() or self.root.winfo_screenwidth()
        vroot_h = self.root.winfo_vrootheight() or self.root.winfo_screenheight()
        reachable = (
            x is not None
            and y is not None
            and -width <= x <= vroot_w
            and -height <= y <= vroot_h
        )
        if not reachable:
            x = vroot_w - width - SCREEN_INSET
            y = vroot_h - height - SCREEN_INSET * 3
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def start_drag(self, event: tk.Event) -> None:
        self.drag_origin = (
            event.x_root - self.root.winfo_x(),
            event.y_root - self.root.winfo_y(),
        )

    def drag(self, event: tk.Event) -> None:
        dx, dy = self.drag_origin
        self.root.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    def save_position(self) -> None:
        remember_position(self.root.winfo_x(), self.root.winfo_y())

    def write_heartbeat(self) -> None:
        """Say we are alive, so a launcher does not start a second companion."""
        try:
            path = state_dir() / "companion.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
        except OSError:
            pass

    def close(self) -> None:
        self.save_position()
        self.root.destroy()

    # -- rendering ---------------------------------------------------------

    def render(self) -> None:
        while not self.hotkeys.empty():
            key = self.hotkeys.get_nowait()
            if key == HOTKEY_TOGGLE:
                self.toggle()
            elif key == HOTKEY_QUIT:
                self.close()
                return

        if self.state == "success" and self.success_since is not None:
            if time.monotonic() - self.success_since > SUCCESS_HOLD_MS / 1000:
                self.state = "idle"
                self.frame = 0
                self.success_since = None

        now = time.monotonic()
        if now - self.last_beat > HEARTBEAT_SECONDS:
            self.last_beat = now
            self.write_heartbeat()

        event = winning_session()
        state = event["state"] if event else "idle"
        if state != self.state:
            self.state = state
            self.frame = 0
            self.success_since = time.monotonic() if state == "success" else None

        # An empty caption keeps its space in the layout but must not paint a
        # card, or a stray bar floats above the sprite.
        text = caption_for(event) if self.state in TEXT_STATES else ""
        self.caption.configure(text=text, bg=BACKGROUND if text else self.blank)

        row = self.layout["rows"].get(self.state, 0)
        column = self.frame % self.layout["frames"]
        self.canvas.coords(
            self.sprite,
            -column * self.layout["col_pitch"],
            -row * self.layout["row_pitch"],
        )
        self.frame += 1

        self.root.after(FRAME_MS, self.render)

    def run(self) -> None:
        self.root.after(FRAME_MS, self.render)
        self.root.mainloop()


def main() -> int:
    sheet, layout = art_choice()
    if not sheet.is_file():
        print(f"pixelpresence: sprite sheet not found: {sheet}", file=sys.stderr)
        print("set PIXELPRESENCE_ART to point at a sheet", file=sys.stderr)
        return 1

    try:
        companion = Companion(sheet, layout)
    except tk.TclError as error:
        print(f"pixelpresence: no display available ({error})", file=sys.stderr)
        return 1

    try:
        companion.run()
    except KeyboardInterrupt:
        remember_position(companion.root.winfo_x(), companion.root.winfo_y())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
