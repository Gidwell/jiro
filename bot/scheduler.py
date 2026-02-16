"""Daily questions, afternoon nudge, weekly summary, streak tracking."""

import json
import logging
from datetime import date, datetime, time, timedelta

from telegram.ext import ContextTypes

from ai.claude_client import ClaudeClient
from config import config
from db.models import Models
from learning.planner import LearningPlanner
from learning.question_generator import QuestionGenerator

logger = logging.getLogger(__name__)


class SchedulerManager:
    def __init__(
        self,
        models: Models,
        claude: ClaudeClient,
        question_gen: QuestionGenerator,
        planner: LearningPlanner,
    ) -> None:
        self.models = models
        self.claude = claude
        self.question_gen = question_gen
        self.planner = planner

    async def setup_jobs(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Set up all scheduled jobs for the user."""
        user = await self.models.get_user(config.allowed_user_id)
        if not user:
            return

        job_queue = context.job_queue

        # Parse daily question time
        time_str = user.get("daily_question_time", "08:00")
        hour, minute = map(int, time_str.split(":"))
        daily_time = time(hour=hour, minute=minute)

        # Daily morning questions
        job_queue.run_daily(
            self._daily_questions_job,
            time=daily_time,
            name="daily_questions",
        )

        # Afternoon nudge (6 hours after morning)
        nudge_hour = (hour + 6) % 24
        job_queue.run_daily(
            self._afternoon_nudge_job,
            time=time(hour=nudge_hour, minute=minute),
            name="afternoon_nudge",
        )

        # Weekly summary — Sundays at 20:00
        job_queue.run_daily(
            self._weekly_summary_job,
            time=time(hour=20, minute=0),
            days=(6,),  # Sunday
            name="weekly_summary",
        )

        logger.info(f"Scheduled daily questions at {time_str}, nudge at {nudge_hour}:{minute:02d}")

    async def reschedule_daily(
        self, user_id: int, time_str: str, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Reschedule daily jobs when user changes their time."""
        job_queue = context.job_queue

        # Remove existing jobs
        for name in ("daily_questions", "afternoon_nudge"):
            jobs = job_queue.get_jobs_by_name(name)
            for job in jobs:
                job.schedule_removal()

        hour, minute = map(int, time_str.split(":"))

        job_queue.run_daily(
            self._daily_questions_job,
            time=time(hour=hour, minute=minute),
            name="daily_questions",
        )

        nudge_hour = (hour + 6) % 24
        job_queue.run_daily(
            self._afternoon_nudge_job,
            time=time(hour=nudge_hour, minute=minute),
            name="afternoon_nudge",
        )

    async def _daily_questions_job(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Send morning questions."""
        user_id = config.allowed_user_id
        user = await self.models.get_user(user_id)
        if not user:
            return

        # Check for extended absence (3+ days)
        last_active = user.get("last_active")
        days_absent = 0
        if last_active:
            try:
                last = datetime.fromisoformat(last_active)
                days_absent = (datetime.now() - last).days
            except (ValueError, TypeError):
                pass

        if days_absent >= 3:
            # Gentle restart — single easy review question
            count = 1
        else:
            count = 3

        try:
            questions = await self.question_gen.generate_daily_questions(user_id, count=count)
            if not questions:
                return

            # Update streak
            streak = user.get("streak_count", 0)
            if days_absent <= 1:
                streak += 1
            else:
                streak = 1  # Reset streak
            await self.models.update_user(user_id, streak_count=streak)

            # Build message
            lines = []
            if days_absent >= 3:
                lines.append("Welcome back! Let's ease back in with a quick question:\n")
            elif streak > 1:
                lines.append(f"Day {streak}! Keep it up!\n")
            else:
                lines.append("Good morning! Time for Japanese practice.\n")

            for i, q in enumerate(questions, 1):
                lines.append(f"{i}. {q.get('question_jp', '')}")
                en = q.get("question_en", "")
                if en:
                    lines.append(f"   <i>{en}</i>")

            lines.append("\nReply with a voice note!")

            await context.bot.send_message(
                chat_id=user_id,
                text="\n".join(lines),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"Daily questions job failed: {e}")

    async def _afternoon_nudge_job(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Send a lighter nudge if morning questions weren't answered."""
        user_id = config.allowed_user_id

        unanswered = await self.models.get_unanswered_questions(user_id)
        if not unanswered:
            return  # All answered, no nudge needed

        try:
            nudge = unanswered[0]
            await context.bot.send_message(
                chat_id=user_id,
                text=f"Quick one! \U0001f3af\n\n{nudge['prompt_text']}\n\n_Just a short voice note!_",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"Afternoon nudge failed: {e}")

    async def _weekly_summary_job(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Generate and send weekly summary on Sundays."""
        user_id = config.allowed_user_id
        user = await self.models.get_user(user_id)
        if not user:
            return

        try:
            # Get this week's grades
            recent_grades = await self.models.get_recent_grades(user_id, limit=50)
            week_start = (date.today() - timedelta(days=7)).isoformat()
            week_grades = []
            for g in recent_grades:
                gd = dict(g)
                if gd.get("created_at", "") >= week_start:
                    if isinstance(gd.get("issues"), str):
                        try:
                            gd["issues"] = json.loads(gd["issues"])
                        except json.JSONDecodeError:
                            pass
                    week_grades.append(gd)

            if not week_grades:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="No practice sessions this week. Let's get back on track tomorrow!",
                )
                return

            summary = await self.claude.generate_weekly_summary(user, week_grades)

            # Store summary
            await self.models.add_weekly_summary(
                user_id=user_id,
                week_start=week_start,
                highlights=summary.get("highlights", []),
                weak_areas=summary.get("weak_areas", []),
                improvements=summary.get("improvements", []),
                recommended_focus=summary.get("recommended_focus", []),
            )

            # Format message
            lines = ["\U0001f4ca <b>Weekly Summary</b>\n"]

            highlights = summary.get("highlights", [])
            if highlights:
                lines.append("<b>Highlights:</b>")
                for h in highlights:
                    lines.append(f"  \u2b50 {h}")

            improvements = summary.get("improvements", [])
            if improvements:
                lines.append("\n<b>Improved:</b>")
                for imp in improvements:
                    lines.append(f"  \U0001f4c8 {imp}")

            weak_areas = summary.get("weak_areas", [])
            if weak_areas:
                lines.append("\n<b>Focus areas:</b>")
                for w in weak_areas:
                    lines.append(f"  \U0001f3af {w}")

            focus = summary.get("recommended_focus", [])
            if focus:
                lines.append("\n<b>Next week's plan:</b>")
                for f in focus:
                    lines.append(f"  \u27a1\ufe0f {f}")

            streak_msg = summary.get("streak_message", "")
            if streak_msg:
                lines.append(f"\n{streak_msg}")

            await context.bot.send_message(
                chat_id=user_id,
                text="\n".join(lines),
                parse_mode="HTML",
            )

            # Also update learner summary
            all_recent = await self.models.get_recent_grades(user_id, limit=20)
            grade_dicts = []
            for g in all_recent:
                gd = dict(g)
                if isinstance(gd.get("issues"), str):
                    try:
                        gd["issues"] = json.loads(gd["issues"])
                    except json.JSONDecodeError:
                        pass
                grade_dicts.append(gd)

            new_summary = await self.claude.update_learner_summary(
                user.get("learner_summary", ""), grade_dicts
            )
            await self.models.update_user(user_id, learner_summary=new_summary)
            await self.planner.update_error_patterns(user_id, grade_dicts)

        except Exception as e:
            logger.error(f"Weekly summary job failed: {e}")
