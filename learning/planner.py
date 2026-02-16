"""SM-2 spaced repetition and learning plan management."""

import json
from datetime import date, timedelta

from db.models import Models


class LearningPlanner:
    def __init__(self, models: Models) -> None:
        self.models = models

    async def seed_items_for_user(self, user_id: int, curriculum_items: list[dict]) -> None:
        """Seed learning items from curriculum if user has none."""
        existing = await self.models.get_learning_items(user_id)
        if existing:
            return
        for item in curriculum_items:
            await self.models.add_learning_item(
                user_id=user_id,
                item_type=item.get("category", "grammar"),
                content=item.get("content", ""),
            )

    async def get_due_items(self, user_id: int, limit: int = 10) -> list[dict]:
        return await self.models.get_due_items(user_id, limit)

    async def review_item(self, item_id: int, quality: int) -> None:
        """Update an item after review using SM-2 algorithm.

        quality: 0-5 (0=complete failure, 5=perfect)
        """
        items = await self.models.db.fetchall(
            "SELECT * FROM learning_items WHERE item_id = ?", (item_id,)
        )
        if not items:
            return
        item = dict(items[0])

        easiness = item["easiness"]
        interval = item["interval_days"]

        # SM-2 algorithm
        if quality < 3:
            # Failed — reset interval
            interval = 1
        else:
            if interval == 1:
                interval = 3
            elif interval == 3:
                interval = 7
            else:
                interval = round(interval * easiness)

        # Update easiness factor
        easiness = easiness + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
        easiness = max(1.3, easiness)

        next_due = (date.today() + timedelta(days=interval)).isoformat()

        await self.models.update_learning_item(
            item_id,
            easiness=round(easiness, 2),
            interval_days=interval,
            next_due=next_due,
            last_reviewed=date.today().isoformat(),
        )

    async def update_error_patterns(self, user_id: int, grades: list[dict]) -> None:
        """Aggregate recurring error patterns from recent grades."""
        pattern_counts: dict[str, int] = {}

        for grade in grades:
            issues = grade.get("issues", "[]")
            if isinstance(issues, str):
                try:
                    issues = json.loads(issues)
                except json.JSONDecodeError:
                    continue

            for issue in issues:
                issue_type = issue.get("type", "unknown")
                key = f"{issue_type}"
                pattern_counts[key] = pattern_counts.get(key, 0) + 1

        # Keep patterns seen 2+ times
        patterns = {k: v for k, v in pattern_counts.items() if v >= 2}
        await self.models.update_user(
            user_id,
            recurring_error_patterns=json.dumps(patterns, ensure_ascii=False),
        )

    async def get_learning_plan_summary(self, user_id: int) -> str:
        """Get a text summary of the learning plan for display."""
        items = await self.models.get_learning_items(user_id)
        if not items:
            return "No learning items yet. Start a conversation to build your plan!"

        due_today = [i for i in items if i["next_due"] <= date.today().isoformat()]
        upcoming = [i for i in items if i["next_due"] > date.today().isoformat()][:5]

        lines = []
        if due_today:
            lines.append(f"<b>Due today ({len(due_today)}):</b>")
            for item in due_today[:5]:
                lines.append(f"  \u2022 [{item['item_type']}] {item['content']}")

        if upcoming:
            lines.append(f"\n<b>Coming up ({len(upcoming)}):</b>")
            for item in upcoming:
                lines.append(f"  \u2022 [{item['item_type']}] {item['content']} (due {item['next_due']})")

        total = len(items)
        mastered = len([i for i in items if i["interval_days"] >= 30])
        lines.append(f"\n<b>Progress:</b> {mastered}/{total} items mastered (30+ day interval)")

        return "\n".join(lines)
