"""Daily question set generation with variety rules."""

import json
import logging
from datetime import date, timedelta

from ai.claude_client import ClaudeClient
from db.models import Models

logger = logging.getLogger(__name__)


class QuestionGenerator:
    def __init__(self, models: Models, claude: ClaudeClient) -> None:
        self.models = models
        self.claude = claude

    async def generate_daily_questions(self, user_id: int, count: int = 3) -> list[dict]:
        """Generate daily questions and store them."""
        user = await self.models.get_user(user_id)
        if not user:
            return []

        # Check what was asked recently to enforce variety
        recent_questions = await self._get_recent_question_skills(user_id, days=3)

        questions = await self.claude.generate_questions(user, count)

        stored = []
        for q in questions:
            if not q.get("question_jp"):
                continue
            qid = await self.models.add_daily_question(
                user_id=user_id,
                prompt_text=q["question_jp"],
                target_skills=q.get("target_skills", []),
            )
            stored.append({**q, "question_id": qid})

        return stored

    async def get_nudge_question(self, user_id: int) -> dict | None:
        """Get a lighter single question for the afternoon nudge."""
        unanswered = await self.models.get_unanswered_questions(user_id)
        if unanswered:
            return dict(unanswered[0])

        # Generate a single easy review question
        user = await self.models.get_user(user_id)
        if not user:
            return None

        questions = await self.claude.generate_questions(user, count=1)
        if questions:
            q = questions[0]
            qid = await self.models.add_daily_question(
                user_id=user_id,
                prompt_text=q.get("question_jp", ""),
                target_skills=q.get("target_skills", []),
            )
            return {**q, "question_id": qid}
        return None

    async def _get_recent_question_skills(self, user_id: int, days: int = 3) -> set[str]:
        """Get skills targeted in recent days to avoid repetition."""
        since = (date.today() - timedelta(days=days)).isoformat()
        rows = await self.models.db.fetchall(
            "SELECT target_skills FROM daily_questions WHERE user_id = ? AND date(created_at) >= ?",
            (user_id, since),
        )
        skills = set()
        for row in rows:
            try:
                parsed = json.loads(row["target_skills"])
                skills.update(parsed)
            except (json.JSONDecodeError, TypeError):
                pass
        return skills
