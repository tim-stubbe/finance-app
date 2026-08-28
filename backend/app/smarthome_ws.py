"""Live-Zustaende von Home Assistant per WebSocket.

Ein Hintergrund-Thread (Kies ist durchgehend synchron, kein async) haelt eine
WebSocket-Verbindung zur HA-API offen, seedet einmalig alle States und
aktualisiert danach einen In-Memory-Cache bei jedem `state_changed`-Event.
Die Smart-Home-Endpunkte lesen bevorzugt aus diesem Cache (schnell + live)
und fallen auf REST zurueck, wenn er nicht frisch ist.

Zusaetzlich ein einfacher Broadcast an Server-Sent-Events-Abnehmer
(`GET /api/smarthome/events`), damit die Web-UI ohne eigenen WebSocket-Client
live nachzieht.
"""

import json
import queue
import threading
import time

try:
    import websocket  # websocket-client
except ImportError:  # pragma: no cover - Paket optional beim lokalen Arbeiten
    websocket = None

_STALE_AFTER = 600  # s ohne Event -> Cache gilt nicht mehr als "live"


class _Cache:
    def __init__(self):
        self.lock = threading.Lock()
        self.states = {}
        self.connected = False
        self.last_event_at = 0.0
        self.subscribers = []

    def replace_all(self, states_list):
        with self.lock:
            self.states = {s["entity_id"]: s for s in states_list if s.get("entity_id")}
            self.last_event_at = time.time()

    def update_one(self, entity_id, new_state):
        if not entity_id:
            return
        with self.lock:
            if new_state is None:
                self.states.pop(entity_id, None)
            else:
                self.states[entity_id] = new_state
            self.last_event_at = time.time()
        self._broadcast({
            "entity_id": entity_id,
            "state": (new_state or {}).get("state"),
            "friendly_name": (new_state or {}).get("attributes", {}).get("friendly_name"),
        })

    def snapshot(self):
        with self.lock:
            return list(self.states.values())

    def is_live(self):
        with self.lock:
            return self.connected and (time.time() - self.last_event_at) < _STALE_AFTER

    def _broadcast(self, payload):
        for q in list(self.subscribers):
            try:
                q.put_nowait(payload)
            except queue.Full:
                self.remove_subscriber(q)

    def add_subscriber(self):
        q = queue.Queue(maxsize=200)
        with self.lock:
            self.subscribers.append(q)
        return q

    def remove_subscriber(self, q):
        with self.lock:
            try:
                self.subscribers.remove(q)
            except ValueError:
                pass


_cache = _Cache()
_thread = None
_get_conn = None  # callable -> (url, token) | (None, None)


def start(get_conn):
    """Aus main.py beim Import aufgerufen (analog zum Scheduler)."""
    global _thread, _get_conn
    _get_conn = get_conn
    if websocket is None or _thread is not None:
        return
    _thread = threading.Thread(target=_run, name="ha-ws", daemon=True)
    _thread.start()


def _ws_url(http_url: str) -> str:
    u = (http_url or "").rstrip("/")
    if u.startswith("https://"):
        return "wss://" + u[8:] + "/api/websocket"
    if u.startswith("http://"):
        return "ws://" + u[7:] + "/api/websocket"
    return "ws://" + u + "/api/websocket"


def _run():
    while True:
        url = token = None
        try:
            url, token = _get_conn()
        except Exception:  # noqa: BLE001
            pass
        if not url or not token:
            _cache.connected = False
            time.sleep(60)
            continue
        try:
            _session(_ws_url(url), token)
        except Exception:  # noqa: BLE001 - jede Stoerung -> neu verbinden
            pass
        _cache.connected = False
        time.sleep(15)


def _session(ws_url, token):
    # TLS wird normal geprueft - genau wie die HA-REST-Aufrufe in ha_client.py
    # (requests mit verify=True). Ein selbst signiertes HA laeuft im LAN
    # ueblicherweise ohnehin ueber http:// -> dann ist das hier irrelevant.
    ws = websocket.create_connection(ws_url, timeout=15)
    ping_id = 10
    try:
        if json.loads(ws.recv()).get("type") != "auth_required":
            return
        ws.send(json.dumps({"type": "auth", "access_token": token}))
        if json.loads(ws.recv()).get("type") != "auth_ok":
            return
        ws.send(json.dumps({"id": 1, "type": "get_states"}))
        ws.send(json.dumps({"id": 2, "type": "subscribe_events", "event_type": "state_changed"}))
        _cache.connected = True
        ws.settimeout(30)
        while True:
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                ping_id += 1
                ws.send(json.dumps({"id": ping_id, "type": "ping"}))
                continue
            if not raw:
                break
            msg = json.loads(raw)
            mtype = msg.get("type")
            if mtype == "result" and msg.get("id") == 1 and msg.get("success"):
                _cache.replace_all(msg.get("result") or [])
            elif mtype == "event":
                data = msg.get("event", {}).get("data", {})
                _cache.update_one(data.get("entity_id"), data.get("new_state"))
    finally:
        try:
            ws.close()
        except Exception:  # noqa: BLE001
            pass


# --- oeffentliche API fuer die Endpunkte ---
def cached_states():
    """HA-/states-formige Liste, oder None wenn der Cache nicht frisch ist."""
    return _cache.snapshot() if _cache.is_live() else None


def is_live() -> bool:
    return _cache.is_live()


def events_stream():
    """SSE-Generator - liefert je Zustandsaenderung eine data:-Zeile."""
    q = _cache.add_subscriber()
    try:
        yield b": connected\n\n"
        while True:
            try:
                payload = q.get(timeout=20)
                yield ("data: " + json.dumps(payload) + "\n\n").encode("utf-8")
            except queue.Empty:
                yield b": ping\n\n"
    finally:
        _cache.remove_subscriber(q)
