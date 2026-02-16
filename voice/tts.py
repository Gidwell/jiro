import logging
import tempfile

from elevenlabs import AsyncElevenLabs
from elevenlabs.types import VoiceSettings

logger = logging.getLogger(__name__)


class TTS:
    def __init__(self, api_key: str, voice_id: str, model_id: str = "eleven_multilingual_v2") -> None:
        self.client = AsyncElevenLabs(api_key=api_key, timeout=120)
        self.voice_id = voice_id
        self.model_id = model_id

    async def synthesize(self, text: str) -> str:
        """Synthesize Japanese text to speech. Returns path to temp MP3 file (caller must clean up)."""
        try:
            audio_generator = self.client.text_to_speech.convert(
                voice_id=self.voice_id,
                text=text,
                model_id=self.model_id,
                voice_settings=VoiceSettings(speed=0.85),
            )
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            async for chunk in audio_generator:
                tmp.write(chunk)
            tmp.close()
            return tmp.name
        except Exception as e:
            logger.error(f"TTS failed: {e}")
            raise
