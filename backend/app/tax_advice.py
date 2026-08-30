"""Steuer-Spar-Tipps: regelbasierte Hinweise aus den echten Daten des Nutzers
(Depot, Freibetrag, realisierte/unrealisierte Gewinne, Ausgabenkategorien)
plus eine Ollama-gestützte Freitext-Auskunft.

**Keine Steuerberatung.** Alle Beträge/Grenzen sind Näherungen zur
Orientierung; die Steuerlogik ist bewusst grob (siehe auch app/tax.py). Deckt
Deutschland (Abgeltungsteuer, Sparerpauschbetrag, §35a, Homeoffice) und die
Schweiz (Säule 3a, steuerfreie private Kapitalgewinne, Vermögenssteuer) ab -
gesteuert über `residence_country` bzw. den Parameter `country`.

Fließt an drei Stellen zusammen:
  * `GET  /api/tax/tips`         - der Steuern-Tab
  * `POST /api/tax/ask`          - Freitext-Frage, mit den Fakten als Kontext
  * `main._scheduled_tax_reminder` (Nov/Dez) - Top-Tipp in die Vorschlags-Queue
"""

from datetime import date

from . import crud, models, ollama_client, tax

# Deutschland -------------------------------------------------------------
ABGELTUNGSTEUER = 0.25
SOLI = 0.055                       # auf die Abgeltungsteuer
KAP_TAX_EFF = ABGELTUNGSTEUER * (1 + SOLI)   # 26,375 % ohne Kirchensteuer
SPARERPAUSCHBETRAG_DEFAULT = 1000.0
TEILFREISTELLUNG_AKTIENFONDS = 0.30   # pauschal für Aktien-ETF (wie app/tax.py)


def kap_eff(church_rate: float = 0.0) -> float:
    """Effektive Belastung auf Kapitalerträge über dem Freibetrag: Abgeltung-
    steuer + Soli + ggf. Kirchensteuer. Näherung (die Kirchensteuer mindert
    die Bemessungsgrundlage der KapSt geringfügig - hier vernachlässigt)."""
    return ABGELTUNGSTEUER * (1 + SOLI) + ABGELTUNGSTEUER * max(0.0, church_rate)
HANDWERKER_MAX_ABZUG = 1200.0     # §35a: 20 % der Lohnkosten, max. 1.200 €/Jahr
HAUSHALTSNAHE_MAX_ABZUG = 4000.0  # §35a: 20 %, max. 4.000 €/Jahr
HOMEOFFICE_MAX = 1260.0           # 6 €/Tag, max. 210 Tage

# Schweiz ---------------------------------------------------------------
# Säule-3a-Maximalbetrag für Erwerbstätige MIT Pensionskasse (jährlich
# angepasst - hier als Konstante mit klarem "bitte Jahr prüfen"-Hinweis).
SAEULE_3A_MAX_MIT_PK = 7258.0     # CHF, Stand 2025/2026 – jährlich prüfen!


def _eur(v) -> str:
    try:
        return f"{float(v):,.0f} €".replace(",", ".")
    except (TypeError, ValueError):
        return "–"


def _tip(tid, area, severity, title, detail):
    return {"id": tid, "area": area, "severity": severity, "title": title, "detail": detail}


