from app import calls


def test_spoken_intro_uses_annabell():
    assert calls._spoken_intro("Dein Termin beginnt gleich.") == (
        "Hallo Tim, hier ist Annabell. Dein Termin beginnt gleich."
    )


def test_spoken_intro_rewrites_old_kies_prefixes():
    result = calls._spoken_intro("Wichtige Meldung von Kies. Bitte prüfe den Kalender.")
    assert result == "Hallo Tim, hier ist Annabell. Wichtige Meldung. Bitte prüfe den Kalender."


def test_spoken_intro_does_not_duplicate_name():
    text = "Hallo Tim, hier ist Annabell. Das ist ein Test."
    assert calls._spoken_intro(text) == text
