"""Agent 2 — Developer: uses Claude CLI to review ideas and implement changes in real files."""

import asyncio
import logging
import json
import subprocess
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("agent.developer")


class IdeaDeveloper:
    """Developer agent that uses Claude Code CLI for real file access and code changes."""

    def __init__(self, project_root: str, repo):
        self.project_root = Path(project_root)
        self.repo = repo

    async def analyze_logs(self) -> str:
        """Read recent logs and extract insights."""
        log_path = self.project_root / "jarvis.log"
        if not log_path.exists():
            return "Лог-файл не найден"

        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()
            recent = lines[-200:]
            errors = [l for l in recent if "ERROR" in l or "Error" in l or "error" in l]
            warnings = [l for l in recent if "WARNING" in l or "Warning" in l]

            parts = [
                f"Последние 200 строк лога (всего {len(lines)} строк):",
                f"  Ошибок: {len(errors)}",
                f"  Предупреждений: {len(warnings)}",
            ]
            if errors:
                parts.append("\nПоследние ошибки (до 5):")
                for e in errors[-5:]:
                    parts.append(f"  {e[:200]}")
            return "\n".join(parts)
        except Exception as e:
            return f"Ошибка чтения лога: {e}"

    async def analyze_project_state(self) -> str:
        """Analyze current project health from DB."""
        tasks = await self.repo.list_tasks(limit=500)
        overdue = await self.repo.get_overdue_tasks()
        reminders = await self.repo.list_reminders(include_sent=True)
        messages = await self.repo.recent_messages(100)
        ideas = await self.repo.list_ideas(limit=50)

        active = [t for t in tasks if t["status"] in ("todo", "in_progress")]
        done = [t for t in tasks if t["status"] == "done"]

        parts = [
            f"Всего задач: {len(tasks)} (активных: {len(active)}, сделано: {len(done)})",
            f"Просрочено: {len(overdue)}",
            f"Напоминаний: {len(reminders)} (активных: {len([r for r in reminders if not r['is_sent']])})",
            f"Сообщений: {len(messages)}",
            f"Идей от агентов: {len(ideas)}",
        ]
        return "\n".join(parts)

    async def review(self, ideas: list[dict], log_analysis: str,
                     project_state: str) -> dict:
        """Use Claude CLI to review ideas — Claude reads actual project files."""

        ideas_text = json.dumps(ideas, ensure_ascii=False, indent=2)

        prompt = f"""Ты — Агент-Разработчик проекта Jarfish (Telegram-бот на Python, личный AI-ассистент).

Прочитай ключевые файлы проекта (jarvis_bot.py, bot/handlers.py, bot/menu.py, bot/commands.py, services/ — хотя бы по одному файлу из каждой папки), чтобы понять архитектуру.

Затем оцени эти идеи от Генератора:

{ideas_text}

Данные о проекте из БД:
{project_state}

Анализ логов:
{log_analysis}

Для КАЖДОЙ идеи дай вердикт (approved/needs_revision/rejected) и КОНКРЕТНЫЙ фидбек на русском.
Для одобренных — напиши какие файлы менять и как именно.

Ответь КОРОТКО (не более 300 слов на русском) в формате:

ОДОБРЕНО:
- [название идеи]: [почему + какие файлы менять]

НУЖНА ДОРАБОТКА:
- [название идеи]: [что поменять]

ОТКЛОНЕНО:
- [название идеи]: [причина]

ИТОГО: X одобрено / Y на доработку / Z отклонено"""

        output = await self._run_claude(prompt)
        return self._parse_review_output(output, ideas)

    async def implement(self, idea: dict) -> str:
        """Use Claude CLI to implement an approved idea in actual files."""

        prompt = f"""Ты — разработчик проекта Jarfish. Твоя задача: ВНЕДРИТЬ улучшение в код.

=== ЧТО ДЕЛАЕМ ===
{idea.get('title', '')}: {idea.get('what', '')}

=== ПОЧЕМУ ===
{idea.get('why', '')}

=== КАК ===
{idea.get('how', '')}

=== ПОРЯДОК ===
1. Прочитай файлы которые нужно менять
2. Внеси изменения через Edit (меняй существующие файлы, не создавай новые без крайней нужды)
3. Убедись что изменения корректны и не ломают архитектуру
4. Сделай коммит с осмысленным сообщением на русском

Если идея слишком сложная для одной итерации — реализуй упрощённую версию, но сделай ХОТЯ БЫ ЧТО-ТО.
Если идея вообще нереализуема — объясни почему.

ВАЖНО: работай быстро. Минимум чтения, максимум действия."""

        output = await self._run_claude(prompt)
        return output[:1000]

    async def _run_claude(self, prompt: str) -> str:
        """Execute Claude CLI in non-interactive mode and return output."""
        try:
            # Run in executor to not block the event loop
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    [
                        "claude", "-p", prompt,
                        "--permission-mode", "bypassPermissions",
                        "--output-format", "text",
                        "--max-turns", "20",
                        "--allowedTools", "Read,Edit,Write,Bash(git *),Glob,Grep"
                    ],
                    cwd=str(self.project_root),
                    capture_output=True,
                    text=True,
                    timeout=600,  # 10 minutes max
                    encoding="utf-8"
                )
            )

            if result.returncode != 0:
                stderr = result.stderr[:500] if result.stderr else ""
                logger.error(f"Claude CLI failed (exit {result.returncode}): {stderr}")
                return f"Ошибка Claude CLI: {stderr}"

            return result.stdout or "Claude выполнил задачу без текстового ответа"

        except subprocess.TimeoutExpired:
            logger.error("Claude CLI timed out after 10 minutes")
            return "Таймаут Claude CLI (10 минут)"
        except Exception as e:
            logger.error(f"Claude CLI error: {e}")
            return f"Ошибка запуска Claude CLI: {e}"

    @staticmethod
    def _parse_review_output(output: str, ideas: list[dict]) -> dict:
        """Parse Claude's text output into structured review dict."""
        approved = []
        needs_revision = []
        rejected = []

        lines = output.split("\n")
        current_section = None

        for line in lines:
            line = line.strip()
            if "ОДОБРЕНО" in line.upper():
                current_section = "approved"
                continue
            elif "ДОРАБОТК" in line.upper() or "НУЖНА" in line.upper():
                current_section = "needs_revision"
                continue
            elif "ОТКЛОНЕНО" in line.upper():
                current_section = "rejected"
                continue
            elif "ИТОГО" in line.upper():
                current_section = None
                continue

            if line.startswith("-") and current_section:
                # Extract idea title and feedback
                title_end = line.find("]:")
                if title_end == -1:
                    title_end = line.find(":")
                if title_end == -1:
                    title_end = len(line)

                title = line[1:title_end].strip().lstrip("- ").strip("[] ")
                title = title.replace("**", "").strip()
                feedback = line[title_end + 1:].strip() if title_end < len(line) else ""

                review = {
                    "idea_title": title,
                    "verdict": current_section,
                    "feedback": feedback[:500],
                    "implementation_plan": feedback[:500] if current_section == "approved" else ""
                }

                if current_section == "approved":
                    approved.append(review)
                elif current_section == "needs_revision":
                    needs_revision.append(review)
                elif current_section == "rejected":
                    rejected.append(review)

        return {
            "reviews": approved + needs_revision + rejected,
            "log_insights": "",
            "architecture_notes": "",
            "summary": f"Claude проверил {len(ideas)} идей: {len(approved)} одобрено, {len(needs_revision)} на доработку, {len(rejected)} отклонено"
        }
