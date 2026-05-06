"""Menu system: inline keyboards for task/project/reminder management."""

import logging
import os
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from bot.formatting import STATUS_EMOJI, PRIORITY_ICONS, emoji_time, format_task_compact

logger = logging.getLogger(__name__)

# Pool of 65 visually distinct, colorful emojis for task buttons
EMOJI_POOL = [
    "❤️", "🧡", "💛", "💚", "💙", "💜", "🤎", "🖤", "🤍", "💗",
    "🔴", "🟠", "🟡", "🟢", "🔵", "🟣", "🟤", "⚫", "⚪",
    "🟥", "🟧", "🟨", "🟩", "🟦", "🟪", "🟫", "⬛", "⬜",
    "⭐", "🌟", "✨", "💫", "🔥", "💥", "🌈", "❄️", "💧", "🎵",
    "👠", "🧂", "🌑", "🎩", "💎", "🔑", "🎯", "📌", "💡", "🏷️",
    "🐱", "🐶", "🐼", "🐨", "🦊", "🐰", "🐸", "🐵", "🦁", "🐯",
    "🍎", "🍊", "🍋", "🍇", "🍓", "🍒", "🥝", "🍌", "🥑", "🌶️",
    "🎲", "🧩", "🔮", "🪄", "🎪", "🚀", "🌍", "🎨", "📷", "🔔",
]


async def _assign_task_emojis(repo, tasks: list[dict]) -> None:
    """Ensure every task in the list has an emoji, assigning from pool if needed."""
    if not tasks:
        return
    bare = [t for t in tasks if not t.get("emoji")]
    if not bare:
        return

    # Collect emojis already used by active tasks
    all_tasks = await repo.list_tasks(limit=200)
    used = {t["emoji"] for t in all_tasks if t.get("emoji")}

    available = [e for e in EMOJI_POOL if e not in used]
    if not available:
        available = EMOJI_POOL  # reuse if pool exhausted

    for i, task in enumerate(bare):
        emoji = available[i % len(available)]
        await repo.update_task(task["id"], emoji=emoji)
        task["emoji"] = emoji
        used.add(emoji)
        if emoji in available:
            available.remove(emoji)


def build_main_menu() -> InlineKeyboardMarkup:
    """Main navigation menu."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Сегодня", callback_data="view_today")],
        [InlineKeyboardButton("📅 Завтра", callback_data="view_tomorrow")],
        [InlineKeyboardButton("📆 Все задачи", callback_data="view_all")],
        [
            InlineKeyboardButton("➕ Задача", callback_data="new_task"),
            InlineKeyboardButton("🔔 Напом.", callback_data="new_remind"),
        ],
        [
            InlineKeyboardButton("📁 Проекты", callback_data="view_projects"),
            InlineKeyboardButton("💭 Мысли", callback_data="view_thoughts"),
        ],
        [InlineKeyboardButton("📊 Сводка", callback_data="view_summary")],
    ])


def build_task_list_keyboard(tasks: list[dict], view: str, reminders: dict[int, str] | None = None) -> InlineKeyboardMarkup:
    """Build one clickable button per task. view: 'today', 'tomorrow', 'all'"""
    from bot.formatting import STATUS_EMOJI, PRIORITY_ICONS
    reminders = reminders or {}
    buttons = []
    for t in tasks:
        s = STATUS_EMOJI.get(t.get("status", "todo"), "?")
        p = PRIORITY_ICONS.get(t.get("priority", 0), "")
        time_str = reminders.get(t["id"], "")
        indicator = _score_indicator(t.get("score", 0))
        label = f"{indicator} {s} #{t['id']}"
        if time_str:
            label += f" {time_str}"
        label += f" {t['title']} {p}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"detail_{t['id']}_{view}")])
    if view in ("today", "tomorrow"):
        rl = "📅 Перенести все на завтра" if view == "today" else "📅 Перенести все на послезавтра"
        buttons.append([InlineKeyboardButton(rl, callback_data=f"rollover_{view}")])
    if view.startswith("proj_"):
        proj_id = view.split("_")[1]
        buttons.append([
            InlineKeyboardButton("◀ Назад в проект", callback_data=f"project_{proj_id}"),
            InlineKeyboardButton("➕ Задачу", callback_data=f"new_proj_task_{proj_id}"),
        ])
    buttons.append([InlineKeyboardButton("🏠 В меню", callback_data="menu")])
    return InlineKeyboardMarkup(buttons)


def build_task_detail_keyboard(task_id: int, view: str) -> InlineKeyboardMarkup:
    """Buttons for a single task detail view."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Завершить", callback_data=f"complete_{task_id}_{view}"),
            InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_{task_id}_{view}"),
        ],
        [
            InlineKeyboardButton("📅 На завтра", callback_data=f"postpone_{task_id}_{view}"),
            InlineKeyboardButton("⏰ Время", callback_data=f"edit_due_{task_id}_{view}"),
        ],
        [
            InlineKeyboardButton("✏ Название", callback_data=f"edit_title_{task_id}_{view}"),
            InlineKeyboardButton("🏷 Теги", callback_data=f"edit_tags_{task_id}_{view}"),
        ],
        [
            InlineKeyboardButton("➕🔔 Напоминание", callback_data=f"edit_remind_{task_id}_{view}"),
        ],
        [
            InlineKeyboardButton("◀ К списку", callback_data=f"view_{view}"),
            InlineKeyboardButton("🏠 В меню", callback_data="menu"),
        ],
    ])


