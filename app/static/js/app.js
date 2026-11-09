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

  // Date inputs marked data-today start on the viewer's own current date.
  function fillToday() {
    document.querySelectorAll("input[type=date][data-today]").forEach(function (el) {
      if (el.value) return;
      var d = new Date();
      el.value = d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
    });
  }
  document.addEventListener("DOMContentLoaded", fillToday);
  document.addEventListener("htmx:afterSettle", fillToday);

  // Service form: "Done by Myself" hides the shop fields.
  function doneBy() {
    var select = document.querySelector("select[data-done-by]");
    var fields = document.querySelector("[data-shop-fields]");
    if (select && fields) fields.hidden = select.value === "self";
  }
  document.addEventListener("change", function (event) {
    if (event.target.matches && event.target.matches("select[data-done-by]")) doneBy();
  });
  document.addEventListener("DOMContentLoaded", doneBy);

  // Repeating rows in a form: <button data-add-row="container-id" data-template="template-id">
  // appends a copy of the template; <button data-remove-row> inside a row removes it.
  document.addEventListener("click", function (event) {
    var add = event.target.closest && event.target.closest("[data-add-row]");
    if (add) {
      var template = document.getElementById(add.dataset.template);
      document.getElementById(add.dataset.addRow).appendChild(template.content.cloneNode(true));
      return;
    }
    var remove = event.target.closest && event.target.closest("[data-remove-row]");
    if (remove) {
      var row = remove.closest("[data-item-row]");
      if (row) row.remove();
    }
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

  // VIN field: Look up only works for 17-character VINs; shorter ones are pre-1981 (FR-2).
  function syncVin(input) {
    var value = input.value.replace(/[\s-]/g, "");
    var short = value.length > 0 && value.length !== 17;
    var scope = input.closest("#car-fields") || document;
    var button = scope.querySelector("[data-vin-lookup]");
    var hint = scope.querySelector("[data-vin-hint]");
    if (button) button.disabled = short;
    if (hint) hint.hidden = !short;
  }
  document.addEventListener("input", function (event) {
    if (event.target.matches && event.target.matches("[data-vin-input]")) syncVin(event.target);
  });

  // Phone: hide the bottom tab bar while a field has focus so the on-screen keyboard
  // doesn't drag it around (NFR-19). Works for every form; no per-page code.
  var FIELD = "input:not([type=checkbox]):not([type=radio]):not([type=button]):not([type=submit]):not([type=file]), select, textarea";
  var blurTimer = null;
  document.addEventListener("focusin", function (event) {
    if (!event.target.matches || !event.target.matches(FIELD)) return;
    clearTimeout(blurTimer);
    document.body.classList.add("keyboard-open");
  });
  document.addEventListener("focusout", function () {
    clearTimeout(blurTimer);
    blurTimer = setTimeout(function () {
      var active = document.activeElement;
      if (!active || !active.matches || !active.matches(FIELD)) {
        document.body.classList.remove("keyboard-open");
      }
    }, 150);
  });
  // A boosted navigation swaps the body; make sure the class doesn't linger.
  document.addEventListener("htmx:afterSettle", function () {
    var active = document.activeElement;
    if (!active || !active.matches || !active.matches(FIELD)) {
      document.body.classList.remove("keyboard-open");
    }
  });
})();
