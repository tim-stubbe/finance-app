"""Kleiner lokaler HTTP->SIP-Anrufdienst für Kies.

Die Telefonleitung steckt in Asterisk. Das kann zunächst ein FRITZ!Box-
IP-Telefon und später unverändert ein VoLTE-SIM-Gateway sein.
"""
import os
import re
import socket
import subprocess
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI()
SOUNDS = Path("/sounds")
TOKEN = os.environ.get("CALL_GATEWAY_TOKEN", "")
AMI_SECRET = os.environ.get("AMI_SECRET", "")
NUMBER_RE = re.compile(r"^\+?[0-9]{6,20}$")


class CallIn(BaseModel):
    to: str
    text: str


def ami(action: str) -> str:
    with socket.create_connection(("asterisk", 5038), timeout=10) as sock:
        payload = (f"Action: Login\r\nUsername: kies\r\nSecret: {AMI_SECRET}\r\n\r\n"
                   + action + "\r\nAction: Logoff\r\n\r\n")
        sock.sendall(payload.encode())
        sock.settimeout(5)
        chunks = []
        try:
            while True:
                part = sock.recv(4096)
                if not part:
                    break
                chunks.append(part)
        except socket.timeout:
            pass
    return b"".join(chunks).decode("utf-8", "replace")


@app.get("/health")
def health():
    try:
        response = ami("Action: Ping\r\n\r\n")
        ready = "Response: Success" in response and "Ping: Pong" in response
    except (OSError, TimeoutError):
        ready = False
    return {"ok": ready, "backend": "asterisk-sip", "line_ready": ready}


@app.post("/call")
def call(data: CallIn, authorization: str | None = Header(None)):
    if not TOKEN or authorization != f"Bearer {TOKEN}":
        raise HTTPException(401, "Nicht autorisiert")
    number = data.to.replace(" ", "").replace("-", "")
    if not NUMBER_RE.fullmatch(number):
        raise HTTPException(400, "Ungültige Zielnummer")
    if not data.text.strip():
        raise HTTPException(400, "Leere Ansage")
    SOUNDS.mkdir(parents=True, exist_ok=True)
    name = "kies-" + uuid.uuid4().hex
    wav = SOUNDS / f"{name}.wav"
    subprocess.run(["espeak-ng", "-v", "de", "-s", "155", "-w", str(wav),
                    data.text[:1200]], check=True, timeout=30)
    response = ami(
        f"Action: Originate\r\nChannel: PJSIP/{number}@outbound\r\n"
        f"Application: Playback\r\nData: custom/{name}\r\n"
        "CallerID: Kies\r\nAsync: true\r\n\r\n")
    if "Response: Error" in response:
        raise HTTPException(502, "Telefonleitung hat den Anruf abgelehnt")
    # Alte Ansagen werden bei späteren Aufrufen entfernt, die aktuelle bleibt
    # sicher lange genug für den asynchronen Anruf bestehen.
    cutoff = time.time() - 86400
    for old in SOUNDS.glob("kies-*.wav"):
        if old != wav and old.stat().st_mtime < cutoff:
            old.unlink(missing_ok=True)
    return {"ok": True}
