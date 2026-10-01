from datetime import date, datetime, timedelta

from app import crud, models
from app.database import SessionLocal


def _event(uid: str, title: str, start: datetime, minutes: int = 45):
    return models.CalendarEvent(
        uid=uid,
        title=title,
        start=start,
        end=start + timedelta(minutes=minutes),
        all_day=False,
        pending_delete=False,
    )


def test_webuntis_lessons_do_not_create_calendar_conflicts():
    db = SessionLocal()
    try:
        start = datetime.utcnow() + timedelta(days=1)
        db.add_all([
            _event("webuntis-101@kies", "Unterricht", start),
            _event("webuntis-102@kies", "Unterricht", start),
        ])
        db.commit()

        assert crud.detect_calendar_conflicts(db) == []
    finally:
        db.close()


def test_regular_overlapping_events_still_create_a_conflict():
    db = SessionLocal()
    try:
        start = datetime.utcnow() + timedelta(days=1)
        db.add_all([
            _event("private-1", "Arzt", start),
            _event("private-2", "Werkstatt", start + timedelta(minutes=15)),
        ])
        db.commit()

        conflicts = crud.detect_calendar_conflicts(db)
        assert len(conflicts) == 1
        assert {conflicts[0]["event_a_title"], conflicts[0]["event_b_title"]} == {"Arzt", "Werkstatt"}
    finally:
        db.close()


def test_morning_briefing_omits_school_during_active_trip():
    db = SessionLocal()
    try:
        space = db.query(models.Space).first()
        db.add(models.Trip(space_id=space.id, name="Urlaub", start_date=date.today(),
                           end_date=date.today() + timedelta(days=4)))
        today_at_ten = datetime.combine(date.today(), datetime.min.time()) + timedelta(hours=10)
        db.add_all([
            _event("webuntis-urlaub@kies", "Unterricht", today_at_ten),
            _event("urlaub-ausflug", "Ausflug", today_at_ten, minutes=90),
        ])
        db.commit()

        text = crud.build_morning_briefing(db, space.id)
        assert "Reise „Urlaub“ läuft" in text
        assert "Unterricht" not in text
        assert "Ausflug" in text
    finally:
        db.close()
