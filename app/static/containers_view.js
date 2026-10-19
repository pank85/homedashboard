(function () {
  // groupContainers, when present, returns [{project, rows}]. Other is last.
  // Caller passes already sorted rows. This file does not read filter inputs.

  function add(parent, tag, text, className) {
    var node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (text !== undefined && text !== null) {
      node.textContent = String(text);
    }
    parent.appendChild(node);
    return node;
  }

  function clear(node) {
    while (node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

  function human(value) {
    if (value === undefined || value === null || value === "" || value === "None" || value === "undefined") {
      return "unknown";
    }
    return String(value);
  }

  function healthWord(value) {
    if (value === undefined || value === null || value === "" || value === "None" || value === "undefined") {
      return "none";
    }
    return String(value);
  }

  function finiteNumber(value) {
    return typeof value === "number" && isFinite(value);
  }

  function clampPercent(value) {
    if (!finiteNumber(value)) {
      return 0;
    }
    if (value < 0) {
      return 0;
    }
    if (value > 100) {
      return 100;
    }
    return value;
  }

  function casefold(value) {
    return String(value).replace(/\u00df/g, "ss").replace(/\u1e9e/g, "ss").replace(/\u0130/g, "i\u0307").toLowerCase();
  }

  function projectName(row) {
    if (row && typeof row.compose_project === "string" && row.compose_project !== "") {
      return row.compose_project;
    }
    return "Other";
  }

  function groupRows(rows) {
    var buckets = Object.create(null);
    var seen = [];
    var index;
    for (index = 0; index < rows.length; index += 1) {
      var row = rows[index] && typeof rows[index] === "object" ? rows[index] : {};
      var project = projectName(row);
      if (!Object.prototype.hasOwnProperty.call(buckets, project)) {
        buckets[project] = [];
        seen.push(project);
      }
      buckets[project].push(row);
    }
    var named = [];
    var hasOther = false;
    for (index = 0; index < seen.length; index += 1) {
      if (seen[index] === "Other") {
        hasOther = true;
      } else {
        named.push(seen[index]);
      }
    }
    named.sort(function (left, right) {
      var foldedLeft = casefold(left);
      var foldedRight = casefold(right);
      if (foldedLeft < foldedRight) {
        return -1;
      }
      if (foldedLeft > foldedRight) {
        return 1;
      }
      return 0;
    });
    if (hasOther) {
      named.push("Other");
    }
    var groups = [];
    for (index = 0; index < named.length; index += 1) {
      groups.push({ project: named[index], rows: buckets[named[index]] });
    }
    return groups;
  }

  function groupedRows(rows) {
    if (typeof globalThis.groupContainers === "function") {
      var grouped = globalThis.groupContainers(rows);
      if (Array.isArray(grouped)) {
        return grouped;
      }
    }
    return groupRows(rows);
  }

  function cardTitle(row) {
    if (typeof row.name === "string" && row.name !== "") {
      return row.name;
    }
    return "unknown";
  }

  function subtitle(row) {
    if (typeof row.compose_service === "string" && row.compose_service !== "") {
      return row.compose_service;
    }
    if (typeof row.image_short === "string" && row.image_short !== "") {
      return row.image_short;
    }
    if (typeof row.image === "string" && row.image !== "") {
      return row.image;
    }
    return "";
  }

  function imageText(row) {
    if (typeof row.image_short === "string" && row.image_short !== "") {
      return row.image_short;
    }
    if (typeof row.image === "string" && row.image !== "") {
      return row.image;
    }
    return "unknown";
  }

  function stateWord(row) {
    if (row.state_label !== undefined && row.state_label !== null && row.state_label !== "") {
      return human(row.state_label);
    }
    return human(row.state);
  }

  function memoryWidth(row) {
    if (finiteNumber(row.memory_percent)) {
      return clampPercent(row.memory_percent);
    }
    if (finiteNumber(row.memory_used_bytes) && finiteNumber(row.memory_limit_bytes) && row.memory_limit_bytes > 0) {
      return clampPercent(row.memory_used_bytes / row.memory_limit_bytes * 100);
    }
    return 0;
  }

  function addMeter(parent, label, width) {
    var meter = add(parent, "div", null, "meter progress");
    meter.setAttribute("role", "img");
    meter.setAttribute("aria-label", label);
    var fill = add(meter, "span", null, "meter-fill progress-bar");
    fill.style.width = clampPercent(width) + "%";
  }

  function renderDesktopCard(parent, row) {
    var state = stateWord(row);
    var health = healthWord(row.health_label !== undefined ? row.health_label : row.health);
    var cpuLabel = human(row.cpu_percent_human);
    var used = human(row.memory_used_human);
    var limit = human(row.memory_limit_human);
    var card = add(parent, "article", null, "container-card");
    add(card, "div", null, "card-status-top state-" + state);
    var body = add(card, "div", null, "card-body");
    add(body, "h3", cardTitle(row));
    var sub = subtitle(row);
    if (sub) {
      add(body, "p", sub, "container-subtitle");
    }
    var badges = add(body, "p");
    add(badges, "span", state, "badge badge-outline state-" + state);
    badges.appendChild(document.createTextNode(" "));
    add(badges, "span", health, "badge badge-outline health-" + health);
    badges.appendChild(document.createTextNode(" "));
    add(badges, "span", null, "status-dot state-" + state);
    add(body, "p", "uptime " + human(row.uptime_human));
    add(body, "p", "restarts " + human(row.restart_count));
    add(body, "p", "cpu " + cpuLabel);
    addMeter(body, "cpu " + cpuLabel, row.cpu_percent);
    add(body, "p", "memory " + used + " / " + limit);
    addMeter(body, "memory " + used + " / " + limit, memoryWidth(row));
    var details = add(body, "details");
    add(details, "summary", "Details");
    add(details, "p", imageText(row));
    add(details, "p", "id " + human(row.id_short));
  }

  function renderMobileCard(parent, row) {
    var state = stateWord(row);
    var card = add(parent, "article", null, "container-card");
    var line = add(card, "div", null, "container-scan");
    add(line, "h3", cardTitle(row));
    add(line, "span", state, "badge badge-outline state-" + state);
    add(line, "span", null, "status-dot state-" + state);
    add(line, "span", "cpu " + human(row.cpu_percent_human));
    add(line, "span", "memory " + human(row.memory_used_human) + " / " + human(row.memory_limit_human));
    var sub = subtitle(row);
    if (sub) {
      add(card, "p", sub, "container-subtitle");
    }
    var details = add(card, "details");
    add(details, "summary", "Details");
    add(details, "p", imageText(row));
    add(details, "p", "uptime " + human(row.uptime_human));
    add(details, "p", "restarts " + human(row.restart_count));
    add(details, "p", "id " + human(row.id_short));
  }

  function renderGroup(body, group, mobile) {
    group = group || {};
    var project = typeof group.project === "string" && group.project !== "" ? group.project : "Other";
    var groupRowsList = Array.isArray(group.rows) ? group.rows : [];
    var block = add(body, "div", null, "project-group");
    add(block, "h3", project, "project-heading");
    var grid = add(block, "div", null, "container-grid");
    var index;
    for (index = 0; index < groupRowsList.length; index += 1) {
      var row = groupRowsList[index] && typeof groupRowsList[index] === "object" ? groupRowsList[index] : {};
      if (mobile) {
        renderMobileCard(grid, row);
      } else {
        renderDesktopCard(grid, row);
      }
    }
  }

  function containersBody(root) {
    if (root && root.id === "containers-body") {
      return root;
    }
    if (root && typeof root.querySelector === "function") {
      var nested = root.querySelector("#containers-body");
      if (nested) {
        return nested;
      }
    }
    if (typeof document !== "undefined" && typeof document.getElementById === "function") {
      return document.getElementById("containers-body");
    }
    return null;
  }

  function renderContainersView(root, rows, view) {
    var body = containersBody(root);
    if (!body) {
      return;
    }
    clear(body);
    var list = Array.isArray(rows) ? rows : [];
    if (!list.length) {
      var empty = add(body, "div", null, "empty");
      add(empty, "p", "No containers.", "empty-title");
      return;
    }
    var groups = groupedRows(list);
    var mobile = view === "mobile";
    var index;
    for (index = 0; index < groups.length; index += 1) {
      renderGroup(body, groups[index], mobile);
    }
  }

  globalThis.renderContainersView = renderContainersView;
})();
