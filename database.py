import logging
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Callable, TypeVar

from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import joinedload

from models import Base, ChatSettings, Label, MonitoredSite, StatusHistory

logger = logging.getLogger(__name__)

_engine = None
_SessionLocal: async_sessionmaker[AsyncSession] | None = None
_available = False

T = TypeVar("T")


class DatabaseError(Exception):
    pass


def is_available() -> bool:
    return _available


def _normalize_database_url(database_url: str) -> str:
    if database_url.startswith("sqlite:///") and "+aiosqlite" not in database_url:
        return database_url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    return database_url


def _db_operation(func: Callable[..., T]) -> Callable[..., T]:
    @wraps(func)
    async def wrapper(*args, **kwargs):
        global _available
        if not _available:
            raise DatabaseError("Database is unavailable")
        try:
            return await func(*args, **kwargs)
        except SQLAlchemyError as exc:
            logger.exception("Database error in %s", func.__name__)
            _available = False
            raise DatabaseError(str(exc)) from exc

    return wrapper


async def init_db(database_url: str) -> bool:
    global _engine, _SessionLocal, _available
    try:
        url = _normalize_database_url(database_url)
        _engine = create_async_engine(url)
        _SessionLocal = async_sessionmaker(_engine, expire_on_commit=False)
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _available = True
        return True
    except SQLAlchemyError:
        logger.exception("Failed to initialize database")
        _available = False
        return False


async def close_db() -> None:
    global _engine, _SessionLocal, _available
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _SessionLocal = None
    _available = False


def _session() -> AsyncSession:
    if _SessionLocal is None:
        raise DatabaseError("Database not initialized")
    return _SessionLocal()


async def _load_site(session: AsyncSession, site: MonitoredSite) -> MonitoredSite:
    await session.refresh(site, attribute_names=["label"])
    _ = site.label.name
    return site


@_db_operation
async def add_site(
    url: str,
    chat_id: str,
    check_interval: int,
    label_name: str,
    name: str | None = None,
) -> MonitoredSite:
    chat_id = str(chat_id)
    async with _session() as session:
        label = await session.scalar(
            select(Label).where(Label.chat_id == chat_id, Label.name == label_name)
        )
        if label is None:
            label = Label(chat_id=chat_id, name=label_name)
            session.add(label)
            await session.flush()

        site = MonitoredSite(
            url=url,
            name=name,
            chat_id=chat_id,
            label_id=label.id,
            check_interval=check_interval,
        )
        session.add(site)
        await session.commit()
        return await _load_site(session, site)


@_db_operation
async def remove_site(url: str, chat_id: str) -> bool:
    async with _session() as session:
        site = await session.scalar(
            select(MonitoredSite).where(
                MonitoredSite.url == url, MonitoredSite.chat_id == str(chat_id)
            )
        )
        if site is None:
            return False
        await session.delete(site)
        await session.commit()
        return True


@_db_operation
async def get_site(url: str, chat_id: str) -> MonitoredSite | None:
    async with _session() as session:
        return await session.scalar(
            select(MonitoredSite)
            .options(joinedload(MonitoredSite.label))
            .where(MonitoredSite.url == url, MonitoredSite.chat_id == str(chat_id))
        )


@_db_operation
async def list_sites(chat_id: str | None = None) -> list[MonitoredSite]:
    async with _session() as session:
        stmt = (
            select(MonitoredSite)
            .options(joinedload(MonitoredSite.label))
            .order_by(MonitoredSite.label_id, MonitoredSite.id)
        )
        if chat_id is not None:
            stmt = stmt.where(MonitoredSite.chat_id == str(chat_id))
        result = await session.scalars(stmt)
        return list(result.unique().all())


@_db_operation
async def update_site_interval(
    url: str, chat_id: str, interval_seconds: int
) -> MonitoredSite | None:
    async with _session() as session:
        site = await session.scalar(
            select(MonitoredSite)
            .options(joinedload(MonitoredSite.label))
            .where(MonitoredSite.url == url, MonitoredSite.chat_id == str(chat_id))
        )
        if site is None:
            return None
        site.check_interval = interval_seconds
        site.updated_at = datetime.now(timezone.utc)
        await session.commit()
        return await _load_site(session, site)


@_db_operation
async def set_site_active(url: str, chat_id: str, active: bool) -> MonitoredSite | None:
    async with _session() as session:
        site = await session.scalar(
            select(MonitoredSite)
            .options(joinedload(MonitoredSite.label))
            .where(MonitoredSite.url == url, MonitoredSite.chat_id == str(chat_id))
        )
        if site is None:
            return None
        site.is_active = active
        site.updated_at = datetime.now(timezone.utc)
        await session.commit()
        return await _load_site(session, site)


@_db_operation
async def set_all_active(chat_id: str, active: bool) -> int:
    async with _session() as session:
        result = await session.execute(
            update(MonitoredSite)
            .where(MonitoredSite.chat_id == str(chat_id))
            .values(is_active=active, updated_at=datetime.now(timezone.utc))
        )
        await session.commit()
        return result.rowcount or 0


@_db_operation
async def get_chat_thread_id(chat_id: str) -> int | None:
    async with _session() as session:
        settings = await session.get(ChatSettings, str(chat_id))
        return settings.thread_id if settings else None


@_db_operation
async def set_chat_thread_id(chat_id: str, thread_id: int | None) -> None:
    chat_id = str(chat_id)
    async with _session() as session:
        settings = await session.get(ChatSettings, chat_id)
        if settings is None:
            settings = ChatSettings(chat_id=chat_id, thread_id=thread_id)
            session.add(settings)
        else:
            settings.thread_id = thread_id
        await session.commit()


@_db_operation
async def record_check(site_id: int, result: dict) -> StatusHistory:
    async with _session() as session:
        entry = StatusHistory(
            site_id=site_id,
            status_code=result.get("status_code"),
            response_time=result.get("response_time"),
            is_ok=result.get("is_ok", False),
            error_message=result.get("error"),
            checked_at=result.get("timestamp", datetime.now(timezone.utc)),
        )
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
        return entry


@_db_operation
async def get_last_status(site_id: int) -> StatusHistory | None:
    async with _session() as session:
        stmt = (
            select(StatusHistory)
            .where(StatusHistory.site_id == site_id)
            .order_by(StatusHistory.checked_at.desc())
        )
        result = await session.scalars(stmt)
        return result.first()


@_db_operation
async def purge_old_history(retention_days: int, chat_id: str | None = None) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    async with _session() as session:
        if chat_id is None:
            result = await session.execute(
                delete(StatusHistory).where(StatusHistory.checked_at < cutoff)
            )
        else:
            site_ids = select(MonitoredSite.id).where(
                MonitoredSite.chat_id == str(chat_id)
            )
            result = await session.execute(
                delete(StatusHistory).where(
                    StatusHistory.site_id.in_(site_ids),
                    StatusHistory.checked_at < cutoff,
                )
            )
        await session.commit()
        return result.rowcount or 0
