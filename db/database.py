import aiosqlite
from pathlib import Path


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self):
        self.conn = await aiosqlite.connect(self.db_path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA foreign_keys=ON")
        await self.conn.execute("PRAGMA busy_timeout=5000")
        await self._migrate()

    async def _migrate(self):
        cursor = await self.conn.execute("PRAGMA user_version")
        row = await cursor.fetchone()
        version = row[0] if row else 0

        if version == 0:
            schema_path = Path(__file__).parent / "schema.sql"
            schema = schema_path.read_text(encoding="utf-8")
            await self.conn.executescript(schema)
            await self.conn.execute("PRAGMA user_version = 4")
            await self.conn.commit()
        elif version == 1:
            await self.conn.execute("ALTER TABLE tasks ADD COLUMN emoji TEXT DEFAULT ''")
            await self.conn.execute("PRAGMA user_version = 2")
            await self.conn.commit()
        if version <= 2:
            await self.conn.execute("""CREATE TABLE IF NOT EXISTS thoughts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT DEFAULT '',
                kind TEXT NOT NULL DEFAULT 'text',
                image_path TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )""")
            await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_thoughts_date ON thoughts(created_at)")
            await self.conn.execute("PRAGMA user_version = 3")
            await self.conn.commit()
        if version <= 3:
            await self.conn.execute("""CREATE TABLE IF NOT EXISTS ideas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                round TEXT NOT NULL DEFAULT 'generation',
                agent TEXT NOT NULL DEFAULT 'generator',
                content TEXT NOT NULL,
                parent_id INTEGER REFERENCES ideas(id) ON DELETE SET NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )""")
            await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_ideas_round ON ideas(round)")
            await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_ideas_status ON ideas(status)")
            await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_ideas_parent ON ideas(parent_id)")
            await self.conn.execute("PRAGMA user_version = 4")
            await self.conn.commit()
        if version <= 4:
            await self.conn.execute("ALTER TABLE tasks ADD COLUMN reschedule_count INTEGER NOT NULL DEFAULT 0")
            await self.conn.execute("PRAGMA user_version = 5")
            await self.conn.commit()
        if version <= 5:
            await self.conn.execute("ALTER TABLE reminders ADD COLUMN adaptive_factor REAL NOT NULL DEFAULT 1.0")
            await self.conn.execute("PRAGMA user_version = 6")
            await self.conn.commit()
        if version <= 6:
            await self.conn.execute("ALTER TABLE tasks ADD COLUMN calendar_event_id TEXT DEFAULT ''")
            await self.conn.execute("ALTER TABLE reminders ADD COLUMN calendar_event_id TEXT DEFAULT ''")
            await self.conn.execute("PRAGMA user_version = 7")
            await self.conn.commit()

    async def close(self):
        if self.conn:
            await self.conn.close()

    async def execute(self, sql: str, params=None):
        return await self.conn.execute(sql, params or [])

    async def fetch_all(self, sql: str, params=None):
        cursor = await self.conn.execute(sql, params or [])
        return await cursor.fetchall()

    async def fetch_one(self, sql: str, params=None):
        cursor = await self.conn.execute(sql, params or [])
        return await cursor.fetchone()

    async def commit(self):
        await self.conn.commit()
