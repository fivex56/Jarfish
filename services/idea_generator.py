"""Agent 1 — Idea Generator: analyses project, searches web trends, brainstorms improvements."""

import logging
import json
from pathlib import Path

import httpx

logger = logging.getLogger("agent.generator")

GENERATOR_SYSTEM = """Ты — Агент-Генератор идей для персонального AI-ассистента Jarfish. Твоя роль: находить способы сделать проект лучше.

Jarfish — это Telegram-бот, личный AI-ассистент. Он умеет:
- Управлять задачами и проектами
- Ставить напоминания с повторами
- Вести заметки и ленту мыслей (текст, голос, фото)
- Понимать естественную речь (русский) через DeepSeek
- Распознавать голос через Whisper
- Понимать фото через DeepSeek Vision
- Присылать утренний брифинг и вечерний обзор
- Генерировать ежедневную «пацанскую мудрость»
- Автоматически переносить незавершённые задачи
- Работать с Google Календарём
- Иметь CLI-мост (консоль ↔ Telegram)

Ты получаешь информацию о текущем состоянии проекта и трендах из интернета.
Твоя задача — придумать КОНКРЕТНЫЕ улучшения: новые функции, доработки существующих, архитектурные улучшения.

Формат ответа — JSON:
{
  "ideas": [
    {
      "title": "Короткое название идеи",
      "what": "Что сделать — конкретно, с деталями",
      "why": "Почему это важно — аргументация",
      "how": "Как это реализовать технически — ключевые шаги",
      "impact": "high|medium|low — насколько сильно повлияет на продукт",
      "effort": "high|medium|low — сколько усилий на реализацию"
    }
  ],
  "summary": "Краткое резюме всех идей в 2-3 предложениях на русском, пацанским языком, но информативно"
}

ПРАВИЛА:
- Минимум 3 идеи, максимум 7
- Идеи должны быть конкретными, не абстрактными
- Учитывай реальное состояние проекта
- Думай о пользе для пользователя
- Не предлагай то, что уже реализовано
- Пиши на русском языке"""


class IdeaGenerator:
    def __init__(self, deepseek_key: str, project_root: str, repo):
        self.api_key = deepseek_key
        self.project_root = Path(project_root)
        self.repo = repo

    async def analyze_project(self) -> str:
        """Read project structure and return a summary for the LLM."""
        py_files = sorted(self.project_root.rglob("*.py"))
        total_lines = 0
        file_summaries = []

        for f in py_files:
            if ".claude" in f.parts or "__pycache__" in f.parts:
                continue
            try:
                content = f.read_text(encoding="utf-8")
                lines = content.splitlines()
                total_lines += len(lines)
                # Extract key classes/functions
                classes = [l.strip() for l in lines if l.startswith("class ") and ":" in l]
                file_summaries.append(f"  {f.relative_to(self.project_root)}: {len(lines)} строк, "
                                      f"{len(classes)} классов" +
                                      (f" ({classes[0].split('(')[0].strip()}...)"
                                       if classes else ""))
            except Exception:
                pass

        # Gather DB stats
        tasks = await self.repo.list_tasks(limit=1000)
        projects = await self.repo.list_projects()
        notes = await self.repo.list_notes(limit=1000)
        reminders = await self.repo.list_reminders(include_sent=True)
        thoughts = await self.repo.list_thoughts(limit=1000)

        summary_parts = [
            f"Проект Jarfish: {len(list(py_files))} Python-файлов, ~{total_lines} строк кода",
            "",
            "Структура:",
            *file_summaries[:25],
            "",
            "Состояние базы данных:",
            f"  Проектов: {len(projects)}",
            f"  Задач: {len(tasks)} (активных: {len([t for t in tasks if t['status'] in ('todo','in_progress')])})",
            f"  Заметок: {len(notes)}",
            f"  Напоминаний: {len(reminders)}",
            f"  Мыслей в ленте: {len(thoughts)}",
            "",
            "Последние задачи (до 10):"
        ]

        for t in tasks[:10]:
            summary_parts.append(
                f"  #{t['id']} [{t['status']}] {t['title']} "
                f"(приоритет: {t['priority']}, due: {t.get('due_date', 'нет')})"
            )

        return "\n".join(summary_parts)

    async def search_trends(self) -> str:
        """Search web for trends related to our features and return findings."""
        topics = [
            "personal AI assistant telegram bot 2026 trends",
            "AI task management productivity tools 2026",
            "life management automation AI agent 2026",
            "telegram bot AI new features 2026",
            "voice assistant personal productivity 2026",
            "self-improving AI agent architecture 2026",
        ]

        findings = []

        for topic in topics[:3]:  # Limit to avoid rate issues
            try:
                results = await self._search_web(topic)
                findings.append(f"Поиск: «{topic}»")
                findings.append(results)
                findings.append("---")
            except Exception as e:
                logger.warning(f"Web search failed for '{topic}': {e}")

        return "\n".join(findings) if findings else "Поиск не дал результатов (сетевые ограничения)"

    async def _search_web(self, query: str) -> str:
        """Basic web search via DuckDuckGo Lite."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    "https://lite.duckduckgo.com/lite/",
                    params={"q": query},
                    headers={"User-Agent": "Mozilla/5.0"}
                )
                # Extract text snippets from results
                from html.parser import HTMLParser

                class SnippetParser(HTMLParser):
                    def __init__(self):
                        super().__init__()
                        self.snippets = []
                        self.in_link = False
                        self.in_snippet = False
                        self.current_text = ""

                    def handle_starttag(self, tag, attrs):
                        if tag == "a":
                            self.in_link = True
                        elif tag == "td":
                            self.in_snippet = True

                    def handle_endtag(self, tag):
                        if tag == "a":
                            self.in_link = False
                        elif tag == "td":
                            self.in_snippet = False

                    def handle_data(self, data):
                        if self.in_snippet and len(data.strip()) > 30:
                            self.snippets.append(data.strip())

                parser = SnippetParser()
                parser.feed(r.text)

                if parser.snippets:
                    return "\n".join(parser.snippets[:5])
                return "Результатов не найдено"
        except Exception as e:
            return f"Ошибка поиска: {e}"

    async def brainstorm(self, project_info: str, trends: str,
                         previous_feedback: str = "") -> dict:
        """Use DeepSeek to generate improvement ideas."""
        prompt = f"""Проанализируй проект и тренды. Предложи идеи для улучшения.

