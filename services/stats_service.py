import io
import os
import tempfile
from datetime import datetime

from db.repository import Repository

DAY_NAMES = ["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"]
DAY_NAMES_FULL = ["Воскресенье", "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"]

HOUR_BLOCKS = [
    ("Ночь   (00-06)", 0, 6),
    ("Утро   (06-12)", 6, 12),
    ("День   (12-18)", 12, 18),
    ("Вечер  (18-24)", 18, 24),
]


class StatsService:
    def __init__(self, repo: Repository):
        self.repo = repo

    async def generate_report(self) -> str:
        """Build a full text stats report with ASCII charts."""
        lines = ["<b>Аналитика продуктивности</b>\n"]
        lines.append(self._separator())

        # 1. Task status overview
        lines.append(await self._status_overview())

        # 2. Completion stats
        lines.append(await self._completion_stats())

        # 3. Productivity by day of week
        lines.append(await self._day_of_week_chart())

        # 4. Productivity by time of day
        lines.append(await self._time_of_day_chart())

        # 5. Daily completion trend
        lines.append(await self._completion_timeline_chart())

        # 6. Reschedule stats
        lines.append(await self._reschedule_stats())

        return "\n".join(lines)

    async def generate_chart_png(self) -> str | None:
        """Generate a daily-completion bar chart as PNG. Returns file path or None."""
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            return None

        timeline = await self.repo.completion_timeline(limit=30)
        if not timeline or len(timeline) < 2:
            return None

        days = [d["day"] for d in timeline]
        counts = [d["cnt"] for d in timeline]

        plt.figure(figsize=(10, 4))
        plt.bar(days, counts, color="#4CAF50", edgecolor="#2E7D32", linewidth=0.5)
        plt.title("Выполнено задач по дням", fontsize=14, fontweight="bold")
        plt.xlabel("Дата")
        plt.ylabel("Задач")
        plt.xticks(rotation=45, ha="right", fontsize=8)
        plt.tight_layout()

        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        plt.savefig(tmp.name, dpi=100)
        plt.close()
        return tmp.name

    async def _status_overview(self) -> str:
        counts = await self.repo.count_tasks_by_status()
        total = sum(counts.values())
        if total == 0:
            return "<b>Задач пока нет</b> — создай первую: /task_add"

        done = counts.get("done", 0)
        todo = counts.get("todo", 0)
        in_progress = counts.get("in_progress", 0)
        blocked = counts.get("blocked", 0)
        cancelled = counts.get("cancelled", 0)
        overdue = await self.repo.count_overdue_tasks()
        rate = round(done / total * 100) if total else 0

        lines = ["<b>Обзор задач</b>"]
        lines.append(f"  Всего:       {total:>4}")
        lines.append(f"  Выполнено:   {done:>4}  ({rate}%)")
        lines.append(f"  В работе:    {in_progress:>4}")
        lines.append(f"  Ожидают:     {todo:>4}")
        lines.append(f"  Заблокировано: {blocked:>3}")
        lines.append(f"  Отменено:    {cancelled:>4}")
        lines.append(f"  Просрочено:  {overdue:>4}")

        # ASCII bar: completion rate
        bar_len = 20
        filled = round(done / total * bar_len) if total else 0
        bar = "█" * filled + "░" * (bar_len - filled)
        lines.append(f"\n  Прогресс:  {bar}  {rate}%")
        lines.append("")
        return "\n".join(lines)

    async def _completion_stats(self) -> str:
        avg_hours = await self.repo.avg_completion_time_hours()
        lines = ["<b>Скорость выполнения</b>"]
        if avg_hours is not None:
            if avg_hours < 24:
                lines.append(f"  Среднее время:  {avg_hours:.1f} ч")
            else:
                lines.append(f"  Среднее время:  {avg_hours / 24:.1f} дн")
        else:
            lines.append("  Нет завершённых задач для расчёта")

        # Top tags from completed tasks
        rows = await self.repo.db.fetch_all(
            "SELECT tags FROM tasks WHERE status = 'done' AND tags != ''")
        tag_counts = {}
        for r in rows:
            for t in (dict(r)["tags"] or "").split(","):
                t = t.strip()
                if t:
                    tag_counts[t] = tag_counts.get(t, 0) + 1
        if tag_counts:
            top = sorted(tag_counts.items(), key=lambda x: -x[1])[:5]
            tag_str = "  ".join(f"#{t}:{c}" for t, c in top)
            lines.append(f"  Топ тегов:  {tag_str}")

        lines.append("")
        return "\n".join(lines)

    async def _day_of_week_chart(self) -> str:
        dow_data = await self.repo.tasks_by_day_of_week()
        if not dow_data:
            return ""

        # Build lookup: day_index -> count
        dow_map = {d["dow"]: d["cnt"] for d in dow_data}
        max_cnt = max(dow_map.values()) if dow_map else 1
        bar_len = 15

        lines = ["<b>Продуктивность по дням недели</b>"]
        for idx in range(7):
            cnt = dow_map.get(idx, 0)
            filled = round(cnt / max_cnt * bar_len) if max_cnt else 0
            bar = "█" * filled + "░" * (bar_len - filled)
            lines.append(f"  {DAY_NAMES[idx]}  {bar}  {cnt}")

        # Highlight most productive day
        best_idx = max(dow_map, key=dow_map.get)
        lines.append(f"\n  Самый продуктивный день: <b>{DAY_NAMES_FULL[best_idx]}</b>")
        lines.append("")
        return "\n".join(lines)

    async def _time_of_day_chart(self) -> str:
        hour_data = await self.repo.tasks_by_hour_of_day()
        if not hour_data:
            return ""

        hour_map = {d["hour"]: d["cnt"] for d in hour_data}
        blocks = []
        for label, start, end in HOUR_BLOCKS:
            total = sum(hour_map.get(h, 0) for h in range(start, end))
            blocks.append((label, total))

        max_cnt = max(b[1] for b in blocks) if blocks else 1
        bar_len = 15

        lines = ["<b>Продуктивность по времени суток</b>"]
        for label, cnt in blocks:
            filled = round(cnt / max_cnt * bar_len) if max_cnt else 0
            bar = "█" * filled + "░" * (bar_len - filled)
            lines.append(f"  {label}  {bar}  {cnt}")

        best_block = max(blocks, key=lambda b: b[1])
        lines.append(f"\n  Самое продуктивное время: <b>{best_block[0]}</b>")
        lines.append("")
        return "\n".join(lines)

    async def _completion_timeline_chart(self) -> str:
        timeline = await self.repo.completion_timeline(limit=14)
        if not timeline:
            return ""

        max_cnt = max(d["cnt"] for d in timeline) if timeline else 1
        bar_len = 12

        lines = ["<b>Выполнение задач за последние дни</b>"]
        for d in timeline:
            cnt = d["cnt"]
            filled = round(cnt / max_cnt * bar_len) if max_cnt else 0
            bar = "▓" * filled + "░" * (bar_len - filled)
            day_label = d["day"][5:]  # MM-DD part
            lines.append(f"  {day_label}  {bar}  {cnt}")

        lines.append("")
        return "\n".join(lines)

    async def _reschedule_stats(self) -> str:
        stats = await self.repo.reschedule_stats()
        total = stats.get("total_with_reschedules", 0) or 0
        avg = stats.get("avg_reschedules", 0) or 0

        lines = ["<b>Переносы задач</b>"]
        if total:
            lines.append(f"  Задач с переносами:  {total}")
            lines.append(f"  Среднее переносов:  {avg:.1f}")
        else:
            lines.append("  Переносов пока не было")
        lines.append("")
        return "\n".join(lines)

    def _separator(self) -> str:
        return "─" * 30
