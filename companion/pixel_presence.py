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
import sys
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
    """Pick the sheet and its layout, preferring an explicit override."""
    override = os.environ.get("PIXELPRESENCE_ART")
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
            # A borderless window has no close button, so quitting needs a
            # gesture of its own.
            widget.bind("<ButtonPress-3>", lambda _event: self.close())

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

    def close(self) -> None:
        remember_position(self.root.winfo_x(), self.root.winfo_y())
        self.root.destroy()

    # -- rendering ---------------------------------------------------------

    def render(self) -> None:
        if self.state == "success" and self.success_since is not None:
            if time.monotonic() - self.success_since > SUCCESS_HOLD_MS / 1000:
                self.state = "idle"
                self.frame = 0
                self.success_since = None

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
