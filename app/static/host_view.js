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

  function finiteNumber(number) {
    return typeof number === "number" && isFinite(number);
  }

  function clampPercent(number) {
    if (number < 0) {
      return 0;
    }
    if (number > 100) {
      return 100;
    }
    return number;
  }

  function addMeter(parent, sentence, percent, level) {
    var track = add(parent, "div", null, "progress");
    track.setAttribute("role", "img");
    track.setAttribute("aria-label", sentence);
    var named = levelClass(level);
    var fill = add(track, "span", null, named ? "progress-bar " + named : "progress-bar");
    if (finiteNumber(percent)) {
      fill.style.width = clampPercent(percent) + "%";
    }
    return track;
  }

  function addStat(parent, sentence, percent, level) {
    var card = add(parent, "article", null, "card card-sm");
    var named = levelClass(level);
    if (named) {
      add(card, "div", null, "card-status-top " + named);
    }
    add(card, "p", sentence, named);
    addMeter(card, sentence, percent, level);
    return card;
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
    add(hostBody, "p", value(host.view), "text-secondary");
    if (!host.available && host.reason) {
      add(hostBody, "p", "unavailable: " + host.reason);
    }
    var cards = add(hostBody, "div", null, "row-cards");
    var cpu = host.cpu || {};
    if (cpu.available) {
      addStat(
        cards,
        "CPU " + value(cpu.percent_human) + " · " + value(cpu.cores) + " cores · load " + value(cpu.loadavg_human),
        cpu.percent,
        cpu.level
      );
    } else {
      add(cards, "p", "unavailable: " + value(cpu.reason));
    }
    var memory = host.memory || {};
    if (memory.available) {
      addStat(
        cards,
        "RAM " + value(memory.used_human) + " / " + value(memory.total_human) + " · " + value(memory.percent_human),
        memory.percent,
        memory.level
      );
    } else {
      add(cards, "p", "unavailable: " + value(memory.reason));
    }
    var table = add(hostBody, "table", null, "table table-vcenter card-table");
    (host.disks || []).forEach(function (disk) {
      disk = disk || {};
      var row = add(table, "tr");
      if (disk.available) {
        var sentence = "disk " + value(disk.path) + " · " + value(disk.percent_human) + " · " + value(disk.used_human) + " / " + value(disk.total_human);
        add(row, "td", sentence, levelClass(disk.level));
        addMeter(add(row, "td"), sentence, disk.percent, disk.level);
      } else {
        add(row, "td", "unavailable: " + value(disk.reason));
      }
    });
    var summary = document.createElement("div");
    summary.id = "host-summary";
    add(summary, "p", containerSentence(containers));
    add(summary, "p", agentSentence(agents));
    hostBody.appendChild(summary);
  };
})();
