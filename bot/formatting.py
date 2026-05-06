def bold(text: str) -> str:
    return f"<b>{text}</b>"

def italic(text: str) -> str:
    return f"<i>{text}</i>"

def code(text: str) -> str:
    return f"<code>{text}</code>"

def pre(text: str) -> str:
    return f"<pre>{text}</pre>"

# Emoji status icons
STATUS_EMOJI = {
    "todo": "⬜", "in_progress": "🟡", "done": "✅",
    "blocked": "🚫", "cancelled": "❌"
}

STATUS_EMOJI_CLI = {
    "todo": "[ ]", "in_progress": "[>]", "done": "[x]",
    "blocked": "[!]", "cancelled": "[-]"
}

PRIORITY_ICONS = {0: "", 1: "⭐", 2: "🔥"}

# Emoji digit mapping
EMOJI_DIGITS = {
    "0": "0️⃣", "1": "1️⃣", "2": "2️⃣", "3": "3️⃣", "4": "4️⃣",
    "5": "5️⃣", "6": "6️⃣", "7": "7️⃣", "8": "8️⃣", "9": "9️⃣"
}


def emoji_time(time_str: str) -> str:
    """Convert '11:00' or '09:30' to emoji digits: 1️⃣1️⃣:0️⃣0️⃣"""
    result = []
    for ch in time_str:
        if ch in EMOJI_DIGITS:
            result.append(EMOJI_DIGITS[ch])
        else:
            result.append(ch)
    return "".join(result)


def get_task_time_emoji(task_id: int, reminders: dict[int, str]) -> str | None:
    """Get emoji-formatted event time for a task from its reminder."""
    time_str = reminders.get(task_id)
    if time_str:
        return emoji_time(time_str)
    return None


def format_task(task: dict, index: int | None = None, cli: bool = False) -> str:
    status_map = STATUS_EMOJI_CLI if cli else STATUS_EMOJI
    status_icon = status_map.get(task.get("status", "todo"), "?")
    prio = PRIORITY_ICONS.get(task.get("priority", 0), "")
    indicator = _score_indicator(task.get("score", 0))

    num = f"{index}." if index is not None else f"#{task['id']}"
    line = f"{indicator} {status_icon} {num} {task['title']} {prio}"
    if task.get("due_date"):
        line += f"  📅 {task['due_date']}"
    if task.get("tags"):
        tags = " ".join(f"#{t.strip()}" for t in task["tags"].split(",") if t.strip())
        line += f"  {tags}"
    return line


def _score_indicator(score: float) -> str:
    if score > 1.5:
        return "🔴"
    elif score > 0.5:
        return "🟡"
    else:
        return "🟢"


def format_task_compact(task: dict, time_str: str | None = None, cli: bool = False) -> str:
    """Compact task format for date-specific lists: no date, emoji time if available."""
    status_map = STATUS_EMOJI_CLI if cli else STATUS_EMOJI
    status_icon = status_map.get(task.get("status", "todo"), "?")
    prio = PRIORITY_ICONS.get(task.get("priority", 0), "")
    emoji = task.get("emoji", "")
    indicator = _score_indicator(task.get("score", 0))

    line = f"{indicator} {status_icon} <b>#{task['id']}</b>"
    if time_str:
        line += f" {time_str}"
    line += f" {task['title']} {prio}"
    return line

def format_project(project: dict) -> str:
    status_icons = {"active": "🟢", "paused": "🟡", "completed": "✅", "archived": "📦"}
    icon = status_icons.get(project.get("status", "active"), "?")
    return f"{icon} {bold(project['name'])} — {project.get('description', '')}"

def format_reminder(reminder: dict) -> str:
    status = "✅" if reminder["is_sent"] else "⏳"
    return f"{status} #{reminder['id']} {reminder['message']} — {reminder['trigger_at']}"

def format_note(note: dict) -> str:
    tags = f" [{note['tags']}]" if note.get("tags") else ""
    return f"📝 #{note['id']}{tags} {note['content'][:200]}"

def split_long_message(text: str, limit: int = 4000) -> list[str]:
    """Split long message at paragraph boundaries for Telegram."""
    if len(text) <= limit:
        return [text]
    parts = []
    current = ""
    for paragraph in text.split("\n\n"):
        if len(current) + len(paragraph) + 2 > limit:
            if current:
                parts.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        parts.append(current)
    return parts
