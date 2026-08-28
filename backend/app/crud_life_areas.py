"""Business-Projekte (Nebenprojekte), Leben (persönliche Lebensbereiche) und
Wunschliste - fünfter Schritt der crud.py-Modularisierung (siehe
ROADMAP.md), analog zu crud_goals.py. Reine Verschiebung ohne
Verhaltensänderung: drei kleinere, voneinander unabhängige "Lebensbereiche"-
Domänen wurden hier zusammengefasst statt drei Mini-Module anzulegen.

crud.py importiert alle hier definierten Namen zurück, damit jeder
bestehende `crud.get_business_projects(...)`-Aufrufstil in main.py/
routers/ unverändert weiterfunktioniert (auch der private Helfer
_life_area_streak_and_history, den main.py direkt nutzt)."""

from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models, schemas


# ---------- Business-Projekte (Nebenprojekte) ----------
def _enrich_business_project(db: Session, project: models.BusinessProject) -> models.BusinessProject:
    """Setzt die nicht in der Tabelle gespeicherten Anzeige-Felder (offene
    Punkte, Konto-Name, Einnahmen) - gemeinsam genutzt von allen Funktionen,
    die ein BusinessProject nach außen geben, damit keine davon vergisst,
    eines der Felder zu befüllen."""
    project.open_issue_count = (
        db.query(models.BusinessIssue)
        .filter(models.BusinessIssue.project_id == project.id, models.BusinessIssue.resolved.is_(False))
        .count()
    )
    project.account_name = None
    project.income_this_month = 0.0
    project.income_total = 0.0
    if project.account_id:
        account = db.query(models.Account).filter(models.Account.id == project.account_id).first()
        if account:
            project.account_name = account.name
            month_start = date.today().replace(day=1)
            # Nur Einnahmen (positive Betraege), keine Umbuchungen - eine
            # interne Umbuchung auf das verknuepfte Konto ist kein Verdienst
            # des Projekts.
            base_query = (
                db.query(func.sum(models.Transaction.amount))
                .filter(
                    models.Transaction.account_id == project.account_id,
                    models.Transaction.amount > 0,
                    models.Transaction.is_transfer.is_(False),
                )
            )
            project.income_total = base_query.scalar() or 0.0
            project.income_this_month = base_query.filter(models.Transaction.date >= month_start).scalar() or 0.0
    return project


def get_business_projects(db: Session, include_inactive: bool = False) -> list[models.BusinessProject]:
    query = db.query(models.BusinessProject)
    if not include_inactive:
        query = query.filter(models.BusinessProject.active.is_(True))
    projects = query.order_by(models.BusinessProject.name).all()
    for p in projects:
        _enrich_business_project(db, p)
    return projects


def get_business_project(db: Session, project_id: int) -> models.BusinessProject | None:
    return db.query(models.BusinessProject).filter(models.BusinessProject.id == project_id).first()