def build_project_list_keyboard(projects: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for p in projects:
        buttons.append([
            InlineKeyboardButton(
                f"{p['name']} ({p['status']})",
                callback_data=f"project_{p['id']}"
            )
        ])
    buttons.append([InlineKeyboardButton("➕ Создать проект", callback_data="new_project")])
    buttons.append([InlineKeyboardButton("🏠 В меню", callback_data="menu")])
    return InlineKeyboardMarkup(buttons)


def build_project_detail_keyboard(project_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Задачи", callback_data=f"proj_tasks_{project_id}"),
            InlineKeyboardButton("➕ Задача", callback_data=f"new_proj_task_{project_id}"),
        ],
        [
            InlineKeyboardButton("⏸ Пауза", callback_data=f"proj_status_{project_id}_paused"),
            InlineKeyboardButton("✅ Завершить", callback_data=f"proj_status_{project_id}_completed"),
        ],
        [
            InlineKeyboardButton("🗑 Архив", callback_data=f"proj_delete_{project_id}"),
        ],
        [InlineKeyboardButton("◀ К проектам", callback_data="view_projects"),
         InlineKeyboardButton("🏠 В меню", callback_data="menu")],
    ])


def build_back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 В меню", callback_data="menu")]
    ])


# ── Time picker keyboards ────────────────────────────────────────

HOURS = list(range(8, 23))  # 8..22


def build_hour_picker(task_id: int, field: str, view: str) -> InlineKeyboardMarkup:
    """Grid of hour buttons for step 1 of time picking."""
    buttons = []
    row = []
    for h in HOURS:
        row.append(InlineKeyboardButton(
            str(h),
            callback_data=f"hoursel_{task_id}_{field}_{view}_{h}"
        ))
        if len(row) == 5:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("Отмена", callback_data=f"detail_{task_id}_{view}")])
    return InlineKeyboardMarkup(buttons)


def build_minute_picker(task_id: int, field: str, view: str, hour: int) -> InlineKeyboardMarkup:
    """Minute buttons for step 2 of time picking."""
    minutes = ["00", "15", "30", "45"]
    row = []
    for m in minutes:
        row.append(InlineKeyboardButton(
            f":{m}",
            callback_data=f"minsel_{task_id}_{field}_{view}_{hour}_{m}"
        ))
    return InlineKeyboardMarkup([
        row,
        [InlineKeyboardButton("◀ Назад", callback_data=f"edit_{field}_{task_id}_{view}")]
    ])


def format_task_detail(task: dict) -> str:
    due = task.get("due_date") or "—"
    tags = task.get("tags") or "—"
    status_icon = STATUS_EMOJI.get(task.get("status", "todo"), "?")
    prio_icon = PRIORITY_ICONS.get(task.get("priority", 0), "")
    return (
        f"{status_icon} <b>Задача #{task['id']}: {task['title']}</b> {prio_icon}\n"
        f"Срок: {due}\n"
        f"Теги: {tags}"
    )


def format_task_list(tasks: list[dict], title: str, reminders: dict[int, str] | None = None) -> str:
    if not tasks:
        return f"<b>{title}</b>\n\nЗадач нет."
    lines = [f"<b>{title} ({len(tasks)}):</b>\n"]
    reminders = reminders or {}
    for t in tasks:
        time_str = reminders.get(t["id"])
        lines.append(format_task_compact(t, time_str))
    return "\n".join(lines)


async def _get_reminder_times(repo, tasks: list[dict]) -> dict[int, str]:
    """Build mapping of task_id -> HH:MM time string for tasks that have reminders."""
    task_ids = {t["id"] for t in tasks}
    if not task_ids:
        return {}
    all_reminders = await repo.list_reminders()
    result = {}
    for r in all_reminders:
        tid = r.get("task_id")
        trigger = r.get("trigger_at", "")
        if tid in task_ids and trigger and " " in trigger:
            result[tid] = trigger.split(" ")[1][:5]
    return result


