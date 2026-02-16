"""Load and query JLPT curriculum seed data."""

import json
from pathlib import Path


class Curriculum:
    def __init__(self, data_path: str = "data/seed_curriculum.json") -> None:
        self.data: dict = {}
        self.data_path = data_path

    def load(self) -> None:
        path = Path(self.data_path)
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
        else:
            self.data = {"grammar": [], "vocab": [], "phrases": []}

    def get_grammar(self) -> list[dict]:
        return self.data.get("grammar", [])

    def get_vocab(self) -> list[dict]:
        return self.data.get("vocab", [])

    def get_phrases(self) -> list[dict]:
        return self.data.get("phrases", [])

    def get_all_items(self) -> list[dict]:
        items = []
        for category in ("grammar", "vocab", "phrases"):
            items.extend(self.data.get(category, []))
        return items

    def get_by_category(self, category: str) -> list[dict]:
        return self.data.get(category, [])
