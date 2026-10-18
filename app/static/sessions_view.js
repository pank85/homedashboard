globalThis.renderSessionsView = function (sessions) {
  var body = document.getElementById("sessions-body");
  if (!body) return;
  while (body.firstChild) body.removeChild(body.firstChild);
  var rows = (sessions && Array.isArray(sessions.sessions)) ? sessions.sessions : [];
  rows.forEach(function (row) {
    var card = document.createElement("article");
    card.className = "session-card";
    var pairs = [
      ["Name", row.label],
      ["Agent", row.agent_kind],
      ["Workspace", row.workspace_id],
      ["Status", row.status],
      ["Folder", row.cwd],
      ["Started", row.created_relative],
      ["Updated", row.updated_relative]
    ];
    pairs.forEach(function (p) {
      var para = document.createElement("p");
      para.textContent = p[0] + " " + (p[1] == null ? "" : p[1]);
      card.appendChild(para);
    });
    var link = document.createElement("a");
    link.href = "/herdr/";
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "Open Herdr Web";
    card.appendChild(link);
    var input = document.createElement("input");
    input.className = "attach-command";
    input.type = "text";
    input.readOnly = true;
    input.value = row.attach_command == null ? "" : row.attach_command;
    card.appendChild(input);
    var copyBtn = document.createElement("button");
    copyBtn.type = "button";
    copyBtn.className = "copy-attach";
    copyBtn.setAttribute("data-attach-command", row.attach_command == null ? "" : row.attach_command);
    copyBtn.textContent = "Copy";
    card.appendChild(copyBtn);
    var archiveBtn = document.createElement("button");
    archiveBtn.type = "button";
    archiveBtn.className = "archive-session";
    archiveBtn.setAttribute("data-session-id", row.id == null ? "" : row.id);
    archiveBtn.textContent = "Archive";
    card.appendChild(archiveBtn);
    body.appendChild(card);
  });
};