import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import "./styles.css";

const STATES = ["idle", "thinking", "working", "waiting", "success", "error"] as const;

type CompanionState = (typeof STATES)[number];

const SUCCESS_HOLD_MS = 5000;
const DETAIL_LIMIT = 22;

const root = document.querySelector<HTMLDivElement>("#app");

if (!root) {
  throw new Error("PixelPresence root element is missing");
}

root.innerHTML = `
  <main class="companion" aria-label="PixelPresence companion">
    <div class="status-bubble">
      <span class="status-dot" aria-hidden="true"></span>
      <span class="status-agent">hermes</span>
      <span class="status-divider">·</span>
      <span class="status-state">idle</span>
    </div>

    <button class="pixel-pet" type="button" data-state="idle" aria-label="PixelPresence companion">
      <span class="pet-art" aria-hidden="true"></span>
    </button>

    <p class="hint">drag me</p>
  </main>
`;

const pet = document.querySelector<HTMLButtonElement>(".pixel-pet");
const hint = document.querySelector<HTMLParagraphElement>(".hint");
const agentLabel = document.querySelector<HTMLSpanElement>(".status-agent");
const stateLabel = document.querySelector<HTMLSpanElement>(".status-state");

let successTimer: number | undefined;

function isCompanionState(value: unknown): value is CompanionState {
  return typeof value === "string" && (STATES as readonly string[]).includes(value);
}

function render(state: CompanionState, detail?: string, agent?: string) {
  pet?.setAttribute("data-state", state);

  if (stateLabel) {
    stateLabel.textContent = detail ? `${state} ${detail}` : state;
  }

  if (agentLabel && agent) {
    agentLabel.textContent = agent;
  }
}

function show(state: CompanionState, detail?: string, agent?: string) {
  window.clearTimeout(successTimer);
  render(state, detail, agent);

  if (state === "success") {
    successTimer = window.setTimeout(() => render("idle", undefined, agent), SUCCESS_HOLD_MS);
  }
}

listen<{ state?: unknown; label?: unknown; agent?: unknown }>("companion://state", (event) => {
  const payload = event.payload;

  if (!isCompanionState(payload.state)) {
    return;
  }

  const detail =
    typeof payload.label === "string" && payload.label
      ? payload.label.slice(0, DETAIL_LIMIT)
      : undefined;
  const agent = typeof payload.agent === "string" ? payload.agent : undefined;

  show(payload.state, detail, agent);
});

root.addEventListener("pointerdown", (event) => {
  if (event.button === 0) {
    void getCurrentWindow().startDragging();
  }
});

pet?.addEventListener("click", () => {
  hint?.classList.add("visible");
  window.setTimeout(() => hint?.classList.remove("visible"), 1200);
});
