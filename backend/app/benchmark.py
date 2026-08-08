"""Vergleich des eigenen Vermögens mit der eigenen Altersgruppe.

Datengrundlage: Vermögensbefragung "Private Haushalte und ihre Finanzen" (PHF,
Welle 5, Erhebungsjahr 2023) der Deutschen Bundesbank, ausgewertet im
IW-Kurzbericht 59/2025 (Niehues/Stockhausen, 09.07.2025), Abbildung
"Altersspezifische Verteilung der Haushaltsnettovermögen".

Bewusst fest im Code hinterlegt statt über eine API geladen: es gibt keine
kostenlose Schnittstelle dafür, die Zahlen ändern sich nur alle paar Jahre, und
eine Vergleichsansicht darf nicht davon abhängen, dass ein fremder Server
erreichbar ist.

Wichtige Einschränkungen, die in der Oberfläche genannt werden müssen, sonst
führt der Vergleich in die Irre:
  * Es sind **Haushalts**vermögen, zugeordnet nach dem Alter der ältesten Person
    im Haushalt. Für einen Einpersonenhaushalt passt der Vergleich gut, bei
    einem Paarhaushalt vergleicht man eine Person mit zwei.
  * Enthalten sind alle Vermögenswerte inklusive Immobilien, Fahrzeugen und
    Betriebsvermögen. Was nicht in der App erfasst ist, fehlt im Vergleich.
  * Stand 2023.
"""

from datetime import date
from typing import NamedTuple

QUELLE = (
    "Bundesbank-Vermögensbefragung PHF (Welle 5, 2023), "
    "ausgewertet im IW-Kurzbericht 59/2025"
)
QUELLE_URL = (
    "https://www.iwkoeln.de/studien/judith-niehues-maximilian-stockhausen-"
    "ein-vermoegensvergleich-nach-altersgruppen.html"
)
DATENJAHR = 2023


class Bracket(NamedTuple):
    key: str
    label: str
    min_age: int
    max_age: int | None
    p10: float
    p50: float
    p90: float


# Nur die in der Quelle beschrifteten Perzentile (10/50/90). Die übrigen Balken
# der Abbildung sind nicht bezifferbar und werden deshalb nicht geraten.
BRACKETS: list[Bracket] = [
    Bracket("u35", "unter 35", 0, 34, -300, 17_300, 200_400),
    Bracket("35_44", "35–44", 35, 44, 600, 75_500, 583_100),
    Bracket("45_54", "45–54", 45, 54, 500, 146_200, 918_900),
    Bracket("55_64", "55–64", 55, 64, 2_400, 241_100, 1_061_200),
    Bracket("65_74", "65–74", 65, 74, 1_900, 193_300, 1_019_800),
    Bracket("75p", "75 und älter", 75, None, 5_100, 172_500, 767_700),
]

GESAMT = Bracket("gesamt", "Alle Haushalte", 0, None, 800, 103_100, 777_200)


def age_from_birth_year(birth_year: int, today: date | None = None) -> int:
    """Alter aus dem Geburtsjahr. Ohne Geburtstag ist das auf ein Jahr genau -
    für die Zuordnung zu einer Zehnjahresgruppe reicht das."""
    today = today or date.today()
    return today.year - birth_year


def bracket_for_age(age: int) -> Bracket:
    for b in BRACKETS:
        if age >= b.min_age and (b.max_age is None or age <= b.max_age):
            return b
    return BRACKETS[-1]


def estimate_percentile(value: float, b: Bracket) -> tuple[float, bool]:
    """Schätzt, wie viel Prozent der Vergleichsgruppe unter `value` liegen.

    Zwischen den drei bekannten Marken wird linear interpoliert. Das ist eine
    Näherung: Vermögen sind stark rechtsschief verteilt, zwischen den Stützstellen
    verläuft die echte Kurve nicht gerade. Ober- und unterhalb der äußeren Marken
    lässt sich gar nichts mehr interpolieren - dort wird nur noch "mehr als 90"
    bzw. "weniger als 10" gemeldet. Das zweite Rückgabefeld sagt, ob der Wert
    innerhalb des belegten Bereichs liegt.
    """
    if value < b.p10:
        return 10.0, False
    if value > b.p90:
        return 90.0, False
    if value <= b.p50:
        spanne = b.p50 - b.p10
        anteil = (value - b.p10) / spanne if spanne else 0
        return 10 + anteil * 40, True
    spanne = b.p90 - b.p50
    anteil = (value - b.p50) / spanne if spanne else 0
    return 50 + anteil * 40, True


def verdict(value: float, b: Bracket) -> str:
    """Einordnung in Worten - nüchtern gehalten. Vermögen hängt stark von Erbe,
    Wohnort und Lebenslage ab; die Zahl ist eine Einordnung, kein Zeugnis."""
    if value > b.p90:
        return f"Über dem Wert, ab dem man zu den vermögendsten 10 % der Gruppe „{b.label}“ zählt."
    if value < b.p10:
        return f"Unter dem Wert der untersten 10 % der Gruppe „{b.label}“."
    if value >= b.p50:
        return f"Über dem Mittelwert (Median) der Gruppe „{b.label}“."
    return f"Unter dem Mittelwert (Median) der Gruppe „{b.label}“."
