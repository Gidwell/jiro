import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Ensure .env is loaded from the project root, not the cwd
_env_path = Path(__file__).parent / ".env"
load_dotenv(_env_path, override=True)


@dataclass(frozen=True)
class Config:
    # Telegram
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    allowed_user_id: int = int(os.getenv("ALLOWED_USER_ID", "0"))

    # Anthropic
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    claude_model: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")
    claude_model_fast: str = os.getenv("CLAUDE_MODEL_FAST", "claude-haiku-4-5-20251001")

    # ElevenLabs
    elevenlabs_api_key: str = os.getenv("ELEVENLABS_API_KEY", "")
    elevenlabs_voice_id: str = os.getenv("ELEVENLABS_VOICE_ID", "")
    elevenlabs_model_id: str = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")

    # Database
    database_url: str = os.getenv("DATABASE_URL", "")  # PostgreSQL (Railway)
    database_path: str = os.getenv("DATABASE_PATH", "jiro.db")  # SQLite (local)

    # Limits
    max_voice_duration_seconds: int = int(os.getenv("MAX_VOICE_DURATION_SECONDS", "60"))
    max_daily_voice_interactions: int = int(os.getenv("MAX_DAILY_VOICE_INTERACTIONS", "50"))

    def validate(self) -> None:
        required = {
            "TELEGRAM_BOT_TOKEN": self.telegram_bot_token,
            "ANTHROPIC_API_KEY": self.anthropic_api_key,
            "ELEVENLABS_API_KEY": self.elevenlabs_api_key,
            "ALLOWED_USER_ID": self.allowed_user_id,
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ValueError(f"Missing required env vars: {', '.join(missing)}")


config = Config()
