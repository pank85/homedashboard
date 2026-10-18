"""Read-only discovery of installed CLI agent config files.

Only the allowlisted top-level keys below are read. Auth files, secret
fields, and every other key are never opened or retained. Stdlib only.
"""

from __future__ import annotations

import json
import os
import re

_SCALAR_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,79}")
_SECRET_PREFIXES = ("sk-", "ghp_", "github_pat_", "xox", "akia", "bearer")

# kind, label, relative path, model key(s), provider key(s)
_JSON_AGENTS = (
    ("claude", "Claude", ".claude/settings.json", ("model",), ()),
    ("pi", "Pi", ".pi/agent/settings.json", ("defaultModel",), ("defaultProvider",)),
    (
        "opencode",
        "OpenCode",
        ".config/opencode/opencode.json",
        ("model",),
        (),
    ),
)
# Hermes keeps ``model.default`` / ``model.provider`` in a YAML block.
_YAML_AGENTS = (
    ("hermes", "Hermes", ".hermes/config.yaml"),
)


def _safe_scalar(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not 1 <= len(text) <= 80:
        return ""
    if _SCALAR_RE.fullmatch(text) is None:
        return ""
    if text.lower().startswith(_SECRET_PREFIXES):
        return ""
    return text


def _read_text(config_home: str, relative: str) -> str | None:
    try:
        with open(
            os.path.join(config_home, relative),
            encoding="utf-8",
            errors="replace",
        ) as handle:
            return handle.read()
    except OSError:
        return None


def _json_fields(text: str, keys: tuple[str, ...]) -> dict[str, object]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {key: parsed[key] for key in keys if key in parsed}


def _yaml_unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _yaml_model_fields(text: str) -> dict[str, str]:
    """Read only ``model.default`` and ``model.provider`` from a YAML file.

    A top-level ``model:`` line with an empty remainder opens the block;
    only indent-2 ``default``/``provider`` scalar lines inside it are kept.
    """
    values: dict[str, str] = {}
    in_model_block = False
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        key, sep, remainder = stripped.partition(":")
        if not sep:
            continue
        key = key.strip()
        remainder = remainder.strip()
        if indent == 0:
            in_model_block = key == "model" and remainder == ""
            continue
        if not in_model_block or indent != 2:
            continue
        if key not in ("default", "provider"):
            continue
        if not remainder or remainder[0] in "{[|>":
            continue
        values[key] = _yaml_unquote(remainder)
    return values


def _config_row(
    kind: str,
    label: str,
    relative: str,
    present: bool,
    model: object,
    provider: object,
) -> dict:
    return {
        "source": "config",
        "workspace_id": "",
        "workspace_label": "installed",
        "label": label,
        "tab_id": "",
        "tab_label": label,
        "pane_id": "",
        "kind": kind,
        "status": "installed" if present else "absent",
        "cwd": "",
        "session": "",
        "pid": None,
        "rss_bytes": None,
        "cpu_percent": None,
        "elapsed_seconds": None,
        "elapsed_source": "unknown",
        "config_path": relative,
        "config_present": present,
        "model": _safe_scalar(model),
        "provider": _safe_scalar(provider),
    }


def discover_agent_configs(config_home: str) -> list[dict]:
    """Return the four installed-agent config rows for ``config_home``."""
    rows: list[dict] = []
    for kind, label, relative, model_keys, provider_keys in _JSON_AGENTS:
        text = _read_text(config_home, relative)
        if text is None:
            rows.append(_config_row(kind, label, relative, False, "", ""))
            continue
        fields = _json_fields(text, model_keys + provider_keys)
        rows.append(
            _config_row(
                kind,
                label,
                relative,
                True,
                fields.get(model_keys[0]) if model_keys else "",
                fields.get(provider_keys[0]) if provider_keys else "",
            )
        )
    for kind, label, relative in _YAML_AGENTS:
        text = _read_text(config_home, relative)
        if text is None:
            rows.append(_config_row(kind, label, relative, False, "", ""))
            continue
        fields = _yaml_model_fields(text)
        rows.append(
            _config_row(
                kind,
                label,
                relative,
                True,
                fields.get("default"),
                fields.get("provider"),
            )
        )
    return rows
