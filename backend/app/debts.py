"""Tilgungsrechnung für das Schulden-Modul.

Zwei getrennte Dinge:
- `payment_breakdown()` teilt die *tatsächlich erfassten* Zahlungen in Zins- und
  Tilgungsanteil auf und liefert den Restschuldverlauf (Ist).
- `projection()` rechnet ab der heutigen Restschuld in die Zukunft (Plan).

Die Aufteilung folgt der üblichen nachschüssigen Monatsrechnung:
Zinsanteil = Restschuld × Jahreszins ÷ 12, der Rest der Zahlung tilgt. Das ist die
Standardnäherung für Annuitätendarlehen; taggenaue Zinsberechnung, Zinsbindung,
Gebühren und Bereitstellungszinsen bildet sie bewusst nicht ab.
"""

from datetime import date
from typing import NamedTuple, Optional

from . import models

# Sicherheitsgrenze, damit eine Rate, die die Zinsen nicht deckt, keine
# Endlosschleife erzeugt (50 Jahre).
MAX_PROJECTION_MONTHS = 600


class PaymentRow(NamedTuple):
    payment_id: int
    date: date
    total_amount: float
    interest_amount: float
    fee_amount: float
    principal_amount: float
    balance_after: float
    is_extra_repayment: bool
    interest_is_manual: bool


class ScheduleRow(NamedTuple):
    month_index: int
    date: date
    payment: float
    interest: float
    fee: float
    principal: float
    balance_after: float
    # True ab dem ersten Monat nach Ablauf der Zinsbindung - ab hier ist der
    # Zinssatz eine Annahme, keine Zusage.
    after_fixed_interest: bool


def _monthly_interest(balance: float, annual_rate_percent: float) -> float:
    if balance <= 0 or annual_rate_percent <= 0:
        return 0.0
    return round(balance * (annual_rate_percent / 100.0) / 12.0, 2)


def monthly_side_costs(debt: models.Debt) -> float:
    """Laufende Nebenkosten pro Monat: Gebühren + Restschuldversicherung.
    Tilgen nichts, gehören aber zur tatsächlichen monatlichen Belastung."""
    return round((debt.monthly_fee or 0.0) + (debt.monthly_insurance or 0.0), 2)


def rate_at(debt: models.Debt, at: date) -> float:
    """Zinssatz zum Stichtag. Nach Ablauf der Zinsbindung gilt der vom Nutzer
    angenommene Anschlusszins; ist keiner hinterlegt, wird der bisherige
    fortgeschrieben (optimistische, aber transparente Annahme)."""
    if debt.interest_fixed_until and at > debt.interest_fixed_until:
        if debt.follow_up_interest_rate_percent is not None:
            return debt.follow_up_interest_rate_percent
    return debt.interest_rate_percent or 0.0


def monthly_commitment_interest(debt: models.Debt) -> float:
    """Bereitstellungszinsen auf den noch nicht abgerufenen Betrag, pro Monat.

    Bewusst vereinfacht: die App kennt den Abrufplan nicht, rechnet also mit dem
    aktuell offenen Betrag als Momentaufnahme. Die bereitstellungszinsfreie Zeit
    wird ab Kreditbeginn gezählt."""
    if not debt.commitment_rate_percent or not debt.undisbursed_amount:
        return 0.0
    if debt.start_date and debt.commitment_free_months:
        free_until = _add_months(debt.start_date, debt.commitment_free_months)
        if date.today() <= free_until:
            return 0.0
    return round(debt.undisbursed_amount * (debt.commitment_rate_percent / 100.0) / 12.0, 2)


def _add_months(d: date, months: int) -> date:
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    # Auf den letzten gültigen Tag des Zielmonats begrenzen (31.01. + 1 Monat).
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


def payment_breakdown(debt: models.Debt) -> list[PaymentRow]:
    """Ist-Verlauf: alle erfassten Zahlungen chronologisch, mit Zins-, Gebühren- und
    Tilgungsanteil sowie Restschuld danach. Ein manuell gesetzter Zinsanteil wird
    respektiert."""
    balance = debt.original_amount
    rows: list[PaymentRow] = []
    for p in sorted(debt.payments, key=lambda x: (x.date, x.id)):
        manual = p.interest_amount is not None
        if manual:
            interest = round(p.interest_amount, 2)
        elif p.is_extra_repayment:
            # Sondertilgungen gehen vollständig in die Tilgung.
            interest = 0.0
        else:
            interest = _monthly_interest(balance, rate_at(debt, p.date))
        # Ist kein Gebührenanteil erfasst, werden die hinterlegten laufenden
        # Nebenkosten angesetzt - außer bei Sondertilgungen, die keine Rate sind.
        if p.fee_amount is not None:
            fee = round(p.fee_amount, 2)
        elif p.is_extra_repayment:
            fee = 0.0
        else:
            fee = monthly_side_costs(debt)
        # Deckt die Zahlung Zinsen und Gebühren nicht, wächst die Restschuld - das
        # darf sichtbar bleiben statt stillschweigend auf 0 geklemmt zu werden.
        principal = round(p.total_amount - interest - fee, 2)
        balance = round(balance - principal, 2)
        rows.append(PaymentRow(
            payment_id=p.id, date=p.date, total_amount=round(p.total_amount, 2),
            interest_amount=interest, fee_amount=fee, principal_amount=principal,
            balance_after=balance, is_extra_repayment=p.is_extra_repayment,
            interest_is_manual=manual,
        ))
    return rows


