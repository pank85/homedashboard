(function () {
  var SECTIONS = ["host", "containers", "agents", "git", "sessions"];

  function activate(section) {
    var panels = document.querySelectorAll("[data-mobile-panel]");
    var found = false;
    for (var i = 0; i < panels.length; i += 1) {
      var panel = panels[i];
      if (panel.getAttribute("data-section") === section) {
        panel.removeAttribute("hidden");
        found = true;
      } else {
        panel.setAttribute("hidden", "hidden");
      }
    }
    var nav = document.querySelector("[data-view-nav]");
    if (nav) {
      var buttons = nav.querySelectorAll("button[data-section]");
      for (var j = 0; j < buttons.length; j += 1) {
        buttons[j].setAttribute("aria-selected", buttons[j].getAttribute("data-section") === section ? "true" : "false");
      }
    }
    return found;
  }

  function sectionFromHash() {
    var hash = window.location.hash.replace(/^#/, "");
    for (var i = 0; i < SECTIONS.length; i += 1) {
      if (SECTIONS[i] === hash) {
        return hash;
      }
    }
    return "host";
  }

  function setMenuOpen(nav, burger, open) {
    nav.setAttribute("data-menu-open", open ? "true" : "false");
    if (burger) {
      burger.setAttribute("aria-expanded", open ? "true" : "false");
    }
  }

  function initViewNav() {
    var nav = document.querySelector("[data-view-nav]");
    if (!nav) {
      return;
    }
    if (nav.getAttribute("data-view-nav-bound") === "true") {
      return;
    }
    nav.setAttribute("data-view-nav-bound", "true");
    var burger = nav.querySelector("[data-burger]");
    var menu = document.getElementById("view-menu");
    setMenuOpen(nav, burger, false);
    var buttons = nav.querySelectorAll("button[data-section]");
    for (var i = 0; i < buttons.length; i += 1) {
      buttons[i].addEventListener("click", function (event) {
        var section = event.currentTarget.getAttribute("data-section");
        activate(section);
        setMenuOpen(nav, burger, false);
      });
    }
    if (burger) {
      burger.addEventListener("click", function () {
        setMenuOpen(nav, burger, nav.getAttribute("data-menu-open") !== "true");
      });
    }
    nav.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        setMenuOpen(nav, burger, false);
      }
    });
    if (menu && burger) {
      menu.addEventListener("keydown", function (event) {
        if (event.key === "Escape") {
          setMenuOpen(nav, burger, false);
          burger.focus();
        }
      });
    }
    activate(sectionFromHash());
    window.addEventListener("hashchange", function () {
      activate(sectionFromHash());
    });
  }

  globalThis.initViewNav = initViewNav;
})();