=== ТЕКУЩЕЕ СОСТОЯНИЕ ПРОЕКТА ===
{project_info}

=== ТРЕНДЫ ИЗ ИНТЕРНЕТА ===
{trends}
"""

        if previous_feedback:
            prompt += f"\n=== ЗАМЕЧАНИЯ РАЗРАБОТЧИКА К ПРЕДЫДУЩИМ ИДЕЯМ ===\n{previous_feedback}\n"
            prompt += "\nУчти эти замечания. Доработай идеи, но не делай их проще — сделай их ЛУЧШЕ."

        prompt += "\nВерни СТРОГО JSON с идеями."

        return await self._call_deepseek(prompt, temperature=0.8)

    async def global_review(self, project_info: str, all_ideas: list[dict]) -> dict:
        """Weekly global strategic review — big picture thinking."""
        ideas_summary = "\n".join(
            f"- {i.get('content', '')[:200]}" for i in all_ideas[:20]
        )

        prompt = f"""Ты проводишь ГЛОБАЛЬНЫЙ СТРАТЕГИЧЕСКИЙ ОБЗОР проекта Jarfish.

=== ТЕКУЩЕЕ СОСТОЯНИЕ ===
{project_info}

=== ИДЕИ ЗА ПОСЛЕДНЮЮ НЕДЕЛЮ ===
{ideas_summary}

Твоя задача — посмотреть на проект СВЕРХУ. Не просто предложить фичи, а подумать:
1. Куда проект движется стратегически?
2. Какие слабые места есть сейчас?
3. Что можно сделать чтобы проект стал по-настоящему классным сервисом для людей?
4. Какие глобальные тренды стоит учесть?

Будь амбициозным. Представь что Jarfish должен стать лучшим персональным AI-ассистентом.

Формат ответа — JSON:
{{
  "vision": "Стратегическое видение — куда движемся",
  "weaknesses": ["Слабое место 1", "Слабое место 2", ...],
  "opportunities": ["Возможность 1", "Возможность 2", ...],
  "big_ideas": [
    {{
      "title": "Глобальная идея",
      "what": "Что сделать",
      "why": "Почему",
      "how": "Как — ключевые шаги",
      "impact": "high|medium|low",
      "effort": "high|medium|low"
    }}
  ],
  "report": "Отчёт для пользователя — 3-5 предложений на русском, пацанским языком, энергично и вдохновляюще. Расскажи что мы сделаем чтобы Jarfish стал ещё мощнее."
}}

ПРАВИЛА:
- Минимум 3 глобальные идеи
- Думай масштабно, на месяцы вперёд
- Пиши отчёт для пользователя человеческим языком без техтерминов"""

        return await self._call_deepseek(prompt, temperature=0.9)

    async def _call_deepseek(self, prompt: str, temperature: float = 0.7) -> dict:
        """Call DeepSeek API and parse JSON response."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": GENERATOR_SYSTEM},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
            "max_tokens": 2000
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

                # Extract JSON from response
                json_start = text.find("{")
                json_end = text.rfind("}") + 1
                if json_start != -1 and json_end > json_start:
                    return json.loads(text[json_start:json_end])
                return {"ideas": [], "summary": text}
        except Exception as e:
            logger.error(f"DeepSeek call failed: {e}")
            return {"ideas": [], "summary": f"Ошибка генерации: {e}"}
