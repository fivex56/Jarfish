from datetime import datetime

from db.repository import Repository


class ReminderService:
    def __init__(self, repo: Repository):
        self.repo = repo

    async def reschedule_repeating(self, reminder: dict):
        """After a repeating reminder fires, create the next occurrence."""
        if reminder.get("repeat_interval", "none") == "none":
            return

        interval = reminder["repeat_interval"]
        now = datetime.now()
        old_trigger = datetime.fromisoformat(reminder["trigger_at"])

        # Calculate next trigger
        if interval == "daily":
            new_trigger = old_trigger.replace(day=old_trigger.day)
            from datetime import timedelta
            new_trigger = old_trigger + timedelta(days=1)
        elif interval == "weekly":
            from datetime import timedelta
            new_trigger = old_trigger + timedelta(weeks=1)
        else:
            return

        # Only schedule future reminders
        if new_trigger > now:
            await self.repo.create_reminder(
                message=reminder["message"],
                trigger_at=new_trigger.strftime("%Y-%m-%d %H:%M"),
                task_id=reminder.get("task_id"),
                repeat_interval=interval
            )
