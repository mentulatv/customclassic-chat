"""Telling the player about a newer version on GitHub."""
import updates


def test_versions_compare_as_numbers():
    assert updates.parse("v1.4.0") == (1, 4, 0) and updates.parse("1.10") == (1, 10, 0)
    assert updates.parse("latest") is None and updates.parse("") is None
    assert updates.newer("1.10.0", "1.9.3") and updates.newer("v2.0", "1.99.99")
    assert not updates.newer("1.4.0", "1.4.0") and not updates.newer("1.3.9", "1.4.0")
    assert not updates.newer("junk", "1.0.0")


def test_only_a_newer_release_is_told(monkeypatch):
    page = "https://github.com/mentulatv/customclassic-chat/releases/tag/v9.0.0"
    monkeypatch.setattr(updates, "latest_release", lambda: ("9.0.0", page))
    told = []
    updates.check(told.append, current="1.4.0")
    assert told == [("update", ("9.0.0", page))]
    told.clear()
    updates.check(told.append, current="9.0.0")
    assert told == []


def test_offline_is_quiet(monkeypatch):
    def offline():
        raise OSError("no network")
    monkeypatch.setattr(updates, "latest_release", offline)
    told = []
    updates.check(told.append)
    assert told == []