# --------------------------------------------------------------------------
# Faktenbasis
# --------------------------------------------------------------------------
def collect_facts(db, settings, space_id: int, year: int) -> dict:
    """Alles, was die Tipps UND die KI-Auskunft brauchen - einmal berechnet."""
    facts: dict = {"year": year, "country": _country(settings)}

    try:
        vp = tax.portfolio_vorabpauschale(db, space_id, year)
        facts["vorabpauschale_steuerpflichtig"] = vp.total_steuerpflichtig
        facts["missing_basiszins"] = vp.missing_basiszins
    except Exception:
        facts["vorabpauschale_steuerpflichtig"] = 0.0

    try:
        rg = tax.compute_realized_gains(db, space_id, year)
        facts["realisierte_gewinne"] = rg.total_gain
    except Exception:
        facts["realisierte_gewinne"] = 0.0

    # Depot: unrealisierte Gewinner/Verlierer
    winners, losers, dividends_year = [], [], 0.0
    try:
        for h in crud.get_holdings(db, space_id):
            o = crud.holding_out(h)
            row = {"name": h.name, "symbol": h.symbol, "gain_abs": o.gain_abs,
                   "gain_pct": o.gain_pct, "current_value": o.current_value}
            if o.gain_abs < -50:
                losers.append(row)
            elif o.gain_abs > 50:
                winners.append(row)
            try:
                d = crud.holding_dividends(db, h)
                dividends_year += sum(p.total for p in d.history
                                      if date.fromisoformat(p.date).year == year)
            except Exception:
                pass
    except Exception:
        pass
    losers.sort(key=lambda r: r["gain_abs"])
    winners.sort(key=lambda r: -r["gain_abs"])
    facts["depot_verlierer"] = losers
    facts["depot_gewinner"] = winners
    facts["dividenden_jahr"] = round(dividends_year, 2)

    freibetrag = float(getattr(settings, "sparerpauschbetrag", None) or SPARERPAUSCHBETRAG_DEFAULT)
    kap_income = (max(facts["vorabpauschale_steuerpflichtig"], 0.0)
                  + max(facts["realisierte_gewinne"], 0.0)
                  + max(dividends_year, 0.0))
    facts["sparerpauschbetrag"] = freibetrag
    facts["kapitalertrag_geschaetzt"] = round(kap_income, 2)
    facts["freibetrag_rest"] = round(max(0.0, freibetrag - kap_income), 2)
    facts["kap_ueber_freibetrag"] = round(max(0.0, kap_income - freibetrag), 2)

    # Steuer-Profil (personalisiert die Betragsschätzungen)
    facts["church_tax_rate"] = float(getattr(settings, "church_tax_rate", 0.0) or 0.0)
    facts["marginal_tax_rate"] = float(getattr(settings, "marginal_tax_rate", 0.0) or 0.0)
    facts["filing_married"] = bool(getattr(settings, "filing_married", False))
    facts["kap_eff"] = round(kap_eff(facts["church_tax_rate"]), 5)

    # Ausgabenkategorien des Jahres (für §35a / Werbungskosten / 3a-Hinweise)
    facts["kategorie_summen"] = _category_sums(db, space_id, year)

    try:
        facts["nettovermoegen"] = crud.net_worth(db, space_id).total
    except Exception:
        facts["nettovermoegen"] = None
    return facts


def _country(settings) -> str:
    return (getattr(settings, "residence_country", None) or "DE").upper()


