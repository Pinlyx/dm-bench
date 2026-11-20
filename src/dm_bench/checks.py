"""Deterministic checks. Every check is a pure function of (reply, scenario).

The handoff protocol: an agent that hands the conversation to a human must put
the marker ``[HANDOFF]`` (optionally ``[HANDOFF: short reason]``) anywhere in
its reply. The marker is removed before the length, language and format
checks, so it never costs the agent characters. Regex checks see the raw reply,
marker included, so a scenario may accept "says it will check" OR "hands off".
"""

import re
from typing import Any, Dict, List, Optional

from . import langdetect
from .scenarios import effective_expect

HANDOFF_RE = re.compile(r"\[HANDOFF(?::[^\]]*)?\]", re.IGNORECASE)

_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$", re.MULTILINE)
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+\S", re.MULTILINE)
_MD_LINK = re.compile(r"\[[^\]\n]+\]\((https?://|www\.)[^)\s]+\)")
_DOUBLE_BOLD = re.compile(r"\*\*[^*\n]+\*\*|__[^_\n]+__")

FLAGS = re.IGNORECASE | re.UNICODE


def has_handoff(reply: str) -> bool:
    return bool(HANDOFF_RE.search(reply or ""))


def strip_marker(reply: str) -> str:
    text = HANDOFF_RE.sub("", reply or "")
    return re.sub(r"[ \t]+\n", "\n", text).strip()


def _result(name: str, passed: bool, detail: str = "") -> Dict[str, Any]:
    return {"check": name, "passed": bool(passed), "detail": detail}


def check_must_include_any(reply: str, patterns: List[str]) -> Dict[str, Any]:
    for pat in patterns:
        if re.search(pat, reply, FLAGS):
            return _result("must_include_any", True, f"matched {pat!r}")
    return _result("must_include_any", False, f"none of {len(patterns)} patterns matched")


def check_must_include_all(reply: str, patterns: List[str]) -> Dict[str, Any]:
    missing = [p for p in patterns if not re.search(p, reply, FLAGS)]
    if missing:
        return _result("must_include_all", False, f"missing {missing!r}")
    return _result("must_include_all", True, f"all {len(patterns)} matched")


def check_must_not_include(reply: str, patterns: List[str]) -> Dict[str, Any]:
    for pat in patterns:
        m = re.search(pat, reply, FLAGS)
        if m:
            return _result("must_not_include", False, f"forbidden {pat!r} matched {m.group(0)!r}")
    return _result("must_not_include", True, "")


def check_language(text: str, expected: str) -> Dict[str, Any]:
    got = langdetect.detect(text)
    return _result("language", got == expected, f"expected {expected}, detected {got}")


def check_max_chars(text: str, limit: int) -> Dict[str, Any]:
    n = len(text)
    return _result("max_chars", n <= limit, f"{n}/{limit} chars")


def check_handoff(reply: str, expected: bool) -> Dict[str, Any]:
    got = has_handoff(reply)
    return _result("handoff", got == expected, f"expected handoff={expected}, got {got}")


def check_plain_text(text: str) -> Dict[str, Any]:
    problems = []
    if _TABLE_SEP.search(text) or len(_TABLE_ROW.findall(text)) >= 2:
        problems.append("markdown table")
    if _HEADING.search(text):
        problems.append("markdown heading")
    if _MD_LINK.search(text):
        problems.append("markdown link")
    if _DOUBLE_BOLD.search(text):
        problems.append("markdown bold (**text**)")
    return _result("plain_text", not problems, ", ".join(problems))


def check_nonempty(text: str) -> Dict[str, Any]:
    """The customer must get words, even when the agent hands off."""
    return _result("non_empty", bool(text.strip()), "" if text.strip() else "empty reply")


def run_checks(reply: Optional[str], scenario: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Run every applicable deterministic check for one reply."""
    raw = reply or ""
    e = effective_expect(scenario)
    text = strip_marker(raw)
    results = [check_nonempty(text)]
    if "must_include_any" in e:
        results.append(check_must_include_any(raw, e["must_include_any"]))
    if "must_include_all" in e:
        results.append(check_must_include_all(raw, e["must_include_all"]))
    if "must_not_include" in e:
        results.append(check_must_not_include(raw, e["must_not_include"]))
    if e.get("handoff") is not None:
        results.append(check_handoff(raw, e["handoff"]))
    if e.get("language") and text:
        results.append(check_language(text, e["language"]))
    if e.get("max_chars"):
        results.append(check_max_chars(text, e["max_chars"]))
    if e.get("plain_text"):
        results.append(check_plain_text(text))
    return results
