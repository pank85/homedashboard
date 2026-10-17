(function () {
  var body = document.body;
  if (!body) {
    return;
  }

  var lastContainers = null;

  function clear(node) {
    while (node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

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

  function levelClass(level) {
    if (level === "ok" || level === "warn" || level === "crit") {
      return "level-" + level;
    }
    return "";
  }

  function human(value) {
    if (value === undefined || value === null || value === "" || value === "None" || value === "undefined") {
      return "unknown";
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

  function cardTitle(row) {
    if (typeof row.compose_service === "string" && row.compose_service !== "") {
      return row.compose_service;
    }
    if (typeof row.name === "string" && row.name !== "") {
      return row.name;
    }
    return "unknown";
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
    var meter = add(parent, "div", null, "meter");
    meter.setAttribute("role", "img");
    meter.setAttribute("aria-label", label);
    var fill = add(meter, "span", null, "meter-fill");
    fill.style.width = clampPercent(width) + "%";
  }

  function renderContainerCard(grid, row) {
    var stateWord = human(row.state_label);
    var healthWord = row.health_label === undefined || row.health_label === null || row.health_label === "" ? "none" : human(row.health_label);
    var cpuLabel = human(row.cpu_percent_human);
    var used = human(row.memory_used_human);
    var limit = human(row.memory_limit_human);
    var card = add(grid, "article", null, "container-card");
    add(card, "h3", cardTitle(row));
    add(card, "p", "id " + human(row.id_short));
    add(card, "p", imageText(row));
    var badges = add(card, "p");
    add(badges, "span", stateWord, "badge state-" + stateWord);
    badges.appendChild(document.createTextNode(" "));
    add(badges, "span", healthWord, "badge health-" + healthWord);
    add(card, "p", "uptime " + human(row.uptime_human));
    add(card, "p", "restarts " + human(row.restart_count));
    add(card, "p", "cpu " + cpuLabel);
    addMeter(card, "cpu " + cpuLabel, row.cpu_percent);
    add(card, "p", "memory " + used + " / " + limit);
    addMeter(card, "memory " + used + " / " + limit, memoryWidth(row));
  }

  function renderContainers(data) {
    var root = document.getElementById("containers-body");
    if (!root) {
      return;
    }
    clear(root);
    data = data || {};
    lastContainers = data;
    var rows = data.containers || [];
    var textNode = document.getElementById("container-filter-text");
    var stateNode = document.getElementById("container-filter-state");
    var hideNode = document.getElementById("container-filter-hide-healthy");
    var text = textNode ? textNode.value : "";
    var state = stateNode && stateNode.value ? stateNode.value : "All";
    var hideHealthy = !!(hideNode && hideNode.checked);
    var shown = globalThis.filterContainers(rows, text, state, hideHealthy);
    var count = document.getElementById("container-filter-count");
    if (count) {
      count.textContent = globalThis.filterCount(data.available ? shown.length : 0, rows.length);
    }
    if (!data.available) {
      add(root, "p", "unavailable: " + (data.reason || ""));
      return;
    }
    if (!shown.length) {
      add(root, "p", rows.length ? "No containers match." : "No containers.");
      return;
    }
    var grid = add(root, "div", null, "container-grid");
    shown.forEach(function (row) {
      renderContainerCard(grid, row || {});
    });
  }

  function renderHerdr(data) {
    var root = document.getElementById("herdr-block");
    if (!root) {
      return;
    }
    clear(root);
    data = data || {};
    var block = data.herdr && typeof data.herdr === "object" ? data.herdr : {};
    var reachable = !!block.reachable;
    add(root, "p", "reachable " + (reachable ? "true" : "false"));
    add(root, "p", "version " + human(block.version));
    add(root, "p", "session " + human(block.session));
    add(root, "p", "workspaces " + (finiteNumber(block.workspace_count) ? String(block.workspace_count) : "0"));
    add(root, "p", "tabs " + (finiteNumber(block.tab_count) ? String(block.tab_count) : "0"));
    add(root, "p", "agents " + (finiteNumber(block.agent_count) ? String(block.agent_count) : "0"));
    if (block.reason) {
      add(root, "p", String(block.reason));
    }
    if (!reachable) {
      add(root, "p", "unavailable: " + (block.reason ? String(block.reason) : "herdr unavailable"));
    }
  }

  function groupTitle(agent) {
    if (typeof agent.workspace_label === "string" && agent.workspace_label !== "") {
      return agent.workspace_label;
    }
    if (agent.source === "proc") {
      return "proc";
    }
    return "unknown";
  }

  function elapsedWord(agent) {
    if (agent.elapsed_source === "herdr") {
      return human(agent.elapsed_human);
    }
    return "unknown";
  }

  function renderAgents(data) {
    var root = document.getElementById("agents-body");
    if (!root) {
      return;
    }
    clear(root);
    data = data || {};
    (data.sources || []).forEach(function (source) {
      var line = "source " + (source.name || "") + " used " + (source.used ? "true" : "false") + " refreshed_at " + (source.refreshed_at == null ? "" : source.refreshed_at);
      if (source.error) {
        line += " error " + source.error;
      }
      add(root, "p", line);
    });
    if (data.note) {
      add(root, "p", data.note);
    }
    var titles = [];
    (data.agents || []).forEach(function (agent) {
      var title = groupTitle(agent || {});
      if (titles.indexOf(title) === -1) {
        titles.push(title);
      }
    });
    titles.forEach(function (title) {
      var group = add(root, "div", null, "workspace-group");
      add(group, "h3", title);
      (data.agents || []).forEach(function (agent) {
        agent = agent || {};
        if (groupTitle(agent) !== title) {
          return;
        }
        var card = add(group, "article");
        add(card, "p", "kind " + human(agent.kind));
        add(card, "p", "workspace " + (agent.workspace_label ? agent.workspace_label : title));
        add(card, "p", "tab " + human(agent.tab_label));
        add(card, "p", "status " + human(agent.status));
        add(card, "p", "cwd " + human(agent.cwd));
        add(card, "p", "elapsed " + elapsedWord(agent));
      });
    });
  }

  function renderHost(data) {
    var root = document.getElementById("host-body");
    if (!root) {
      return;
    }
    clear(root);
    data = data || {};
    add(root, "p", data.view || "");
    if (!data.available && data.reason) {
      add(root, "p", "unavailable: " + data.reason);
    }
    var cpu = data.cpu || {};
    if (cpu.available) {
      add(root, "p", "CPU " + (cpu.percent == null ? "" : cpu.percent) + " cores " + (cpu.cores == null ? "" : cpu.cores) + " load " + (cpu.loadavg == null ? "" : cpu.loadavg), levelClass(cpu.level));
    } else {
      add(root, "p", "unavailable: " + (cpu.reason || ""));
    }
    var memory = data.memory || {};
    if (memory.available) {
      add(root, "p", "RAM " + (memory.used_bytes == null ? "" : memory.used_bytes) + " / " + (memory.total_bytes == null ? "" : memory.total_bytes) + " " + (memory.percent == null ? "" : memory.percent), levelClass(memory.level));
    } else {
      add(root, "p", "unavailable: " + (memory.reason || ""));
    }
    (data.disks || []).forEach(function (disk) {
      if (disk.available) {
        add(root, "p", "disk " + (disk.path || "") + " " + (disk.percent == null ? "" : disk.percent), levelClass(disk.level));
      } else {
        add(root, "p", "unavailable: " + (disk.reason || ""));
      }
    });
  }

  function mutationsEnabled() {
    var form = document.getElementById("new-session-form");
    return !!(form && form.getAttribute("data-mutations-enabled") === "true");
  }

  function renderSession(root, row) {
    var command = typeof row.attach_command === "string" ? row.attach_command : "";
    var card = add(root, "article", null, "session-card");
    add(card, "p", "label " + human(row.label));
    add(card, "p", "kind " + human(row.agent_kind));
    add(card, "p", "workspace " + human(row.workspace_id));
    add(card, "p", "status " + human(row.status));
    add(card, "p", "cwd " + human(row.cwd));
    add(card, "p", "created " + human(row.created_relative));
    add(card, "p", "updated " + human(row.updated_relative));
    var link = add(card, "a", "Open Herdr Web");
    link.href = "/herdr/";
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    var input = add(card, "input", null, "attach-command");
    input.type = "text";
    input.readOnly = true;
    input.value = command;
    var copy = add(card, "button", "Copy", "copy-attach");
    copy.type = "button";
    copy.setAttribute("data-attach-command", command);
    var archive = add(card, "button", "Archive", "archive-session");
    archive.type = "button";
    archive.setAttribute("data-session-id", row.id || "");
    if (!mutationsEnabled()) {
      archive.disabled = true;
    }
  }

  function renderSessions(data) {
    data = data || {};
    var note = document.getElementById("sessions-unavailable");
    if (note) {
      note.textContent = data.available ? "" : "unavailable: " + (data.reason || "");
    }
    var root = document.getElementById("sessions-body");
    if (!root) {
      return;
    }
    clear(root);
    (data.sessions || []).forEach(function (row) {
      renderSession(root, row || {});
    });
  }

  function tick() {
    fetch("/api/metrics", { headers: { Accept: "application/json" } })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("metrics unavailable");
        }
        return response.json();
      })
      .then(function (data) {
        var updated = document.getElementById("last-updated");
        if (updated) {
          updated.textContent = data.generated_at || "";
        }
        renderContainers(data.containers);
        renderHerdr(data.agents);
        renderAgents(data.agents);
        renderHost(data.host);
        renderSessions(data.sessions);
      })
      .catch(function () {
        return null;
      });
  }

  function showActionReason(text) {
    var node = document.getElementById("session-action-reason");
    if (node) {
      node.textContent = text || "";
    }
  }

  function chatToken() {
    var input = document.getElementById("session-token");
    if (input && input.value) {
      return input.value;
    }
    try {
      return localStorage.getItem("homedashboard.chatApiToken") || "";
    } catch (err) {
      return "";
    }
  }

  function authHeaders(token) {
    return {
      Accept: "application/json",
      "Content-Type": "application/json",
      Authorization: "Bearer " + token
    };
  }

  function handleMutation(response) {
    return response.json().then(function (payload) {
      return { ok: response.ok, status: response.status, body: payload || {} };
    }, function () {
      return { ok: response.ok, status: response.status, body: {} };
    }).then(function (result) {
      if (result.status === 400 || result.status === 401 || result.status === 403 || result.status === 502 || result.status === 503) {
        var reason = result.body && typeof result.body.reason === "string" ? result.body.reason : "";
        showActionReason(reason);
        return result;
      }
      if (result.ok) {
        showActionReason("");
        tick();
      }
      return result;
    });
  }

  function onCreate(event) {
    event.preventDefault();
    var tokenInput = document.getElementById("session-token");
    var typed = tokenInput && tokenInput.value ? tokenInput.value : "";
    if (typed) {
      try {
        localStorage.setItem("homedashboard.chatApiToken", typed);
      } catch (err) {
        /* keep the field value for the request if storage is blocked */
      }
    }
    var token = chatToken();
    var kind = document.getElementById("session-kind");
    var cwd = document.getElementById("session-cwd");
    var label = document.getElementById("session-label");
    fetch("/api/sessions", {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify({
        kind: kind ? kind.value : "",
        cwd: cwd ? cwd.value : "",
        label: label ? label.value : ""
      })
    }).then(handleMutation).catch(function () {
      showActionReason("request failed");
    });
  }

  function selectAttach(input) {
    if (!input) {
      return;
    }
    input.focus();
    input.select();
  }

  function copyAttach(button) {
    var command = button.getAttribute("data-attach-command") || "";
    var article = button.closest("article");
    var input = article ? article.querySelector(".attach-command") : null;
    if (!command && input) {
      command = input.value;
    }
    if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
      navigator.clipboard.writeText(command).then(function () {
        return null;
      }, function () {
        selectAttach(input);
      });
      return;
    }
    selectAttach(input);
  }

  function onSessionClick(event) {
    var target = event.target;
    if (!target || !target.closest) {
      return;
    }
    var copy = target.closest(".copy-attach");
    if (copy) {
      copyAttach(copy);
      return;
    }
    var archive = target.closest(".archive-session");
    if (!archive || archive.disabled) {
      return;
    }
    var id = archive.getAttribute("data-session-id") || "";
    if (!id) {
      return;
    }
    fetch("/api/sessions/" + encodeURIComponent(id) + "/archive", {
      method: "POST",
      headers: authHeaders(chatToken()),
      body: "{}"
    }).then(handleMutation).catch(function () {
      showActionReason("request failed");
    });
  }

  var filterText = document.getElementById("container-filter-text");
  var filterState = document.getElementById("container-filter-state");
  var filterHide = document.getElementById("container-filter-hide-healthy");
  function onFilterChange() {
    if (lastContainers) {
      renderContainers(lastContainers);
    }
  }
  if (filterText) {
    filterText.addEventListener("input", onFilterChange);
  }
  if (filterState) {
    filterState.addEventListener("change", onFilterChange);
  }
  if (filterHide) {
    filterHide.addEventListener("change", onFilterChange);
  }

  var form = document.getElementById("new-session-form");
  if (form) {
    form.addEventListener("submit", onCreate);
  }
  var sessionsPanel = document.getElementById("panel-sessions");
  if (sessionsPanel) {
    sessionsPanel.addEventListener("click", onSessionClick);
  }

  var raw = body.getAttribute("data-refresh");
  tick();
  if (raw === null || raw === "" || raw === "0") {
    return;
  }
  var seconds = Number(raw);
  if (!Number.isFinite(seconds) || seconds <= 0) {
    return;
  }
  setInterval(tick, seconds * 1000);
})();
