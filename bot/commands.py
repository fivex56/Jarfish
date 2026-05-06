from db.repository import Repository
from bot.formatting import bold, code, format_task, format_project, format_reminder, format_note


class CommandProcessor:
    def __init__(self, repo: Repository, allowed_user_id: int):
        self.repo = repo
        self.allowed_user_id = allowed_user_id

    async def start(self) -> str:
        return (
            f"{bold('Привет! Я Джарвис.')}\n"
            f"Я отслеживаю твои проекты, задачи и напоминания.\n\n"
            f"{bold('Команды:')}\n"
            f"/task_add — добавить задачу\n"
            f"/tasks — список задач\n"
            f"/task_done — отметить задачу выполненной\n"
            f"/project_add — создать проект\n"
            f"/projects — список проектов\n"
            f"/remind — установить напоминание\n"
            f"/reminders — список напоминаний\n"
            f"/note — сохранить заметку\n"
            f"/notes — поиск по заметкам\n"
            f"/summary — сводка на сегодня\n"
            f"/overdue — просроченные задачи\n"
            f"/help — помощь"
        )

    async def help(self) -> str:
        return (
            f"{bold('Помощь по командам')}\n\n"

            f"{bold('Задачи')}\n"
            f"/task_add {code('Заголовок #проект prio:1 due:2026-05-10 Описание')}\n"
            f"  prio: 0-норм, 1-важно, 2-критично\n"
            f"  due: YYYY-MM-DD или 'завтра', 'пятница'\n\n"
            f"/tasks {code('[todo|all]')}\n"
            f"  Без аргументов — все задачи. /tasks todo — только активные\n\n"
            f"/task_done {code('номер')}\n"
            f"  Пример: /task_done 3\n\n"
            f"/task_edit {code('номер поле новое_значение')}\n"
            f"  Пример: /task_edit 5 title Новый заголовок\n\n"
            f"/summary\n"
            f"  Сводка на сегодня: задачи, настроение, статистика\n\n"
            f"/overdue\n"
            f"  Просроченные задачи\n\n"

            f"{bold('Проекты')}\n"
            f"/project_add {code('Название [Описание]')}\n"
            f"  Пример: /project_add POLY Проект по полимерам\n\n"
            f"/projects\n"
            f"  Список всех проектов\n\n"

            f"{bold('Напоминания')}\n"
            f"/remind {code('Текст когда')}\n"
            f"  Пример: /remind Купить молоко завтра в 15:00\n"
            f"  Пример: /remind Позвонить врачу 2026-05-10 11:00\n\n"
            f"/reminders\n"
            f"  Список активных напоминаний\n\n"
            f"/remind_del {code('номер')}\n"
            f"  Удалить напоминание\n\n"

            f"{bold('Заметки')}\n"
            f"/note {code('Текст')}\n"
            f"  Сохранить заметку. Можно добавить #теги\n\n"
            f"/notes {code('[поиск]')}\n"
            f"  Без аргументов — последние заметки. С аргументом — поиск\n\n"

            f"{bold('Голос')}\n"
            f"/voice_on — отвечать голосом (синтез речи)\n"
            f"/voice_off — отвечать текстом\n\n"

            f"{bold('Прочее')}\n"
            f"/start — перезапуск и меню\n"
            f"/menu — главное меню с кнопками\n\n"

            f"{bold('Свободный текст')}\n"
            f"Можешь писать без команд — бот поймёт и создаст задачу или напоминание.\n"
            f"  «напомни завтра в 9 позвонить маме»\n"
            f"  «сделать отчёт до пятницы prio:2»"
        )

    async def task_add(self, args: str) -> str:
        if not args.strip():
            return "Укажи название задачи. Пример: /task_add Починить баг #POLY prio:1 due:завтра"

        title = args.strip()
        project_id = None
        description = ""
        priority = 0
        due_date = None
        tags = ""

        # Parse #project reference
        parts = title.split()
        title_parts = []
        for part in parts:
            if part.startswith("#") and not part.startswith("#") == False:
                tag_name = part[1:]
                project = await self.repo.get_project_by_name(tag_name)
                if project:
                    project_id = project["id"]
                    continue
                tags += f"{tag_name},"
                continue
            if part.startswith("prio:"):
                try:
                    priority = int(part.split(":")[1])
                except (ValueError, IndexError):
                    pass
                continue
            if part.startswith("due:"):
                due_date = part[4:]
                continue
            title_parts.append(part)

        title = " ".join(title_parts)
        if tags:
            tags = tags.rstrip(",")

        task = await self.repo.create_task(
            title=title, project_id=project_id,
            description=description, priority=priority,
            due_date=due_date, tags=tags
        )
        return f"Задача создана:\n{format_task(task)}"

    async def tasks(self, args: str) -> str:
        status = None
        project_id = None
        parts = args.strip().split()
        if parts:
            if parts[0] in ("todo", "in_progress", "done", "blocked"):
                status = parts[0]
            elif parts[0] == "all":
                status = None
            else:
                # Check if it's a project name
                project = await self.repo.get_project_by_name(parts[0])
                if project:
                    project_id = project["id"]

        tasks = await self.repo.list_tasks(status=status, project_id=project_id, limit=30)
        if not tasks:
            return "Задач нет. Создай новую: /task_add"

        lines = [f"{bold('Задачи')} ({len(tasks)}):"]
        for i, t in enumerate(tasks, 1):
            lines.append(format_task(t, i))
        return "\n".join(lines)

    async def task_done(self, args: str) -> str:
        try:
            task_id = int(args.strip())
        except ValueError:
            return "Укажи номер задачи: /task_done 3"
        task = await self.repo.update_task(task_id, status="done")
        if task is None:
            return f"Задача #{task_id} не найдена"
        return f"Задача выполнена: {format_task(task)}"

    async def task_edit(self, args: str) -> str:
        parts = args.strip().split(maxsplit=1)
        if len(parts) < 2:
            return "Формат: /task_edit 5 status=in_progress или prio:2"
        try:
            task_id = int(parts[0])
        except ValueError:
            return "Укажи ID задачи: /task_edit 5 status=in_progress"

        kwargs = {}
        for part in parts[1].split():
            if "=" in part:
                k, v = part.split("=", 1)
                kwargs[k] = v
            elif part.startswith("prio:"):
                kwargs["priority"] = int(part.split(":")[1])

        task = await self.repo.update_task(task_id, **kwargs)
        if task is None:
            return f"Задача #{task_id} не найдена"
        return f"Обновлено: {format_task(task)}"

    async def project_add(self, args: str) -> str:
        if not args.strip():
            return "Укажи название проекта: /project_add МойПроект"
        parts = args.strip().split(maxsplit=1)
        name = parts[0]
        desc = parts[1] if len(parts) > 1 else ""
        existing = await self.repo.get_project_by_name(name)
        if existing:
            return f"Проект '{name}' уже существует"
        project = await self.repo.create_project(name, desc)
        return f"Проект создан: {format_project(project)}"

    async def projects(self, args: str = "") -> str:
        status = args.strip() if args.strip() else "active"
        if status == "all":
            status = "active"  # show active by default
        projects = await self.repo.list_projects(status)
        if not projects:
            return "Проектов нет. Создай: /project_add"
        lines = [f"{bold('Проекты')} ({len(projects)}):"]
        for p in projects:
            task_count = len(await self.repo.list_tasks(status="todo", project_id=p["id"]))
            lines.append(f"{format_project(p)} [{task_count} задач]")
        return "\n".join(lines)

    async def remind(self, args: str) -> tuple[str, dict | None]:
        from utils.time_utils import parse_time
        if not args.strip():
            return "Укажи напоминание: /remind Текст когда\nПример: /remind Купить молоко завтра 15:00", None

        trigger_at, message = parse_time(args.strip())
        if trigger_at is None:
            return "Не понял время. Укажи дату/время: завтра 15:00 или 2026-05-10 11:00", None

        reminder = await self.repo.create_reminder(message=message, trigger_at=trigger_at)
        return f"Напоминание создано:\n{format_reminder(reminder)}", reminder

    async def reminders(self, args: str = "") -> str:
        reminders = await self.repo.list_reminders()
        if not reminders:
            return "Напоминаний нет. Создай: /remind"
        lines = [f"{bold('Напоминания')} ({len(reminders)}):"]
        for r in reminders:
            lines.append(format_reminder(r))
        return "\n".join(lines)

    async def remind_del(self, args: str) -> str:
        try:
            rid = int(args.strip())
        except ValueError:
            return "Укажи ID напоминания: /remind_del 3"
        await self.repo.delete_reminder(rid)
        return f"Напоминание #{rid} удалено"

    async def note(self, args: str) -> str:
        if not args.strip():
            return "Укажи текст заметки: /note Важная мысль #идея"

        text = args.strip()
        title = ""
        tags = ""
        project_id = None

        # Extract #tags and #project
        words = text.split()
        content_parts = []
        for word in words:
            if word.startswith("#"):
                tag = word[1:]
                project = await self.repo.get_project_by_name(tag)
                if project:
                    project_id = project["id"]
                else:
                    tags += f"{tag},"
                continue
            content_parts.append(word)
        content = " ".join(content_parts)
        if not title:
            title = content[:50]

        note = await self.repo.create_note(content=content, title=title, tags=tags.rstrip(","), project_id=project_id)
        return f"Заметка сохранена: {format_note(note)}"

    async def notes(self, args: str = "") -> str:
        keyword = args.strip()
        if keyword:
            notes = await self.repo.search_notes(keyword)
        else:
            notes = await self.repo.list_notes(20)
        if not notes:
            return "Заметок нет" + (f" по '{keyword}'" if keyword else "")
        header = f"Заметки по '{keyword}' ({len(notes)}):" if keyword else f"Заметки ({len(notes)}):"
        lines = [bold(header)]
        for n in notes:
            lines.append(format_note(n))
        return "\n".join(lines)

    async def summary(self) -> str:
        tasks_today = await self.repo.get_today_tasks()
        overdue = await self.repo.get_overdue_tasks()
        reminders = await self.repo.get_upcoming_reminders()
        projects = await self.repo.list_projects("active")

        lines = [f"{bold('Сводка на сегодня')}\n"]

        if projects:
            lines.append(f"🗂 Проектов: {len(projects)}")
        else:
            lines.append("🗂 Проектов: 0")

        if tasks_today:
            lines.append(f"\n{bold('Задачи на сегодня')} ({len(tasks_today)}):")
            for i, t in enumerate(tasks_today, 1):
                lines.append(format_task(t, i))
        else:
            lines.append(f"\n{bold('На сегодня задач нет')}")

        if overdue:
            lines.append(f"\n{bold('Просрочено')} ({len(overdue)}):")
            for i, t in enumerate(overdue, 1):
                lines.append(format_task(t, i))

        if reminders:
            lines.append(f"\n{bold('Ближайшие напоминания')} ({len(reminders)}):")
            for r in reminders:
                lines.append(format_reminder(r))

        return "\n".join(lines)

    async def overdue(self) -> str:
        overdue = await self.repo.get_overdue_tasks()
        if not overdue:
            return "Просроченных задач нет"
        lines = [f"{bold('Просроченные задачи')} ({len(overdue)}):"]
        for i, t in enumerate(overdue, 1):
            lines.append(format_task(t, i))
        return "\n".join(lines)
