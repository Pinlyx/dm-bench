"""Scenario loading and schema validation (stdlib only, no jsonschema)."""

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

CHANNELS = ("instagram", "whatsapp", "messenger", "telegram", "x", "live_chat")
LANGUAGES = ("en", "tr", "es", "ru", "de", "pt", "ar")
CATEGORIES = (
    "grounded_answer",
    "unknown_fact",
    "handoff",
    "language_match",
    "channel_policy",
    "length_and_format",
    "prompt_injection",
    "privacy",
    "sales",
    "multi_turn",
)
BUSINESS_TYPES = ("cafe", "clinic", "ecommerce", "saas", "hotel", "course_creator", "agency")
ROLES = ("customer", "agent")

# Default reply length budget per channel, in characters, after the handoff
# marker is removed. A scenario can tighten (or loosen) it with expect.max_chars.
CHANNEL_MAX_CHARS = {
    "x": 280,
    "whatsapp": 700,
    "instagram": 600,
    "messenger": 700,
    "telegram": 900,
    "live_chat": 900,
}

# Channels that render plain text only: markdown tables, headings and
# [text](url) links show up as raw symbols there.
PLAIN_TEXT_CHANNELS = ("whatsapp", "instagram", "messenger", "x", "telegram")

EXPECT_KEYS = {
    "must_include_any",
    "must_include_all",
    "must_not_include",
    "language",
    "max_chars",
    "handoff",
    "plain_text",
}
SCENARIO_KEYS = {
    "id",
    "channel",
    "language",
    "category",
    "business",
    "context",
    "history",
    "message",
    "expect",
    "judge_notes",
    "notes",
}
REQUIRED_KEYS = ("id", "channel", "language", "category", "business", "history", "message", "expect", "judge_notes")
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def find_home(explicit: Optional[str] = None) -> Path:
    """Locate the benchmark root (the folder holding scenarios/ and prompts/)."""
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("DMBENCH_HOME"):
        candidates.append(Path(os.environ["DMBENCH_HOME"]))
    candidates.append(Path.cwd())
    candidates.append(Path(__file__).resolve().parents[2])
    for c in candidates:
        if (c / "scenarios").is_dir() and (c / "prompts").is_dir():
            return c
    raise FileNotFoundError(
        "Could not find the dm-bench data folder (scenarios/ and prompts/). "
        "Run from a clone of the repository, or set DMBENCH_HOME / --home."
    )


def load_scenarios(scenario_dir: Path) -> List[Dict[str, Any]]:
    """Load every scenario from *.json files in a folder, sorted by id."""
    items: List[Dict[str, Any]] = []
    for path in sorted(Path(scenario_dir).glob("*.json")):
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            raise ValueError(f"{path.name}: top level must be a JSON array of scenarios")
        for s in data:
            if isinstance(s, dict):
                s.setdefault("_file", path.name)
            items.append(s)
    return items


def _check_regex_list(errs: List[str], where: str, value: Any) -> None:
    if not isinstance(value, list) or not value:
        errs.append(f"{where}: must be a non-empty list of regex strings")
        return
    for pat in value:
        if not isinstance(pat, str) or not pat:
            errs.append(f"{where}: every pattern must be a non-empty string")
            continue
        try:
            re.compile(pat, re.IGNORECASE)
        except re.error as exc:
            errs.append(f"{where}: invalid regex {pat!r}: {exc}")