# ── Thought feed keyboards ──────────────────────────────────────


def build_thoughts_keyboard(thoughts: list[dict], date: str) -> InlineKeyboardMarkup:
    """One button per thought, showing preview."""
    buttons = []
    for t in thoughts:
        if t["kind"] == "image":
            preview = f"🖼 Фото {t['created_at'][11:16] if len(t['created_at']) > 11 else ''}"
        elif t["kind"] == "voice":
            preview = f"🎤 {t['content'][:35]}"
        else:
            preview = t["content"][:40]
        buttons.append([InlineKeyboardButton(preview, callback_data=f"thought_{t['id']}")])
    buttons.append([
        InlineKeyboardButton("➕ Мысль", callback_data="new_thought"),
        InlineKeyboardButton("📅 Дни", callback_data="thought_dates"),
    ])
    buttons.append([InlineKeyboardButton("🏠 В меню", callback_data="menu")])
    return InlineKeyboardMarkup(buttons)


def build_thought_detail_keyboard(thought_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 Удалить", callback_data=f"thought_del_{thought_id}")],
        [InlineKeyboardButton("◀ К ленте", callback_data="view_thoughts"),
         InlineKeyboardButton("🏠 В меню", callback_data="menu")],
    ])


def build_thought_dates_keyboard(dates: list[str]) -> InlineKeyboardMarkup:
    buttons = []
    for d in dates:
        buttons.append([InlineKeyboardButton(d, callback_data=f"thought_date_{d}")])
    buttons.append([InlineKeyboardButton("◀ К ленте", callback_data="view_thoughts"),
                    InlineKeyboardButton("🏠 В меню", callback_data="menu")])
    return InlineKeyboardMarkup(buttons)


# ── Menu Callback Handlers ──────────────────────────────────────


