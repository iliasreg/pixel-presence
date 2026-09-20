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
      <span class="antenna" aria-hidden="true"></span>
      <span class="pet-body" aria-hidden="true">
        <span class="pet-eye left"></span>
        <span class="pet-eye right"></span>
        <span class="pet-mouth"></span>
      </span>
    </button>

    <p class="hint">drag me</p>
  </main>
`;

const pet = document.querySelector<HTMLButtonElement>(".pixel-pet");
const hint = document.querySelector<HTMLParagraphElement>(".hint");

pet?.addEventListener("click", () => {
  hint?.classList.add("visible");
  window.setTimeout(() => hint?.classList.remove("visible"), 1200);
});
