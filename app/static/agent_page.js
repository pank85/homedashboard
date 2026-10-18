(function () {
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

  function human(value) {
    if (value === undefined || value === null || value === "" || value === "None" || value === "undefined") {
      return "unknown";
    }
    return String(value);
  }

  function keyOf(agent) {
    agent = agent && typeof agent === "object" ? agent : {};
    var kind = typeof agent.kind === "string" && agent.kind !== "" ? agent.kind : agent.label;
    if (typeof kind !== "string" || kind === "") {
      return "";
    }
    var key = kind.toLowerCase();
    if (!/^[a-z][a-z0-9-]{0,31}$/.test(key)) {
      return "";
    }
    return key;
  }

  function list(payload, name) {
    payload = payload && typeof payload === "object" ? payload : {};
    return Array.isArray(payload[name]) ? payload[name] : [];
  }

  function rowsForKey(payload, key) {
    if (!key) {
      return [];
    }
    return list(payload, "agents").filter(function (row) {
      return row && typeof row === "object" && keyOf(row) === key;
    });
  }

  function primaryRow(rows) {
    if (!rows.length) {
      return {};
    }
    for (var index = 0; index < rows.length; index += 1) {
      if (rows[index] && rows[index].source === "herdr") {
        return rows[index];
      }
    }
    return rows[0];
  }

  function runningSignal(rows, sessions) {
    var liveSession = sessions.some(function (row) {
      return row && row.status === "running";
    });
    if (liveSession) {
      return "session";
    }
    var liveAgent = rows.some(function (row) {
      return row && (row.status === "working" || row.source === "proc");
    });
    if (liveAgent) {
      return "agent";
    }
    return "";
  }

  function render(page, agentsPayload) {
    var key = page ? page.getAttribute("data-agent-key") : "";
    var rows = rowsForKey(agentsPayload, key);
    var primary = primaryRow(rows);
    var heading = document.getElementById("agent-heading");
    if (heading) {
      heading.textContent = rows.length
        ? human(primary.kind || primary.label)
        : "Agent not found";
    }
    var status = document.getElementById("agent-status");
    if (status) {
      status.textContent = human(primary.status);
    }
    var source = document.getElementById("agent-source");
    if (source) {
      source.textContent = human(primary.source);
    }
    var cwd = document.getElementById("agent-cwd");
    if (cwd) {
      cwd.textContent = "cwd " + human(primary.cwd) + " · source " + human(primary.source);
    }
    var running = document.getElementById("agent-running");
    if (running) {
      var signal = runningSignal(rows, []);
      running.textContent = signal === "session" ? "running" : signal === "agent" ? "live" : "";
    }
  }

  function readJson(path) {
    return fetch(path, { headers: { Accept: "application/json" } }).then(
      function (response) {
        return response.ok ? response.json() : {};
      },
      function () {
        return {};
      }
    );
  }

  function refresh() {
    var page = document.getElementById("agent-page");
    if (!page) {
      return;
    }
    readJson("/api/agents").then(function (agentsPayload) {
      render(page, agentsPayload);
    });
  }

  function start() {
    refresh();
    var body = document.body;
    var raw = body ? body.getAttribute("data-refresh") : "";
    var seconds = Number(raw);
    if (!Number.isFinite(seconds) || seconds <= 0) {
      return;
    }
    setInterval(refresh, seconds * 1000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
