import base64

import fitz  # PyMuPDF

MAX_PDF_PAGES_AS_IMAGES = 3
MAX_TEXT_CHARS = 8000


def extract_pdf(data: bytes) -> tuple[str | None, list[str]]:
    """Liest ein PDF aus. Enthält es durchsuchbaren Text (z.B. ein digital
    erzeugter Kontoauszug/eine Wertpapierabrechnung), wird der Text zurückgegeben.
    Andernfalls (z.B. ein eingescannter Beleg) werden die ersten Seiten als
    PNG-Bilder (base64) gerendert, damit ein Vision-Modell sie lesen kann."""
    doc = fitz.open(stream=data, filetype="pdf")
    text_parts = []
    for page in doc:
        page_text = page.get_text().strip()
        if page_text:
            text_parts.append(page_text)

    if text_parts:
        return "\n".join(text_parts)[:MAX_TEXT_CHARS], []

    images = []
    for page in doc[:MAX_PDF_PAGES_AS_IMAGES]:
        pix = page.get_pixmap(dpi=150)
        images.append(base64.b64encode(pix.tobytes("png")).decode())
    return None, images
