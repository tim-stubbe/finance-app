"""_extract_action: Aktions-Block auch ohne ```action```-Fences erkennen
(schwaechere Modelle vergessen die Fences -> rohes JSON darf nicht als
Antwort durchrutschen), aber nicht bei Fliesstext-Antworten."""
from app.telegram_bot import _extract_action


def test_fenced_action_block():
    r = 'Klar!\n```action\n{"type": "create_todo", "title": "Milch kaufen"}\n```'
    assert _extract_action(r) == {"type": "create_todo", "title": "Milch kaufen"}


def test_bare_json_action_is_caught():
    r = '{"type": "classify_trips", "purpose": "privat"}'
    assert _extract_action(r) == {"type": "classify_trips", "purpose": "privat"}


def test_plain_text_reply_is_no_action():
    assert _extract_action("Ja, die Fahrten sind jetzt alle auf privat gestellt.") is None
    assert _extract_action('Das Feld heißt "type" in der Config.') is None


def test_unknown_type_ignored():
    assert _extract_action('{"type": "rm_rf", "path": "/"}') is None


def test_classify_trips_command_matches_clear_instructions():
    from app.telegram_bot import _CLASSIFY_TRIPS_RE, _CLASSIFY_VERB_RE
    def hits(t):
        return bool(_CLASSIFY_TRIPS_RE.search(t) and _CLASSIFY_VERB_RE.search(t) and len(t) <= 200)
    assert hits("trag die Fahrten als privat ein")
    assert hits("klassifizier alle Fahrten geschäftlich")
    assert hits("dann möchte ich, dass du alle 190 Fahrten als privat klassifizierst")
    assert not hits("Wie viele Fahrten sind noch offen?")
    assert not hits("Ich fahre morgen privat nach Hause")