async def handle_menu_callbacks(handlers, update, context):
    """Route all menu-related callbacks. 'handlers' is the BotHandlers instance."""
    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id

    if not handlers.is_allowed(user_id):
        await query.answer("Нет доступа")
        return

    repo = handlers.processor.repo

    try:
        # ── Main views ──
        if data == "menu":
            await query.edit_message_text(
                "<b>Меню</b>",
                reply_markup=build_main_menu(),
                parse_mode="HTML"
            )

        elif data == "view_today":
            subset, times, text, _ = await _build_view_data(repo, "today")
            await query.edit_message_text(text, reply_markup=build_task_list_keyboard(subset, "today", times), parse_mode="HTML")

        elif data == "view_tomorrow":
            subset, times, text, _ = await _build_view_data(repo, "tomorrow")
            await query.edit_message_text(text, reply_markup=build_task_list_keyboard(subset, "tomorrow", times), parse_mode="HTML")

        elif data == "view_all":
            subset, times, text, _ = await _build_view_data(repo, "all")
            await query.edit_message_text(text, reply_markup=build_task_list_keyboard(subset, "all", times), parse_mode="HTML")

        elif data.startswith("view_proj_"):
            proj_id = int(data.split("_")[2])
            view_key = f"proj_{proj_id}"
            subset, times, text, _ = await _build_view_data(repo, view_key)
            await query.edit_message_text(text, reply_markup=build_task_list_keyboard(subset, view_key, times), parse_mode="HTML")

        # ── Rollover all tasks to next day ──
        elif data.startswith("rollover_"):
            view = data.split("_")[1]  # "today" or "tomorrow"
            if view == "today":
                src = datetime.now().strftime("%Y-%m-%d")
                dst = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            else:
                src = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
                dst = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")

            tasks = await repo.list_tasks(limit=100)
            rolled = 0
            for t in tasks:
                due = t.get("due_date") or ""
                if due.startswith(src) and t["status"] not in ("done", "cancelled"):
                    new_due = dst + due[len(src):]
                    await repo.update_task(t["id"], due_date=new_due)
                    rolled += 1
            await query.answer(f"Перенесено задач: {rolled}")
            # Refresh the view
            await _show_view(query, repo, view)

        # ── Task detail ──
        elif data.startswith("detail_"):
            parts = data.split("_", 2)
            task_id = int(parts[1])
            view = parts[2] if len(parts) > 2 else "all"
            task = await repo.get_task(task_id)
            if not task:
                await query.answer("Задача не найдена")
                return
            text = format_task_detail(task)
            await query.edit_message_text(
                text,
                reply_markup=build_task_detail_keyboard(task_id, view),
                parse_mode="HTML"
            )

        # ── Complete task ──
        elif data.startswith("complete_"):
            parts = data.split("_", 2)
            task_id = int(parts[1])
            view = parts[2] if len(parts) > 2 else "all"
            await repo.update_task(task_id, status="done")
            await query.answer("Выполнено!")
            # Refresh the detail view
            task = await repo.get_task(task_id)
            if task:
                await query.edit_message_text(
                    format_task_detail(task),
                    reply_markup=build_task_detail_keyboard(task_id, view),
                    parse_mode="HTML"
                )

        # ── Delete task ──
        elif data.startswith("delete_"):
            parts = data.split("_", 2)
            task_id = int(parts[1])
            view = parts[2] if len(parts) > 2 else "all"
            task = await repo.get_task(task_id)
            title = task["title"] if task else f"#{task_id}"
            await repo.update_task(task_id, status="cancelled")
            await query.answer(f"Удалено: {title}")
            # Go back to the list
            await _show_view(query, repo, view)

        # ── Postpone to tomorrow ──
        elif data.startswith("postpone_"):
            parts = data.split("_", 2)
            task_id = int(parts[1])
            view = parts[2] if len(parts) > 2 else "all"
            task = await repo.get_task(task_id)
            if not task:
                await query.answer("Задача не найдена")
                return

            due = task.get("due_date") or ""
            if due and " " in due:
                # Keep same time, move date to tomorrow
                time_part = due.split(" ")[1][:5]
                tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
                new_due = f"{tomorrow} {time_part}"
            else:
                tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
                new_due = tomorrow

            await repo.update_task(task_id, due_date=new_due)
            await query.answer(f"Перенесено на завтра: {new_due}")

            task = await repo.get_task(task_id)
            await query.edit_message_text(
                format_task_detail(task),
                reply_markup=build_task_detail_keyboard(task_id, view),
                parse_mode="HTML"
            )

        # ── Edit title ──
        elif data.startswith("edit_title_"):
            parts = data.split("_", 3)
            task_id = int(parts[2])
            view = parts[3] if len(parts) > 3 else "all"
            handlers._edit_state[user_id] = {"task_id": task_id, "field": "title", "view": view}
            await query.edit_message_text(
                f"<b>Новое название для задачи #{task_id}:</b>\n\nОтправь текст в чат.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Отмена", callback_data=f"detail_{task_id}_{view}")
                ]]),
                parse_mode="HTML"
            )

        # ── Edit due date (time picker) ──
        elif data.startswith("edit_due_"):
            parts = data.split("_", 3)
            task_id = int(parts[2])
            view = parts[3] if len(parts) > 3 else "all"
            await query.edit_message_text(
                f"<b>Выбери время для задачи #{task_id}:</b>",
                reply_markup=build_hour_picker(task_id, "due", view),
                parse_mode="HTML"
            )

        # ── Edit tags ──
        elif data.startswith("edit_tags_"):
            parts = data.split("_", 3)
            task_id = int(parts[2])
            view = parts[3] if len(parts) > 3 else "all"
            handlers._edit_state[user_id] = {"task_id": task_id, "field": "tags", "view": view}
            await query.edit_message_text(
                f"<b>Новые теги для задачи #{task_id}:</b>\n\n"
                "Отправь теги через запятую (например: важно, созвон, клиент).",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Отмена", callback_data=f"detail_{task_id}_{view}")
                ]]),
                parse_mode="HTML"
            )

        # ── Add reminder to task (time picker) ──
        elif data.startswith("edit_remind_"):
            parts = data.split("_", 3)
            task_id = int(parts[2])
            view = parts[3] if len(parts) > 3 else "all"
            await query.edit_message_text(
                f"<b>Выбери время напоминания для задачи #{task_id}:</b>",
                reply_markup=build_hour_picker(task_id, "remind", view),
                parse_mode="HTML"
            )

        # ── View projects ──
        elif data == "view_projects":
            projects = await repo.list_projects("active")
            text = f"<b>Проекты ({len(projects)}):</b>" if projects else "<b>Проектов нет</b>"
            await query.edit_message_text(
                text,
                reply_markup=build_project_list_keyboard(projects),
                parse_mode="HTML"
            )

        # ── Project detail ──
        elif data.startswith("project_") and not data.startswith("proj_"):
            proj_id = int(data.split("_")[1])
            proj = await repo.get_project(proj_id)
            if not proj:
                await query.answer("Проект не найден")
                return
            tasks = await repo.list_tasks(project_id=proj_id, limit=50)
            done = sum(1 for t in tasks if t["status"] == "done")
            active_cnt = sum(1 for t in tasks if t["status"] not in ("done", "cancelled"))
            text = (
                f"<b>Проект: {proj['name']}</b>\n"
                f"Статус: {proj['status']} | Прогресс: {done}/{len(tasks)} ✅\n"
                f"Активных: {active_cnt}"
            )
            await query.edit_message_text(
                text,
                reply_markup=build_project_detail_keyboard(proj_id),
                parse_mode="HTML"
            )

        # ── View project tasks as list ──
        elif data.startswith("proj_tasks_"):
            proj_id = int(data.split("_")[2])
            proj = await repo.get_project(proj_id)
            if not proj:
                await query.answer("Проект не найден")
                return
            tasks = await repo.list_tasks(project_id=proj_id, limit=50)
            active = [t for t in tasks if t.get("status") != "cancelled"]
            times = await _get_reminder_times(repo, active)
            text = f"<b>{proj['name']} — задачи ({len(active)}):</b>"
            view_name = f"proj_{proj_id}"
            await query.edit_message_text(
                text,
                reply_markup=build_task_list_keyboard(active, view_name, times),
                parse_mode="HTML"
            )

        # ── Quick-add task to project ──
        elif data.startswith("new_proj_task_"):
            proj_id = int(data.split("_")[3])
            handlers._edit_state[user_id] = {"field": "new_proj_task", "project_id": proj_id}
            proj = await repo.get_project(proj_id)
            await query.edit_message_text(
                f"<b>Новая задача → {proj['name']}</b>\n\n"
                "Отправь описание (нейросеть поймёт):\n"
                "Например: <i>позвонить клиенту завтра в 15:00</i>",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Отмена", callback_data=f"project_{proj_id}")
                ]]),
                parse_mode="HTML"
            )

        # ── Project status change ──
        elif data.startswith("proj_status_"):
            _, _, proj_id, status = data.split("_")
            await repo.update_project(int(proj_id), status=status)
            await query.answer(f"Проект → {status}")
            proj = await repo.get_project(int(proj_id))
            tasks = await repo.list_tasks(project_id=int(proj_id), limit=50)
            done = sum(1 for t in tasks if t["status"] == "done")
            active_cnt = sum(1 for t in tasks if t["status"] not in ("done", "cancelled"))
            text = (
                f"<b>Проект: {proj['name']}</b>\n"
                f"Статус: {proj['status']} | Прогресс: {done}/{len(tasks)} ✅\n"
                f"Активных: {active_cnt}"
            )
            await query.edit_message_text(
                text,
                reply_markup=build_project_detail_keyboard(int(proj_id)),
                parse_mode="HTML"
            )

        # ── Delete project ──
        elif data.startswith("proj_delete_"):
            proj_id = int(data.split("_")[2])
            await repo.update_project(proj_id, status="archived")
            await query.answer("Проект архивирован")
            await _show_projects(query, repo)

        # ── View notes ──
        elif data == "view_notes":
            notes = await repo.list_notes(20)
            if not notes:
                text = "<b>Заметок нет</b>"
            else:
                lines = [f"<b>Заметки ({len(notes)}):</b>"]
                for n in notes[:15]:
                    lines.append(f"📝 #{n['id']}: {n['content'][:100]}")
                text = "\n".join(lines)
            await query.edit_message_text(
                text,
                reply_markup=build_back_to_menu(),
                parse_mode="HTML"
            )

        # ── Summary ──
        elif data == "view_summary":
            summary = await handlers.processor.summary()
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Сегодня", callback_data="view_today"),
                 InlineKeyboardButton("📅 Завтра", callback_data="view_tomorrow")],
                [InlineKeyboardButton("🏠 В меню", callback_data="menu")],
            ])
            await query.edit_message_text(summary, reply_markup=keyboard, parse_mode="HTML")

        # ── New task / project / reminder prompts ──
        elif data == "new_task":
            handlers._edit_state[user_id] = {"field": "new_task"}
            await query.edit_message_text(
                "<b>Новая задача</b>\n\n"
                "Отправь описание в свободной форме (нейросеть поймёт):\n"
                "Например: <i>позвонить клиенту завтра в 15:00</i>",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Отмена", callback_data="menu")
                ]]),
                parse_mode="HTML"
            )

        elif data == "new_remind":
            handlers._edit_state[user_id] = {"field": "new_remind"}
            await query.edit_message_text(
                "<b>Новое напоминание</b>\n\n"
                "Отправь текст и время:\n"
                "Например: <i>купить подарок завтра 18:00</i>",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Отмена", callback_data="menu")
                ]]),
                parse_mode="HTML"
            )

        elif data == "new_project":
            handlers._edit_state[user_id] = {"field": "new_project"}
            await query.edit_message_text(
                "<b>Новый проект</b>\n\nОтправь название проекта:",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Отмена", callback_data="view_projects")
                ]]),
                parse_mode="HTML"
            )

        # ── Time picker: hour selected ──
        elif data.startswith("hoursel_"):
            _, task_id_str, field, view, hour_str = data.split("_", 4)
            task_id = int(task_id_str)
            hour = int(hour_str)
            await query.edit_message_text(
                f"<b>Задача #{task_id} — {hour}:??</b>\nВыбери минуты:",
                reply_markup=build_minute_picker(task_id, field, view, hour),
                parse_mode="HTML"
            )

        # ── Time picker: minute selected → apply ──
        elif data.startswith("minsel_"):
            _, task_id_str, field, view, hour_str, min_str = data.split("_", 5)
            task_id = int(task_id_str)
            hour = int(hour_str)
            time_str = f"{hour:02d}:{min_str}"

            task = await repo.get_task(task_id)
            if not task:
                await query.answer("Задача не найдена")
                return

            if field == "due":
                # Preserve date part, replace time
                due = task.get("due_date") or datetime.now().strftime("%Y-%m-%d")
                date_part = due.split(" ")[0] if " " in due else due
                new_due = f"{date_part} {time_str}"
                await repo.update_task(task_id, due_date=new_due)
                await query.answer(f"Время: {time_str}")

            elif field == "remind":
                due = task.get("due_date") or datetime.now().strftime("%Y-%m-%d")
                date_part = due.split(" ")[0] if " " in due else due
                trigger = f"{date_part} {time_str}"
                reminder = await repo.create_reminder(
                    message=f"{task['title']}",
                    trigger_at=trigger,
                    task_id=task_id
                )
                if handlers.job_queue:
                    handlers._schedule_reminder_job(reminder)
                await query.answer(f"Напоминание: {time_str}")

            # Refresh task detail
            task = await repo.get_task(task_id)
            if task:
                await query.edit_message_text(
                    format_task_detail(task),
                    reply_markup=build_task_detail_keyboard(task_id, view),
                    parse_mode="HTML"
                )

        # ── Thought feed ──
        elif data == "view_thoughts":
            today = datetime.now().strftime("%Y-%m-%d")
            thoughts = await repo.list_thoughts(date=today)
            text = f"<b>Мысли за сегодня ({today})</b>"
            if not thoughts:
                text += "\n\nПока ничего. Нажми ➕ Мысль чтобы добавить."
            await query.edit_message_text(
                text,
                reply_markup=build_thoughts_keyboard(thoughts, today),
                parse_mode="HTML"
            )

        elif data == "new_thought":
            handlers._edit_state[user_id] = {"field": "new_thought"}
            await query.edit_message_text(
                "<b>Новая мысль</b>\n\n"
                "Отправь текст, голосовое или картинку — сохраню в ленту.\n"
                "Текст: просто напиши\n"
                "Голос: расшифрую и сохраню\n"
                "Фото: сохраню на комп и в ленту",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Отмена", callback_data="view_thoughts")
                ]]),
                parse_mode="HTML"
            )

        elif data == "thought_dates":
            dates = await repo.get_thought_dates()
            if not dates:
                await query.answer("Мыслей пока нет")
                return
            today = datetime.now().strftime("%Y-%m-%d")
            await query.edit_message_text(
                "<b>Дни с мыслями:</b>",
                reply_markup=build_thought_dates_keyboard(dates),
                parse_mode="HTML"
            )

        elif data.startswith("thought_date_"):
            date = data.split("_", 2)[2]
            thoughts = await repo.list_thoughts(date=date)
            await query.edit_message_text(
                f"<b>Мысли за {date} ({len(thoughts)}):</b>",
                reply_markup=build_thoughts_keyboard(thoughts, date),
                parse_mode="HTML"
            )

        elif data.startswith("thought_del_"):
            thought_id = int(data.split("_")[2])
            await repo.db.execute("DELETE FROM thoughts WHERE id = ?", (thought_id,))
            await repo.db.commit()
            await query.answer("Удалено")
            today = datetime.now().strftime("%Y-%m-%d")
            thoughts = await repo.list_thoughts(date=today)
            await query.edit_message_text(
                f"<b>Мысли за сегодня ({today})</b>",
                reply_markup=build_thoughts_keyboard(thoughts, today),
                parse_mode="HTML"
            )

        elif data.startswith("thought_"):
            thought_id = int(data.split("_")[1])
            thought = await repo.get_thought(thought_id)
            if not thought:
                await query.answer("Не найдено")
                return
            if thought["kind"] == "image" and thought["image_path"]:
                # Send the image file
                img_path = thought["image_path"]
                if os.path.exists(img_path):
                    caption = f"🖼 {thought['created_at']}"
                    await query.message.reply_photo(
                        photo=open(img_path, "rb"),
                        caption=caption,
                        reply_markup=build_thought_detail_keyboard(thought_id)
                    )
                    await query.answer()
                    return
            text = f"<b>💭 {thought['created_at']}</b>\n\n{thought['content']}"
            await query.edit_message_text(
                text,
                reply_markup=build_thought_detail_keyboard(thought_id),
                parse_mode="HTML"
            )

        else:
            await query.answer("Неизвестное действие")

    except Exception as e:
        logger.error(f"Menu callback error: {e}")
        await query.answer("Ошибка")
        try:
            await query.edit_message_text(
                "Произошла ошибка. Возвращаю в меню.",
                reply_markup=build_main_menu(),
                parse_mode="HTML"
            )
        except Exception:
            pass

    await query.answer()


