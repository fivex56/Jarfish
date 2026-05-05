import base64
import logging

import httpx

logger = logging.getLogger(__name__)

DEEPSEEK_API = "https://api.deepseek.com/v1/chat/completions"


class VisionService:
    """Recognizes images using DeepSeek Vision API."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def describe(self, image_path: str, prompt: str | None = None) -> str:
        """Send image to DeepSeek and get description."""
        try:
            with open(image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")

            # Detect MIME type
            ext = image_path.lower().split(".")[-1]
            mime_map = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp", "gif": "gif"}
            mime_type = f"image/{mime_map.get(ext, 'jpeg')}"

            user_prompt = prompt or "Опиши это изображение подробно на русском языке"

            body = {
                "model": "deepseek-chat",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime_type};base64,{image_data}"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 500
            }

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    DEEPSEEK_API,
                    json=body,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    }
                )
                if resp.status_code != 200:
                    logger.error(f"DeepSeek error {resp.status_code}: {resp.text[:200]}")
                    return f"Ошибка распознавания: {resp.status_code}"

                data = resp.json()
                return data["choices"][0]["message"]["content"]

        except Exception as e:
            logger.error(f"Vision error: {e}")
            return f"Не удалось распознать изображение: {e}"