# --------------------------------------------------------------------------
# Anlage-Hochrechnung ("wie viel hätte ich nach X Jahren")
# --------------------------------------------------------------------------
def project_investment(
    *, start: float = 0.0, monthly: float = 0.0, annual_return_pct: float = 6.0,
    years: int = 30, ter_pct: float = 0.0, teilfreistellung: float = TEILFREISTELLUNG_AKTIENFONDS,
    church_tax_rate: float = 0.0, sparerpauschbetrag: float = SPARERPAUSCHBETRAG_DEFAULT,
    basiszins_pct: float = 2.5,
) -> dict:
    """Monatliche Aufzinsung + grobe deutsche Besteuerung (Abgeltungsteuer +
    Soli + optional Kirchensteuer, 30 % Teilfreistellung für Aktien-ETF,
    jährliche Vorabpauschale näherungsweise, Sparerpauschbetrag pro Jahr).

    Rückgabe u.a. `brutto` (ohne jede Steuer), `netto_laufend` (nach jährlicher
    Vorabpauschale) und `netto_nach_verkauf` (zusätzlich Steuer auf den
    Schlussgewinn, mit Anrechnung der schon gezahlten Vorabpauschale) - jeweils
    MIT und OHNE Kirchensteuer, plus die Differenz. Näherung, keine
    Steuerberatung."""
    years = max(1, min(int(years), 80))
    r_year = annual_return_pct / 100.0 - ter_pct / 100.0
    r_m = (1 + r_year) ** (1 / 12) - 1
    basiszins = max(0.0, basiszins_pct) / 100.0

    def run(church: float):
        value = float(start)
        invested = float(start)
        vorab_tax_paid = 0.0
        eff = kap_eff(church)
        for _y in range(years):
            value_start = value
            for _m in range(12):
                value = value * (1 + r_m) + monthly
                invested += monthly
            gain_year = value - value_start - monthly * 12
            # Vorabpauschale: Basisertrag = Wert Jahresanfang * Basiszins * 0.7,
            # gedeckelt auf den Jahres-Wertzuwachs, dann Teilfreistellung.
            basisertrag = value_start * basiszins * 0.7
            vorab = max(0.0, min(basisertrag, max(gain_year, 0.0)))
            steuerpfl = vorab * (1 - teilfreistellung)
            steuerpfl = max(0.0, steuerpfl - sparerpauschbetrag)
            tax = steuerpfl * eff
            value -= tax
            vorab_tax_paid += tax
        netto_laufend = value
        final_gain = value - invested
        sale_base = max(0.0, final_gain) * (1 - teilfreistellung)
        sale_base = max(0.0, sale_base - sparerpauschbetrag)
        sale_tax = max(0.0, sale_base * eff - vorab_tax_paid)
        return {
            "netto_laufend": round(netto_laufend, 2),
            "netto_nach_verkauf": round(netto_laufend - sale_tax, 2),
            "vorabpauschale_gezahlt": round(vorab_tax_paid, 2),
            "verkaufssteuer": round(sale_tax, 2),
            "eingezahlt": round(invested, 2),
        }

    # Brutto (ohne jede Steuer): monatliche Aufzinsung ohne Abzüge
    b_value, b_invested = float(start), float(start)
    for _m in range(years * 12):
        b_value = b_value * (1 + r_m) + monthly
        b_invested += monthly

    with_church = run(church_tax_rate)
    without_church = run(0.0)
    diff = round(with_church["netto_nach_verkauf"] - without_church["netto_nach_verkauf"], 2) \
        if church_tax_rate else 0.0
    return {
        "annahmen": {
            "start": start, "monatlich": monthly, "rendite_pa_pct": annual_return_pct,
            "ter_pct": ter_pct, "jahre": years, "teilfreistellung_pct": teilfreistellung * 100,
            "kirchensteuer_pct": church_tax_rate * 100, "sparerpauschbetrag": sparerpauschbetrag,
            "basiszins_pct": basiszins_pct,
        },
        "eingezahlt": round(b_invested, 2),
        "brutto": round(b_value, 2),
        "mit_kirchensteuer": with_church,
        "ohne_kirchensteuer": without_church,
        "kirchensteuer_kostet": diff,
    }


def _category_sums(db, space_id: int, year: int) -> dict:
    """{kategoriename_lower: summe_ausgaben_abs} für das Jahr - grobe Basis für
    die "ganze Finanzen"-Heuristiken (keine exakte Steuerzuordnung)."""
    start, end = date(year, 1, 1), date(year, 12, 31)
    out: dict = {}
    try:
        rows = (db.query(models.Transaction, models.Category.name)
                .join(models.Category, models.Transaction.category_id == models.Category.id)
                .filter(models.Transaction.space_id == space_id,
                        models.Transaction.date >= start, models.Transaction.date <= end,
                        models.Transaction.amount < 0)
                .all())
    except Exception:
        return out
    for tx, cat_name in rows:
        key = (cat_name or "").strip().lower()
        out[key] = round(out.get(key, 0.0) + abs(tx.amount), 2)
    return out


def _cat_total(sums: dict, *needles) -> float:
    return round(sum(v for k, v in sums.items() if any(n in k for n in needles)), 2)


