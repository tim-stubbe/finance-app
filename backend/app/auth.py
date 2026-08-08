import secrets

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from . import models
from .database import get_db


def get_or_create_settings(db: Session) -> models.Settings:
    settings = db.query(models.Settings).filter(models.Settings.id == 1).first()
    if not settings:
        settings = models.Settings(id=1, secret_key=secrets.token_hex(32))
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def get_active_space_id(request: Request, db: Session = Depends(get_db)) -> int:
    space_id = request.session.get("space_id")
    if not space_id:
        # Gibt es nur einen Bereich, automatisch übernehmen statt eine
        # Bereichsauswahl anzuzeigen - die App hat keine UI mehr dafür, weil ein
        # einzelner Nutzer (hier: Einzelunternehmer) ohnehin nur einen Bereich
        # braucht. Bei mehreren Bereichen (z.B. nach manuellem Anlegen über die
        # API) bleibt die alte Fehlermeldung als Sicherheitsnetz bestehen.
        spaces = db.query(models.Space).all()
        if len(spaces) == 1:
            space_id = spaces[0].id
            request.session["space_id"] = space_id
            return space_id
        raise HTTPException(status_code=400, detail="Kein Bereich ausgewählt")
    return space_id
