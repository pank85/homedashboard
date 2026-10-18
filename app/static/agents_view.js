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

  function finiteNumber(value) {
    return typeof value === "number" && isFinite(value);
  }

  function presentText(value) {
    return value !== undefined && value !== null && value !== "";
  }

  function herdrBlock(agents) {
    agents = agents && typeof agents === "object" ? agents : {};
    var block = agents.herdr && typeof agents.herdr === "object" ? agents.herdr : {};
    return block;
  }

  function countText(value) {
    return finiteNumber(value) ? String(value) : "0";
  }

  function groupTitle(agent) {
    agent = agent && typeof agent === "object" ? agent : {};
    if (typeof agent.workspace_label === "string" && agent.workspace_label !== "") {
      return agent.workspace_label;
    }
    if (agent.source === "proc") {
      return "proc";
    }
    return "unknown";
  }

  function cardTitle(agent) {
    if (typeof agent.tab_label === "string" && agent.tab_label !== "") {
      return agent.tab_label;
    }
    if (typeof agent.kind === "string" && agent.kind !== "") {
      return agent.kind;
    }
    if (typeof agent.agent === "string" && agent.agent !== "") {
      return agent.agent;
    }
    return "unknown";
  }

  function renderHerdrBlock(root, agents) {
    if (!root) {
      return;
    }
    clear(root);
    var block = herdrBlock(agents);
    var reachable = !!block.reachable;
    add(
      root,
      "p",
      "reachable " + (reachable ? "true" : "false")
        + " · version " + human(block.version)
        + " · session " + human(block.session)
        + " · workspaces " + countText(block.workspace_count)
        + " · tabs " + countText(block.tab_count)
        + " · agents " + countText(block.agent_count),
      "herdr-summary"
    );
    if (block.reason) {
      add(root, "p", String(block.reason), "herdr-reason");
    }
    if (!reachable) {
      add(root, "p", "unavailable: " + (block.reason ? String(block.reason) : "herdr unavailable"), "herdr-unavailable");
    }
  }

  function agentKey(agent) {
    agent = agent && typeof agent === "object" ? agent : {};
    var identity = typeof agent.kind === "string" && agent.kind !== "" ? agent.kind : agent.label;
    if (typeof identity !== "string" || identity === "") {
      return "";
    }
    var key = identity.toLowerCase();
    if (!/^[a-z][a-z0-9-]{0,31}$/.test(key)) {
      return "";
    }
    return key;
  }

  function renderCard(group, agent) {
    var key = agentKey(agent);
    var card = add(group, "article", null, "agent-card");
    var body = card;
    if (key) {
      body = add(card, "a", null, "agent-card-link");
      body.setAttribute("href", "/agents/" + key);
    }
    add(body, "h3", cardTitle(agent), "agent-title");
    var badges = add(body, "p", null, "agent-badges");
    add(badges, "span", human(agent.status), "badge badge-status status-" + human(agent.status));
    badges.appendChild(document.createTextNode(" "));
    add(badges, "span", human(agent.source), "badge badge-source source-" + human(agent.source));
    badges.appendChild(document.createTextNode(" "));
    add(badges, "span", human(agent.kind), "badge badge-kind kind-" + human(agent.kind));
    var workspace = agent.workspace_label ? agent.workspace_label : groupTitle(agent);
    add(body, "p", "workspace " + workspace + " · cwd " + human(agent.cwd), "agent-meta");
    if (agent.elapsed_source === "herdr") {
      add(body, "p", "elapsed " + human(agent.elapsed_human), "agent-elapsed");
    }
    if (agent.source === "proc") {
      if (presentText(agent.cpu_percent_human)) {
        add(body, "p", "cpu " + human(agent.cpu_percent_human), "agent-cpu");
      }
      if (presentText(agent.rss_human)) {
        add(body, "p", "rss " + human(agent.rss_human), "agent-rss");
      }
    }
  }

  function renderAgentsBody(root, agents, view) {
    if (!root) {
      return;
    }
    clear(root);
    root.setAttribute("data-agents-view", view === "mobile" ? "mobile" : "desktop");
    agents = agents && typeof agents === "object" ? agents : {};
    var rows = Array.isArray(agents.agents) ? agents.agents : [];
    var note = agents.note ? String(agents.note) : "";
    if (!rows.length || note === "no agents detected") {
      add(root, "p", "No agents detected.", "agents-empty");
      return;
    }
    if (note) {
      add(root, "p", note, "agents-note");
    }
    var titles = [];
    rows.forEach(function (agent) {
      var title = groupTitle(agent);
      if (titles.indexOf(title) === -1) {
        titles.push(title);
      }
    });
    titles.forEach(function (title) {
      var group = add(root, "div", null, "workspace-group");
      add(group, "h3", title);
      rows.forEach(function (agent) {
        agent = agent && typeof agent === "object" ? agent : {};
        if (groupTitle(agent) !== title) {
          return;
        }
        renderCard(group, agent);
      });
    });
  }

  globalThis.renderHerdrBlock = renderHerdrBlock;
  globalThis.renderAgentsBody = renderAgentsBody;
})();