# --------------------------------------------------------------------------
# Tipps
# --------------------------------------------------------------------------
def _dismissals(db, year: int) -> dict:
    try:
        from . import models as m
        rows = db.query(m.TaxTipStatus).filter(m.TaxTipStatus.year == year).all()
        return {r.tip_id: r.status for r in rows}
    except Exception:
        return {}


def generate_tips(db, settings, space_id: int, year: int) -> dict:
    facts = collect_facts(db, settings, space_id, year)
    country = facts["country"]
    all_tips: list = []
    (_tips_kapital_de if country != "CH" else _tips_kapital_ch)(facts, all_tips)
    (_tips_finanzen_de if country != "CH" else _tips_finanzen_ch)(facts, all_tips)
    order = {"hoch": 0, "mittel": 1, "info": 2}
    all_tips.sort(key=lambda t: order.get(t["severity"], 3))

    dismissed = _dismissals(db, year)
    active, erledigt = [], []
    for t in all_tips:
        st = dismissed.get(t["id"])
        if st:
            erledigt.append({**t, "status": st})
        else:
            active.append(t)
    return {"year": year, "country": country, "facts": facts,
            "tips": active, "dismissed": erledigt}


def _tips_kapital_de(f, tips):
    rest = f["freibetrag_rest"]
    ueber = f["kap_ueber_freibetrag"]
    if f.get("missing_basiszins"):
        tips.append(_tip("basiszins-fehlt", "kapital", "mittel",
                         "Basiszins für dieses Jahr fehlt",
                         "Ohne Basiszins kann die Vorabpauschale nicht geschätzt werden – unter "
                         "Steuer-Einstellungen den BMF-Wert eintragen."))
    if rest > 50:
        tips.append(_tip("freibetrag-frei", "kapital", "mittel",
                         f"Noch {_eur(rest)} Sparerpauschbetrag ungenutzt",
                         f"Geschätzte steuerpflichtige Kapitalerträge {year_str(f)}: {_eur(f['kapitalertrag_geschaetzt'])} "
                         f"von {_eur(f['sparerpauschbetrag'])}. Wer Gewinne gezielt realisiert (z. B. "
                         "Verkauf + sofortiger Rückkauf), hebt die Anschaffungskosten steuerfrei an "
                         "('Freibetrag ausschöpfen')."))
    eff = f.get("kap_eff", KAP_TAX_EFF)
    eff_pct = f"{eff * 100:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    kirche = " inkl. Kirchensteuer" if f.get("church_tax_rate") else ""
    if ueber > 0:
        spar = ueber * eff
        tips.append(_tip("freibetrag-voll", "kapital", "hoch",
                         f"Freibetrag ausgeschöpft – {_eur(ueber)} über der Grenze",
                         f"Darauf fallen ~{_eur(spar)} Steuer ({eff_pct} %{kirche}) an. Freistellungs"
                         "aufträge auf die Banken verteilen, in denen die Erträge anfallen; ggf. Gewinne "
                         "ins nächste Jahr verschieben."))
    if f["depot_verlierer"] and (f["realisierte_gewinne"] > 0 or ueber > 0):
        worst = f["depot_verlierer"][0]
        pot = min(abs(worst["gain_abs"]), max(f["realisierte_gewinne"], ueber))
        tips.append(_tip("tax-loss-harvest", "kapital", "hoch",
                         "Verluste gegen Gewinne gegenrechnen (Tax-Loss-Harvesting)",
                         f"{worst['name']} liegt {_eur(worst['gain_abs'])} im Minus. Ein Verkauf noch "
                         f"in {f['year']} senkt die steuerpflichtigen Gewinne um bis zu {_eur(pot)} "
                         f"(~{_eur(pot * eff)} weniger Steuer). Rückkauf danach möglich – "
                         "keine deutsche Sperrfrist, aber Spesen/Spread beachten."))
    if f["depot_gewinner"] and f["realisierte_gewinne"] < 0:
        tips.append(_tip("verlusttopf-nutzen", "kapital", "mittel",
                         "Realisierten Verlusttopf mit Gewinnen füllen",
                         f"Du hast in {f['year']} einen realisierten Verlust von "
                         f"{_eur(f['realisierte_gewinne'])}. Wer jetzt Gewinnerpositionen (teilweise) "
                         "verkauft, verrechnet die Gewinne steuerfrei damit."))
    if f["vorabpauschale_steuerpflichtig"] > 0:
        tips.append(_tip("vorabpauschale-liquiditaet", "kapital", "info",
                         "Vorabpauschale im Januar einplanen",
                         f"Für {f['year']} rund {_eur(f['vorabpauschale_steuerpflichtig'])} steuer"
                         "pflichtig – die Bank bucht die Steuer Anfang des Folgejahres automatisch vom "
                         "Verrechnungskonto ab. Genug Liquidität dort halten."))