def validate_scenario(s: Any) -> List[str]:
    """Return a list of human-readable problems for one scenario (empty = valid)."""
    if not isinstance(s, dict):
        return ["scenario must be a JSON object"]
    sid = s.get("id", "<no id>")
    errs: List[str] = []
    for key in REQUIRED_KEYS:
        if key not in s:
            errs.append(f"missing required field '{key}'")
    unknown = set(s) - SCENARIO_KEYS - {"_file"}
    if unknown:
        errs.append(f"unknown fields: {sorted(unknown)}")
    if "id" in s and (not isinstance(s["id"], str) or not ID_RE.match(s["id"])):
        errs.append("id must be lowercase kebab-case, e.g. 'grounded-cafe-hours-en'")
    if s.get("channel") not in CHANNELS:
        errs.append(f"channel must be one of {CHANNELS}")
    if s.get("language") not in LANGUAGES:
        errs.append(f"language must be one of {LANGUAGES}")
    if s.get("category") not in CATEGORIES:
        errs.append(f"category must be one of {CATEGORIES}")

    b = s.get("business")
    if not isinstance(b, dict):
        errs.append("business must be an object")
    else:
        for key in ("name", "type", "knowledge_base"):
            if key not in b:
                errs.append(f"business.{key} is required")
        if "type" in b and b["type"] not in BUSINESS_TYPES:
            errs.append(f"business.type must be one of {BUSINESS_TYPES}")
        kb = b.get("knowledge_base")
        if kb is not None and (not isinstance(kb, list) or not kb or not all(isinstance(x, str) and x for x in kb)):
            errs.append("business.knowledge_base must be a non-empty list of strings")
        extra = set(b) - {"name", "type", "knowledge_base", "description"}
        if extra:
            errs.append(f"business has unknown fields: {sorted(extra)}")

    ctx = s.get("context", {})
    if not isinstance(ctx, dict):
        errs.append("context must be an object")
    else:
        for k, v in ctx.items():
            if not isinstance(v, (str, int, float, bool)) or v is None:
                errs.append(f"context.{k} must be a string, number or boolean")

    hist = s.get("history")
    if not isinstance(hist, list):
        errs.append("history must be a list (use [] for a first message)")
    else:
        for i, turn in enumerate(hist):
            if not isinstance(turn, dict) or turn.get("role") not in ROLES or not isinstance(turn.get("text"), str) or not turn.get("text"):
                errs.append(f"history[{i}] must be {{'role': 'customer'|'agent', 'text': '...'}}")
            elif set(turn) - {"role", "text"}:
                errs.append(f"history[{i}] has unknown fields")

    if "message" in s and (not isinstance(s["message"], str) or not s["message"].strip()):
        errs.append("message must be a non-empty string")
    if "judge_notes" in s and (not isinstance(s["judge_notes"], str) or not s["judge_notes"].strip()):
        errs.append("judge_notes must be a non-empty string")

    e = s.get("expect")
    if not isinstance(e, dict):
        errs.append("expect must be an object")
    else:
        unknown_e = set(e) - EXPECT_KEYS
        if unknown_e:
            errs.append(f"expect has unknown fields: {sorted(unknown_e)}")
        for key in ("must_include_any", "must_include_all", "must_not_include"):
            if key in e:
                _check_regex_list(errs, f"expect.{key}", e[key])
        if "language" in e and e["language"] is not None and e["language"] not in LANGUAGES:
            errs.append(f"expect.language must be null or one of {LANGUAGES}")
        if "max_chars" in e and (not isinstance(e["max_chars"], int) or isinstance(e["max_chars"], bool) or e["max_chars"] <= 0):
            errs.append("expect.max_chars must be a positive integer")
        if "handoff" in e and e["handoff"] not in (True, False, None):
            errs.append("expect.handoff must be true, false or null")
        if "plain_text" in e and not isinstance(e["plain_text"], bool):
            errs.append("expect.plain_text must be a boolean")
        has_content_check = any(k in e for k in ("must_include_any", "must_include_all", "must_not_include", "handoff"))
        if not has_content_check:
            errs.append("expect needs at least one of must_include_any, must_include_all, must_not_include, handoff")
    return [f"{sid}: {msg}" for msg in errs]


def validate_all(scenarios: List[Any]) -> Tuple[List[str], List[str]]:
    """Validate a scenario list. Returns (errors, warnings)."""
    errors: List[str] = []
    warnings: List[str] = []
    seen = {}
    for s in scenarios:
        errors.extend(validate_scenario(s))
        if isinstance(s, dict) and isinstance(s.get("id"), str):
            if s["id"] in seen:
                errors.append(f"{s['id']}: duplicate id (also in {seen[s['id']]})")
            seen[s["id"]] = s.get("_file", "?")
    counts = coverage(scenarios)
    for lang in LANGUAGES:
        if lang != "en" and counts["language"].get(lang, 0) < 4:
            warnings.append(f"language '{lang}' has fewer than 4 scenarios")
    for cat in CATEGORIES:
        if counts["category"].get(cat, 0) < 3:
            warnings.append(f"category '{cat}' has fewer than 3 scenarios")
    for ch in CHANNELS:
        if counts["channel"].get(ch, 0) < 3:
            warnings.append(f"channel '{ch}' has fewer than 3 scenarios")
    return errors, warnings


def coverage(scenarios: List[Any]) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {"category": {}, "channel": {}, "language": {}}
    for s in scenarios:
        if not isinstance(s, dict):
            continue
        for dim in out:
            v = s.get(dim)
            if isinstance(v, str):
                out[dim][v] = out[dim].get(v, 0) + 1
    return out


def effective_expect(s: Dict[str, Any]) -> Dict[str, Any]:
    """Expectations with channel and language defaults filled in."""
    e = dict(s.get("expect", {}))
    e.setdefault("language", s.get("language"))
    e.setdefault("max_chars", CHANNEL_MAX_CHARS.get(s.get("channel"), 900))
    e.setdefault("plain_text", s.get("channel") in PLAIN_TEXT_CHANNELS)
    return e
