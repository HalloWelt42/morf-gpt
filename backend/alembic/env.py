"""Alembic-Umgebung (asynchron, asyncpg). Adresse und Metadaten kommen aus der App."""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool

from app.config import einstellungen
from app.db.modelle import Basis

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", einstellungen.datenbank_url)
ziel_metadaten = Basis.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=einstellungen.datenbank_url,
        target_metadata=ziel_metadaten,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _migrieren(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(connection=connection, target_metadata=ziel_metadaten)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_migrieren)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
