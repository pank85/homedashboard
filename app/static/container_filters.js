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

  function rowName(row) {
    if (!row || typeof row !== "object") {
      return "";
    }
    return typeof row.name === "string" ? row.name : "";
  }

  function isNumber(value) {
    return typeof value === "number" && isFinite(value);
  }

  function compareStrings(a, b) {
    if (a < b) {
      return -1;
    }
    if (a > b) {
      return 1;
    }
    return 0;
  }

  function statusRank(row) {
    if (!row || typeof row !== "object") {
      return 2;
    }
    if (row.state === "restarting" || row.health === "unhealthy") {
      return 0;
    }
    if (row.state === "running") {
      return 1;
    }
    return 2;
  }

  function compareStatus(a, b) {
    var rankA = statusRank(a);
    var rankB = statusRank(b);
    if (rankA !== rankB) {
      return rankA - rankB;
    }
    return compareStrings(rowName(a), rowName(b));
  }

  function compareNames(a, b) {
    var nameA = rowName(a).toLowerCase();
    var nameB = rowName(b).toLowerCase();
    var emptyA = nameA === "";
    var emptyB = nameB === "";
    if (emptyA !== emptyB) {
      return emptyA ? 1 : -1;
    }
    return compareStrings(nameA, nameB);
  }

  function cpuValue(row) {
    var value = row && typeof row === "object" ? row.cpu_percent : undefined;
    return isNumber(value) ? value : null;
  }

  function memoryValue(row) {
    var percent = row && typeof row === "object" ? row.memory_percent : undefined;
    if (isNumber(percent)) {
      return percent;
    }
    var used = row && typeof row === "object" ? row.memory_used_bytes : undefined;
    var limit = row && typeof row === "object" ? row.memory_limit_bytes : undefined;
    if (isNumber(used) && isNumber(limit) && limit > 0) {
      return used / limit * 100;
    }
    return null;
  }

  function compareDescending(valueOf) {
    return function (a, b) {
      var valueA = valueOf(a);
      var valueB = valueOf(b);
      var missingA = valueA === null;
      var missingB = valueB === null;
      if (missingA !== missingB) {
        return missingA ? 1 : -1;
      }
      if (!missingA && valueA !== valueB) {
        return valueA > valueB ? -1 : 1;
      }
      return compareStrings(rowName(a).toLowerCase(), rowName(b).toLowerCase());
    };
  }

  var COMPARATORS = {
    status: compareStatus,
    name: compareNames,
    cpu: compareDescending(cpuValue),
    memory: compareDescending(memoryValue),
  };

  function sortContainers(rows, mode) {
    var list = Array.isArray(rows) ? rows.slice() : [];
    var compare = COMPARATORS[mode] || compareStatus;
    return list.sort(compare);
  }

  function projectName(row) {
    var project = row && typeof row === "object" ? row.compose_project : undefined;
    return typeof project === "string" && project !== "" ? project : "Other";
  }

  function groupContainers(rows) {
    var list = Array.isArray(rows) ? rows : [];
    var groups = Object.create(null);
    var order = [];
    var index;
    for (index = 0; index < list.length; index += 1) {
      var name = projectName(list[index]);
      if (!(name in groups)) {
        groups[name] = [];
        order.push(name);
      }
      groups[name].push(list[index]);
    }
    order.sort(function (a, b) {
      var otherA = a === "Other" ? 1 : 0;
      var otherB = b === "Other" ? 1 : 0;
      if (otherA !== otherB) {
        return otherA - otherB;
      }
      return compareStrings(a.toLowerCase(), b.toLowerCase());
    });
    return order.map(function (name) {
      return { project: name, rows: groups[name] };
    });
  }

  globalThis.filterContainers = filterContainers;
  globalThis.filterCount = filterCount;
  globalThis.sortContainers = sortContainers;
  globalThis.groupContainers = groupContainers;
})();