def create_business_project(db: Session, data: schemas.BusinessProjectCreate) -> models.BusinessProject:
    project = models.BusinessProject(
        name=data.name, description=data.description, check_interval_days=data.check_interval_days,
        account_id=data.account_id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return _enrich_business_project(db, project)


def update_business_project(db: Session, project: models.BusinessProject, data: schemas.BusinessProjectUpdate) -> models.BusinessProject:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(project, key, value)
    db.commit()
    db.refresh(project)
    return _enrich_business_project(db, project)


def mark_business_project_checked(db: Session, project: models.BusinessProject) -> models.BusinessProject:
    project.last_checked_at = datetime.utcnow()
    db.commit()
    db.refresh(project)
    return _enrich_business_project(db, project)


def _business_issue_out(issue: models.BusinessIssue) -> schemas.BusinessIssueOut:
    return schemas.BusinessIssueOut(
        id=issue.id, project_id=issue.project_id,
        project_name=issue.project.name if issue.project else None,
        title=issue.title, notes=issue.notes, resolved=issue.resolved,
        created_at=issue.created_at, resolved_at=issue.resolved_at,
    )


def get_business_issues(db: Session, project_id: int | None = None, include_resolved: bool = False) -> list[schemas.BusinessIssueOut]:
    query = db.query(models.BusinessIssue)
    if project_id:
        query = query.filter(models.BusinessIssue.project_id == project_id)
    if not include_resolved:
        query = query.filter(models.BusinessIssue.resolved.is_(False))
    rows = query.order_by(models.BusinessIssue.created_at.desc()).all()
    return [_business_issue_out(r) for r in rows]


def create_business_issue(db: Session, project_id: int, title: str, notes: str | None = None) -> schemas.BusinessIssueOut:
    issue = models.BusinessIssue(project_id=project_id, title=title, notes=notes)
    db.add(issue)
    db.commit()
    db.refresh(issue)
    return _business_issue_out(issue)


def resolve_business_issue(db: Session, issue: models.BusinessIssue) -> schemas.BusinessIssueOut:
    issue.resolved = True
    issue.resolved_at = datetime.utcnow()
    db.commit()
    db.refresh(issue)
    return _business_issue_out(issue)


def find_business_project_by_name(db: Session, name_query: str) -> tuple[models.BusinessProject | None, str | None]:
    """Sucht ein aktives Projekt per (Teil-)Name - fürs Telegram-Freitext-
    Anlegen eines offenen Punkts, analog zu complete_todo_by_name. Gibt
    (projekt, error) zurück: error ist None bei Erfolg, sonst ein Text zum
    direkten Zurücksenden (kein Treffer / mehrdeutig)."""
    q = name_query.strip().lower()
    if not q:
        return None, "Kein Projektname angegeben."
    projects = db.query(models.BusinessProject).filter(models.BusinessProject.active.is_(True)).all()
    matches = [p for p in projects if q in p.name.lower()]
    if not matches:
        namen = ", ".join(p.name for p in projects) or "noch keine Projekte angelegt"
        return None, f"Kein Projekt mit „{name_query}“ gefunden. Vorhanden: {namen}"
    if len(matches) > 1:
        namen = ", ".join(p.name for p in matches)
        return None, f"„{name_query}“ ist nicht eindeutig, passt auf: {namen}. Bitte genauer benennen."
    return matches[0], None


def find_open_business_issue(db: Session, project_id: int, title_query: str) -> tuple[models.BusinessIssue | None, str | None]:
    """Wie find_business_project_by_name, aber für einen offenen Punkt
    innerhalb eines Projekts (zum Abhaken per Telegram)."""
    q = title_query.strip().lower()
    if not q:
        return None, "Kein Stichwort angegeben."
    open_issues = (
        db.query(models.BusinessIssue)
        .filter(models.BusinessIssue.project_id == project_id, models.BusinessIssue.resolved.is_(False))
        .all()
    )
    matches = [i for i in open_issues if q in i.title.lower()]
    if not matches:
        namen = ", ".join(i.title for i in open_issues) or "keine offenen Punkte"
        return None, f"Nichts mit „{title_query}“ gefunden. Offen: {namen}"
    if len(matches) > 1:
        namen = ", ".join(i.title for i in matches)
        return None, f"„{title_query}“ ist nicht eindeutig, passt auf: {namen}. Bitte genauer benennen."
    return matches[0], None


# ---------- Leben (persönliche Lebensbereiche) ----------
LIFE_AREA_HISTORY_DAYS = 30


def _life_area_streak_and_history(db: Session, area_id: int, days: int = LIFE_AREA_HISTORY_DAYS) -> tuple[list[str], int]:
    """Liefert (Tage mit mind. einem Check-in der letzten `days` Tage als
    ISO-Strings, aktuelle Streak-Länge) für die visuelle Historie im Frontend
    (Nutzerwunsch: Konsequenz sichtbar machen, nicht nur eine Liste). Die
    Streak zählt rückwärts ab heute - hat der Nutzer heute noch nicht
    eingecheckt, aber gestern schon, bricht die Streak dadurch noch nicht ab
    (Kulanz bis Tagesende, wie bei den gängigen Streak-Apps)."""
    since = date.today() - timedelta(days=days - 1)
    rows = (
        db.query(func.date(models.LifeCheckIn.created_at))
        .filter(
            models.LifeCheckIn.area_id == area_id,
            models.LifeCheckIn.created_at >= datetime.combine(since, datetime.min.time()),
        )
        .distinct()
        .all()
    )
    checkin_days = {r[0] for r in rows}

    streak = 0
    cursor = date.today()
    if cursor.isoformat() not in checkin_days:
        cursor -= timedelta(days=1)
    while cursor.isoformat() in checkin_days:
        streak += 1
        cursor -= timedelta(days=1)

    return sorted(checkin_days), streak


def life_heatmap(db: Session, days: int = 371, area_id=None):
    """Pro Tag die Anzahl Check-ins der letzten `days` Tage (fuer die
    GitHub-artige Jahres-Heatmap). Fehlende Tage = 0, chronologisch."""
    since = date.today() - timedelta(days=days - 1)
    q = (
        db.query(func.date(models.LifeCheckIn.created_at), func.count(models.LifeCheckIn.id))
        .filter(models.LifeCheckIn.created_at >= datetime.combine(since, datetime.min.time()))
    )
    if area_id:
        q = q.filter(models.LifeCheckIn.area_id == area_id)
    counts = {str(d): int(c) for d, c in q.group_by(func.date(models.LifeCheckIn.created_at)).all()}
    return [{"date": (since + timedelta(days=i)).isoformat(),
             "count": counts.get((since + timedelta(days=i)).isoformat(), 0)}
            for i in range(days)]


def _life_area_week_days(checkin_days_30: list[str]) -> list[bool]:
    """Mo-So der laufenden Woche als Bool-Liste, aus checkin_days_30
    abgeleitet (deckt die letzten 30 Tage ab, die laufende Woche liegt immer
    darin) - keine zusaetzliche Abfrage noetig."""
    checkin_set = set(checkin_days_30)
    monday = date.today() - timedelta(days=date.today().weekday())
    return [(monday + timedelta(days=i)).isoformat() in checkin_set for i in range(7)]


def get_life_areas(db: Session, include_inactive: bool = False) -> list[models.LifeArea]:
    query = db.query(models.LifeArea)
    if not include_inactive:
        query = query.filter(models.LifeArea.active.is_(True))
    areas = query.order_by(models.LifeArea.name).all()
    for a in areas:
        a.checkin_days_30, a.streak_days = _life_area_streak_and_history(db, a.id)
        a.week_days = _life_area_week_days(a.checkin_days_30)
    return areas


def get_life_area(db: Session, area_id: int) -> models.LifeArea | None:
    area = db.query(models.LifeArea).filter(models.LifeArea.id == area_id).first()
    if area:
        area.checkin_days_30, area.streak_days = _life_area_streak_and_history(db, area.id)
        area.week_days = _life_area_week_days(area.checkin_days_30)
    return area


def create_life_area(db: Session, data: schemas.LifeAreaCreate) -> models.LifeArea:
    # Dieselbe Begrenzung wie update_life_area/create_life_checkin - ohne das
    # könnte ein direkter POST-Aufruf (z.B. Tippfehler) den Fortschritt
    # außerhalb 0-100 anlegen und die Balken-Darstellung verzerren.
    progress = max(0, min(100, data.progress_percent)) if data.progress_percent is not None else None
    area = models.LifeArea(
        name=data.name, description=data.description, target_date=data.target_date,
        progress_percent=progress, check_interval_days=data.check_interval_days,
        target_days_per_week=data.target_days_per_week,
    )
    db.add(area)
    db.commit()
    db.refresh(area)
    area.checkin_days_30, area.streak_days = _life_area_streak_and_history(db, area.id)
    area.week_days = _life_area_week_days(area.checkin_days_30)
    return area


def update_life_area(db: Session, area: models.LifeArea, data: schemas.LifeAreaUpdate) -> models.LifeArea:
    for key, value in data.model_dump(exclude_unset=True).items():
        # Dieselbe Begrenzung wie create_life_checkin - ohne das könnte ein
        # direktes PATCH (z.B. Tippfehler) den Fortschritt außerhalb 0-100
        # setzen, was die Balken-Darstellung im Frontend verzerren würde.
        if key == "progress_percent" and value is not None:
            value = max(0, min(100, value))
        setattr(area, key, value)
    db.commit()
    db.refresh(area)
    area.checkin_days_30, area.streak_days = _life_area_streak_and_history(db, area.id)
    area.week_days = _life_area_week_days(area.checkin_days_30)
    return area


def _life_checkin_out(checkin: models.LifeCheckIn) -> schemas.LifeCheckInOut:
    return schemas.LifeCheckInOut(
        id=checkin.id, area_id=checkin.area_id,
        area_name=checkin.area.name if checkin.area else None,
        note=checkin.note, created_at=checkin.created_at,
    )


def get_life_checkins(db: Session, area_id: int | None = None, limit: int = 50) -> list[schemas.LifeCheckInOut]:
    query = db.query(models.LifeCheckIn)
    if area_id:
        query = query.filter(models.LifeCheckIn.area_id == area_id)
    rows = query.order_by(models.LifeCheckIn.created_at.desc()).limit(limit).all()
    return [_life_checkin_out(r) for r in rows]


def create_life_checkin(db: Session, area_id: int, note: str, progress_percent: int | None = None) -> schemas.LifeCheckInOut:
    checkin = models.LifeCheckIn(area_id=area_id, note=note)
    db.add(checkin)
    area = db.query(models.LifeArea).filter(models.LifeArea.id == area_id).first()
    if area:
        area.last_checked_at = datetime.utcnow()
        if progress_percent is not None:
            area.progress_percent = max(0, min(100, progress_percent))
    db.commit()
    db.refresh(checkin)
    return _life_checkin_out(checkin)


def find_life_area_by_name(db: Session, name_query: str) -> tuple[models.LifeArea | None, str | None]:
    """Sucht einen aktiven Lebensbereich per (Teil-)Name - fürs Telegram-
    Freitext-Check-in, analog zu find_business_project_by_name."""
    q = name_query.strip().lower()
    if not q:
        return None, "Kein Bereichsname angegeben."
    areas = db.query(models.LifeArea).filter(models.LifeArea.active.is_(True)).all()
    matches = [a for a in areas if q in a.name.lower()]
    if not matches:
        namen = ", ".join(a.name for a in areas) or "noch keine Lebensbereiche angelegt"
        return None, f"Kein Lebensbereich mit „{name_query}“ gefunden. Vorhanden: {namen}"
    if len(matches) > 1:
        namen = ", ".join(a.name for a in matches)
        return None, f"„{name_query}“ ist nicht eindeutig, passt auf: {namen}. Bitte genauer benennen."
    return matches[0], None


# ---------- Wunschliste ----------
def get_wishlist_items(db: Session, include_inactive: bool = False) -> list[models.WishlistItem]:
    query = db.query(models.WishlistItem)
    if not include_inactive:
        query = query.filter(models.WishlistItem.active.is_(True))
    return query.order_by(models.WishlistItem.created_at.desc()).all()


def get_wishlist_item(db: Session, item_id: int) -> models.WishlistItem | None:
    return db.query(models.WishlistItem).filter(models.WishlistItem.id == item_id).first()


def create_wishlist_item(db: Session, data: schemas.WishlistItemCreate) -> models.WishlistItem:
    item = models.WishlistItem(
        name=data.name, category=data.category, target_price=data.target_price, url=data.url,
        notes=data.notes, check_interval_days=data.check_interval_days,
        auto_check_enabled=data.auto_check_enabled,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def update_wishlist_item(db: Session, item: models.WishlistItem, data: schemas.WishlistItemUpdate) -> models.WishlistItem:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


def mark_wishlist_item_checked(db: Session, item: models.WishlistItem) -> models.WishlistItem:
    item.last_checked_at = datetime.utcnow()
    db.commit()
    db.refresh(item)
    return item


def find_wishlist_item_by_name(db: Session, name_query: str) -> tuple[models.WishlistItem | None, str | None]:
    """Analog zu find_business_project_by_name/find_life_area_by_name."""
    q = name_query.strip().lower()
    if not q:
        return None, "Kein Name angegeben."
    items = db.query(models.WishlistItem).filter(
        models.WishlistItem.active.is_(True), models.WishlistItem.purchased.is_(False),
    ).all()
    matches = [i for i in items if q in i.name.lower()]
    if not matches:
        namen = ", ".join(i.name for i in items) or "noch nichts auf der Wunschliste"
        return None, f"Nichts mit „{name_query}“ auf der Wunschliste gefunden. Vorhanden: {namen}"
    if len(matches) > 1:
        namen = ", ".join(i.name for i in matches)
        return None, f"„{name_query}“ ist nicht eindeutig, passt auf: {namen}. Bitte genauer benennen."
    return matches[0], None


