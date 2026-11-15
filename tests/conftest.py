from __future__ import annotations

import pytest

from fedresurs.storage.db import open_database


@pytest.fixture
async def db(tmp_path):
    database = await open_database(tmp_path / "test.sqlite3")
    try:
        yield database
    finally:
        await database.close()
