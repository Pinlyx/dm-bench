"""Optional LLM-judge pass. Uses the same generic chat completions protocol as
the agent, configured separately (DMBENCH_JUDGE_BASE_URL, DMBENCH_JUDGE_API_KEY,
DMBENCH_JUDGE_MODEL), so the judge can be a different model than the one under
test. Judged scores are always reported separately from deterministic ones."""

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .agents import AgentError, format_context, load_channel_rules, post_json

DIMENSIONS = ("grounding", "helpfulness", "tone", "policy")


def render_judge_prompt(template: str, scenario: Dict[str, Any], reply: str, channel_rules: Dict[str, Any]) -> str:
    b = scenario["business"]
    ch = channel_rules.get(scenario["channel"], {"name": scenario["channel"]})
    history = "\n".join(f"{t['role']}: {t['text']}" for t in scenario["history"]) or "(no earlier messages)"
    values = {
        "business_name": b["name"],
        "business_type": b["type"].replace("_", " "),
        "channel_name": ch["name"],
        "knowledge_base": "\n".join(f"- {line}" for line in b["knowledge_base"]),
        "context": format_context(scenario.get("context", {})),
        "history": history,
        "message": scenario["message"],
        "judge_notes": scenario["judge_notes"],
        "reply": reply,
    }
    out = template
    for key, val in values.items():
        out = out.replace("{{" + key + "}}", val)
    return out


def parse_verdict(text: str) -> Dict[str, Any]:
    """Extract the judge's JSON object, tolerating code fences or extra prose."""
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        raise AgentError(f"judge did not return JSON: {text[:200]!r}")
    data = json.loads(m.group(0))
    out: Dict[str, Any] = {}
    for dim in DIMENSIONS:
        v = data.get(dim)
        if not isinstance(v, (int, float)) or not 1 <= v <= 5:
            raise AgentError(f"judge score '{dim}' missing or out of range: {v!r}")
        out[dim] = float(v)
    verdict = str(data.get("verdict", "")).strip().lower()
    if verdict not in ("pass", "fail"):
        raise AgentError(f"judge verdict must be pass or fail, got {verdict!r}")
    out["verdict"] = verdict
    out["reason"] = str(data.get("reason", ""))[:500]
    out["score"] = round(sum(out[d] for d in DIMENSIONS) / (5.0 * len(DIMENSIONS)), 4)
    return out


class Judge:
    def __init__(self, model: str, base_url: str, api_key: Optional[str], home: Path, timeout: float = 90.0):
        if not base_url:
            raise AgentError("No judge endpoint: pass --judge-base-url or set DMBENCH_JUDGE_BASE_URL")
        self.model = model
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.api_key = api_key
        self.template = (home / "prompts" / "judge_rubric.txt").read_text(encoding="utf-8")
        self.channel_rules = load_channel_rules(home)
        self.timeout = timeout

    def grade(self, scenario: Dict[str, Any], reply: str, checks: List[Dict[str, Any]]) -> Dict[str, Any]:
        prompt = render_judge_prompt(self.template, scenario, reply, self.channel_rules)
        payload = {"model": self.model, "messages": [{"role": "user", "content": prompt}], "temperature": 0, "max_tokens": 300}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        data = post_json(self.url, payload, headers, self.timeout)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise AgentError(f"unexpected judge response shape: {json.dumps(data)[:300]}")
        return parse_verdict(content)


class MockJudge:
    """Offline stand-in for tests: mirrors the deterministic result. Not a real judge."""

    model = "mock:judge"

    def grade(self, scenario: Dict[str, Any], reply: str, checks: List[Dict[str, Any]]) -> Dict[str, Any]:
        ok = all(c["passed"] for c in checks)
        s = 5 if ok else 2
        data: Dict[str, Any] = {d: s for d in DIMENSIONS}
        data["verdict"] = "pass" if ok else "fail"
        data["reason"] = "mock judge mirrors the deterministic checks"
        return parse_verdict(json.dumps(data))


def make_judge(model: Optional[str], home: Path, base_url: Optional[str] = None, api_key: Optional[str] = None,
               timeout: float = 90.0):
    model = model or os.environ.get("DMBENCH_JUDGE_MODEL")
    if not model:
        raise AgentError("--judge needs a judge model: pass --judge-model or set DMBENCH_JUDGE_MODEL")
    if model == "mock:judge":
        return MockJudge()
    return Judge(
        model=model,
        base_url=base_url or os.environ.get("DMBENCH_JUDGE_BASE_URL", ""),
        api_key=api_key or os.environ.get("DMBENCH_JUDGE_API_KEY"),
        home=home,
        timeout=timeout,
    )
