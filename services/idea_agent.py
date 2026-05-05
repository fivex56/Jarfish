"""Daily idea agent: analyzes logs and project state, sends improvement suggestions to Telegram."""
import logging
import os
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

DEEPSEEK_API = "https://api.deepseek.com/v1/chat/completions"

AGENT_PROMPT = """Ты — технический аналитик персонального проекта "Jarvis Bot". Твоя задача — раз в сутки анализировать состояние проекта и предлагать идеи по улучшению.

Jarvis Bot — это персональный Telegram-бот-ассистент, который:
- Управляет задачами, проектами, напоминаниями, заметками
- Интегрирован с Google Calendar
- Распознаёт голосовые сообщения (Whisper) и изображения (DeepSeek Vision)
- Понимает естественный язык через DeepSeek LLM
- Имеет CLI-мост (консоль ↔ Telegram)
- Шлёт проактивные уведомления (утренний брифинг, вечерний обзор)

Текущая дата: {now}

ТВОЯ ЗАДАЧА:
Проанализируй предоставленные логи и состояние проекта. Предложи 3-5 КОНКРЕТНЫХ идей:
- Что можно улучшить в архитектуре или коде
- Какие новые сервисы или интеграции добавить
- Что лишнее или дублирующееся — предложи удалить
- Какие AI-фичи можно внедрить (используя DeepSeek, Whisper, Vision API которые уже есть)
- Что сделает бота умнее и полезнее

ФОРМАТ ОТВЕТА:
Пиши на русском, коротко и по делу. Для каждой идеи:
1. Заголовок (одна строка)
2. Краткое описание (2-3 предложения)
3. Что конкретно нужно сделать

НЕ предлагай очевидного (типа "добавь тесты" или "напиши документацию"). Ищи нестандартные идеи, которые реально улучшат продукт.
"""


class IdeaAgent:
    def __init__(self, api_key: str, project_dir: str, out_queue, chat_id: int):
        self.api_key = api_key
        self.project_dir = project_dir
        self.out_queue = out_queue
        self.chat_id = chat_id

    async def analyze_and_suggest(self):
        """Main entry point: analyze project and send suggestions to Telegram."""
        logger.info("IdeaAgent: starting daily analysis")

        # Gather context
        logs = self._read_recent_logs()
        project_info = self._gather_project_info()

        if not self.api_key:
            logger.warning("IdeaAgent: no DeepSeek API key, skipping")
            await self.out_queue.put({
                "text": "[IdeaAgent] Нет API ключа DeepSeek — пропускаю анализ",
                "source": "system"
            })
            return

        # Ask DeepSeek for ideas
        ideas = await self._ask_deepseek(logs, project_info)
        if not ideas:
            logger.warning("IdeaAgent: no ideas generated")
            return

        # Send to Telegram via out_queue
        message = f"<b>Idea Agent — Идеи на {datetime.now().strftime('%d.%m.%Y')}</b>\n\n{ideas}"
        await self.out_queue.put({"text": message, "source": "system"})
        logger.info("IdeaAgent: suggestions sent")

    def _read_recent_logs(self, lines: int = 200) -> str:
        """Read recent log entries."""
        log_path = os.path.join(self.project_dir, "jarvis.log")
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                all_lines = f.readlines()
                recent = all_lines[-lines:] if len(all_lines) > lines else all_lines
                return "".join(recent)
        except FileNotFoundError:
            return "[Лог-файл не найден]"
        except Exception as e:
            return f"[Ошибка чтения логов: {e}]"

    def _gather_project_info(self) -> str:
        """Gather project structure and stats."""
        info = []
        project_dir = self.project_dir

        # List Python files
        py_files = []
        for root, dirs, files in os.walk(project_dir):
            # Skip __pycache__ and .git
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", ".claude")]
            for f in files:
                if f.endswith(".py") or f.endswith(".sql"):
                    py_files.append(os.path.relpath(os.path.join(root, f), project_dir))

        info.append(f"Файлы проекта ({len(py_files)}):")
        for f in sorted(py_files):
            info.append(f"  {f}")

        # DB stats
        db_path = os.path.join(project_dir, "jarvis.db")
        if os.path.exists(db_path):
            try:
                import sqlite3
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                tables = ["tasks", "projects", "reminders", "notes", "messages"]
                for table in tables:
                    cnt = cur.execute(f"SELECT COUNT(*) as c FROM {table}").fetchone()
                    info.append(f"  {table}: {cnt['c']} rows")
                conn.close()
            except Exception:
                pass

        return "\n".join(info)

    async def _ask_deepseek(self, logs: str, project_info: str) -> str | None:
        """Send context to DeepSeek and get improvement ideas."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        prompt = AGENT_PROMPT.format(now=now)

        # Truncate logs if too long (leave room for response)
        max_log_len = 3000
        if len(logs) > max_log_len:
            logs = logs[-max_log_len:]

        user_msg = f"""=== ЛОГИ (последние записи) ===
{logs}

=== СОСТОЯНИЕ ПРОЕКТА ===
{project_info}

Предложи 3-5 идей по улучшению проекта."""

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    DEEPSEEK_API,
                    json={
                        "model": "deepseek-chat",
                        "messages": [
                            {"role": "system", "content": prompt},
                            {"role": "user", "content": user_msg}
                        ],
                        "max_tokens": 1500,
                        "temperature": 0.7,
                    },
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    }
                )

                if resp.status_code != 200:
                    logger.error(f"IdeaAgent DeepSeek error: {resp.status_code}")
                    return None

                data = resp.json()
                return data["choices"][0]["message"]["content"]

        except Exception as e:
            logger.error(f"IdeaAgent error: {e}")
            return None
