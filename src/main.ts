import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import "./styles.css";

const localPetArt = import.meta.env.VITE_PIXELPRESENCE_ART;
if (localPetArt) {
  document.documentElement.dataset.petArt = "uei";
  document.documentElement.style.setProperty("--pet-art-image", `url("${localPetArt}")`);
  document.documentElement.style.setProperty("--pet-art-step", "-192px");
  document.documentElement.style.setProperty("--pet-art-size", "1536px 1152px");
}

const STATES = ["idle", "thinking", "working", "waiting", "success", "error"] as const;

type CompanionState = (typeof STATES)[number];

const SUCCESS_HOLD_MS = 5000;
const DETAIL_LIMIT = 22;
// Only states that carry information worth a caption. idle and thinking are
// already legible from the character alone, so the caption stays hidden and the
// companion reads as just the character. Empty this set to drop the caption
// entirely.
const TEXT_STATES = new Set<CompanionState>(["working", "waiting", "success", "error"]);
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
  <main class="companion" aria-label="UEI companion">
    <div class="dialogue-box" aria-live="polite" hidden>
      <span class="dialogue-text">resting</span>
    </div>

    <button class="pixel-pet" type="button" data-state="idle" aria-label="UEI companion">
      <span class="pet-art" aria-hidden="true"></span>
    </button>

    <div class="context-menu" role="menu" hidden>
      <button class="context-menu-close" type="button" role="menuitem">Close</button>
    </div>
  </main>
`;

const pet = document.querySelector<HTMLButtonElement>(".pixel-pet");
const dialogue = document.querySelector<HTMLSpanElement>(".dialogue-text");
const dialogueBox = document.querySelector<HTMLDivElement>(".dialogue-box");
const contextMenu = document.querySelector<HTMLDivElement>(".context-menu");
const closeButton = document.querySelector<HTMLButtonElement>(".context-menu-close");

let successTimer: number | undefined;

function hideContextMenu() {
  if (contextMenu && !contextMenu.hidden) {
    contextMenu.hidden = true;
    // Give the window back to the desktop.
    void invoke("set_menu_open", { open: false });
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
  // The menu can reach past the character, where the window is click-through.
  void invoke("set_menu_open", { open: true });
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

  if (dialogueBox) {
    dialogueBox.hidden = !TEXT_STATES.has(state);
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

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    hideContextMenu();
  }
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
