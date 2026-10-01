/* Sprachweg — small vanilla-JS layer. No build step, no framework. */
(function () {
  "use strict";

  const prefersReducedMotion = () =>
    window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---- Theme -------------------------------------------------------------
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("sprachweg-theme", theme);
    } catch (e) {
      /* private browsing / blocked storage: theme just won't persist */
    }
  }

  function toggleTheme() {
    const current = document.documentElement.getAttribute("data-theme");
    const isDark =
      current === "dark" ||
      (!current && window.matchMedia("(prefers-color-scheme: dark)").matches);
    applyTheme(isDark ? "light" : "dark");
  }

  // ---- Count-up animation for hero numbers -------------------------------
  function countUp(el) {
    const target = parseFloat(el.dataset.countTo);
    if (Number.isNaN(target) || prefersReducedMotion()) {
      el.textContent = el.dataset.countDisplay || target;
      return;
    }
    const decimals = el.dataset.countDecimals ? parseInt(el.dataset.countDecimals, 10) : 0;
    const duration = 900;
    const start = performance.now();
    function frame(now) {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      el.textContent = (target * eased).toFixed(decimals);
      if (t < 1) requestAnimationFrame(frame);
      else el.textContent = el.dataset.countDisplay || target.toFixed(decimals);
    }
    requestAnimationFrame(frame);
  }

  function initCountUps(root) {
    (root || document).querySelectorAll("[data-count-to]").forEach(countUp);
  }

  // ---- Toasts --------------------------------------------------------------
  function showToast(message) {
    const root = document.getElementById("toast-root");
    if (!root) return;
    const el = document.createElement("div");
    el.className = "toast";
    el.textContent = message;
    root.appendChild(el);
    setTimeout(() => el.remove(), 4200);
  }

  // ---- Tiny confetti burst (no external lib) --------------------------------
  function confettiBurst() {
    if (prefersReducedMotion()) return;
    const colors = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"];
    const container = document.createElement("div");
    container.style.cssText =
      "position:fixed;inset:0;pointer-events:none;z-index:200;overflow:hidden;";
    document.body.appendChild(container);
    for (let i = 0; i < 40; i++) {
      const piece = document.createElement("div");
      const size = 6 + Math.random() * 6;
      piece.style.cssText = `position:absolute;top:-20px;left:${Math.random() * 100}%;
        width:${size}px;height:${size * 0.4}px;background:${colors[i % colors.length]};
        opacity:${0.8 + Math.random() * 0.2};
        transform:rotate(${Math.random() * 360}deg);border-radius:2px;`;
      const fallDuration = 1800 + Math.random() * 1200;
      const drift = (Math.random() - 0.5) * 160;
      piece.animate(
        [
          { transform: `translate(0, 0) rotate(0deg)`, opacity: 1 },
          {
            transform: `translate(${drift}px, 100vh) rotate(${360 + Math.random() * 360}deg)`,
            opacity: 0.3,
          },
        ],
        { duration: fallDuration, easing: "cubic-bezier(.2,.6,.4,1)" }
      );
      container.appendChild(piece);
    }
    setTimeout(() => container.remove(), 3200);
  }

  // ---- Modal (HTMX-loaded quick-log sheet) -----------------------------
  function closeModal() {
    const root = document.getElementById("modal-root");
    if (root) root.innerHTML = "";
  }

  document.addEventListener("click", (e) => {
    if (e.target.classList && e.target.classList.contains("modal-overlay")) {
      closeModal();
    }
    if (e.target.closest("[data-close-modal]")) {
      closeModal();
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeModal();
  });

  // Keyboard shortcut: "n" opens quick-log (unless typing in a field)
  document.addEventListener("keydown", (e) => {
    const tag = (e.target.tagName || "").toLowerCase();
    if (e.key === "n" && tag !== "input" && tag !== "textarea" && !e.metaKey && !e.ctrlKey) {
      const fab = document.querySelector(".fab-desktop, .bottom-nav .fab");
      if (fab) fab.click();
    }
  });

  // ---- HTMX integration ---------------------------------------------------
  document.body.addEventListener("htmx:afterSwap", (e) => {
    initCountUps(e.detail.target);
  });

  document.body.addEventListener("sessionLogged", (e) => {
    const detail = e.detail || {};
    showToast(detail.message || "Session logged 🎉");
    (detail.milestones || []).forEach((label) => {
      setTimeout(() => {
        showToast("🎉 " + label);
        confettiBurst();
      }, 400);
    });
    // Soft refresh so the hero bar, streak tiles and heatmap reflect the new
    // session. A short delay lets the toast render first.
    setTimeout(() => window.location.reload(), 900);
  });

  document.body.addEventListener("htmx:responseError", () => {
    showToast("Something went wrong — please try again.");
  });

  // ---- Plan builder: "universal daily plan" quick-fill rows ---------------
  // Build one day's activities, clone rows as needed, apply to many weekdays.
  function addQuickfillRow() {
    const rows = document.getElementById("quickfill-rows");
    if (!rows) return;
    const last = rows.querySelector(".quickfill-row");
    if (!last) return;
    const clone = last.cloneNode(true);
    clone.querySelectorAll("select").forEach((s) => (s.selectedIndex = 0));
    clone.querySelectorAll('input[type="number"]').forEach((i) => (i.value = 30));
    rows.appendChild(clone);
  }

  function removeQuickfillRow(button) {
    const rows = document.getElementById("quickfill-rows");
    const row = button.closest(".quickfill-row");
    if (rows && row && rows.querySelectorAll(".quickfill-row").length > 1) {
      row.remove();
    }
  }

  window.Sprachweg = {
    toggleTheme,
    showToast,
    confettiBurst,
    closeModal,
    initCountUps,
    addQuickfillRow,
    removeQuickfillRow,
  };

  document.addEventListener("DOMContentLoaded", () => initCountUps(document));
})();
