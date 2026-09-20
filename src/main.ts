import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import "./styles.css";

const STATES = ["idle", "thinking", "working", "waiting", "success", "error"] as const;

type CompanionState = (typeof STATES)[number];

const SUCCESS_HOLD_MS = 5000;
const DETAIL_LIMIT = 22;
const ACTIVITY_TEXT: Record<CompanionState, string> = {
  idle: "resting",
  thinking: "thinking",
  working: "working",
  waiting: "waiting for you",
  success: "finished",
  error: "something went wrong",
};

const root = document.querySelector<HTMLDivElement>("#app");

if (!root) {
  throw new Error("PixelPresence root element is missing");
}

root.innerHTML = `
  <main class="companion" aria-label="PixelPresence companion">
    <div class="dialogue-box" aria-live="polite">
      <span class="dialogue-text">resting</span>
    </div>

    <button class="pixel-pet" type="button" data-state="idle" aria-label="PixelPresence companion">
      <span class="pet-art" aria-hidden="true"></span>
    </button>

    <div class="context-menu" role="menu" hidden>
      <button class="context-menu-close" type="button" role="menuitem">Close</button>
    </div>
  </main>
`;

const pet = document.querySelector<HTMLButtonElement>(".pixel-pet");
const dialogue = document.querySelector<HTMLSpanElement>(".dialogue-text");
const contextMenu = document.querySelector<HTMLDivElement>(".context-menu");
const closeButton = document.querySelector<HTMLButtonElement>(".context-menu-close");

let successTimer: number | undefined;

function hideContextMenu() {
  if (contextMenu) {
    contextMenu.hidden = true;
  }
}

function showContextMenu(event: MouseEvent) {
  if (!contextMenu) {
    return;
  }

  const bounds = root!.getBoundingClientRect();
  contextMenu.style.left = `${Math.min(event.clientX - bounds.left, bounds.width - 86)}px`;
  contextMenu.style.top = `${Math.min(event.clientY - bounds.top, bounds.height - 42)}px`;
  contextMenu.hidden = false;
}

function isCompanionState(value: unknown): value is CompanionState {
  return typeof value === "string" && (STATES as readonly string[]).includes(value);
}

function activityText(state: CompanionState, detail?: string) {
  if (!detail) {
    return ACTIVITY_TEXT[state];
  }

  if (state === "working") {
    return `using ${detail}`;
  }

  if (state === "error") {
    return `${detail} failed`;
  }

  return ACTIVITY_TEXT[state];
}

function render(state: CompanionState, detail?: string) {
  pet?.setAttribute("data-state", state);

  if (dialogue) {
    dialogue.textContent = activityText(state, detail);
  }
}

function show(state: CompanionState, detail?: string) {
  window.clearTimeout(successTimer);
  render(state, detail);

  if (state === "success") {
    successTimer = window.setTimeout(() => render("idle"), SUCCESS_HOLD_MS);
  }
}

listen<{ state?: unknown; label?: unknown }>("companion://state", (event) => {
  const payload = event.payload;

  if (!isCompanionState(payload.state)) {
    return;
  }

  const detail =
    typeof payload.label === "string" && payload.label
      ? payload.label.slice(0, DETAIL_LIMIT)
      : undefined;
  show(payload.state, detail);
});

root.addEventListener("contextmenu", (event) => {
  event.preventDefault();
  showContextMenu(event);
});

root.addEventListener("pointerdown", (event) => {
  if (event.button === 0) {
    hideContextMenu();
    void getCurrentWindow().startDragging();
  }
});

closeButton?.addEventListener("click", () => {
  void invoke("quit_app");
});
