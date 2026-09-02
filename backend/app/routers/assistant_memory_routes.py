"""Assistenten-Gedächtnis im Browser (siehe assistant_memory.py).

Read-only-Liste + Einzellöschung, damit Tim ohne Telegram-`/gedächtnis` sehen
kann, was der Assistent sich gemerkt hat, und Einträge wegwerfen kann.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import assistant_memory
from ..database import get_db

assistant_memory_router = APIRouter(prefix="/api/assistant-memory")


@assistant_memory_router.get("")
def list_memory(db: Session = Depends(get_db)):
    rows = assistant_memory.list_memories(db)
    return [{
        "id": r.id,
        "text": r.text,
        "category": r.category,
        "source": r.source,
        "importance": r.importance,
        "pinned": bool(r.pinned),
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]


@assistant_memory_router.delete("/{mem_id}")
def delete_memory(mem_id: int, db: Session = Depends(get_db)):
    ok = assistant_memory.forget_memory(db, mem_id=mem_id)
    db.commit()
    return {"ok": ok}