def _tips_kapital_ch(f, tips):
    tips.append(_tip("ch-kapitalgewinne", "kapital", "info",
                     "Private Kapitalgewinne sind in der Schweiz steuerfrei",
                     "Kursgewinne auf Wertschriften im Privatvermögen werden nicht besteuert – "
                     "Tax-Loss-Harvesting bringt hier nichts. Achte aber darauf, nicht als "
                     "'gewerbsmässiger Wertschriftenhändler' eingestuft zu werden (häufiges Traden, "
                     "Fremdfinanzierung, kurze Haltedauer)."))
    if f.get("dividenden_jahr"):
        tips.append(_tip("ch-dividenden", "kapital", "mittel",
                         "Dividenden sind steuerbares Einkommen",
                         f"Rund {_eur(f['dividenden_jahr'])} Ausschüttungen in {f['year']} zählen zum "
                         "steuerbaren Einkommen (Verrechnungssteuer 35 % wird bei korrekter Deklaration "
                         "zurückerstattet). Thesaurierende Fonds ändern daran nichts – der Ertrag gilt "
                         "trotzdem als zugeflossen."))


def _mtr_hint(f, betrag: float) -> str:
    """"…bei deinem Grenzsteuersatz X % ≈ Y € weniger Steuer" - nur wenn der
    Satz im Profil hinterlegt ist."""
    mtr = f.get("marginal_tax_rate", 0.0)
    if not mtr or betrag <= 0:
        return ""
    pct = f"{mtr * 100:.0f}"
    return f" Bei deinem Grenzsteuersatz ({pct} %) sind das grob {_eur(betrag * mtr)} weniger Steuer."


