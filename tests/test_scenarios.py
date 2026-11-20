import re

from conftest import make_scenario

from dm_bench.scenarios import CATEGORIES, CHANNELS, LANGUAGES, coverage, validate_all, validate_scenario


def test_repo_scenarios_are_valid(scenarios):
    errors, warnings = validate_all(scenarios)
    assert errors == []
    assert warnings == []


def test_size_and_balance(scenarios):
    assert len(scenarios) >= 60
    cov = coverage(scenarios)
    for cat in CATEGORIES:
        assert cov["category"].get(cat, 0) >= 5, cat
    for ch in CHANNELS:
        assert cov["channel"].get(ch, 0) >= 8, ch
    for lang in LANGUAGES:
        if lang != "en":
            assert cov["language"].get(lang, 0) >= 4, lang


def test_every_scenario_is_passable_in_principle(scenarios):
    # A handoff scenario cannot also forbid the marker, and limits must leave room to answer.
    for s in scenarios:
        e = s["expect"]
        if e.get("handoff") is True:
            assert not any(re.search(p, "[HANDOFF]", re.I) for p in e.get("must_not_include", [])), s["id"]
        assert e.get("max_chars", 100) >= 100, s["id"]


def test_valid_minimal_scenario():
    assert validate_scenario(make_scenario()) == []


def test_validator_catches_problems():
    cases = [
        (make_scenario(channel="sms"), "channel must be one of"),
        (make_scenario(language="fr"), "language must be one of"),
        (make_scenario(category="other"), "category must be one of"),
        (make_scenario(id="Bad Id"), "kebab-case"),
        (make_scenario(extra=1), "unknown fields"),
        (make_scenario(expect={"must_include_any": ["("]}), "invalid regex"),
        (make_scenario(expect={"language": "en"}), "at least one of"),
        (make_scenario(expect={"handoff": "yes"}), "handoff must be"),
        (make_scenario(expect={"handoff": True, "max_chars": 0}), "max_chars must be"),
        (make_scenario(history=[{"role": "bot", "text": "hi"}]), "history[0]"),
        (make_scenario(business={"name": "X", "type": "bank", "knowledge_base": ["a"]}), "business.type"),
        (make_scenario(business={"name": "X", "type": "cafe", "knowledge_base": []}), "knowledge_base must be"),
        (make_scenario(message="  "), "message must be"),
    ]
    for scenario, needle in cases:
        errs = validate_scenario(scenario)
        assert any(needle in e for e in errs), (needle, errs)


def test_duplicate_ids_are_errors():
    errors, _ = validate_all([make_scenario(), make_scenario()])
    assert any("duplicate id" in e for e in errors)
