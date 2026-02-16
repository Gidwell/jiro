"""Voice and text message handlers — the core interaction loop."""

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from ai.claude_client import ClaudeClient
from ai.conversation import ConversationManager
from config import config
from db.models import Models
from learning.grader import format_feedback_text
from learning.planner import LearningPlanner
from voice.audio_converter import mp3_to_ogg
from voice.stt import STT
from voice.tts import TTS

logger = logging.getLogger(__name__)


def _authorized(update: Update) -> bool:
    return update.effective_user.id == config.allowed_user_id


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming voice note — the main pipeline."""
    if not _authorized(update):
        return

    user_id = update.effective_user.id
    models: Models = context.bot_data["models"]
    claude: ClaudeClient = context.bot_data["claude"]
    stt: STT = context.bot_data["stt"]
    tts: TTS = context.bot_data["tts"]
    conversation: ConversationManager = context.bot_data["conversation"]
    planner: LearningPlanner = context.bot_data["planner"]

    # Check daily rate limit
    daily_count = await models.get_daily_voice_count(user_id)
    if daily_count >= config.max_daily_voice_interactions:
        await update.message.reply_text(
            f"You've reached the daily limit of {config.max_daily_voice_interactions} voice interactions. "
            "Great work today! Come back tomorrow."
        )
        return

    # Check voice duration
    voice = update.message.voice
    if voice.duration and voice.duration > config.max_voice_duration_seconds:
        await update.message.reply_text(
            f"Voice note too long ({voice.duration}s). "
            f"Please keep it under {config.max_voice_duration_seconds} seconds!"
        )
        return

    # Send typing indicator
    await update.message.chat.send_action("typing")

    ogg_path = None
    tts_mp3_path = None
    tts_ogg_path = None

    try:
        # Download voice note
        voice_file = await voice.get_file()
        ogg_tmp = tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)
        ogg_path = ogg_tmp.name
        ogg_tmp.close()
        await voice_file.download_to_drive(ogg_path)

        # STT — transcribe (ElevenLabs Scribe accepts OGG directly)
        try:
            transcript = await stt.transcribe(ogg_path)
        except Exception as e:
            logger.error(f"STT failed: {e}")
            await update.message.reply_text(
                "Sorry, I couldn't transcribe your voice note. "
                "Could you try sending it again, or type your message instead?"
            )
            return

        if not transcript.strip():
            await update.message.reply_text(
                "I couldn't detect any speech in your voice note. "
                "Please try again with a clearer recording."
            )
            return

        # Get user profile and session
        user = await models.get_or_create_user(user_id)
        session = await conversation.get_session(user_id, user["mode"])
        context_messages = await conversation.get_context(session["session_id"])

        # Store user message
        msg_id = await conversation.add_user_message(
            session["session_id"], transcript, transcript
        )

        # Get due review items
        due_items = await planner.get_due_items(user_id, limit=5)

        # Get today's daily prompt if any
        daily_prompt = None
        todays_questions = await models.get_todays_questions(user_id)
        unanswered = [q for q in todays_questions if q["answered_at"] is None]
        if unanswered:
            daily_prompt = unanswered[0]["prompt_text"]
            await models.mark_question_answered(unanswered[0]["question_id"])

        # Single Claude call — the coach prompt returns reply + grades + drill in one JSON
        grading_result = await claude.generate_conversation_response(
            user_profile=user,
            conversation_messages=context_messages,
            transcript=transcript,
            due_items=due_items,
            daily_prompt=daily_prompt,
        )

        # Store bot response
        reply_text = grading_result.get("reply_jp", "")
        follow_up = grading_result.get("follow_up_question_jp", "")
        bot_text = f"{reply_text}\n{follow_up}" if follow_up else reply_text
        await conversation.add_bot_message(session["session_id"], bot_text)

        # Store grade
        scores = grading_result.get("scores", {})
        await models.add_grade(
            message_id=msg_id,
            overall_score=scores.get("overall", 0),
            grammar_score=scores.get("grammar", 0),
            vocab_score=scores.get("vocab", 0),
            pronunciation_score=scores.get("pronunciation", 0),
            fluency_score=scores.get("fluency", 0),
            naturalness_score=scores.get("naturalness", 0),
            issues=grading_result.get("issues", []),
            suggestions=[],
        )

        # Update streak and last_active
        await models.update_user(user_id, last_active=str(asyncio.get_event_loop().time()))

        # Format and send text feedback IMMEDIATELY (don't wait for TTS)
        feedback = format_feedback_text(grading_result, transcript)
        await update.message.reply_text(feedback, parse_mode="HTML")

        # TTS — synthesize voice reply (only the natural response, not drill notation)
        tts_text = reply_text
        logger.info(f"TTS text ({len(tts_text)} chars): {tts_text[:200]}")

        try:
            tts_mp3_path = await tts.synthesize(tts_text)
            tts_ogg_path = mp3_to_ogg(tts_mp3_path)

            # Store drill audio path for /repeat
            context.user_data["last_drill_audio"] = tts_ogg_path

            # Send voice reply
            with open(tts_ogg_path, "rb") as f:
                await update.message.reply_voice(voice=f)
        except Exception as e:
            logger.error(f"TTS failed: {e}")
            # Fallback: send text only
            await update.message.reply_text(
                f"\U0001f50a <i>{reply_text}</i>\n\n"
                "(Voice reply unavailable — TTS error)",
                parse_mode="HTML",
            )

        # Check if learner summary needs update
        if await conversation.should_update_learner_summary(user_id):
            recent_grades = await models.get_recent_grades(user_id, limit=20)
            grade_dicts = []
            for g in recent_grades:
                gd = dict(g)
                if isinstance(gd.get("issues"), str):
                    try:
                        gd["issues"] = json.loads(gd["issues"])
                    except json.JSONDecodeError:
                        pass
                grade_dicts.append(gd)

            new_summary = await claude.update_learner_summary(
                user.get("learner_summary", ""), grade_dicts
            )
            await models.update_user(user_id, learner_summary=new_summary)

            # Also update error patterns
            await planner.update_error_patterns(user_id, grade_dicts)

    except Exception as e:
        logger.exception(f"Error handling voice message: {e}")
        await update.message.reply_text(
            "Something went wrong processing your voice note. Please try again!"
        )
    finally:
        # Clean up temp files
        for path in [ogg_path, tts_mp3_path]:
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
        # Note: tts_ogg_path is kept for /repeat command


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages — basic text conversation without grading."""
    if not _authorized(update):
        return

    # Clear delete confirmation on any non-delete message
    if context.user_data.get("delete_confirmed"):
        context.user_data.pop("delete_confirmed", None)

    text = update.message.text
    if not text:
        return

    models: Models = context.bot_data["models"]
    claude: ClaudeClient = context.bot_data["claude"]
    conversation: ConversationManager = context.bot_data["conversation"]

    user = await models.get_or_create_user(update.effective_user.id)
    session = await conversation.get_session(update.effective_user.id, user["mode"])
    context_messages = await conversation.get_context(session["session_id"])

    await conversation.add_user_message(session["session_id"], text)

    try:
        result = await claude.generate_conversation_response(
            user_profile=user,
            conversation_messages=context_messages,
            transcript=text,
        )
        reply = result.get("reply_jp", "")
        follow_up = result.get("follow_up_question_jp", "")
        bot_text = f"{reply}\n{follow_up}" if follow_up else reply

        await conversation.add_bot_message(session["session_id"], bot_text)
        await update.message.reply_text(bot_text)

    except Exception as e:
        logger.error(f"Error handling text message: {e}")
        await update.message.reply_text(
            "Sorry, something went wrong. Please try again!"
        )
