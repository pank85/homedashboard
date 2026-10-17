(function () {
  var body = document.body;
  if (!body) {
    return;
  }
  var raw = body.getAttribute("data-refresh");
  if (raw === null || raw === "" || raw === "0") {
    return;
  }
  var seconds = Number(raw);
  if (!Number.isFinite(seconds) || seconds <= 0) {
    return;
  }

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

  function renderContainers(data) {
    var root = document.getElementById("containers-body");
    if (!root) {
      return;
    }
    clear(root);
    data = data || {};
    if (!data.available) {
      add(root, "p", "unavailable: " + (data.reason || ""));
      return;
    }
    var rows = data.containers || [];
    if (!rows.length) {
      add(root, "p", "No containers.");
      return;
    }
    rows.forEach(function (row) {
      var card = add(root, "article");
      add(card, "h3", row.name || "");
      add(card, "p", row.image || "");
      var state = row.state || "";
      if (row.health) {
        state = state + " · " + row.health;
      }
      add(card, "p", state);
      add(card, "p", "uptime " + (row.uptime_seconds == null ? "" : row.uptime_seconds));
      add(card, "p", "restarts " + (row.restart_count == null ? "" : row.restart_count));
      add(card, "p", "cpu " + (row.cpu_percent == null ? "" : row.cpu_percent));
      add(card, "p", "memory " + (row.memory_used_bytes == null ? "" : row.memory_used_bytes) + " / " + (row.memory_limit_bytes == null ? "" : row.memory_limit_bytes));
    });
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
    (data.agents || []).forEach(function (agent) {
      var card = add(root, "article");
      add(card, "h3", agent.label || "");
      add(card, "p", agent.status || "");
      add(card, "p", agent.cwd || "");
      add(card, "p", agent.source || "");
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
        renderAgents(data.agents);
        renderHost(data.host);
      })
      .catch(function () {
        return null;
      });
  }

  setInterval(tick, seconds * 1000);
})();
