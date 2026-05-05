import json
import logging
import re
from datetime import datetime, timedelta

import httpx

logger = logging.getLogger(__name__)

DEEPSEEK_API = "https://api.deepseek.com/v1/chat/completions"

SYSTEM_PROMPT = """Ты — ассистент календаря и задач (Джарвис). Пользователь общается с тобой из Telegram.
Его сообщения ВСЕГДА касаются календаря, встреч, напоминаний, задач или заметок.

Извлеки из сообщения ВСЁ, что пользователь хочет сделать, и верни ТОЛЬКО JSON (без markdown, без текста до/после):

{{
  "events": [
    {{
      "summary": "краткое название встречи/события",
      "start": "YYYY-MM-DD HH:MM",
      "end": "YYYY-MM-DD HH:MM или null если не указано",
      "description": "дополнительная информация",
      "reminder_minutes": [30, 10] или [120] или []
    }}
  ],
  "tasks": [
    {{
      "title": "название задачи",
      "due_date": "YYYY-MM-DD или null",
      "priority": 0 или 1 или 2 (0=обычная, 1=важная, 2=срочная),
      "tags": "теги через запятую"
    }}
  ],
  "reminders": [
    {{
      "message": "текст напоминания",
      "when": "YYYY-MM-DD HH:MM"
    }}
  ],
  "notes": ["заметка 1", "заметка 2"],
  "query": "если пользователь задал вопрос (какие встречи? что на сегодня? и т.д.) — напиши суть вопроса. если это не вопрос — null",
  "reply": "естественный ответ пользователю на русском языке, подтверждающий понятые действия"
}}

ПРАВИЛА:
- ВСЕГДА возвращай reply — короткое подтверждение на русском, что ты понял и сделал
- Если пользователь сказал "напомни за 20 минут до" — добавь в events.reminder_minutes: [20]
- Если время не указано явно, предположи разумное (утро=09:00, день=14:00, вечер=18:00)
- "завтра" = {tomorrow}, "сегодня" = {today}
- Сейчас: {now}
- Таймзона: Азия/Хошимин (UTC+7, Дананг)
- Извлекай ВСЕ события и задачи из сообщения, даже если их несколько
- Если пользователь явно просит создать встречу/напоминание/задачу — обязательно создай
- query заполняй ТОЛЬКО если это вопрос, на который нужно ответить данными
"""


class NLParser:
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def parse(self, text: str) -> dict:
        """Parse user message and extract calendar/task intents."""
        now = datetime.now()
        tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        today = now.strftime("%Y-%m-%d")
        now_str = now.strftime("%Y-%m-%d %H:%M")

        prompt = SYSTEM_PROMPT.format(today=today, tomorrow=tomorrow, now=now_str)

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    DEEPSEEK_API,
                    json={
                        "model": "deepseek-chat",
                        "messages": [
                            {"role": "system", "content": prompt},
                            {"role": "user", "content": text}
                        ],
                        "max_tokens": 1000,
                        "temperature": 0.1,
                    },
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    }
                )

                if resp.status_code != 200:
                    logger.error(f"DeepSeek error: {resp.status_code} {resp.text[:300]}")
                    return self._fallback(text)

                data = resp.json()
                content = data["choices"][0]["message"]["content"]

                # Strip markdown code fences if present
                content = content.strip()
                if content.startswith("```"):
                    lines = content.split("\n")
                    content = "\n".join(lines[1:])
                    if content.endswith("```"):
                        content = content[:-3]
                content = content.strip()

                parsed = self._extract_json(content)
                if parsed is None:
                    logger.warning(f"Could not parse JSON from: {content[:300]}")
                    return self._fallback(text)

                return parsed

        except Exception as e:
            logger.error(f"NL parse error: {e}")
            return self._fallback(text)

    def _extract_json(self, content: str) -> dict | None:
        """Extract valid JSON from LLM response, trying multiple strategies."""
        # Strategy 1: direct parse
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Strategy 2: find JSON object with balanced braces
        start = content.find("{")
        if start >= 0:
            brace_count = 0
            for i in range(start, len(content)):
                if content[i] == "{":
                    brace_count += 1
                elif content[i] == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        try:
                            return json.loads(content[start:i + 1])
                        except json.JSONDecodeError:
                            break
            # Try the greedy regex as last resort for this strategy
            m = re.search(r'\{[\s\S]*\}', content[start:])
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    pass

        # Strategy 3: the LLM returned JSON properties without outer braces
        if '"events"' in content or '"tasks"' in content:
            try:
                wrapped = "{" + content.strip().lstrip("{").rstrip("}") + "}"
                return json.loads(wrapped)
            except json.JSONDecodeError:
                pass

        return None

    def _fallback(self, text: str) -> dict:
        """Minimal fallback when LLM is unavailable."""
        return {
            "events": [],
            "tasks": [],
            "reminders": [],
            "notes": [text],
            "query": None,
            "reply": f"Записал: {text[:100]}"
        }
