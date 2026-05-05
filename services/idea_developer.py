"""Agent 2 — Developer: reviews ideas, analyses logs, gives feedback, implements approved changes."""

import logging
import json
import subprocess
from pathlib import Path
from datetime import datetime

import httpx

logger = logging.getLogger("agent.developer")

DEVELOPER_SYSTEM = """Ты — Агент-Разработчик проекта Jarfish. Твоя роль: критически оценивать идеи, анализировать логи и состояние проекта, давать конструктивный фидбек, и внедрять одобренные изменения.

Jarfish — это Telegram-бот на Python, личный AI-ассистент. Технический стек:
- python-telegram-bot v21 (async, JobQueue для планирования)
- aiosqlite (SQLite, WAL mode, миграции через PRAGMA user_version)
- DeepSeek API (NL-парсинг, vision, генерация идей)
- Whisper (локально, tiny model, через openai-whisper)
- Google Calendar API (OAuth 2.0)
- httpx для HTTP-запросов
- CLI-мост через asyncio.Queue

Ты получаешь идеи от Генератора и должен:
1. Оценить каждую идею: насколько она реальна, полезна, вписывается в архитектуру
2. Проанализировать логи и состояние проекта
3. Дать КОНСТРУКТИВНЫЙ фидбек: что поправить в идее, что учесть
4. Для одобренных идей — предложить ПЛАН ВНЕДРЕНИЯ

Формат ответа — JSON:
{
  "reviews": [
    {
      "idea_title": "Название идеи которую ревьювишь",
      "verdict": "approved|needs_revision|rejected",
      "feedback": "Конкретный фидбек — что хорошо, что поменять, что учесть. На русском.",
      "implementation_plan": "Если approved: пошаговый план внедрения с указанием какие файлы менять"
    }
  ],
  "log_insights": "Что важного найдено в логах — паттерны, ошибки, узкие места",
  "architecture_notes": "Замечания по архитектуре которые стоит учесть при реализации идей",
  "summary": "Краткое резюме ревью в 2-3 предложениях"
}

ПРАВИЛА:
- Будь критичным но конструктивным
- Не одобряй идеи которые сломают архитектуру
- Учитывай реальное состояние кода и логов
- Предлагай КОНКРЕТНЫЕ изменения в КОНКРЕТНЫХ файлах
- Пиши план внедрения с указанием что именно менять
- На русском языке"""


