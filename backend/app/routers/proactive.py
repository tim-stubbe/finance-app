"""Proaktive Vorschläge im Browser (siehe proactive.py, models.ProactiveProposal).

Damit Tim die strukturierten Vorschläge des Assistenten auch im Hub sieht und
beantworten kann, nicht nur per Telegram-Button (siehe [[feedback-push-not-pull]]).
"""
import json

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import auth, models, proactive, schemas
from ..database import get_db

proactive_router = APIRouter(prefix="/api/proactive")


def _proposal_dict(p: models.ProactiveProposal) -> dict:
    opts = json.loads(p.options_json or "[]")
    return {
        "id": p.id,
        "kind": p.kind,
        "urgency": p.urgency,
        "title": p.title,
        "body": p.body or "",
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "options": [{"key": o["key"], "label": o["label"]} for o in opts],
    }


@proactive_router.get("/proposals")
def list_open_proposals(db: Session = Depends(get_db)):
    rows = (db.query(models.ProactiveProposal)
            .filter(models.ProactiveProposal.status == "offen")
            .order_by(models.ProactiveProposal.created_at.desc())
            .limit(20).all())
    return [_proposal_dict(p) for p in rows]


@proactive_router.post("/proposals/{proposal_id}/answer")
def answer_proposal(proposal_id: int, data: schemas.ProactiveAnswerIn,
                    db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    result = proactive.answer(db, settings, proposal_id, data.key)
    return {"result": result}
