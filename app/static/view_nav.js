(function () {
  function activate(section) {
    var panels = document.querySelectorAll("[data-mobile-panel]");
    for (var i = 0; i < panels.length; i += 1) {
      var panel = panels[i];
      if (panel.getAttribute("data-section") === section) {
        panel.removeAttribute("hidden");
      } else {
        panel.setAttribute("hidden", "hidden");
      }
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
    var buttons = nav.querySelectorAll("button[data-section]");
    for (var i = 0; i < buttons.length; i += 1) {
      buttons[i].addEventListener("click", function (event) {
        activate(event.currentTarget.getAttribute("data-section"));
      });
    }
  }

  globalThis.initViewNav = initViewNav;
})();
