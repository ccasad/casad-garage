// Registers the service worker and shows an offline banner.
(function () {
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js");
    });
  }

  function setOffline(offline) {
    var banner = document.getElementById("offline-banner");
    if (banner) banner.hidden = !offline;
  }

  function sync() {
    setOffline(!navigator.onLine);
  }

  window.addEventListener("online", sync);
  window.addEventListener("offline", sync);
  document.addEventListener("DOMContentLoaded", sync);
  // hx-boost swaps the whole body, banner included.
  document.addEventListener("htmx:afterSettle", sync);
  // A boosted navigation that never reached the server.
  document.addEventListener("htmx:sendError", function () {
    setOffline(true);
  });

  // Popovers (the header's person menu): close on an outside click or Escape.
  document.addEventListener("click", function (event) {
    document.querySelectorAll("details[data-popover][open]").forEach(function (menu) {
      if (!menu.contains(event.target)) menu.removeAttribute("open");
    });
  });
  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    document.querySelectorAll("details[data-popover][open]").forEach(function (menu) {
      menu.removeAttribute("open");
      menu.querySelector("summary").focus();
    });
  });

  // Show times in the viewer's own time zone; the server only knows UTC.
  // Markup: <time datetime="2026-11-05T14:00:00+00:00" data-local="date|datetime">Nov 5, 2026</time>
  function localTimes() {
    document.querySelectorAll("time[data-local]").forEach(function (el) {
      var date = new Date(el.dateTime);
      if (isNaN(date)) return;
      el.textContent = el.dataset.local === "datetime"
        ? date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" })
        : date.toLocaleDateString([], { dateStyle: "medium" });
      el.removeAttribute("data-local");
    });
  }
  document.addEventListener("DOMContentLoaded", localTimes);
  document.addEventListener("htmx:afterSettle", localTimes);
})();
