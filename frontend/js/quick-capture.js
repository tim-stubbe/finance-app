// ================= QUICK-CAPTURE-FAB (Spezifikationspunkt D, 2026-08-28) =================
// Reine Navigations-/Fokus-Hilfe, kein eigenes Formular-System: nutzt exakt
// dieselben Ziele wie die entsprechenden CMDK_ACTIONS in command-palette.js
// (goToTab + bestehendes Formular fokussieren), hier nur zusätzlich per Tap
// ohne Tastatur erreichbar.
const QUICK_CAPTURE_TARGETS = {
  transaction: () => { goToTab("transactions"); setTimeout(() => document.getElementById("tx-new-btn")?.click(), 150); },
  todo: () => { goToTab("goals"); setTimeout(() => document.getElementById("todo-title")?.focus(), 150); },
  // Check-in braucht einen Lebensbereich - kein generischer Eintrag ohne
  // Auswahl möglich, deshalb zum Leben-Tab statt direkt ins Modal (dort
  // wählt man per "+ Check-in mit Notiz" den Bereich selbst).
  checkin: () => { goToTab("life"); },
};

function quickCaptureToggle(open) {
  const menu = document.getElementById("quick-capture-menu");
  const shouldOpen = open ?? menu.classList.contains("hidden");
  menu.classList.toggle("hidden", !shouldOpen);
}

document.getElementById("quick-capture-fab").addEventListener("click", () => quickCaptureToggle());

document.getElementById("quick-capture-menu").addEventListener("click", e => {
  const btn = e.target.closest("[data-qc]");
  if (!btn) return;
  quickCaptureToggle(false);
  QUICK_CAPTURE_TARGETS[btn.dataset.qc]?.();
});

document.addEventListener("click", e => {
  const wrap = document.getElementById("quick-capture-wrap");
  if (!wrap.contains(e.target)) quickCaptureToggle(false);
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape") quickCaptureToggle(false);
});
