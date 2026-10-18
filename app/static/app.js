(function () {
  var body = document.body;
  if (!body) {
    return;
  }

  var lastContainers = null;
  var viewQuery = window.matchMedia("(max-width: 767px)");

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

  function pageView() {
    var mobile = viewQuery.matches;
    body.setAttribute("data-view", mobile ? "mobile" : "desktop");
    return mobile ? "mobile" : "desktop";
  }

  function containerSummary(rows) {
    var running = 0;
    var stopped = 0;
    var unhealthy = 0;
    rows.forEach(function (row) {
      row = row || {};
      if (row.state === "running") {
        running += 1;
      } else {
        stopped += 1;
      }
      if (row.health === "unhealthy" || row.state === "restarting") {
        unhealthy += 1;
      }
    });
    return running + " running · " + stopped + " stopped · " + unhealthy + " unhealthy";
  }

  function renderContainers(data) {
    var root = document.getElementById("containers-body");
    if (!root) {
      return;
    }
    data = data || {};
    lastContainers = data;
    var rows = data.containers || [];
    var summary = document.getElementById("container-summary");
    if (summary) {
      summary.textContent = containerSummary(rows);
    }
    var textNode = document.getElementById("container-filter-text");
    var stateNode = document.getElementById("container-filter-state");
    var hideNode = document.getElementById("container-filter-hide-healthy");
    var sortNode = document.getElementById("container-filter-sort");
    var text = textNode ? textNode.value : "";
    var state = stateNode && stateNode.value ? stateNode.value : "All";
    var hideHealthy = !!(hideNode && hideNode.checked);
    var mode = sortNode && sortNode.value ? sortNode.value : "status";
    var shown = globalThis.filterContainers(rows, text, state, hideHealthy);
    var sorted = shown;
    if (typeof globalThis.sortContainers === "function") {
      sorted = globalThis.sortContainers(shown, mode);
    }
    var count = document.getElementById("container-filter-count");
    if (count) {
      count.textContent = globalThis.filterCount(data.available ? shown.length : 0, rows.length);
    }
    if (!data.available) {
      clear(root);
      add(root, "p", "unavailable: " + (data.reason || ""));
      return;
    }
    if (typeof globalThis.renderContainersView === "function") {
      globalThis.renderContainersView(root, sorted, pageView());
      return;
    }
    clear(root);
    if (!sorted.length) {
      add(root, "p", rows.length ? "No containers match." : "No containers.");
    }
  }

  function renderHerdr(data) {
    var root = document.getElementById("herdr-block");
    if (!root) {
      return;
    }
    if (typeof globalThis.renderHerdrBlock === "function") {
      globalThis.renderHerdrBlock(root, data);
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
    if (typeof globalThis.renderAgentsBody === "function") {
      globalThis.renderAgentsBody(root, data, pageView());
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
        if (typeof globalThis.renderGitView === "function") {
          globalThis.renderGitView(document.getElementById("git-body"), data.git, pageView());
        }
        if (typeof globalThis.renderHostView === "function") {
          globalThis.renderHostView(document.getElementById("host-body"), data.host, data.containers, data.agents);
        } else {
          renderHost(data.host);
        }
      })
      .catch(function () {
        return null;
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
  var filterSort = document.getElementById("container-filter-sort");
  if (filterSort) {
    filterSort.addEventListener("change", onFilterChange);
  }

  if (typeof globalThis.initViewNav === "function") {
    globalThis.initViewNav();
  }

  pageView();

  if (viewQuery.addEventListener) {
    viewQuery.addEventListener("change", function () {
      pageView();
      tick();
    });
  } else if (viewQuery.addListener) {
    viewQuery.addListener(function () {
      pageView();
      tick();
    });
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
