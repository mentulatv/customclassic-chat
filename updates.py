"""Telling the player when a newer CustomClassic Chat is out on GitHub.

Nothing is downloaded or installed: the app asks GitHub which release is the latest (the same
public page anyone can open) and, if it's newer than this one, shows a note with a link to it.
"""
from __future__ import annotations

import re

VERSION = "2.0.2"  # this version: bump it with every release (its tag is "v" + this)
REPO = "mentulatv/customclassic-chat"
LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES = f"https://github.com/{REPO}/releases/latest"


def parse(version: str) -> tuple[int, ...] | None:
    """ "v1.4.0" or "1.4" -> (1, 4, 0); None for anything else."""
    m = re.fullmatch(r"\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?\s*", version or "")
    return tuple(int(n or 0) for n in m.groups()) if m else None


def newer(latest: str, current: str = VERSION) -> bool:
    a, b = parse(latest), parse(current)
    return bool(a and b and a > b)


def latest_release() -> tuple[str, str] | None:
    """The latest release on GitHub: (its version, its page), or None when GitHub can't be asked."""
    import httpx
    r = httpx.get(LATEST, timeout=10, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": f"CustomClassicChat/{VERSION}"})
    if r.status_code != 200:
        return None
    data = r.json()
    version = str(data.get("tag_name") or "").lstrip("v")
    return (version, str(data.get("html_url") or RELEASES)) if parse(version) else None


def check(put, current: str = VERSION) -> None:
    """Ask GitHub once; a newer release goes to put as ("update", (version, page)). Quiet when offline."""
    try:
        found = latest_release()
    except Exception:
        return
    if found and newer(found[0], current):
        put(("update", found))
