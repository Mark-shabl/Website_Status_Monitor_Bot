from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, joinedload, sessionmaker

from models import Base, Label, MonitoredSite, StatusHistory

_engine = None
_SessionLocal = None


def init_db(database_url: str) -> None:
    global _engine, _SessionLocal
    _engine = create_engine(database_url, connect_args={"check_same_thread": False})
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    Base.metadata.create_all(_engine)


def get_session() -> Session:
    if _SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _SessionLocal()


def add_site(
    url: str,
    chat_id: str,
    check_interval: int,
    label_name: str,
    name: str | None = None,
) -> MonitoredSite:
    chat_id = str(chat_id)
    with get_session() as session:
        label = session.scalar(
            select(Label).where(Label.chat_id == chat_id, Label.name == label_name)
        )
        if label is None:
            label = Label(chat_id=chat_id, name=label_name)
            session.add(label)
            session.flush()

        site = MonitoredSite(
            url=url,
            name=name,
            chat_id=chat_id,
            label_id=label.id,
            check_interval=check_interval,
        )
        session.add(site)
        session.commit()
        session.refresh(site)
        _ = site.label.name  # force-load relationship while the session is still open
        return site


def remove_site(url: str, chat_id: str) -> bool:
    with get_session() as session:
        site = session.scalar(
            select(MonitoredSite).where(
                MonitoredSite.url == url, MonitoredSite.chat_id == str(chat_id)
            )
        )
        if site is None:
            return False
        session.delete(site)
        session.commit()
        return True


def get_site(url: str, chat_id: str) -> MonitoredSite | None:
    with get_session() as session:
        return session.scalar(
            select(MonitoredSite)
            .options(joinedload(MonitoredSite.label))
            .where(MonitoredSite.url == url, MonitoredSite.chat_id == str(chat_id))
        )


def list_sites(chat_id: str | None = None) -> list[MonitoredSite]:
    """Returns sites ordered by label creation order, then by site add order.

    This ordering is what /list and /status rely on to group same-label
    sites together in a stable, predictable order.
    """
    with get_session() as session:
        stmt = (
            select(MonitoredSite)
            .options(joinedload(MonitoredSite.label))
            .order_by(MonitoredSite.label_id, MonitoredSite.id)
        )
        if chat_id is not None:
            stmt = stmt.where(MonitoredSite.chat_id == str(chat_id))
        return list(session.scalars(stmt).unique().all())


def update_site_interval(url: str, chat_id: str, interval_seconds: int) -> MonitoredSite | None:
    with get_session() as session:
        site = session.scalar(
            select(MonitoredSite)
            .options(joinedload(MonitoredSite.label))
            .where(MonitoredSite.url == url, MonitoredSite.chat_id == str(chat_id))
        )
        if site is None:
            return None
        site.check_interval = interval_seconds
        site.updated_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(site)
        _ = site.label.name  # force-load relationship while the session is still open
        return site


def record_check(site_id: int, result: dict) -> StatusHistory:
    with get_session() as session:
        entry = StatusHistory(
            site_id=site_id,
            status_code=result.get("status_code"),
            response_time=result.get("response_time"),
            is_ok=result.get("is_ok", False),
            error_message=result.get("error"),
            checked_at=result.get("timestamp", datetime.now(timezone.utc)),
        )
        session.add(entry)
        session.commit()
        session.refresh(entry)
        return entry


def get_last_status(site_id: int) -> StatusHistory | None:
    """Returns the most recently recorded check for a site, if any.

    Call this before record_check() for the current check so it reflects
    the previous result, not the one about to be inserted.
    """
    with get_session() as session:
        stmt = (
            select(StatusHistory)
            .where(StatusHistory.site_id == site_id)
            .order_by(StatusHistory.checked_at.desc())
        )
        return session.scalars(stmt).first()
