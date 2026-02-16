import json
import logging

from anthropic import AsyncAnthropic

from ai.prompts import (
    COACH_SYSTEM_PROMPT,
    LEARNER_SUMMARY_UPDATE_PROMPT,
    QUESTION_GENERATION_PROMPT,
    WEEKLY_SUMMARY_PROMPT,
)

logger = logging.getLogger(__name__)

MAX_RETRIES = 2


class ClaudeClient:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model

    async def _call(
        self, system: str, messages: list[dict], max_tokens: int = 2000
    ) -> str:
        """Make a Claude API call with retry logic and prompt caching."""
        # Use cache_control on system prompt to reduce TTFT on repeat calls
        system_with_cache = [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        last_error = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    system=system_with_cache,
                    messages=messages,
                )
                return response.content[0].text
            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    logger.warning(f"Claude API attempt {attempt + 1} failed: {e}")
                    import asyncio
                    await asyncio.sleep(2 ** attempt)
        raise last_error

    def _build_coach_system(self, user_profile: dict) -> str:
        return COACH_SYSTEM_PROMPT.format(
            learner_summary=user_profile.get("learner_summary", "New learner — no history yet."),
            register_preference=user_profile.get("register_preference", "mixed"),
            correction_intensity=user_profile.get("correction_intensity", "normal"),
            mode=user_profile.get("mode", "conversation"),
            difficulty_ramp=user_profile.get("difficulty_ramp", "normal"),
            recurring_error_patterns=user_profile.get("recurring_error_patterns", "{}"),
        )

    async def generate_conversation_response(
        self,
        user_profile: dict,
        conversation_messages: list[dict],
        transcript: str,
        due_items: list[dict] | None = None,
        daily_prompt: str | None = None,
    ) -> dict:
        """Generate a full graded response for a user voice message."""
        system = self._build_coach_system(user_profile)

        # Build context messages
        messages = []

        if daily_prompt:
            messages.append({
                "role": "user",
                "content": f"[Today's daily prompt: {daily_prompt}]",
            })
            messages.append({
                "role": "assistant",
                "content": "[Acknowledged — I'll incorporate this context.]",
            })

        if due_items:
            items_text = ", ".join(
                f"{i.get('item_type', 'item')}: {i.get('content', '')}" for i in due_items[:5]
            )
            messages.append({
                "role": "user",
                "content": f"[Due review items: {items_text}]",
            })
            messages.append({
                "role": "assistant",
                "content": "[Acknowledged — I'll weave these into my feedback.]",
            })

        # Add conversation history
        for msg in conversation_messages:
            messages.append({
                "role": "user" if msg["role"] == "user" else "assistant",
                "content": msg["text"],
            })

        # Add the current transcript
        messages.append({
            "role": "user",
            "content": transcript,
        })

        raw = await self._call(system, messages)
        return self._parse_json(raw)

    async def grade_response(
        self,
        user_profile: dict,
        transcript: str,
        conversation_context: list[dict],
    ) -> dict:
        """Grade a user's voice response (runs concurrently with conversation response)."""
        system = self._build_coach_system(user_profile)

        messages = []
        for msg in conversation_context[-10:]:
            messages.append({
                "role": "user" if msg["role"] == "user" else "assistant",
                "content": msg["text"],
            })

        messages.append({
            "role": "user",
            "content": f"[Grade this response]: {transcript}",
        })

        raw = await self._call(system, messages)
        return self._parse_json(raw)

    async def generate_questions(
        self, user_profile: dict, count: int = 3
    ) -> list[dict]:
        """Generate daily practice questions."""
        system = QUESTION_GENERATION_PROMPT.format(
            learner_summary=user_profile.get("learner_summary", "New learner."),
            mode=user_profile.get("mode", "conversation"),
            difficulty_ramp=user_profile.get("difficulty_ramp", "normal"),
            preferred_topics=user_profile.get("preferred_topics", "[]"),
            recurring_error_patterns=user_profile.get("recurring_error_patterns", "{}"),
            count=count,
        )

        messages = [{"role": "user", "content": "Generate today's questions."}]
        raw = await self._call(system, messages, max_tokens=1500)
        result = self._parse_json(raw)
        return result if isinstance(result, list) else []

    async def generate_weekly_summary(
        self, user_profile: dict, grades: list[dict]
    ) -> dict:
        """Generate a weekly progress summary."""
        system = WEEKLY_SUMMARY_PROMPT.format(
            learner_summary=user_profile.get("learner_summary", ""),
            grades_json=json.dumps(grades, ensure_ascii=False, default=str),
        )

        messages = [{"role": "user", "content": "Generate this week's summary."}]
        raw = await self._call(system, messages, max_tokens=1500)
        return self._parse_json(raw)

    async def update_learner_summary(
        self, current_summary: str, grades: list[dict]
    ) -> str:
        """Rewrite the learner summary based on recent grades."""
        system = LEARNER_SUMMARY_UPDATE_PROMPT.format(
            current_summary=current_summary or "No previous summary.",
            grades_json=json.dumps(grades, ensure_ascii=False, default=str),
        )

        messages = [{"role": "user", "content": "Update the learner summary."}]
        raw = await self._call(system, messages, max_tokens=1200)
        # This returns plain text, not JSON
        return raw.strip()[:1000]

    def _parse_json(self, raw: str) -> dict | list:
        """Parse JSON from Claude response, stripping any accidental markdown fences."""
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines if they're fences
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse Claude JSON response: {text[:200]}")
            raise