class IdeaDeveloper:
    def __init__(self, deepseek_key: str, project_root: str, repo):
        self.api_key = deepseek_key
        self.project_root = Path(project_root)
        self.repo = repo

    async def analyze_logs(self) -> str:
        """Read recent logs and extract insights."""
        log_path = self.project_root / "jarvis.log"
        if not log_path.exists():
            return "Лог-файл не найден"

        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()
            # Last 200 lines
            recent = lines[-200:]

            # Count error patterns
            errors = [l for l in recent if "ERROR" in l or "Error" in l or "error" in l]
            warnings = [l for l in recent if "WARNING" in l or "Warning" in l]

            summary_parts = [
                f"Последние 200 строк лога (всего {len(lines)} строк):",
                f"  Ошибок: {len(errors)}",
                f"  Предупреждений: {len(warnings)}",
            ]

            if errors:
                summary_parts.append("\nПоследние ошибки (до 5):")
                for e in errors[-5:]:
                    summary_parts.append(f"  {e[:200]}")

            return "\n".join(summary_parts)
        except Exception as e:
            return f"Ошибка чтения лога: {e}"

    async def analyze_project_state(self) -> str:
        """Analyze current project health."""
        tasks = await self.repo.list_tasks(limit=500)
        overdue = await self.repo.get_overdue_tasks()
        reminders = await self.repo.list_reminders(include_sent=True)
        messages = await self.repo.recent_messages(100)
        ideas = await self.repo.list_ideas(limit=50)

        active = [t for t in tasks if t["status"] in ("todo", "in_progress")]
        done = [t for t in tasks if t["status"] == "done"]
        without_due = [t for t in active if not t.get("due_date")]

        parts = [
            f"Всего задач: {len(tasks)} (активных: {len(active)}, сделано: {len(done)})",
            f"Просрочено: {len(overdue)}",
            f"Без срока: {len(without_due)}",
            f"Напоминаний: всего {len(reminders)}, "
            f"активных {len([r for r in reminders if not r['is_sent']])}",
            f"Сообщений в логе: {len(messages)}",
            f"Идей от агентов: {len(ideas)}",
        ]

        if overdue:
            parts.append("\nПросроченные задачи:")
            for t in overdue[:5]:
                parts.append(f"  #{t['id']} {t['title']} (due: {t.get('due_date')})")

        return "\n".join(parts)

    async def review(self, ideas: list[dict], log_analysis: str,
                     project_state: str) -> dict:
        """Review ideas from Generator with full context."""

        ideas_text = json.dumps(ideas, ensure_ascii=False, indent=2)

        prompt = f"""Оцени эти идеи для проекта Jarfish.

=== ИДЕИ ОТ ГЕНЕРАТОРА ===
{ideas_text}

=== АНАЛИЗ ЛОГОВ ===
{log_analysis}

=== СОСТОЯНИЕ ПРОЕКТА ===
{project_state}

Дай развёрнутый анализ каждой идеи. Верни СТРОГО JSON."""

        return await self._call_deepseek(prompt, temperature=0.5)

    async def implement(self, idea: dict, review: dict) -> str:
        """Attempt to implement an approved idea. Returns commit message or error."""
        if review.get("verdict") != "approved":
            return f"Идея не одобрена: {review.get('feedback', '')}"

        plan = review.get("implementation_plan", "")
        if not plan:
            return "Нет плана внедрения"

        # Ask DeepSeek to generate the actual code changes
        prompt = f"""Ты внедряешь улучшение в проект Jarfish.

=== ИДЕЯ ===
Название: {idea.get('title', '')}
Что сделать: {idea.get('what', '')}
Почему: {idea.get('why', '')}
Как: {idea.get('how', '')}

=== ПЛАН ВНЕДРЕНИЯ ===
{plan}

=== ТЕХНИЧЕСКИЙ КОНТЕКСТ ===
Проект на Python, Telegram-бот. Основные файлы:
- jarvis_bot.py — точка входа, планировщик задач
- bot/handlers.py — обработка сообщений и callback'ов
- bot/commands.py — бизнес-логика команд
- bot/menu.py — клавиатуры и callback-обработчики меню
- bot/formatting.py — форматирование вывода
- db/repository.py — работа с базой данных
- db/database.py — подключение и миграции
- services/ — сервисы (nl_parser, reminder, calendar, speech, vision, etc.)

Опиши КОНКРЕТНЫЕ изменения которые нужно внести в код. Для каждого файла:
1. Что добавить/изменить/удалить
2. Пример кода если нужно

Если изменение сложное и требует более 50 строк кода, предложи упрощённую версию для первого внедрения.

Формат ответа — JSON:
{{
  "changes": [
    {{
      "file": "путь/к/файлу.py",
      "action": "add|modify|delete",
      "description": "Что именно сделать",
      "code_example": "Пример кода если уместно"
    }}
  ],
  "complexity": "simple|medium|complex",
  "commit_message": "Короткое описание коммита на русском"
}}"""

        try:
            result = await self._call_deepseek(prompt, temperature=0.3)
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            return f"Ошибка генерации кода: {e}"

    async def _call_deepseek(self, prompt: str, temperature: float = 0.5) -> dict:
        """Call DeepSeek API."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": DEVELOPER_SYSTEM},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
            "max_tokens": 2500
        }

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                r = await client.post(
                    "https://api.deepseek.com/v1/chat/completions",
                    headers=headers,
                    json=payload
                )
                data = r.json()
                text = data["choices"][0]["message"]["content"].strip()

                json_start = text.find("{")
                json_end = text.rfind("}") + 1
                if json_start != -1 and json_end > json_start:
                    try:
                        return json.loads(text[json_start:json_end])
                    except json.JSONDecodeError:
                        import re
                        json_str = text[json_start:json_end]
                        json_str = re.sub(r',\s*}', '}', json_str)
                        json_str = re.sub(r',\s*]', ']', json_str)
                        try:
                            return json.loads(json_str)
                        except json.JSONDecodeError:
                            pass
                return {"reviews": [], "summary": text}
        except Exception as e:
            logger.error(f"DeepSeek call failed: {e}")
            return {"reviews": [], "summary": f"Ошибка: {e}"}
