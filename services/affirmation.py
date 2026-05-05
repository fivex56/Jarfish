"""Daily gangster wisdom via DeepSeek API."""

import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

AFFIRMATION_PROMPT = """Дай случайную мудрость (о финансах, делах, жизни вообще, хоть глобально как жить, хоть как менять в часах батарейку — похуй, полный рандом), переделанную на пацанский язык. Используй такие слова как хуй, пизда, очко, ебаться, залупянка, пятихуй, очконавт и прочие, абстрактные матные и настоящий отборный лютый сленг дворовый пацанский арестантский даже, бери самые разъёбные слова, и чем больше такой грязи тем лучше. На выходе должно быть от 3 до 15 слов.

Верни ТОЛЬКО саму мудрость, без кавычек, без пояснений. Одна строка."""


class AffirmationService:
    def __init__(self, deepseek_key: str):
        self.api_key = deepseek_key

    async def generate(self) -> str:
        """Call DeepSeek to generate a fresh gangster affirmation."""
        import httpx

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "Ты — дворовый пацанский оракул. Отвечай одной строкой."},
                {"role": "user", "content": AFFIRMATION_PROMPT}
            ],
            "temperature": 1.2,
            "max_tokens": 80
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    "https://api.deepseek.com/v1/chat/completions",
                    headers=headers,
                    json=payload
                )
                data = r.json()
                text = data["choices"][0]["message"]["content"].strip()
                # Clean up quotes, dashes, etc.
                text = text.strip('"\'«»—-– \n')
                logger.info(f"Affirmation generated: {text}")
                return text
        except Exception as e:
            logger.error(f"Affirmation generation failed: {e}")
            return None
