(function () {
  var root = document.documentElement;

  function currentTheme() {
    var explicit = root.getAttribute("data-theme");
    if (explicit) return explicit;
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }

  function updateIcon(btn) {
    btn.textContent = currentTheme() === "dark" ? "☀️" : "🌙";
    btn.setAttribute("aria-label", currentTheme() === "dark" ? "라이트 모드로 전환" : "다크 모드로 전환");
  }

  document.addEventListener("DOMContentLoaded", function () {
    var btn = document.getElementById("themeToggle");
    if (!btn) return;
    updateIcon(btn);
    btn.addEventListener("click", function () {
      var next = currentTheme() === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem("theme", next); } catch (e) {}
      updateIcon(btn);
    });
  });
})();