def total_fees_paid(debt: models.Debt) -> float:
    """Bisher gezahlte laufende Nebenkosten plus einmalige Abschlusskosten."""
    return round(sum(r.fee_amount for r in payment_breakdown(debt)) + (debt.upfront_fees or 0.0), 2)


def current_balance(debt: models.Debt) -> float:
    rows = payment_breakdown(debt)
    return rows[-1].balance_after if rows else round(debt.original_amount, 2)


def total_interest_paid(debt: models.Debt) -> float:
    return round(sum(r.interest_amount for r in payment_breakdown(debt)), 2)


def projection(debt: models.Debt, from_date: Optional[date] = None) -> tuple[list[ScheduleRow], Optional[str]]:
    """Plan-Verlauf ab der aktuellen Restschuld. Liefert (Zeilen, Hinweis).
    Der Hinweis ist gesetzt, wenn keine sinnvolle Prognose möglich ist."""
    balance = current_balance(debt)
    if balance <= 0:
        return [], None

    start = from_date or date.today()
    fee = monthly_side_costs(debt)

    def _after_fix(d: date) -> bool:
        return bool(debt.interest_fixed_until and d > debt.interest_fixed_until)

    if debt.kind == models.DebtKind.endfaellig:
        if not debt.planned_end_date:
            return [], "Für ein endfälliges Darlehen wird ein geplantes Laufzeitende benötigt."
        rows = []
        month = 0
        d = _add_months(start, 1)
        while d < debt.planned_end_date and month < MAX_PROJECTION_MONTHS:
            month += 1
            interest = _monthly_interest(balance, rate_at(debt, d))
            rows.append(ScheduleRow(month, d, round(interest + fee, 2), interest, fee, 0.0, balance, _after_fix(d)))
            d = _add_months(start, month + 1)
        end_d = debt.planned_end_date
        interest = _monthly_interest(balance, rate_at(debt, end_d))
        rows.append(ScheduleRow(month + 1, end_d, round(balance + interest + fee, 2),
                                interest, fee, balance, 0.0, _after_fix(end_d)))
        return rows, None

    if debt.kind == models.DebtKind.raten:
        if not debt.planned_end_date:
            return [], "Für einen Ratenkredit wird ein geplantes Laufzeitende benötigt."
        months_left = max(1, (debt.planned_end_date.year - start.year) * 12
                          + debt.planned_end_date.month - start.month)
        principal_per_month = round(balance / months_left, 2)
        rows = []
        for i in range(1, months_left + 1):
            d = _add_months(start, i)
            interest = _monthly_interest(balance, rate_at(debt, d))
            principal = min(principal_per_month, balance)
            balance = round(balance - principal, 2)
            rows.append(ScheduleRow(i, d, round(principal + interest + fee, 2),
                                    interest, fee, principal, balance, _after_fix(d)))
            if balance <= 0:
                break
        return rows, None

    # Annuität (auch für Dispo/Privatdarlehen, sofern eine Rate hinterlegt ist)
    payment = debt.monthly_payment or 0.0
    if payment <= 0:
        return [], "Ohne hinterlegte Monatsrate lässt sich kein Tilgungsplan berechnen."
    # Die hinterlegte Rate ist die Gesamtbelastung inkl. Nebenkosten - für die
    # Tilgung bleibt entsprechend weniger übrig.
    first_interest = _monthly_interest(balance, rate_at(debt, _add_months(start, 1)))
    if payment <= first_interest + fee:
        detail = f"Zinsen {first_interest:.2f} €" + (f" + Nebenkosten {fee:.2f} €" if fee else "")
        return [], (f"Die Rate von {payment:.2f} € deckt nicht einmal {detail} "
                    "- die Restschuld würde wachsen.")

    rows = []
    for i in range(1, MAX_PROJECTION_MONTHS + 1):
        d = _add_months(start, i)
        interest = _monthly_interest(balance, rate_at(debt, d))
        principal = round(payment - interest - fee, 2)
        if principal <= 0:
            # Kann nach einer Zinserhöhung zum Ende der Zinsbindung eintreten.
            return rows, ("Nach Ablauf der Zinsbindung reicht die Rate beim angenommenen "
                          "Anschlusszins nicht mehr zur Tilgung.")
        principal = min(principal, balance)
        balance = round(balance - principal, 2)
        rows.append(ScheduleRow(i, d, round(principal + interest + fee, 2),
                                interest, fee, principal, balance, _after_fix(d)))
        if balance <= 0:
            break
    return rows, None


def balance_at_fixed_interest_end(debt: models.Debt) -> Optional[float]:
    """Restschuld bei Ablauf der Zinsbindung - die entscheidende Zahl für die
    Anschlussfinanzierung."""
    if not debt.interest_fixed_until or debt.interest_fixed_until <= date.today():
        return None
    rows, _ = projection(debt)
    before = [r for r in rows if not r.after_fixed_interest]
    if not before:
        return None
    return before[-1].balance_after
