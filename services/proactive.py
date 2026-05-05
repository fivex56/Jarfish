from datetime import time

from db.repository import Repository
from bot.formatting import bold, format_task, format_reminder


class ProactiveService:
    def __init__(self, job_queue, repo: Repository, out_queue, bot):
        self.job_queue = job_queue
        self.repo = repo
        self.out_queue = out_queue
        self.bot = bot

    async def _get_user_id(self) -> int:
        return self.bot._user_id

    async def morning_briefing(self, context):
        tasks = await self.repo.get_today_tasks()
        overdue = await self.repo.get_overdue_tasks()
        reminders = await self.repo.get_upcoming_reminders()

        lines = [f"☀️ {bold('Утренний брифинг. Доброе утро!')}\n"]

        total = len(tasks) + len(overdue)
        if total == 0:
            lines.append("На сегодня задач нет. Хорошего дня!")
        else:
            if tasks:
                lines.append(f"Сегодня ({len(tasks)}):")
                for i, t in enumerate(tasks, 1):
                    lines.append(format_task(t, i))
            if overdue:
                lines.append(f"\n{bold('Просрочено')} ({len(overdue)}):")
                for i, t in enumerate(overdue, 1):
                    lines.append(format_task(t, i))

        if reminders:
            lines.append(f"\n{bold('Напоминания на сегодня')} ({len(reminders)}):")
            for r in reminders:
                lines.append(format_reminder(r))

        text = "\n".join(lines)
        await self.out_queue.put({"text": text, "source": "system"})
        await context.bot.send_message(chat_id=context.job.data["user_id"], text=text, parse_mode="HTML")

    async def evening_wrapup(self, context):
        tasks_todo = await self.repo.list_tasks(status="todo", limit=5)
        tasks_done_raw = await self.repo.list_tasks(status="done", limit=10)

        # Filter tasks done today
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        tasks_done = [t for t in tasks_done_raw if t.get("completed_at", "").startswith(today)]

        lines = [f"\U0001f31a {bold('Вечерний обзор')}\n"]

        if tasks_done:
            lines.append(f"Сегодня выполнено ({len(tasks_done)}):")
            for i, t in enumerate(tasks_done, 1):
                lines.append(format_task(t, i))
        else:
            lines.append("Сегодня задач не выполнено")

        if tasks_todo:
            lines.append(f"\n{bold('Осталось на завтра')} ({len(tasks_todo)}):")
            for i, t in enumerate(tasks_todo, 1):
                lines.append(format_task(t, i))

        text = "\n".join(lines)
        await self.out_queue.put({"text": text, "source": "system"})
        await context.bot.send_message(chat_id=context.job.data["user_id"], text=text, parse_mode="HTML")

    async def check_overdue(self, context):
        overdue = await self.repo.get_overdue_tasks()
        if overdue:
            lines = [f"⚠️ {bold('Просроченные задачи')} ({len(overdue)}):"]
            for i, t in enumerate(overdue, 1):
                lines.append(format_task(t, i))
            text = "\n".join(lines)
            await self.out_queue.put({"text": text, "source": "system"})
            await context.bot.send_message(chat_id=context.job.data["user_id"], text=text, parse_mode="HTML")

    def schedule_all(self, user_id: int):
        """Schedule all proactive jobs."""
        self.job_queue.run_daily(
            self.morning_briefing,
            time=time(hour=8, minute=0),
            days=(0, 1, 2, 3, 4, 5, 6),
            data={"user_id": user_id},
            name="morning_briefing"
        )
        self.job_queue.run_daily(
            self.evening_wrapup,
            time=time(hour=21, minute=0),
            days=(0, 1, 2, 3, 4, 5, 6),
            data={"user_id": user_id},
            name="evening_wrapup"
        )
        self.job_queue.run_repeating(
            self.check_overdue,
            interval=14400,  # 4 hours
            first=10,
            data={"user_id": user_id},
            name="check_overdue"
        )
