import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dm_bench.scenarios import load_scenarios  # noqa: E402


@pytest.fixture(scope="session")
def home() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def scenarios(home):
    return load_scenarios(home / "scenarios")


@pytest.fixture(scope="session")
def reference_answers(home):
    return json.loads((home / "tests" / "reference_answers.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def bad_answers(home):
    return json.loads((home / "tests" / "bad_answers.json").read_text(encoding="utf-8"))


def make_scenario(**overrides):
    """A minimal valid scenario for unit tests."""
    s = {
        "id": "unit-test-scenario",
        "channel": "whatsapp",
        "language": "en",
        "category": "grounded_answer",
        "business": {"name": "Test Cafe", "type": "cafe", "knowledge_base": ["Open 8:00-18:00 every day."]},
        "history": [],
        "message": "When do you open?",
        "expect": {"must_include_any": ["8[:.]?00"]},
        "judge_notes": "Gives the opening hours.",
    }
    s.update(overrides)
    return s
