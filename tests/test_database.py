from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

import database
from database import DatabaseError


@pytest.mark.asyncio
async def test_add_list_remove_site(db):
    site = await database.add_site(
        url="https://example.com",
        chat_id="123",
        check_interval=300,
        label_name="prod",
        name="Example",
    )
    assert site.url == "https://example.com"
    assert site.label.name == "prod"

    sites = await database.list_sites("123")
    assert len(sites) == 1

    removed = await database.remove_site("https://example.com", "123")
    assert removed is True
    assert await database.list_sites("123") == []


@pytest.mark.asyncio
async def test_pause_and_resume(db):
    await database.add_site(
        url="https://example.com",
        chat_id="123",
        check_interval=300,
        label_name="prod",
    )
    paused = await database.set_site_active("https://example.com", "123", False)
    assert paused is not None
    assert paused.is_active is False

    resumed = await database.set_site_active("https://example.com", "123", True)
    assert resumed is not None
    assert resumed.is_active is True


@pytest.mark.asyncio
async def test_set_all_active(db):
    await database.add_site("https://a.com", "123", 300, "prod")
    await database.add_site("https://b.com", "123", 300, "prod")

    count = await database.set_all_active("123", False)
    assert count == 2

    sites = await database.list_sites("123")
    assert all(not site.is_active for site in sites)


@pytest.mark.asyncio
async def test_record_and_get_last_status(db):
    site = await database.add_site("https://example.com", "123", 300, "prod")
    result = {
        "status_code": 200,
        "is_ok": True,
        "response_time": 0.2,
        "error": None,
        "timestamp": datetime.now(timezone.utc),
    }
    await database.record_check(site.id, result)
    last = await database.get_last_status(site.id)
    assert last is not None
    assert last.is_ok is True


@pytest.mark.asyncio
async def test_purge_old_history(db):
    site = await database.add_site("https://example.com", "123", 300, "prod")
    old_ts = datetime.now(timezone.utc) - timedelta(days=5)
    await database.record_check(
        site.id,
        {
            "status_code": 200,
            "is_ok": True,
            "response_time": 0.1,
            "error": None,
            "timestamp": old_ts,
        },
    )
    deleted = await database.purge_old_history(3, chat_id="123")
    assert deleted == 1


@pytest.mark.asyncio
async def test_chat_thread_id_get_set_reset(db):
    assert await database.get_chat_thread_id("123") is None

    await database.set_chat_thread_id("123", 42)
    assert await database.get_chat_thread_id("123") == 42

    await database.set_chat_thread_id("123", None)
    assert await database.get_chat_thread_id("123") is None


@pytest.mark.asyncio
async def test_init_db_failure_returns_false():
    await database.close_db()
    ok = await database.init_db("sqlite+aiosqlite:////invalid/path/db.sqlite")
    assert ok is False
    assert database.is_available() is False


@pytest.mark.asyncio
async def test_operations_raise_when_unavailable():
    await database.close_db()
    with pytest.raises(DatabaseError):
        await database.list_sites()
