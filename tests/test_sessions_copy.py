from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARTIAL = ROOT / "app/templates/partials/sessions.html"


def test_sessions_copy_strings():
    text = PARTIAL.read_text(encoding="utf-8")
    assert "Chats started here" in text
    assert "A chat is a record this dashboard keeps when you start an agent. It is not the Herdr session name and it does not stop the agent if you archive it." in text
    for label in ("Name", "Agent", "Workspace", "Status", "Folder", "Started", "Updated"):
        assert label in text
    assert "Herdr session: {{ sessions.herdr_session }}. Attaching that name opens the whole Herdr session, not this one chat." in text
    assert 'class="archive-session"' in text
    assert 'id="session-token"' in text
    assert "Archive only updates this dashboard. It does not stop or delete the herdr workspace, tab, or agent." in text
    assert "herdr --session &lt;name&gt; attach is not a working command on herdr 0.9.5." in text
