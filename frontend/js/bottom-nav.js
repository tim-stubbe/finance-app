// ================= MOBILE BOTTOM-NAV (Spezifikationspunkt D, 2026-08-28) =================
// Reine Zusatz-Navigation für schmale Viewports (siehe style.css) - baut
// bewusst NICHT auf der generischen .nav-btn-Verkabelung in core.js auf
// (dort hängt auch moveNavIndicator() dran, das den Sidebar-Indikator anhand
// von offsetLeft/offsetTop im Sidebar-Koordinatensystem positioniert - bei
// einem Klick auf einen dieser fixen Bottom-Buttons hätte das den Indikator
// oben auf eine sinnlose Position springen lassen). Stattdessen: goToTab()
// klickt intern den ECHTEN oberen .nav-btn, wodurch die komplette bestehende
// Logik (Laden, aktiv-Klasse, Indikator) unverändert greift.
document.getElementById("bottom-nav").addEventListener("click", e => {
  const btn = e.target.closest("[data-bottom-tab]");
  if (btn) goToTab(btn.dataset.bottomTab);
});

document.getElementById("bottom-nav-more").addEventListener("click", () => cmdkOpen());

// Aktiv-Status mitführen: dieselbe Stelle, an der die obere Nav ihre
// aktive Klasse setzt (siehe core.js), spiegelt hier zusätzlich auf die
// Bottom-Nav - kein eigener State, nur ein weiterer Listener auf denselben
// Klick.
document.querySelectorAll(".nav-btn").forEach(topBtn => {
  topBtn.addEventListener("click", () => {
    if (!topBtn.dataset.tab) return;
    document.querySelectorAll(".bottom-nav-btn[data-bottom-tab]").forEach(b =>
      b.classList.toggle("active", b.dataset.bottomTab === topBtn.dataset.tab));
  });
});

// Beim ersten Laden: Hub ist der Start-Tab (siehe index.html .nav-btn.active),
// Bottom-Nav soll das von Anfang an spiegeln statt erst nach dem ersten Klick.
document.querySelector('.bottom-nav-btn[data-bottom-tab="hub"]')?.classList.add("active");
