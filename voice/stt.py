import logging

from elevenlabs import AsyncElevenLabs

logger = logging.getLogger(__name__)


class STT:
    def __init__(self, api_key: str) -> None:
        self.client = AsyncElevenLabs(api_key=api_key)

    async def transcribe(self, audio_path: str) -> str:
        """Transcribe audio file to Japanese text using ElevenLabs Scribe v2."""
        try:
            with open(audio_path, "rb") as f:
                result = await self.client.speech_to_text.convert(
                    file=f,
                    model_id="scribe_v1",
                    language_code="jpn",
                )
            return result.text.strip()
        except Exception as e:
            logger.error(f"STT failed: {e}")
            raise