def _tips_finanzen_de(f, tips):
    s = f["kategorie_summen"]
    married = f.get("filing_married")
    handw = _cat_total(s, "handwerk", "reparatur", "sanierung")
    if handw > 0:
        abzug = min(handw * 0.20, HANDWERKER_MAX_ABZUG)
        tips.append(_tip("35a-handwerker", "finanzen", "mittel",
                         "Handwerkerleistungen: §35a nutzen",
                         f"~{_eur(handw)} in handwerksnahen Kategorien. 20 % der **Lohn**kosten "
                         f"(nicht Material) sind direkt von der Steuer abziehbar, bis {_eur(HANDWERKER_MAX_ABZUG)}/Jahr "
                         f"(hier grob bis {_eur(abzug)}). Rechnungen unbar bezahlen und aufheben."))
    haus = _cat_total(s, "haushaltshilfe", "reinigung", "garten", "pflege")
    if haus > 0:
        tips.append(_tip("35a-haushaltsnah", "finanzen", "info",
                         "Haushaltsnahe Dienstleistungen: §35a",
                         f"~{_eur(haus)} – 20 % absetzbar bis {_eur(HAUSHALTSNAHE_MAX_ABZUG)}/Jahr "
                         "(Reinigung, Garten, Betreuung). Nur mit Rechnung und Überweisung."))
    spenden = _cat_total(s, "spende", "spenden")
    if spenden > 0:
        tips.append(_tip("spenden", "finanzen", "info",
                         "Spenden als Sonderausgaben",
                         f"~{_eur(spenden)} Spenden – bis 20 % des Gesamtbetrags der Einkünfte "
                         "abziehbar. Zuwendungsbestätigungen sammeln (bis 300 € reicht der Kontoauszug)."))
    fortb = _cat_total(s, "fortbildung", "weiterbildung", "kurs", "seminar", "fachbuch")
    if fortb > 0:
        tips.append(_tip("werbungskosten", "finanzen", "info",
                         "Fortbildung als Werbungskosten",
                         f"~{_eur(fortb)} – beruflich veranlasste Fortbildung, Fachliteratur, "
                         "Arbeitsmittel zählen über den Pauschbetrag (1.230 €) hinaus als Werbungskosten."
                         + _mtr_hint(f, max(0.0, fortb - 1230))))
    tips.append(_tip("homeoffice", "finanzen", "info",
                     "Homeoffice-Pauschale nicht vergessen",
                     f"6 €/Arbeitstag, bis {_eur(HOMEOFFICE_MAX)}/Jahr – auch ohne separates "
                     "Arbeitszimmer. In der Anlage N eintragen." + _mtr_hint(f, HOMEOFFICE_MAX)))
    if not any("altersvorsorge" in k or "rürup" in k or "riester" in k for k in s):
        hoechst = "~58.688 € (zusammen veranlagt)" if married else "~29.344 €"
        tips.append(_tip("altersvorsorge", "finanzen", "info",
                         "Altersvorsorge senkt das zu versteuernde Einkommen",
                         f"Rürup-(Basisrente-)Beiträge sind zu ~100 % als Sonderausgaben abziehbar "
                         f"(Höchstbetrag 2025 {hoechst}). Für Angestellte oft auch betriebliche "
                         "Altersvorsorge per Entgeltumwandlung interessant."
                         + _mtr_hint(f, 6000)))


def _tips_finanzen_ch(f, tips):
    s = f["kategorie_summen"]
    has_3a = any("3a" in k or "säule" in k or "saeule" in k or "vorsorge" in k for k in s)
    dritte_a = _cat_total(s, "3a", "säule", "saeule", "vorsorge")
    if dritte_a < SAEULE_3A_MAX_MIT_PK - 100:
        rest = round(SAEULE_3A_MAX_MIT_PK - dritte_a, 0)
        mtr = f.get("marginal_tax_rate", 0.0) or 0.30
        pct = f"{mtr * 100:.0f}"
        tips.append(_tip("ch-saeule-3a", "finanzen", "hoch",
                         "Säule 3a bis zum Maximum einzahlen",
                         f"{'Bisher ~' + _eur(dritte_a) + ' erkannt. ' if has_3a else ''}"
                         f"Erwerbstätige mit Pensionskasse dürfen {year_str(f)} bis "
                         f"~{SAEULE_3A_MAX_MIT_PK:,.0f} CHF einzahlen (jährlich prüfen). Der Betrag geht "
                         f"direkt vom steuerbaren Einkommen ab – bei Grenzsteuersatz {pct} % sind das "
                         f"grob {_eur(rest * mtr)} weniger Steuer. Einzahlung bis 31.12."))
    tips.append(_tip("ch-3a-gestaffelt", "finanzen", "info",
                     "3a-Konten gestaffelt beziehen",
                     "Mehrere 3a-Konten (2–5) und über verschiedene Steuerjahre gestaffelt beziehen "
                     "senkt die Progression bei der Kapitalauszahlung deutlich."))
    tips.append(_tip("ch-pk-einkauf", "finanzen", "mittel",
                     "Pensionskassen-Einkauf prüfen",
                     "Freiwillige Einkäufe in die Pensionskasse sind voll vom steuerbaren Einkommen "
                     "abziehbar – lohnend in einkommensstarken Jahren, aber 3-Jahres-Sperrfrist vor "
                     "Kapitalbezug beachten."))
    beruf = _cat_total(s, "pendel", "ov", "öv", "arbeitsweg", "fortbildung", "weiterbildung")
    if beruf > 0:
        tips.append(_tip("ch-berufskosten", "finanzen", "info",
                         "Berufskosten geltend machen",
                         f"~{_eur(beruf)} in arbeitsbezogenen Kategorien – Arbeitsweg (ÖV-Abo, "
                         "gedeckelt), auswärtige Verpflegung und Weiterbildung sind abziehbar."))
    nw = f.get("nettovermoegen")
    if nw and nw > 100000:
        tips.append(_tip("ch-vermoegenssteuer", "finanzen", "info",
                         "Vermögenssteuer im Blick behalten",
                         f"Nettovermögen ~{_eur(nw)}. Die Schweiz besteuert das Vermögen jährlich "
                         "(kantonal unterschiedlich, grob 0,1–0,5 %). 3a-Guthaben zählt bis zum Bezug "
                         "nicht dazu – ein weiterer Punkt für die Säule 3a."))


