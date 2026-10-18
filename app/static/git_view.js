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

  function isMapping(value) {
    return !!value && typeof value === "object" && !Array.isArray(value);
  }

  function gitBody(root) {
    if (root && root.id === "git-body") {
      return root;
    }
    if (root && typeof root.querySelector === "function") {
      var nested = root.querySelector("#git-body");
      if (nested) {
        return nested;
      }
    }
    if (typeof document !== "undefined" && typeof document.getElementById === "function") {
      return document.getElementById("git-body");
    }
    return null;
  }

  function statusMessage(git) {
    if (!isMapping(git)) {
      return "No git roots configured.";
    }
    if (!git.available) {
      return "unavailable: " + (typeof git.reason === "string" ? git.reason : "");
    }
    if (!git.scanned || !Array.isArray(git.roots) || git.roots.length === 0) {
      return "No git roots configured.";
    }
    if (!Array.isArray(git.projects) || git.projects.length === 0) {
      return "No git projects found.";
    }
    return "";
  }

  function branchLabel(project) {
    if (project.detached) {
      return "detached";
    }
    return human(project.branch);
  }

  function remoteText(project) {
    if (typeof project.remote_url !== "string") {
      return "unknown";
    }
    return human(project.remote_url);
  }

  function addBadges(parent, project) {
    var flags = project.in_progress;
    var index;
    var flag;
    if (!Array.isArray(flags)) {
      return;
    }
    for (index = 0; index < flags.length; index += 1) {
      flag = flags[index];
      if (typeof flag === "string" && flag !== "") {
        add(parent, "span", flag, "badge git-badge");
      }
    }
  }

  function renderDesktop(root, git) {
    var list = add(root, "ul", null, "git-list");
    var projects = git.projects;
    var index;
    var project;
    var row;
    var progress;
    for (index = 0; index < projects.length; index += 1) {
      project = projects[index];
      if (!isMapping(project)) {
        continue;
      }
      row = add(list, "li", null, "git-row");
      add(row, "span", human(project.name), "git-name");
      add(row, "span", branchLabel(project), project.detached ? "git-detached" : "git-branch");
      add(row, "span", "head " + human(project.head_short), "git-head");
      add(row, "span", "upstream " + human(project.upstream), "git-upstream");
      add(row, "span", "remote " + remoteText(project), "git-remote");
      progress = add(row, "span", null, "git-progress");
      addBadges(progress, project);
      add(row, "span", human(project.commit_subject), "git-subject");
      add(row, "span", human(project.commit_relative), "git-when");
    }
  }

  function renderMobile(root, git) {
    var projects = git.projects;
    var index;
    var project;
    var card;
    var details;
    for (index = 0; index < projects.length; index += 1) {
      project = projects[index];
      if (!isMapping(project)) {
        continue;
      }
      card = add(root, "article", null, "git-card");
      add(card, "h3", human(project.name), "git-name");
      add(card, "p", branchLabel(project), project.detached ? "git-detached" : "git-branch");
      add(card, "p", human(project.commit_subject), "git-subject");
      details = add(card, "details");
      add(details, "summary", "Details");
      add(details, "p", "head " + human(project.head_short));
      add(details, "p", "upstream " + human(project.upstream));
      add(details, "p", "remote " + remoteText(project));
      addBadges(details, project);
      add(details, "p", human(project.commit_relative));
    }
  }

  function renderGitView(root, git, view) {
    var body = gitBody(root);
    if (!body) {
      return;
    }
    clear(body);
    var message = statusMessage(git);
    if (message) {
      add(body, "p", message, !isMapping(git) || git.available ? "git-status" : "git-status git-unavailable");
    } else if (view === "mobile") {
      renderMobile(body, git);
    } else {
      renderDesktop(body, git);
    }
    if (isMapping(git) && git.truncated) {
      add(body, "p", "The list stopped at the repo cap.", "git-truncated");
    }
  }

  globalThis.renderGitView = renderGitView;
})();
