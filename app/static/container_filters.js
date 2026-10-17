(function () {
  var TEXT_FIELDS = ["name", "compose_service", "image", "image_short"];

  function field(row, key) {
    if (!row || typeof row !== "object") {
      return "";
    }
    var value = row[key];
    return typeof value === "string" ? value : "";
  }

  function matchesText(row, needle) {
    var index;
    for (index = 0; index < TEXT_FIELDS.length; index += 1) {
      if (field(row, TEXT_FIELDS[index]).toLowerCase().indexOf(needle) !== -1) {
        return true;
      }
    }
    return false;
  }

  function matchesState(row, state) {
    var rowState = row && typeof row === "object" ? row.state : undefined;
    if (state === "Running") {
      return rowState === "running";
    }
    if (state === "Stopped") {
      return rowState !== "running";
    }
    return true;
  }

  function isHealthy(row) {
    if (!row || typeof row !== "object") {
      return false;
    }
    return row.health === "healthy" || row.health_label === "healthy";
  }

  function filterContainers(rows, text, state, hideHealthy) {
    var list = Array.isArray(rows) ? rows : [];
    var needle = String(text == null ? "" : text).trim().toLowerCase();
    var chosen = state == null ? "All" : String(state);
    var hide = !!hideHealthy;
    var shown = [];
    var index;
    for (index = 0; index < list.length; index += 1) {
      var row = list[index];
      if (!matchesState(row, chosen)) {
        continue;
      }
      if (needle && !matchesText(row, needle)) {
        continue;
      }
      if (hide && isHealthy(row)) {
        continue;
      }
      shown.push(row);
    }
    return shown;
  }

  function filterCount(shown, total) {
    return String(shown) + " of " + String(total) + " shown";
  }

  globalThis.filterContainers = filterContainers;
  globalThis.filterCount = filterCount;
})();
