"""Steuer-Export: CSV und PDF für einen gefilterten Buchungszeitraum - für die
Vorbereitung beim Steuerberater/ELSTER gedacht, kein Buchhaltungsformat.
PyMuPDF ist ohnehin schon Abhängigkeit (Beleg-Texterkennung, siehe
document_extract.py), erspart eine weitere PDF-Bibliothek nur fürs Rendern
einer einfachen Tabelle."""

import csv
import io

import pymupdf

CSV_HEADER = ["Datum", "Betrag", "Konto", "Geschäftlich/Privat", "Kategorie", "Beschreibung", "Notiz", "Beleg"]


def build_csv(transactions) -> str:
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(CSV_HEADER)
    for t in transactions:
        writer.writerow([
            t.date.isoformat(),
            f"{t.amount:.2f}".replace(".", ","),
            t.account.name if t.account else "",
            "Geschäftlich" if (t.account and t.account.is_business) else "Privat",
            t.category.name if t.category else "",
            t.description or "",
            t.notes or "",
            t.receipt_filename or "",
        ])
    return output.getvalue()


PAGE_WIDTH, PAGE_HEIGHT = 595, 842
MARGIN = 36
ROW_HEIGHT = 16
COLS = [
    ("Datum", MARGIN),
    ("Betrag", MARGIN + 60),
    ("Konto", MARGIN + 120),
    ("Kategorie", MARGIN + 210),
    ("Beschreibung", MARGIN + 300),
    ("Beleg", MARGIN + 470),
]


def build_pdf(transactions, title: str, subtitle: str = "") -> bytes:
    """Baut eine einfache, paginierte Tabelle - kein Layout-Framework, nur
    direktes Text-/Linien-Zeichnen auf jeder Seite."""
    doc = pymupdf.open()
    state = {"page": None, "y": 0.0}

    def new_page():
        page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        y = MARGIN
        page.insert_text((MARGIN, y), title, fontsize=14, fontname="helv")
        y += 20
        if subtitle:
            page.insert_text((MARGIN, y), subtitle, fontsize=9, fontname="helv", color=(0.4, 0.4, 0.4))
            y += 16
        y += 6
        for label, x in COLS:
            page.insert_text((x, y), label, fontsize=9, fontname="helv")
        y += 4
        page.draw_line((MARGIN, y), (PAGE_WIDTH - MARGIN, y))
        y += ROW_HEIGHT
        state["page"] = page
        state["y"] = y

    new_page()
    total = 0.0
    for t in transactions:
        if state["y"] > PAGE_HEIGHT - MARGIN - ROW_HEIGHT:
            new_page()
        total += t.amount
        values = [
            t.date.strftime("%d.%m.%Y"),
            f"{t.amount:.2f} EUR".replace(".", ","),
            (t.account.name if t.account else "")[:16],
            (t.category.name if t.category else "")[:16],
            (t.description or "")[:34],
            (t.receipt_filename or "-")[:14],
        ]
        page = state["page"]
        for (label, x), value in zip(COLS, values):
            page.insert_text((x, state["y"]), value, fontsize=8, fontname="helv")
        state["y"] += ROW_HEIGHT

    if state["y"] > PAGE_HEIGHT - MARGIN - ROW_HEIGHT * 2:
        new_page()
    state["y"] += 8
    page = state["page"]
    page.draw_line((MARGIN, state["y"]), (PAGE_WIDTH - MARGIN, state["y"]))
    state["y"] += ROW_HEIGHT
    page.insert_text((MARGIN, state["y"]), f"Summe: {total:.2f} EUR".replace(".", ","), fontsize=10, fontname="helv")

    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()
