"""All slash command handlers."""

import json
import logging

from telegram import Update
from telegram.ext import ContextTypes

from config import config
from db.models import Models
from learning.planner import LearningPlanner
from learning.curriculum import Curriculum

logger = logging.getLogger(__name__)


def _get_models(context: ContextTypes.DEFAULT_TYPE) -> Models:
    return context.bot_data["models"]


def _get_planner(context: ContextTypes.DEFAULT_TYPE) -> LearningPlanner:
    return context.bot_data["planner"]


def _authorized(update: Update) -> bool:
    return update.effective_user.id == config.allowed_user_id


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await update.message.reply_text("Sorry, this bot is private.")
        return

    models = _get_models(context)
    user = await models.get_or_create_user(
        update.effective_user.id,
        update.effective_user.first_name or "",
    )

    # Seed curriculum items
    planner = _get_planner(context)
    curriculum: Curriculum = context.bot_data["curriculum"]
    await planner.seed_items_for_user(user["user_id"], curriculum.get_all_items())

    await update.message.reply_text(
        "Welcome to Jiro! I'm your Japanese speaking coach.\n\n"
        "Send me a voice note in Japanese and I'll help you improve.\n\n"
        "<b>Commands:</b>\n"
        "/settime HH:MM — set daily prompt time\n"
        "/mode — toggle test_prep / conversation\n"
        "/talk — start a free conversation\n"
        "/plan — view your learning plan\n"
        "/stats — streak + progress\n"
        "/review — review due items\n"
        "/repeat — replay last micro-drill\n"
        "/strict — cycle correction intensity\n"
        "/delete — delete all your data\n\n"
        f"Your timezone is set to: {user['timezone']}\n"
        f"Daily prompt time: {user['daily_question_time']}",
        parse_mode="HTML",
    )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return

    models = _get_models(context)
    user = await models.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Use /start first!")
        return

    trends = await models.get_score_trends(user["user_id"])
    total_grades = await models.get_grade_count_total(user["user_id"])

    lines = [
        f"<b>Your Stats</b>",
        f"Streak: {user['streak_count']} days",
        f"Level: {user['current_level']} \u2192 {user['target_level']}",
        f"Mode: {user['mode']}",
        f"Correction: {user['correction_intensity']}",
        f"Total graded responses: {total_grades}",
    ]

    if trends:
        lines.append("\n<b>Score Trends (recent vs previous):</b>")
        trend_names = {
            "grammar_score": "Grammar",
            "vocab_score": "Vocab",
            "pronunciation_score": "Pronunciation",
            "fluency_score": "Fluency",
            "naturalness_score": "Naturalness",
            "overall_score": "Overall",
        }
        for key, label in trend_names.items():
            val = trends.get(key, 0)
            arrow = "\u2191" if val > 0 else "\u2193" if val < 0 else "\u2192"
            lines.append(f"  {label}: {arrow} {val:+.1f}")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return

    planner = _get_planner(context)
    summary = await planner.get_learning_plan_summary(update.effective_user.id)
    await update.message.reply_text(summary, parse_mode="HTML")


async def review_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return

    planner = _get_planner(context)
    due = await planner.get_due_items(update.effective_user.id, limit=5)

    if not due:
        await update.message.reply_text("No items due for review! Great job staying on top of things.")
        return

    lines = ["<b>Review Time!</b> Here are your due items:\n"]
    for i, item in enumerate(due, 1):
        lines.append(f"{i}. [{item['item_type']}] {item['content']}")
    lines.append("\nSend a voice note to practice these items in conversation.")

    # Store due items in user_data for the handler to use
    context.user_data["review_items"] = due

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def talk_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return

    topic = " ".join(context.args) if context.args else None
    if topic:
        await update.message.reply_text(
            f"Let's talk about <b>{topic}</b>! Send me a voice note in Japanese.",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            "Let's have a free conversation! Send me a voice note about anything in Japanese.\n"
            "Tip: Use /talk <topic> to suggest a topic.",
        )


async def settime_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return

    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: /settime HH:MM (e.g., /settime 08:30)")
        return

    time_str = context.args[0]
    # Validate format
    try:
        parts = time_str.split(":")
        hour, minute = int(parts[0]), int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except (ValueError, IndexError):
        await update.message.reply_text("Invalid time format. Use HH:MM (e.g., 08:30)")
        return

    models = _get_models(context)
    await models.update_user(update.effective_user.id, daily_question_time=time_str)

    # Reschedule the daily job
    scheduler = context.bot_data.get("scheduler_manager")
    if scheduler:
        await scheduler.reschedule_daily(update.effective_user.id, time_str, context)

    await update.message.reply_text(f"Daily prompt time set to {time_str}!")


async def mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return

    models = _get_models(context)
    user = await models.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Use /start first!")
        return

    new_mode = "test_prep" if user["mode"] == "conversation" else "conversation"
    await models.update_user(update.effective_user.id, mode=new_mode)

    mode_desc = "JLPT test prep" if new_mode == "test_prep" else "Free conversation"
    await update.message.reply_text(f"Mode switched to: <b>{mode_desc}</b>", parse_mode="HTML")


async def repeat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return

    last_drill_audio = context.user_data.get("last_drill_audio")
    if last_drill_audio:
        try:
            with open(last_drill_audio, "rb") as f:
                await update.message.reply_voice(voice=f)
        except FileNotFoundError:
            await update.message.reply_text("Last drill audio is no longer available. Send a new voice note!")
    else:
        await update.message.reply_text("No drill audio yet. Send a voice note first!")


async def strict_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return

    models = _get_models(context)
    user = await models.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Use /start first!")
        return

    cycle = {"light": "normal", "normal": "strict", "strict": "light"}
    new_intensity = cycle[user["correction_intensity"]]
    await models.update_user(update.effective_user.id, correction_intensity=new_intensity)

    await update.message.reply_text(f"Correction intensity: <b>{new_intensity}</b>", parse_mode="HTML")


async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return

    # Require confirmation
    if context.user_data.get("delete_confirmed"):
        models = _get_models(context)
        await models.delete_user_data(update.effective_user.id)
        context.user_data.clear()
        await update.message.reply_text("All your data has been deleted. Use /start to begin again.")
    else:
        context.user_data["delete_confirmed"] = True
        await update.message.reply_text(
            "Are you sure you want to delete ALL your data? "
            "This includes your profile, conversations, grades, learning plan, and summaries.\n\n"
            "Send /delete again to confirm."
        )
