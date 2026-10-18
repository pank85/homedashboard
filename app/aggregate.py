"""Pure dashboard payload assembly.

Stdlib only. No I/O, no settings, no collectors. The HTML page and
``/api/metrics`` both render from this one shape.
"""


def build_dashboard(
    *,
    containers: dict,
    agents: dict,
    host: dict,
    herdr_href: str,
    herdr_embed: bool,
    herdr_embed_src: str,
    herdr_mode: str,
    refresh_seconds: int,
    generated_at: str,
    git: dict | None = None,
) -> dict:
    """Return the dashboard payload shared by the page and the JSON API."""
    if not isinstance(git, dict):
        git = {
            "available": True,
            "reason": "",
            "note": "git collector not configured",
            "scanned": False,
            "roots": [],
            "truncated": False,
            "refreshed_at": "",
            "projects": [],
        }
    return {
        "generated_at": generated_at,
        "refresh_seconds": refresh_seconds,
        "herdr": {
            "mode": herdr_mode,
            "href": herdr_href,
            "embed": bool(herdr_embed) and bool(herdr_embed_src),
            "embed_src": herdr_embed_src if herdr_embed else "",
            "proxy_path": "/herdr/",
        },
        "containers": containers,
        "agents": agents,
        "host": host,
        "git": git,
    }
