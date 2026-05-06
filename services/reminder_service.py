from datetime import datetime, timedelta

from db.repository import Repository

# Minutes in each base interval
INTERVAL_MINUTES = {
    "daily": 1440,
    "weekly": 10080,
}

MIN_FACTOR = 0.3
MAX_FACTOR = 3.0


class ReminderService:
    def __init__(self, repo: Repository):
        self.repo = repo

    @staticmethod
    def _base_interval_minutes(repeat_interval: str) -> int | None:
        return INTERVAL_MINUTES.get(repeat_interval)

    async def reschedule_repeating(self, reminder: dict):
        """After a repeating reminder fires, create the next occurrence with adaptive interval."""
        repeat_interval = reminder.get("repeat_interval", "none")
        if repeat_interval == "none":
            return

        base_minutes = self._base_interval_minutes(repeat_interval)
        if base_minutes is None:
            return

        # Check if linked task was completed to adjust the interval factor
        old_factor = float(reminder.get("adaptive_factor", 1.0))
        new_factor = await self._adjust_factor(reminder, old_factor)

        # Calculate adaptive interval in minutes
        adaptive_minutes = base_minutes * new_factor

        now = datetime.now()
        old_trigger = datetime.fromisoformat(reminder["trigger_at"])
        new_trigger = old_trigger + timedelta(minutes=adaptive_minutes)

        # Only schedule future reminders
        if new_trigger > now:
            await self.repo.create_reminder(
                message=reminder["message"],
                trigger_at=new_trigger.strftime("%Y-%m-%d %H:%M"),
                task_id=reminder.get("task_id"),
                repeat_interval=repeat_interval,
                adaptive_factor=new_factor,
            )

    async def _adjust_factor(self, reminder: dict, current_factor: float) -> float:
        """Adjust adaptive factor based on linked task completion status.

        Task done → widen interval by 10% (user doesn't need frequent reminders).
        Task not done → shorten interval by 20% (user needs more nudging).
        Factor is clamped to [MIN_FACTOR, MAX_FACTOR].
        """
        task_id = reminder.get("task_id")
        if task_id is None:
            return current_factor

        task = await self.repo.get_task(task_id)
        if task is None:
            return current_factor

        if task.get("status") == "done":
            new_factor = current_factor * 1.1
        else:
            new_factor = current_factor * 0.8

        return max(MIN_FACTOR, min(MAX_FACTOR, new_factor))
