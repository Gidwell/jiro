"""Jiro — Voice-First Japanese Speaking Coach (Telegram)"""

import logging
import os
import signal

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

from ai.claude_client import ClaudeClient
from ai.conversation import ConversationManager
from bot.commands import (
    delete_command,
    mode_command,
    plan_command,
    repeat_command,
    review_command,
    settime_command,
    start_command,
    stats_command,
    strict_command,
    talk_command,
)
from bot.handlers import handle_text, handle_voice
from bot.scheduler import SchedulerManager
from config import config
from db.database import create_database
from db.models import Models
from learning.curriculum import Curriculum
from learning.planner import LearningPlanner
from learning.question_generator import QuestionGenerator
from voice.stt import STT
from voice.tts import TTS

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def post_init(application: Application) -> None:
    """Initialize all services and store them in bot_data."""
    config.validate()

    # Database
    db = create_database(config.database_url, config.database_path)
    await db.init()
    models = Models(db)

    # Voice
    stt = STT(config.elevenlabs_api_key)
    tts = TTS(config.elevenlabs_api_key, config.elevenlabs_voice_id, config.elevenlabs_model_id)

    # AI
    claude = ClaudeClient(config.anthropic_api_key, config.claude_model)
    conversation = ConversationManager(models)

    # Learning
    curriculum = Curriculum()
    curriculum.load()
    planner = LearningPlanner(models)
    question_gen = QuestionGenerator(models, claude)

    # Scheduler
    scheduler_manager = SchedulerManager(models, claude, question_gen, planner)

    # Store in bot_data
    application.bot_data["db"] = db
    application.bot_data["models"] = models
    application.bot_data["stt"] = stt
    application.bot_data["tts"] = tts
    application.bot_data["claude"] = claude
    application.bot_data["conversation"] = conversation
    application.bot_data["curriculum"] = curriculum
    application.bot_data["planner"] = planner
    application.bot_data["question_gen"] = question_gen
    application.bot_data["scheduler_manager"] = scheduler_manager

    # Set up scheduled jobs
    await scheduler_manager.setup_jobs(application)

    logger.info("Jiro initialized successfully!")


async def post_shutdown(application: Application) -> None:
    """Clean up on shutdown."""
    db = application.bot_data.get("db")
    if db:
        await db.close()
    logger.info("Jiro shut down.")


def _kill_existing_instances() -> None:
    """Kill any other running Jiro bot instances to prevent 409 Conflicts."""
    my_pid = os.getpid()
    try:
        # Find all python3 processes running main.py
        import subprocess
        result = subprocess.run(
            ["pgrep", "-f", "python3.*main\\.py"],
            capture_output=True, text=True
        )
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            pid = int(line)
            if pid != my_pid:
                logger.info(f"Killing existing bot instance (PID {pid})")
                os.kill(pid, signal.SIGKILL)
    except Exception as e:
        logger.warning(f"Could not check for existing instances: {e}")


def main() -> None:
    _kill_existing_instances()

    application = (
        Application.builder()
        .token(config.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Register command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("plan", plan_command))
    application.add_handler(CommandHandler("review", review_command))
    application.add_handler(CommandHandler("talk", talk_command))
    application.add_handler(CommandHandler("settime", settime_command))
    application.add_handler(CommandHandler("mode", mode_command))
    application.add_handler(CommandHandler("repeat", repeat_command))
    application.add_handler(CommandHandler("strict", strict_command))
    application.add_handler(CommandHandler("delete", delete_command))

    # Register message handlers
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )

    logger.info("Starting Jiro...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
