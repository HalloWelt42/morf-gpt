"""Datenbankanbindung: asynchrone Engine und Sitzungen (SQLAlchemy 2, asyncpg)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from ..config import einstellungen

_engine: AsyncEngine | None = None
_sitzungen: async_sessionmaker[AsyncSession] | None = None


def engine() -> AsyncEngine:
    global _engine, _sitzungen
    if _engine is None:
        _engine = create_async_engine(
            einstellungen.datenbank_url,
            pool_size=10,
            max_overflow=10,
            pool_pre_ping=True,
        )
        _sitzungen = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def sitzungsfabrik() -> async_sessionmaker[AsyncSession]:
    engine()
    assert _sitzungen is not None
    return _sitzungen


@asynccontextmanager
async def sitzung() -> AsyncIterator[AsyncSession]:
    """Sitzung für Dienste außerhalb einer Anfrage (Auftragsläufer)."""
    async with sitzungsfabrik()() as s:
        yield s


async def sitzung_abhaengigkeit() -> AsyncIterator[AsyncSession]:
    """FastAPI-Abhängigkeit: eine Sitzung je Anfrage."""
    async with sitzungsfabrik()() as s:
        yield s


async def engine_schliessen() -> None:
    global _engine, _sitzungen
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sitzungen = None
