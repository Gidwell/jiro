"""Session management — one conversation session per day."""

from datetime import date

from db.models import Models


class ConversationManager:
    def __init__(self, models: Models) -> None:
        self.models = models

    async def get_session(self, user_id: int, mode: str = "conversation") -> dict:
        """Get or create today's session."""
        return await self.models.get_or_create_session(user_id, mode)

    async def add_user_message(
        self, session_id: str, text: str, transcript: str | None = None
    ) -> int:
        return await self.models.add_message(session_id, "user", text, transcript)

    async def add_bot_message(self, session_id: str, text: str) -> int:
        return await self.models.add_message(session_id, "bot", text)

    async def get_context(self, session_id: str, limit: int = 10) -> list[dict]:
        """Get the last N messages for context window."""
        return await self.models.get_recent_messages(session_id, limit)

    async def should_update_learner_summary(self, user_id: int) -> bool:
        """Check if learner summary needs updating (every 10 graded interactions)."""
        total = await self.models.get_grade_count_total(user_id)
        # Update at every 10th grade
        return total > 0 and total % 10 == 0
