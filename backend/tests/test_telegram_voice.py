"""Sprachnachrichten an den Telegram-Bot: herunterladen, lokal (voice.get_stt)
zu Text machen, dann wie eine getippte Nachricht weiterreichen."""
from app import telegram_bot, voice


class _Resp:
    def __init__(self, payload=None, content=b""):
        self._payload = payload
        self.content = content

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_transcribe_voice_downloads_and_calls_stt(monkeypatch):
    calls = {}

    def fake_get(url, params=None, timeout=None):
        if "getFile" in url:
            calls["file_id"] = params["file_id"]
            return _Resp(payload={"result": {"file_path": "voice/file_42.oga"}})
        calls["download_url"] = url
        return _Resp(content=b"OGGDATA")

    class FakeSTT:
        def transcribe(self, audio):
            calls["audio"] = audio
            return "  leg einen Termin für morgen an  "

    monkeypatch.setattr(telegram_bot.requests, "get", fake_get)
    monkeypatch.setattr(voice, "get_stt", lambda: FakeSTT())

    text = telegram_bot._transcribe_voice("TOKEN", "AbC123")
    assert text == "leg einen Termin für morgen an"
    assert calls["file_id"] == "AbC123"
    assert calls["download_url"].endswith("/file/botTOKEN/voice/file_42.oga")
    assert calls["audio"] == b"OGGDATA"


def test_transcribe_voice_without_stt_raises(monkeypatch):
    monkeypatch.setattr(telegram_bot.requests, "get",
                        lambda *a, **k: _Resp(payload={"result": {"file_path": "v.oga"}}, content=b"x"))
    # Default-Backend ist "stub" -> NotImplementedError
    monkeypatch.delenv("STT_BACKEND", raising=False)
    import pytest
    with pytest.raises(NotImplementedError):
        telegram_bot._transcribe_voice("T", "f")
