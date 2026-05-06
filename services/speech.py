import logging
import os
import tempfile

logger = logging.getLogger(__name__)


class SpeechService:
    """Transcribes voice messages (Whisper) and synthesizes text to speech (gTTS)."""

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

    async def transcribe(self, file_path: str, language: str = "ru") -> str:
        """Transcribe an audio file. Returns text or empty string on failure."""
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            # Run blocking Whisper call in thread pool
            result = await loop.run_in_executor(
                None, self._transcribe_sync, file_path, language
            )
            return result
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            return ""

    def _transcribe_sync(self, file_path: str, language: str) -> str:
        model = self._load_model()
        result = model.transcribe(
            file_path,
            language=language,
            fp16=False,  # CPU mode
            verbose=False
        )
        text = result.get("text", "").strip()
        logger.info(f"Transcribed: {text[:100]}")
        return text

    async def synthesize(self, text: str, lang: str = "ru") -> str:
        """Synthesize text to speech via gTTS. Returns path to OGG file."""
        from gtts import gTTS
        import asyncio
        ogg_path = os.path.join(tempfile.gettempdir(), f"tts_{hash(text) % 100000}.ogg")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._synthesize_sync, text, lang, ogg_path)
        return ogg_path

    @staticmethod
    def _synthesize_sync(text: str, lang: str, ogg_path: str):
        from gtts import gTTS
        tts = gTTS(text=text, lang=lang)
        tts.save(ogg_path)
        logger.info(f"TTS synthesized: {text[:100]} -> {ogg_path}")
