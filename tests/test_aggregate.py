import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.aggregate import build_dashboard

TOKEN = "super-secret-token"


def _kwargs(**overrides):
    kwargs = {
        "containers": {"available": True, "containers": []},
        "agents": {"available": True, "sources": [], "note": None},
        "host": {"available": True, "view": "container view"},
        "herdr_href": "/herdr/",
        "herdr_embed": True,
        "herdr_embed_src": "/herdr/",
        "herdr_mode": "embedded",
        "refresh_seconds": 30,
        "generated_at": "2026-10-17T11:26:03Z",
    }
    kwargs.update(overrides)
    return kwargs


def test_payload_shape_and_proxy_path():
    payload = build_dashboard(**_kwargs())
    assert payload["herdr"]["proxy_path"] == "/herdr/"
    assert payload["generated_at"] == "2026-10-17T11:26:03Z"
    assert payload["refresh_seconds"] == 30
    assert payload["containers"] == {"available": True, "containers": []}
    assert payload["agents"]["available"] is True
    assert payload["host"]["view"] == "container view"


def test_embed_false_when_embed_src_empty():
    payload = build_dashboard(**_kwargs(herdr_embed=True, herdr_embed_src=""))
    assert payload["herdr"]["embed"] is False
    assert payload["herdr"]["embed_src"] == ""


def test_embed_false_when_flag_false():
    payload = build_dashboard(**_kwargs(herdr_embed=False, herdr_embed_src="/herdr/"))
    assert payload["herdr"]["embed"] is False
    assert payload["herdr"]["embed_src"] == ""


def test_embed_true_when_flag_and_src_present():
    payload = build_dashboard(**_kwargs(herdr_embed=True, herdr_embed_src="/herdr/"))
    assert payload["herdr"]["embed"] is True
    assert payload["herdr"]["embed_src"] == "/herdr/"


def test_payload_does_not_contain_token():
    payload = build_dashboard(**_kwargs())
    assert TOKEN not in json.dumps(payload)


def test_signature_has_no_token_parameter():
    params = inspect.signature(build_dashboard).parameters
    assert "token" not in params
    assert "herdr_web_token" not in params


UNSET_GIT = {
    "available": True,
    "reason": "",
    "note": "git collector not configured",
    "scanned": False,
    "roots": [],
    "truncated": False,
    "refreshed_at": "",
    "projects": [],
}


def test_git_omitted_is_unset_object():
    payload = build_dashboard(**_kwargs())
    assert payload["git"] == UNSET_GIT


def test_git_explicit_dict_passes_through():
    git = {
        "available": True,
        "reason": "",
        "note": "",
        "scanned": True,
        "roots": ["/srv"],
        "truncated": False,
        "refreshed_at": "2026-10-17T11:26:03Z",
        "projects": [{"name": "demo"}],
    }
    payload = build_dashboard(**_kwargs(git=git))
    assert payload["git"] is git


def test_git_non_dict_becomes_unset_object():
    for value in (None, [], "", 0, ["x"]):
        payload = build_dashboard(**_kwargs(git=value))
        assert payload["git"] == UNSET_GIT