def _compute_score(task: dict) -> float:
    """Score = (1 / max(days_until_due, 1)) * 0.6 + priority * 0.4"""
    due_date = task.get("due_date") or ""
    priority = task.get("priority", 0)
    if due_date:
        try:
            due_dt = datetime.strptime(due_date.split(" ")[0], "%Y-%m-%d")
            days_until_due = (due_dt - datetime.now()).days
        except (ValueError, IndexError):
            days_until_due = 999
    else:
        days_until_due = 999
    return (1.0 / max(days_until_due, 1)) * 0.6 + priority * 0.4


def _score_indicator(score: float) -> str:
    if score > 1.5:
        return "🔴"
    elif score > 0.5:
        return "🟡"
    else:
        return "🟢"


async def _build_view_data(repo, view: str) -> tuple[list[dict], dict[int, str], str, str]:
    """Shared logic: fetch tasks for a view, return (tasks, times, text, view_key)."""
    if view == "today":
        today = datetime.now().strftime("%Y-%m-%d")
        tasks = await repo.list_tasks(limit=50)
        subset = [t for t in tasks
                  if (t.get("due_date") or "").startswith(today)
                  and t.get("status") != "cancelled"]
        title = f"Задачи на сегодня ({today})"
    elif view == "tomorrow":
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        tasks = await repo.list_tasks(limit=50)
        subset = [t for t in tasks
                  if (t.get("due_date") or "").startswith(tomorrow)
                  and t.get("status") != "cancelled"]
        title = f"Задачи на завтра ({tomorrow})"
    elif view.startswith("proj_"):
        proj_id = int(view.split("_")[1])
        proj = await repo.get_project(proj_id)
        tasks = await repo.list_tasks(project_id=proj_id, limit=50)
        subset = [t for t in tasks if t.get("status") != "cancelled"]
        title = f"{proj['name']} — задачи" if proj else "Задачи проекта"
    else:
        tasks = await repo.list_tasks(limit=50)
        subset = [t for t in tasks if t.get("status") != "cancelled"]
        title = "Все задачи"
    # Compute score and sort
    for t in subset:
        t["score"] = _compute_score(t)
    subset.sort(key=lambda t: t["score"], reverse=True)
    times = await _get_reminder_times(repo, subset)
    text = f"<b>{title} ({len(subset)}):</b>"
    return subset, times, text, view


