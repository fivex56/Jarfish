PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS projects (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    description     TEXT DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'active',
    priority        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at    TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    title           TEXT NOT NULL,
    description     TEXT DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'todo',
    priority        INTEGER NOT NULL DEFAULT 0,
    due_date        TEXT,
    tags            TEXT DEFAULT '',
    emoji           TEXT DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at    TEXT
);

CREATE TABLE IF NOT EXISTS reminders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
    message         TEXT NOT NULL,
    trigger_at      TEXT NOT NULL,
    repeat_interval TEXT DEFAULT 'none',
    is_sent         INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT DEFAULT '',
    content         TEXT NOT NULL,
    tags            TEXT DEFAULT '',
    project_id      INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    task_id         INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    direction       TEXT NOT NULL,
    text            TEXT NOT NULL,
    source          TEXT NOT NULL DEFAULT 'telegram',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tasks_project     ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status      ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_due_date    ON tasks(due_date);
CREATE INDEX IF NOT EXISTS idx_reminders_trigger ON reminders(trigger_at, is_sent);
CREATE INDEX IF NOT EXISTS idx_reminders_task    ON reminders(task_id);
CREATE INDEX IF NOT EXISTS idx_notes_project     ON notes(project_id);
CREATE INDEX IF NOT EXISTS idx_messages_time     ON messages(created_at);

CREATE TABLE IF NOT EXISTS thoughts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    content         TEXT DEFAULT '',
    kind            TEXT NOT NULL DEFAULT 'text',
    image_path      TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_thoughts_date ON thoughts(created_at);

CREATE VIEW IF NOT EXISTS v_overdue_tasks AS
SELECT t.*, p.name AS project_name
FROM tasks t
LEFT JOIN projects p ON t.project_id = p.id
WHERE t.status IN ('todo', 'in_progress')
  AND t.due_date IS NOT NULL
  AND datetime(t.due_date) < datetime('now');

CREATE VIEW IF NOT EXISTS v_upcoming_reminders AS
SELECT r.*, t.title AS task_title
FROM reminders r
LEFT JOIN tasks t ON r.task_id = t.id
WHERE r.is_sent = 0
  AND datetime(r.trigger_at) BETWEEN datetime('now') AND datetime('now', '+24 hours')
ORDER BY r.trigger_at ASC;
