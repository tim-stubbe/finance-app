from datetime import date, datetime
from types import SimpleNamespace

from app import webuntis_sync


LINK = "https://rheingrafen.webuntis.com/WebUntis?school=rheingrafen#/basic/timetablePublic/my-student?date=2026-08-17&entityId=3708"


def test_parse_public_link():
    assert webuntis_sync.parse_share_url(LINK) == {
        "base": "https://rheingrafen.webuntis.com/WebUntis",
        "school": "rheingrafen",
        "entity_id": 3708,
    }


def test_normalise_cancelled_period():
    event = webuntis_sync.normalise_period({
        "id": 42, "date": 20260914, "startTime": 815, "endTime": 900,
        "su": [{"name": "M"}], "ro": [{"name": "R12"}],
        "te": [{"name": "AB"}], "code": "cancelled", "substText": "Entfall",
    })
    assert event["uid"] == "webuntis-42@kies"
    assert event["title"] == "Entfällt · M"
    assert event["start"] == datetime(2026, 9, 14, 8, 15)
    assert event["location"] == "R12"
    assert event["cancelled"] is True


def test_sync_only_touches_webuntis_resources(monkeypatch):
    settings = SimpleNamespace(
        webuntis_url=LINK, webuntis_username="tim", webuntis_calendar_url="https://dav/tim/arbeit_stubbe/",
        radicale_username="tim", webuntis_state_json='{"webuntis-old@kies":"x"}',
        webuntis_last_sync_at=None,
    )
    monkeypatch.setattr(webuntis_sync, "fetch_periods", lambda *args: [{
        "id": 42, "date": 20260914, "startTime": 815, "endTime": 900,
        "su": [{"name": "M"}], "ro": [], "te": [],
    }])

    class Response:
        status_code = 404
        headers = {}

    monkeypatch.setattr(webuntis_sync.requests, "get", lambda *args, **kwargs: Response())
    written, deleted = [], []
    monkeypatch.setattr(webuntis_sync.radicale_sync, "put_ics", lambda url, *args: written.append(url))
    monkeypatch.setattr(webuntis_sync.radicale_sync, "delete_ics", lambda url, *args: deleted.append(url))
    result = webuntis_sync.sync(settings, "wu-pass", "dav-pass", today=date(2026, 9, 14))
    assert written == ["https://dav/tim/arbeit_stubbe/webuntis-42@kies.ics"]
    assert deleted == ["https://dav/tim/arbeit_stubbe/webuntis-old@kies.ics"]
    assert result["created"] == 1 and result["removed"] == 1
    assert result["details"][0]["type"] == "neu"
    saved = __import__("json").loads(settings.webuntis_state_json)
    assert "fingerprints" in saved and "events" in saved
