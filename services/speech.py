import logging
import os
import tempfile

logger = logging.getLogger(__name__)


class SpeechService:
    """Transcribes voice messages using OpenAI Whisper."""

    def __init__(self, model_name: str = "tiny"):
        self.model_name = model_name
        self._model = None

    def _load_model(self):
        if self._model is None:
            import whisper
            logger.info(f"Loading Whisper model: {self.model_name}")
            self._model = whisper.load_model(self.model_name)
            logger.info("Whisper model loaded")
        return self._model

    async def transcribe(self, file_path: str) -> str:
        """Transcribe an audio file. Returns text or empty string on failure."""
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            # Run blocking Whisper call in thread pool
            result = await loop.run_in_executor(
                None, self._transcribe_sync, file_path
            )
            return result
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            return ""

    def _transcribe_sync(self, file_path: str) -> str:
        model = self._load_model()
        result = model.transcribe(
            file_path,
            language="ru",
            fp16=False,  # CPU mode
            verbose=False
        )
        text = result.get("text", "").strip()
        logger.info(f"Transcribed: {text[:100]}")
        return text
