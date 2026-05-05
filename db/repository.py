from db.database import Database


class Repository:
    def __init__(self, db: Database):
        self.db = db

    # ── Projects ──────────────────────────────────────────

    async def create_project(self, name: str, description: str = "", priority: int = 0) -> dict:
        sql = "INSERT INTO projects (name, description, priority) VALUES (?, ?, ?)"
        cur = await self.db.execute(sql, (name, description, priority))
        await self.db.commit()
        return await self.get_project(cur.lastrowid)

    async def get_project(self, project_id: int) -> dict | None:
        row = await self.db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
        return dict(row) if row else None

    async def get_project_by_name(self, name: str) -> dict | None:
        row = await self.db.fetch_one("SELECT * FROM projects WHERE name = ?", (name,))
        return dict(row) if row else None

    async def list_projects(self, status: str = "active") -> list[dict]:
        rows = await self.db.fetch_all(
            "SELECT * FROM projects WHERE status = ? ORDER BY priority DESC, created_at DESC",
            (status,)
        )
        return [dict(r) for r in rows]

    async def update_project(self, project_id: int, **kwargs) -> dict | None:
        if not kwargs:
            return await self.get_project(project_id)
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [project_id]
        await self.db.execute(f"UPDATE projects SET {sets}, updated_at = datetime('now') WHERE id = ?", values)
        await self.db.commit()
        return await self.get_project(project_id)

    # ── Tasks ─────────────────────────────────────────────

    async def create_task(self, title: str, project_id: int | None = None,
                          description: str = "", priority: int = 0,
                          due_date: str | None = None, tags: str = "") -> dict:
        sql = """INSERT INTO tasks (title, project_id, description, priority, due_date, tags)
                 VALUES (?, ?, ?, ?, ?, ?)"""
        cur = await self.db.execute(sql, (title, project_id, description, priority, due_date, tags))
        await self.db.commit()
        return await self.get_task(cur.lastrowid)

    async def get_task(self, task_id: int) -> dict | None:
        row = await self.db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
        return dict(row) if row else None

    async def list_tasks(self, status: str | None = None, project_id: int | None = None,
                         limit: int = 20) -> list[dict]:
        sql = "SELECT * FROM tasks WHERE 1=1"
        params = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if project_id is not None:
            sql += " AND project_id = ?"
            params.append(project_id)
        sql += " ORDER BY priority DESC, due_date ASC, created_at DESC LIMIT ?"
        params.append(limit)
        rows = await self.db.fetch_all(sql, params)
        return [dict(r) for r in rows]

    async def update_task(self, task_id: int, **kwargs) -> dict | None:
        if not kwargs:
            return await self.get_task(task_id)
        if "status" in kwargs and kwargs["status"] == "done":
            kwargs["completed_at"] = "datetime('now')"
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [task_id]
        await self.db.execute(f"UPDATE tasks SET {sets}, updated_at = datetime('now') WHERE id = ?", values)
        await self.db.commit()
        return await self.get_task(task_id)

    async def get_overdue_tasks(self) -> list[dict]:
        rows = await self.db.fetch_all("SELECT * FROM v_overdue_tasks ORDER BY due_date ASC")
        return [dict(r) for r in rows]

    async def get_today_tasks(self) -> list[dict]:
        rows = await self.db.fetch_all(
            """SELECT * FROM tasks
               WHERE status IN ('todo', 'in_progress')
                 AND date(due_date) = date('now')
               ORDER BY priority DESC""")
        return [dict(r) for r in rows]

    async def search_tasks(self, keyword: str) -> list[dict]:
        rows = await self.db.fetch_all(
            "SELECT * FROM tasks WHERE title LIKE ? OR description LIKE ? ORDER BY created_at DESC LIMIT 20",
            (f"%{keyword}%", f"%{keyword}%"))
        return [dict(r) for r in rows]

    # ── Reminders ─────────────────────────────────────────

    async def create_reminder(self, message: str, trigger_at: str,
                              task_id: int | None = None,
                              repeat_interval: str = "none") -> dict:
        sql = "INSERT INTO reminders (message, trigger_at, task_id, repeat_interval) VALUES (?, ?, ?, ?)"
        cur = await self.db.execute(sql, (message, trigger_at, task_id, repeat_interval))
        await self.db.commit()
        return await self.get_reminder(cur.lastrowid)

    async def get_reminder(self, reminder_id: int) -> dict | None:
        row = await self.db.fetch_one("SELECT * FROM reminders WHERE id = ?", (reminder_id,))
        return dict(row) if row else None

    async def list_reminders(self, include_sent: bool = False) -> list[dict]:
        sql = "SELECT * FROM reminders"
        if not include_sent:
            sql += " WHERE is_sent = 0"
        sql += " ORDER BY trigger_at ASC"
        rows = await self.db.fetch_all(sql)
        return [dict(r) for r in rows]

    async def mark_reminder_sent(self, reminder_id: int):
        await self.db.execute("UPDATE reminders SET is_sent = 1 WHERE id = ?", (reminder_id,))
        await self.db.commit()

    async def delete_reminder(self, reminder_id: int):
        await self.db.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        await self.db.commit()

    async def get_pending_reminders(self) -> list[dict]:
        rows = await self.db.fetch_all(
            "SELECT * FROM reminders WHERE is_sent = 0 ORDER BY trigger_at ASC")
        return [dict(r) for r in rows]

    async def get_upcoming_reminders(self) -> list[dict]:
        rows = await self.db.fetch_all("SELECT * FROM v_upcoming_reminders")
        return [dict(r) for r in rows]

    # ── Notes ─────────────────────────────────────────────

    async def create_note(self, content: str, title: str = "", tags: str = "",
                          project_id: int | None = None) -> dict:
        sql = "INSERT INTO notes (content, title, tags, project_id) VALUES (?, ?, ?, ?)"
        cur = await self.db.execute(sql, (content, title, tags, project_id))
        await self.db.commit()
        return await self.get_note(cur.lastrowid)

    async def get_note(self, note_id: int) -> dict | None:
        row = await self.db.fetch_one("SELECT * FROM notes WHERE id = ?", (note_id,))
        return dict(row) if row else None

    async def list_notes(self, limit: int = 20, project_id: int | None = None) -> list[dict]:
        sql = "SELECT * FROM notes WHERE 1=1"
        params = []
        if project_id is not None:
            sql += " AND project_id = ?"
            params.append(project_id)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = await self.db.fetch_all(sql, params)
        return [dict(r) for r in rows]

    async def search_notes(self, keyword: str) -> list[dict]:
        rows = await self.db.fetch_all(
            "SELECT * FROM notes WHERE content LIKE ? OR title LIKE ? OR tags LIKE ? ORDER BY created_at DESC LIMIT 20",
            (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"))
        return [dict(r) for r in rows]

    # ── Messages ──────────────────────────────────────────

    async def save_message(self, direction: str, text: str, source: str = "telegram"):
        await self.db.execute(
            "INSERT INTO messages (direction, text, source) VALUES (?, ?, ?)",
            (direction, text, source))
        await self.db.commit()

    async def recent_messages(self, limit: int = 50) -> list[dict]:
        rows = await self.db.fetch_all(
            "SELECT * FROM messages ORDER BY created_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    # ── Thoughts ────────────────────────────────────────────

    async def create_thought(self, content: str = "", kind: str = "text",
                             image_path: str = "") -> dict:
        sql = "INSERT INTO thoughts (content, kind, image_path) VALUES (?, ?, ?)"
        cur = await self.db.execute(sql, (content, kind, image_path))
        await self.db.commit()
        return await self.get_thought(cur.lastrowid)

    async def get_thought(self, thought_id: int) -> dict | None:
        row = await self.db.fetch_one("SELECT * FROM thoughts WHERE id = ?", (thought_id,))
        return dict(row) if row else None

    async def list_thoughts(self, date: str | None = None, limit: int = 30) -> list[dict]:
        if date:
            rows = await self.db.fetch_all(
                "SELECT * FROM thoughts WHERE date(created_at) = ? ORDER BY created_at DESC LIMIT ?",
                (date, limit))
        else:
            rows = await self.db.fetch_all(
                "SELECT * FROM thoughts ORDER BY created_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    async def get_thought_dates(self, limit: int = 14) -> list[str]:
        rows = await self.db.fetch_all(
            "SELECT DISTINCT date(created_at) as d FROM thoughts ORDER BY d DESC LIMIT ?",
            (limit,))
        return [dict(r)["d"] for r in rows]
