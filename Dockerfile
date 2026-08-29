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

# Sprach-Ein-/Ausgabe (faster-whisper + Piper + openWakeWord) ist BEWUSST
# nicht im Standard-Image: die Kette hat auf python:3.14-slim (linux/amd64)
# keine vollstaendigen Wheels und liess den CI-Build fehlschlagen. Wer
# Sprachsteuerung will, baut ein eigenes Image mit
# `pip install -r requirements-voice.txt` ODER faehrt einen lokalen
# Whisper-/Piper-HTTP-Dienst und setzt STT_BACKEND=http / TTS_BACKEND=http.
# Ohne die Pakete bleibt /api/smarthome/voice/* im Stub-Modus (HTTP 501).

# Offizielles Scalable-Capital-CLI-Binary ("sc") fuer die Investments-
# Anbindung (siehe backend/app/scalable_sync.py) - kein REST-API verfuegbar,
# nur dieses Rust-Binary. Download per Python statt curl/wget (python:slim
# hat keins von beiden vorinstalliert, keine zusaetzliche apt-Abhaengigkeit
# noetig). Checksumme fest hier hinterlegt (nicht zur Build-Zeit von
# github.com nachgeladen) statt der mitgelieferten SHA256SUMS-Datei zu
# vertrauen, die selbst veraenderlich waere - bei einem Versions-Update muss
# der Hash hier bewusst mit aktualisiert werden.
# Quelle: https://github.com/ScalableCapital/scalable-cli/releases/tag/v1.0.0
RUN python -c "import urllib.request; urllib.request.urlretrieve('https://github.com/ScalableCapital/scalable-cli/releases/download/v1.0.0/sc-v1.0.0-linux-x86_64-gnu.tar.gz', '/tmp/sc.tar.gz')" \
 && echo "f572bf49b853be35c56bc59b7ab2f4576be2ed524a1a3a0b0658ed69a54a6180  /tmp/sc.tar.gz" | sha256sum -c - \
 && tar xzf /tmp/sc.tar.gz -C /tmp \
 && mv /tmp/sc-v1.0.0-linux-x86_64-gnu/sc /usr/local/bin/sc \
 && chmod +x /usr/local/bin/sc \
 && rm -rf /tmp/sc.tar.gz /tmp/sc-v1.0.0-linux-x86_64-gnu

COPY backend/app ./app
COPY frontend /frontend

# Von GitHub Actions befuellt (siehe docker-publish.yml), lokal leer ("dev").
# Dient nur der Anzeige im Frontend, damit erkennbar ist, ob Watchtower
# wirklich aktualisiert hat oder ob eine sichtbare Aenderung an einem alten
# Stand liegt - kein Einfluss auf die Anwendungslogik.
ARG GIT_SHA=dev
ARG BUILD_DATE=""
ENV GIT_SHA=${GIT_SHA}
ENV BUILD_DATE=${BUILD_DATE}
# Steht zusaetzlich als OCI-Label im Image selbst, damit sich der SHA auch von
# aussen ueber die Registry ablesen laesst (Grundlage fuer den
# "veraltet"-Hinweis) - nicht nur aus dem laufenden Container heraus.
LABEL org.opencontainers.image.revision=${GIT_SHA}

ENV DATA_DIR=/data
ENV FRONTEND_DIR=/frontend
# Scalable-CLI legt Config+Session komplett unter $XDG_CONFIG_HOME/scalable-cli/
# ab (session.json, config.toml, auth-signing-key.json - alles ein Ordner,
# siehe scalable_sync.py-Docstring) - nach /data zeigen, damit der einmalige
# Login (siehe ROADMAP) einen Container-Neustart/-Redeploy uebersteht.
ENV XDG_CONFIG_HOME=/data/scalable-cli-home

VOLUME ["/data"]
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