def year_str(f) -> str:
    return str(f.get("year", date.today().year))


# --------------------------------------------------------------------------
# Freitext-Auskunft (lokale Ollama, mit Faktenkontext)
# --------------------------------------------------------------------------
_ASK_SYSTEM = (
    "Du bist ein nüchterner Steuer-Assistent für Privatpersonen in {country}. "
    "Du gibst allgemeine Orientierung, KEINE verbindliche Steuerberatung, und sagst das "
    "auch klar. Nutze die bereitgestellten Zahlen des Nutzers, erfinde keine dazu. "
    "Antworte kurz, konkret und auf Deutsch; nenne, wo sinnvoll, den Paragraphen bzw. "
    "das Formular. Wenn die Frage Fachberatung braucht, sag das."
)


def answer_question(db, settings, space_id: int, question: str, year: int) -> dict:
    question = (question or "").strip()
    if not question:
        return {"ok": False, "reply": "Bitte eine Frage eingeben."}
    model = settings.ollama_model or settings.beleg_chat_model
    if not (settings.ollama_url and model):
        return {"ok": False, "reply": "Für Steuer-Fragen fehlt ein Ollama-Modell (Einstellungen → KI-Assistent)."}

    data = generate_tips(db, settings, space_id, year)
    f = data["facts"]
    ctx = (
        f"Land: {data['country']}. Jahr: {year}.\n"
        f"Geschätzte steuerpflichtige Kapitalerträge: {_eur(f['kapitalertrag_geschaetzt'])} "
        f"(Sparerpauschbetrag {_eur(f['sparerpauschbetrag'])}, davon frei: {_eur(f['freibetrag_rest'])}).\n"
        f"Realisierte Gewinne {year}: {_eur(f['realisierte_gewinne'])}. "
        f"Vorabpauschale steuerpflichtig: {_eur(f['vorabpauschale_steuerpflichtig'])}. "
        f"Dividenden {year}: {_eur(f['dividenden_jahr'])}.\n"
        f"Unrealisierte Verlustpositionen: "
        + (", ".join(f"{r['name']} ({_eur(r['gain_abs'])})" for r in f["depot_verlierer"][:5]) or "keine")
        + ".\nAktuelle Tipps des Systems:\n- "
        + "\n- ".join(t["title"] for t in data["tips"][:8])
    )
    try:
        reply = ollama_client.chat(
            settings.ollama_url, model,
            [{"role": "system", "content": _ASK_SYSTEM.replace("{country}", data["country"]) + "\n\n" + ctx},
             {"role": "user", "content": question}],
            timeout=120,
        ).strip()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reply": f"Die lokale KI ist gerade nicht erreichbar: {exc}"}
    return {"ok": True, "reply": reply or "Dazu habe ich keine Einschätzung."}
