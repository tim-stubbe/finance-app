"""Zentrale Besitz-Prüfung für Multi-User Phase 2.

Modell (mit Tim abgestimmt, 2026-08-30): **ein Besitzer pro Bereich**.
`Space.owner_id` zeigt auf `users.id`; alles, was per `space_id` an einem
Bereich hängt (Konten, Buchungen, Ziele, Budgets ...), gehört damit genau
diesem Nutzer. Kein Teilen, kein Rollensystem.

Diese erste Scheibe verdrahtet nur die im Sicherheits-Audit (2026-08-30,
[[project-security-audit-2026-08]]) als IDOR markierten Bereichs-Endpunkte
(`/api/spaces`, `/api/spaces/{id}/select`). `sync.py` bleibt vorerst außen
vor: dessen Auth ist ein instanzweites Shared Secret ohne Nutzerbezug -
echte Trennung dort braucht zuerst pro-Nutzer-Sync-Secrets.

`NULL`-`owner_id` (Altbestand vor der Migration) wird als "gehört jedem
angemeldeten Nutzer" behandelt, damit die Migration nichts sperrt, bevor
der Bootstrap in `main.py` die Spalte aufgefüllt hat. Ist erst einmal ein
Besitzer gesetzt, greift die strikte Prüfung.

Fehlerfall ist bewusst **404, nicht 403**: die Existenz eines fremden
Bereichs soll nicht durchsickern.
"""

from fastapi import HTTPException

from . import models


def owns_space(user: "models.User | None", space: "models.Space | None") -> bool:
    """True, wenn `user` auf `space` zugreifen darf. NULL-owner_id (noch nicht
    migriert) gilt als Zugriff erlaubt; sonst muss owner_id == user.id sein."""
    if space is None:
        return False
    if user is None:
        return False
    if space.owner_id is None:
        return True
    return space.owner_id == user.id


def require_owned_space(db, user: "models.User", space_id) -> "models.Space":
    """Lädt den Bereich und stellt sicher, dass er `user` gehört. 404, wenn er
    nicht existiert ODER einem anderen Nutzer gehört (kein Existenz-Leak)."""
    space = db.query(models.Space).filter(models.Space.id == space_id).first()
    if not owns_space(user, space):
        raise HTTPException(status_code=404, detail="Bereich nicht gefunden")
    return space


def visible_spaces(db, user: "models.User") -> "list[models.Space]":
    """Alle Bereiche, die `user` sehen darf - die eigenen plus noch nicht
    migrierte (owner_id NULL)."""
    return (
        db.query(models.Space)
        .filter(
            (models.Space.owner_id == user.id) | (models.Space.owner_id.is_(None))
        )
        .order_by(models.Space.id)
        .all()
    )


def require_owned_object(db, user: "models.User", model, obj_id):
    """Generische Variante für Zeilen mit `space_id`: lädt `model[obj_id]`,
    löst den Bereich auf und prüft den Besitz. Für `space_id IS NULL`
    (bereichsübergreifende Ziele o.ä.) gilt Zugriff erlaubt - solche Objekte
    hängen an keinem Bereich und bleiben wie bisher für jeden angemeldeten
    Nutzer sichtbar. 404 bei fehlend/fremd."""
    obj = db.query(model).filter(model.id == obj_id).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="Nicht gefunden")
    space_id = getattr(obj, "space_id", None)
    if space_id is None:
        return obj
    require_owned_space(db, user, space_id)
    return obj
