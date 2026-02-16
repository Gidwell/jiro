"""Formats the response contract text block from Claude's JSON output."""

import html


SCORE_WEIGHTS = {
    "grammar": 0.25,
    "vocab": 0.20,
    "pronunciation": 0.20,
    "fluency": 0.20,
    "naturalness": 0.15,
}

ISSUE_TYPE_EMOJI = {
    "grammar": "\u2699\ufe0f",
    "vocab": "\U0001f4d6",
    "naturalness": "\U0001f3af",
    "pronunciation": "\U0001f50a",
    "fluency": "\U0001f30a",
}


def _e(text: str) -> str:
    """Escape text for HTML parse mode."""
    return html.escape(str(text))


def format_feedback_text(grading_result: dict, transcript: str) -> str:
    """Format Claude's JSON grading output into Telegram HTML text message."""
    lines = []

    # You said
    lines.append(f"\U0001f5e3 <b>You said:</b> {_e(transcript)}")
    lines.append("")

    # Clean version
    cleaned = grading_result.get("cleaned_up", {})
    casual = cleaned.get("casual_jp")
    polite = cleaned.get("polite_jp")
    if casual and polite:
        lines.append(f"\u2705 <b>Clean version:</b>")
        lines.append(f"  Casual: {_e(casual)}")
        lines.append(f"  Polite: {_e(polite)}")
    elif casual:
        lines.append(f"\u2705 <b>Clean version:</b> {_e(casual)}")
    elif polite:
        lines.append(f"\u2705 <b>Clean version:</b> {_e(polite)}")
    lines.append("")

    # Issues
    issues = grading_result.get("issues", [])
    if issues:
        lines.append(f"\u26a0\ufe0f <b>Issues ({len(issues)}):</b>")
        for i, issue in enumerate(issues, 1):
            emoji = ISSUE_TYPE_EMOJI.get(issue.get("type", ""), "\u2022")
            lines.append(f"  {emoji} {_e(issue.get('original', ''))} \u2192 {_e(issue.get('corrected', ''))}")
            if issue.get("explanation"):
                lines.append(f"     <i>{_e(issue['explanation'])}</i>")
        lines.append("")

    # Micro-drill
    drill = grading_result.get("micro_drill", {})
    if drill and drill.get("prompt_jp"):
        drill_type = drill.get("type", "repeat")
        lines.append(f"\U0001f3af <b>Micro-drill</b> ({_e(drill_type)}):")
        lines.append(f"  {_e(drill['prompt_jp'])}")
        if drill.get("expected_jp"):
            lines.append(f"  Expected: {_e(drill['expected_jp'])}")
        lines.append("")

    # Scores
    scores = grading_result.get("scores", {})
    if scores:
        overall = scores.get("overall", 0)
        lines.append(f"\U0001f4ca <b>Score: {overall}/100</b>")
        details = []
        for key in ("grammar", "vocab", "pronunciation", "fluency", "naturalness"):
            val = scores.get(key, 0)
            details.append(f"{key.capitalize()}: {val}")
        lines.append(f"  {' | '.join(details)}")

    # Key vocabulary
    key_vocab = grading_result.get("key_vocab", [])
    if key_vocab:
        lines.append("")
        lines.append("\U0001f4d6 <b>Key Vocabulary:</b>")
        for item in key_vocab:
            word = _e(item.get("word", ""))
            reading = _e(item.get("reading", ""))
            english = _e(item.get("english", ""))
            lines.append(f"  • {word}（{reading}）— {english}")

    # Praise
    praise = grading_result.get("praise")
    if praise:
        lines.append(f"\n\u2728 {_e(praise)}")

    return "\n".join(lines)


def calculate_weighted_score(scores: dict) -> int:
    """Calculate weighted overall score from subscores."""
    total = 0.0
    for key, weight in SCORE_WEIGHTS.items():
        total += scores.get(key, 0) * weight
    return round(total)
