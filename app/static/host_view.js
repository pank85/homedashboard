(function () {
  // Host panel refresh. Reads the presented payload (the *_human keys) and the
  // same containers/agents payloads app.js already holds. Server partial
  // partials/host.html renders the same lines, so first paint and the tick agree.

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

  function levelClass(level) {
    if (level === "ok" || level === "warn" || level === "crit") {
      return "level-" + level;
    }
    return "";
  }

  function value(value) {
    return value === undefined || value === null ? "" : value;
  }

  function containerSentence(containers) {
    if (!containers || !containers.available) {
      return "containers unavailable";
    }
    var rows = Array.isArray(containers.containers) ? containers.containers : [];
    var running = 0;
    rows.forEach(function (row) {
      row = row || {};
      if (row.state === "running") {
        running += 1;
      }
    });
    return running + " running containers";
  }

  function agentSentence(agents) {
    if (!agents || !Array.isArray(agents.agents)) {
      return "agents unavailable";
    }
    var seen = {};
    var running = {};
    agents.agents.forEach(function (row) {
      row = row || {};
      var identity = row.kind ? row.kind : row.label;
      seen[identity] = true;
      if (row.status === "working" || row.source === "proc") {
        running[identity] = true;
      }
    });
    var total = Object.keys(seen).length;
    var live = Object.keys(running).length;
    return total + " CLI AI agents / " + live + " running";
  }

  globalThis.renderHostView = function (hostBody, host, containers, agents) {
    if (!hostBody) {
      return;
    }
    clear(hostBody);
    host = host || {};
    add(hostBody, "p", value(host.view));
    if (!host.available && host.reason) {
      add(hostBody, "p", "unavailable: " + host.reason);
    }
    var cpu = host.cpu || {};
    if (cpu.available) {
      add(
        hostBody,
        "p",
        "CPU " + value(cpu.percent_human) + " · " + value(cpu.cores) + " cores · load " + value(cpu.loadavg_human),
        levelClass(cpu.level)
      );
    } else {
      add(hostBody, "p", "unavailable: " + value(cpu.reason));
    }
    var memory = host.memory || {};
    if (memory.available) {
      add(
        hostBody,
        "p",
        "RAM " + value(memory.used_human) + " / " + value(memory.total_human) + " · " + value(memory.percent_human),
        levelClass(memory.level)
      );
    } else {
      add(hostBody, "p", "unavailable: " + value(memory.reason));
    }
    (host.disks || []).forEach(function (disk) {
      disk = disk || {};
      if (disk.available) {
        add(
          hostBody,
          "p",
          "disk " + value(disk.path) + " · " + value(disk.percent_human) + " · " + value(disk.used_human) + " / " + value(disk.total_human),
          levelClass(disk.level)
        );
      } else {
        add(hostBody, "p", "unavailable: " + value(disk.reason));
      }
    });
    var summary = document.createElement("div");
    summary.id = "host-summary";
    add(summary, "p", containerSentence(containers));
    add(summary, "p", agentSentence(agents));
    hostBody.appendChild(summary);
  };
})();
