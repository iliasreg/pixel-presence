import { getCurrentWindow } from "@tauri-apps/api/window";
import "./styles.css";

const root = document.querySelector<HTMLDivElement>("#app");

if (!root) {
  throw new Error("PixelPresence root element is missing");
}

root.innerHTML = `
  <main class="companion" aria-label="PixelPresence companion" data-tauri-drag-region>
    <div class="status-bubble" data-tauri-drag-region>
      <span class="status-dot" aria-hidden="true"></span>
      <span>PixelPresence</span>
      <span class="status-divider">·</span>
      <span>idle</span>
    </div>

    <button class="pixel-pet" type="button" aria-label="PixelPresence companion">
      <span class="pet-art" aria-hidden="true"></span>
    </button>

    <p class="hint">drag me</p>
  </main>
`;

const pet = document.querySelector<HTMLButtonElement>(".pixel-pet");
const hint = document.querySelector<HTMLParagraphElement>(".hint");

root.addEventListener("pointerdown", (event) => {
  if (event.button === 0) {
    void getCurrentWindow().startDragging();
  }
});

pet?.addEventListener("click", () => {
  hint?.classList.add("visible");
  window.setTimeout(() => hint?.classList.remove("visible"), 1200);
});