async def _show_view(query, repo, view: str):
    """Navigate back to a task list view."""
    subset, times, text, view_key = await _build_view_data(repo, view)
    kb = build_task_list_keyboard(subset, view_key, times)
    await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")


async def _show_projects(query, repo):
    projects = await repo.list_projects("active")
    text = f"<b>Проекты ({len(projects)}):</b>" if projects else "<b>Проектов нет</b>"
    await query.edit_message_text(
        text,
        reply_markup=build_project_list_keyboard(projects),
        parse_mode="HTML"
    )


# ── Edit state text handler ─────────────────────────────────────


async def handle_edit_input(handlers, update, context):
    """Process text input when user is in edit mode."""
    user_id = update.effective_user.id
    state = handlers._edit_state.pop(user_id, None)

    if state is None:
        return False  # Not in edit mode, caller should continue NL parsing

    repo = handlers.processor.repo
    field = state.get("field")
    task_id = state.get("task_id")
    view = state.get("view", "all")
    text = update.message.text.strip()

    if field == "title":
        await repo.update_task(task_id, title=text)
        await update.message.reply_text(
            f"Название обновлено ✅",
            reply_markup=build_back_to_menu()
        )
        task = await repo.get_task(task_id)
        await update.message.reply_text(
            format_task_detail(task),
            reply_markup=build_task_detail_keyboard(task_id, view),
            parse_mode="HTML"
        )

    elif field == "due_date":
        from utils.time_utils import parse_time
        trigger, clean = parse_time(text)
        if trigger:
            await repo.update_task(task_id, due_date=trigger.split(" ")[0] if " " in trigger else trigger)
            await update.message.reply_text(f"Дата обновлена на {trigger} ✅")
        else:
            await repo.update_task(task_id, due_date=text)
            await update.message.reply_text(f"Дата обновлена на {text} ✅")
        task = await repo.get_task(task_id)
        await update.message.reply_text(
            format_task_detail(task),
            reply_markup=build_task_detail_keyboard(task_id, view),
            parse_mode="HTML"
        )

    elif field == "tags":
        await repo.update_task(task_id, tags=text)
        await update.message.reply_text(f"Теги обновлены ✅")
        task = await repo.get_task(task_id)
        await update.message.reply_text(
            format_task_detail(task),
            reply_markup=build_task_detail_keyboard(task_id, view),
            parse_mode="HTML"
        )

    elif field == "reminder":
        from utils.time_utils import parse_time
        trigger, clean = parse_time(text)
        task = await repo.get_task(task_id)
        if trigger:
            reminder = await repo.create_reminder(
                message=f"{task['title']}",
                trigger_at=trigger,
                task_id=task_id
            )
            if handlers.job_queue:
                handlers._schedule_reminder_job(reminder)
            await update.message.reply_text(
                f"Напоминание создано на {trigger} ✅",
                reply_markup=build_back_to_menu()
            )
        else:
            await update.message.reply_text(
                "Не понял время. Попробуй ещё раз.",
                reply_markup=build_back_to_menu()
            )

    elif field == "new_task":
        parsed = await handlers.nl.parse(text) if handlers.nl else None
        if parsed and handlers._has_actions(parsed):
            handlers._pending_intents[user_id] = parsed
            confirm_msg = handlers._build_confirm_message(parsed)
            await update.message.reply_text(
                confirm_msg,
                reply_markup=build_confirm_keyboard(),
                parse_mode="HTML"
            )
        elif parsed:
            query_data = await handlers._execute_intents(parsed)
            reply = parsed.get("reply", "")
            if query_data:
                reply = reply + "\n\n" + query_data if reply else query_data
            await update.message.reply_text(reply or "Создал!", parse_mode="HTML")
        else:
            await update.message.reply_text(
                "Не удалось распознать. Попробуй /task_add",
                reply_markup=build_back_to_menu()
            )

    elif field == "new_remind":
        from utils.time_utils import parse_time
        trigger, msg = parse_time(text)
        if trigger:
            reminder = await repo.create_reminder(message=msg, trigger_at=trigger)
            if handlers.job_queue:
                handlers._schedule_reminder_job(reminder)
            await update.message.reply_text(
                f"Напоминание создано: {msg} → {trigger} ✅",
                reply_markup=build_back_to_menu()
            )
        else:
            await update.message.reply_text(
                "Не понял время. Пример: купить хлеб завтра 15:00",
                reply_markup=build_back_to_menu()
            )

    elif field == "new_proj_task":
        project_id = state.get("project_id")
        parsed = await handlers.nl.parse(text) if handlers.nl else None
        if parsed and handlers._has_actions(parsed):
            handlers._pending_intents[user_id] = {**parsed, "_project_id": project_id}
            confirm_msg = handlers._build_confirm_message(parsed)
            await update.message.reply_text(
                confirm_msg,
                reply_markup=build_confirm_keyboard(),
                parse_mode="HTML"
            )
        elif parsed:
            # Execute directly, injecting project_id
            for t in parsed.get("tasks", []):
                t["project_id"] = project_id
            await handlers._execute_intents(parsed)
            await update.message.reply_text(
                parsed.get("reply", "Создал!"),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀ К проекту", callback_data=f"project_{project_id}")
                ]]),
                parse_mode="HTML"
            )
        else:
            # Fallback: create task directly
            task = await repo.create_task(title=text, project_id=project_id)
            await update.message.reply_text(
                f"Задача создана: #{task['id']} {task['title']}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀ К проекту", callback_data=f"project_{project_id}")
                ]])
            )

    elif field == "new_thought":
        kind = "text"
        image_path = ""
        await repo.create_thought(content=text, kind=kind, image_path=image_path)
        await update.message.reply_text(
            "Мысль сохранена 💭",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀ К ленте", callback_data="view_thoughts"),
                InlineKeyboardButton("➕ Ещё", callback_data="new_thought"),
            ]])
        )

    elif field == "new_project":
        existing = await repo.get_project_by_name(text)
        if existing:
            await update.message.reply_text(
                f"Проект '{text}' уже существует",
                reply_markup=build_back_to_menu()
            )
        else:
            proj = await repo.create_project(text)
            await update.message.reply_text(
                f"Проект '{proj['name']}' создан ✅",
                reply_markup=build_back_to_menu()
            )

    return True  # Handled as edit input


def build_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("OK", callback_data="confirm_ok"),
            InlineKeyboardButton("Нет", callback_data="confirm_no"),
        ]
    ])
