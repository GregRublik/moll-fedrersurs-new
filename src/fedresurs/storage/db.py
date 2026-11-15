from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import aiosqlite

from config import settings

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


class Database:
    """Single-writer SQLite wrapper with WAL and explicit transactions."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else settings.app.db_path
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
        self._in_tx = False

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("database is not connected")
        return self._conn

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path, isolation_level=None)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.execute("PRAGMA synchronous=NORMAL")

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator["Database"]:
        async with self._lock:
            if self._in_tx:
                yield self
                return
            await self.conn.execute("BEGIN IMMEDIATE")
            self._in_tx = True
            try:
                yield self
            except BaseException:
                await self.conn.rollback()
                raise
            else:
                await self.conn.commit()
            finally:
                self._in_tx = False

    async def execute(self, sql: str, params: tuple | list = ()) -> aiosqlite.Cursor:
        cursor = await self.conn.execute(sql, params)
        if not self._in_tx:
            await self.conn.commit()
        return cursor

    async def executemany(self, sql: str, rows: list[tuple]) -> None:
        await self.conn.executemany(sql, rows)
        if not self._in_tx:
            await self.conn.commit()

    async def fetchone(self, sql: str, params: tuple | list = ()) -> aiosqlite.Row | None:
        cursor = await self.conn.execute(sql, params)
        return await cursor.fetchone()

    async def fetchall(self, sql: str, params: tuple | list = ()) -> list[aiosqlite.Row]:
        cursor = await self.conn.execute(sql, params)
        return list(await cursor.fetchall())

    async def executescript(self, sql: str) -> None:
        await self.conn.executescript(sql)

    async def migrate(self) -> list[str]:
        """Apply pending .sql migrations; returns the list of applied versions."""
        await self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        await self.conn.commit()

        rows = await self.fetchall("SELECT version FROM schema_migrations")
        applied = {row["version"] for row in rows}
        newly_applied: list[str] = []

        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = path.name.split("_", 1)[0]
            if version in applied:
                continue
            await self.conn.executescript(path.read_text(encoding="utf-8"))
            await self.conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, datetime('now'))",
                (version,),
            )
            await self.conn.commit()
            newly_applied.append(version)

        return newly_applied

    async def schema_version(self) -> str | None:
        row = await self.fetchone("SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1")
        return row["version"] if row else None


async def open_database(path: str | Path | None = None) -> Database:
    db = Database(path)
    await db.connect()
    await db.migrate()
    return db
