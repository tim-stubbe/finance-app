FROM python:3.14-slim

WORKDIR /app

COPY backend/requirements.txt .

# pip selbst aktualisieren - die im Basis-Image mitgelieferte Version hat
# bekannte Schwachstellen.
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt \
 # fints 5.0.0 verlangt "lxml~=6.0.2" und schliesst damit 6.1.0 aus. In 6.0.4
 # steckt aber CVE-2026-41066 (XXE): beim Parsen von XML aus nicht
 # vertrauenswuerdiger Quelle koennen lokale Dateien ausgelesen werden. Genau
 # dieser Pfad ist ueber fints/camt_parser.py erreichbar, wenn eine Bank
 # CAMT-Umsaetze liefert. Die Einschraenkung von fints ist nur konservativ
 # gesetzt - fints laeuft mit 6.1.0 nachweislich einwandfrei -, daher wird lxml
 # bewusst nachtraeglich ohne Abhaengigkeitsaufloesung angehoben.
 && pip install --no-cache-dir --no-deps lxml==6.1.0

COPY backend/app ./app
COPY frontend /frontend

ENV DATA_DIR=/data
ENV FRONTEND_DIR=/frontend

VOLUME ["/data"]
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
