import json
from datetime import date, datetime

from db.database import Database


class Models:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ── user_profile ──

    async def get_or_create_user(self, user_id: int, display_name: str = "") -> dict:
        row = await self.db.fetchone("SELECT * FROM user_profile WHERE user_id = ?", (user_id,))
        if row:
            return row
        await self.db.execute_write(
            "INSERT INTO user_profile (user_id, display_name) VALUES (?, ?)",
            (user_id, display_name),
        )
        row = await self.db.fetchone("SELECT * FROM user_profile WHERE user_id = ?", (user_id,))
        return row

    async def update_user(self, user_id: int, **fields) -> None:
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [user_id]
        await self.db.execute_write(
            f"UPDATE user_profile SET {set_clause} WHERE user_id = ?",
            tuple(values),
        )

    async def get_user(self, user_id: int) -> dict | None:
        return await self.db.fetchone("SELECT * FROM user_profile WHERE user_id = ?", (user_id,))

    async def delete_user_data(self, user_id: int) -> None:
        """Wipe all 7 tables for a user."""
        # Get all session IDs for this user
        sessions = await self.db.fetchall(
            "SELECT session_id FROM conversation_sessions WHERE user_id = ?", (user_id,)
        )
        session_ids = [s["session_id"] for s in sessions]

        if session_ids:
            placeholders = ",".join("?" * len(session_ids))
            # Get all message IDs from these sessions
            messages = await self.db.fetchall(
                f"SELECT message_id FROM conversation_messages WHERE session_id IN ({placeholders})",
                tuple(session_ids),
            )
            message_ids = [m["message_id"] for m in messages]

            if message_ids:
                msg_placeholders = ",".join("?" * len(message_ids))
                await self.db.execute_write(
                    f"DELETE FROM grades WHERE message_id IN ({msg_placeholders})",
                    tuple(message_ids),
                )

            await self.db.execute_write(
                f"DELETE FROM conversation_messages WHERE session_id IN ({placeholders})",
                tuple(session_ids),
            )

        await self.db.execute_write(
            "DELETE FROM conversation_sessions WHERE user_id = ?", (user_id,)
        )
        await self.db.execute_write(
            "DELETE FROM learning_items WHERE user_id = ?", (user_id,)
        )
        await self.db.execute_write(
            "DELETE FROM daily_questions WHERE user_id = ?", (user_id,)
        )
        await self.db.execute_write(
            "DELETE FROM weekly_summaries WHERE user_id = ?", (user_id,)
        )
        await self.db.execute_write(
            "DELETE FROM user_profile WHERE user_id = ?", (user_id,)
        )

    # ── conversation_sessions ──

    async def get_or_create_session(self, user_id: int, mode: str = "conversation") -> dict:
        session_id = f"session_{date.today().isoformat()}"
        row = await self.db.fetchone(
            "SELECT * FROM conversation_sessions WHERE session_id = ? AND user_id = ?",
            (session_id, user_id),
        )
        if row:
            return row
        await self.db.execute_write(
            "INSERT INTO conversation_sessions (session_id, user_id, mode) VALUES (?, ?, ?)",
            (session_id, user_id, mode),
        )
        row = await self.db.fetchone(
            "SELECT * FROM conversation_sessions WHERE session_id = ?", (session_id,)
        )
        return row

    async def end_session(self, session_id: str) -> None:
        await self.db.execute_write(
            "UPDATE conversation_sessions SET ended_at = datetime('now') WHERE session_id = ?",
            (session_id,),
        )

    # ── conversation_messages ──

    async def add_message(
        self, session_id: str, role: str, text: str, transcript: str | None = None
    ) -> int:
        return await self.db.execute_write(
            "INSERT INTO conversation_messages (session_id, role, text, transcript) VALUES (?, ?, ?, ?) RETURNING message_id",
            (session_id, role, text, transcript),
        )

    async def get_recent_messages(self, session_id: str, limit: int = 20) -> list[dict]:
        rows = await self.db.fetchall(
            "SELECT * FROM conversation_messages WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
            (session_id, limit),
        )
        return list(reversed(rows))

    # ── grades ──

    async def add_grade(
        self,
        message_id: int,
        overall_score: int,
        grammar_score: int,
        vocab_score: int,
        pronunciation_score: int,
        fluency_score: int,
        naturalness_score: int,
        issues: list,
        suggestions: list,
    ) -> int:
        return await self.db.execute_write(
            """INSERT INTO grades
               (message_id, overall_score, grammar_score, vocab_score,
                pronunciation_score, fluency_score, naturalness_score, issues, suggestions)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING grade_id""",
            (
                message_id,
                overall_score,
                grammar_score,
                vocab_score,
                pronunciation_score,
                fluency_score,
                naturalness_score,
                json.dumps(issues, ensure_ascii=False),
                json.dumps(suggestions, ensure_ascii=False),
            ),
        )

    async def get_recent_grades(self, user_id: int, limit: int = 20) -> list[dict]:
        return await self.db.fetchall(
            """SELECT g.* FROM grades g
               JOIN conversation_messages m ON g.message_id = m.message_id
               JOIN conversation_sessions s ON m.session_id = s.session_id
               WHERE s.user_id = ?
               ORDER BY g.created_at DESC LIMIT ?""",
            (user_id, limit),
        )

    async def count_graded_since(self, user_id: int, since: str) -> int:
        row = await self.db.fetchone(
            """SELECT COUNT(*) as cnt FROM grades g
               JOIN conversation_messages m ON g.message_id = m.message_id
               JOIN conversation_sessions s ON m.session_id = s.session_id
               WHERE s.user_id = ? AND g.created_at >= ?""",
            (user_id, since),
        )
        return row["cnt"] if row else 0

    # ── learning_items ──

    async def add_learning_item(
        self,
        user_id: int,
        item_type: str,
        content: str,
        easiness: float = 2.5,
        interval_days: int = 1,
    ) -> int:
        return await self.db.execute_write(
            """INSERT INTO learning_items (user_id, item_type, content, easiness, interval_days)
               VALUES (?, ?, ?, ?, ?) RETURNING item_id""",
            (user_id, item_type, content, easiness, interval_days),
        )

    async def get_due_items(self, user_id: int, limit: int = 10) -> list[dict]:
        return await self.db.fetchall(
            """SELECT * FROM learning_items
               WHERE user_id = ? AND next_due <= date('now')
               ORDER BY next_due ASC LIMIT ?""",
            (user_id, limit),
        )

    async def update_learning_item(self, item_id: int, **fields) -> None:
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [item_id]
        await self.db.execute_write(
            f"UPDATE learning_items SET {set_clause} WHERE item_id = ?",
            tuple(values),
        )

    async def get_learning_items(self, user_id: int) -> list[dict]:
        return await self.db.fetchall(
            "SELECT * FROM learning_items WHERE user_id = ? ORDER BY next_due ASC",
            (user_id,),
        )

    # ── daily_questions ──

    async def add_daily_question(
        self, user_id: int, prompt_text: str, target_skills: list
    ) -> int:
        return await self.db.execute_write(
            "INSERT INTO daily_questions (user_id, prompt_text, target_skills) VALUES (?, ?, ?) RETURNING question_id",
            (user_id, prompt_text, json.dumps(target_skills, ensure_ascii=False)),
        )

    async def get_todays_questions(self, user_id: int) -> list[dict]:
        today = date.today().isoformat()
        return await self.db.fetchall(
            "SELECT * FROM daily_questions WHERE user_id = ? AND date(created_at) = ?",
            (user_id, today),
        )

    async def get_unanswered_questions(self, user_id: int) -> list[dict]:
        today = date.today().isoformat()
        return await self.db.fetchall(
            "SELECT * FROM daily_questions WHERE user_id = ? AND date(created_at) = ? AND answered_at IS NULL",
            (user_id, today),
        )

    async def mark_question_answered(self, question_id: int) -> None:
        await self.db.execute_write(
            "UPDATE daily_questions SET answered_at = datetime('now') WHERE question_id = ?",
            (question_id,),
        )

    # ── weekly_summaries ──

    async def add_weekly_summary(
        self,
        user_id: int,
        week_start: str,
        highlights: list,
        weak_areas: list,
        improvements: list,
        recommended_focus: list,
    ) -> int:
        return await self.db.execute_write(
            """INSERT INTO weekly_summaries
               (user_id, week_start, highlights, weak_areas, improvements, recommended_focus)
               VALUES (?, ?, ?, ?, ?, ?) RETURNING summary_id""",
            (
                user_id,
                week_start,
                json.dumps(highlights, ensure_ascii=False),
                json.dumps(weak_areas, ensure_ascii=False),
                json.dumps(improvements, ensure_ascii=False),
                json.dumps(recommended_focus, ensure_ascii=False),
            ),
        )

    async def get_latest_weekly_summary(self, user_id: int) -> dict | None:
        return await self.db.fetchone(
            "SELECT * FROM weekly_summaries WHERE user_id = ? ORDER BY week_start DESC LIMIT 1",
            (user_id,),
        )

    # ── utility ──

    async def get_grade_count_total(self, user_id: int) -> int:
        row = await self.db.fetchone(
            """SELECT COUNT(*) as cnt FROM grades g
               JOIN conversation_messages m ON g.message_id = m.message_id
               JOIN conversation_sessions s ON m.session_id = s.session_id
               WHERE s.user_id = ?""",
            (user_id,),
        )
        return row["cnt"] if row else 0

    async def get_daily_voice_count(self, user_id: int) -> int:
        today = date.today().isoformat()
        row = await self.db.fetchone(
            """SELECT COUNT(*) as cnt FROM conversation_messages m
               JOIN conversation_sessions s ON m.session_id = s.session_id
               WHERE s.user_id = ? AND m.role = 'user' AND m.transcript IS NOT NULL
               AND date(m.created_at) = ?""",
            (user_id, today),
        )
        return row["cnt"] if row else 0

    async def get_score_trends(self, user_id: int, days: int = 7) -> dict:
        """Get average scores for recent period vs previous period for trend calculation."""
        rows = await self.db.fetchall(
            """SELECT g.grammar_score, g.vocab_score, g.pronunciation_score,
                      g.fluency_score, g.naturalness_score, g.overall_score, g.created_at
               FROM grades g
               JOIN conversation_messages m ON g.message_id = m.message_id
               JOIN conversation_sessions s ON m.session_id = s.session_id
               WHERE s.user_id = ?
               ORDER BY g.created_at DESC LIMIT 40""",
            (user_id,),
        )
        if not rows:
            return {}

        cutoff = len(rows) // 2 if len(rows) >= 4 else len(rows)
        recent = rows[:cutoff]
        previous = rows[cutoff:] if cutoff < len(rows) else []

        def avg(items: list[dict], key: str) -> float:
            vals = [i[key] for i in items if i[key] is not None]
            return sum(vals) / len(vals) if vals else 0

        fields = ["grammar_score", "vocab_score", "pronunciation_score",
                   "fluency_score", "naturalness_score", "overall_score"]
        trends = {}
        for f in fields:
            recent_avg = avg(recent, f)
            prev_avg = avg(previous, f) if previous else recent_avg
            trends[f] = round(recent_avg - prev_avg, 1)

        return trends
