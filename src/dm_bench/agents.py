"""Agents under test: an OpenAI-compatible chat endpoint, your own HTTP agent,
or built-in mocks used to verify the pipeline offline."""

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __version__

HANDOFF_MARKER = "[HANDOFF]"
USER_AGENT = f"dm-bench/{__version__}"


class AgentError(RuntimeError):
    pass


def load_channel_rules(home: Path) -> Dict[str, Any]:
    with open(home / "prompts" / "channel_rules.json", encoding="utf-8") as fh:
        return json.load(fh)


def format_context(ctx: Dict[str, Any]) -> str:
    if not ctx:
        return "- No extra context."
    return "\n".join(f"- {k.replace('_', ' ')}: {v}" for k, v in ctx.items())


def render_system_prompt(template: str, scenario: Dict[str, Any], channel_rules: Dict[str, Any]) -> str:
    """Fill the published template for one scenario."""
    b = scenario["business"]
    ch = channel_rules.get(scenario["channel"], {"name": scenario["channel"], "rules": []})
    values = {
        "business_name": b["name"],
        "business_type": b["type"].replace("_", " "),
        "channel_name": ch["name"],
        "knowledge_base": "\n".join(f"- {line}" for line in b["knowledge_base"]),
        "context": format_context(scenario.get("context", {})),
        "channel_rules": "\n".join(f"- {r}" for r in ch["rules"]),
    }
    out = template
    for key, val in values.items():
        out = out.replace("{{" + key + "}}", val)
    return out


def build_messages(system_prompt: str, scenario: Dict[str, Any]) -> List[Dict[str, str]]:
    msgs = [{"role": "system", "content": system_prompt}]
    for turn in scenario["history"]:
        msgs.append({"role": "user" if turn["role"] == "customer" else "assistant", "content": turn["text"]})
    msgs.append({"role": "user", "content": scenario["message"]})
    return msgs


def post_json(url: str, payload: Dict[str, Any], headers: Dict[str, str], timeout: float, retries: int = 3) -> Dict[str, Any]:
    """POST JSON with retry on 429 and 5xx. Stdlib only."""
    body = json.dumps(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    hdrs.update(headers)
    last: Optional[Exception] = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            last = AgentError(f"HTTP {exc.code} from {url}: {detail}")
            if exc.code != 429 and exc.code < 500:
                break
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            last = AgentError(f"request to {url} failed: {exc}")
        if attempt < retries - 1:
            time.sleep(2 ** attempt)
    raise last or AgentError("request failed")


class ChatCompletionsAgent:
    """Any OpenAI-compatible /chat/completions endpoint, including local servers."""

    kind = "chat"

    def __init__(self, model: str, base_url: str, api_key: Optional[str], system_template: str,
                 channel_rules: Dict[str, Any], temperature: float = 0.0, max_tokens: int = 600,
                 timeout: float = 90.0):
        if not base_url:
            raise AgentError("No endpoint: pass --base-url or set DMBENCH_BASE_URL")
        self.model = model
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.api_key = api_key
        self.system_template = system_template
        self.channel_rules = channel_rules
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    def reply(self, scenario: Dict[str, Any]) -> Dict[str, Any]:
        system = render_system_prompt(self.system_template, scenario, self.channel_rules)
        payload = {
            "model": self.model,
            "messages": build_messages(system, scenario),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        data = post_json(self.url, payload, headers, self.timeout)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise AgentError(f"unexpected response shape: {json.dumps(data)[:300]}")
        return {"reply": content or "", "usage": data.get("usage")}


def http_agent_payload(scenario: Dict[str, Any]) -> Dict[str, Any]:
    """The JSON body sent to a user's own agent (see README, 'Test your own agent').

    The expected language, category and expectations are deliberately not sent.
    """
    return {
        "benchmark": "dm-bench",
        "version": __version__,
        "scenario_id": scenario["id"],
        "channel": scenario["channel"],
        "business": {
            "name": scenario["business"]["name"],
            "type": scenario["business"]["type"],
            "knowledge_base": scenario["business"]["knowledge_base"],
        },
        "context": scenario.get("context", {}),
        "history": scenario["history"],
        "message": scenario["message"],
        "protocol": {"handoff_marker": HANDOFF_MARKER},
    }


class HttpAgent:
    """POSTs each scenario to the user's own agent endpoint."""

    kind = "http"

    def __init__(self, url: str, token: Optional[str] = None, timeout: float = 90.0):
        self.url = url
        self.token = token
        self.timeout = timeout
        self.model = f"http-agent:{url}"

    def reply(self, scenario: Dict[str, Any]) -> Dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        data = post_json(self.url, http_agent_payload(scenario), headers, self.timeout)
        if not isinstance(data, dict) or not isinstance(data.get("reply"), str):
            raise AgentError("agent response must be a JSON object with a string 'reply'")
        text = data["reply"]
        if data.get("handoff") is True and HANDOFF_MARKER not in text.upper():
            text = text.rstrip() + "\n" + HANDOFF_MARKER
        return {"reply": text}


GENERIC_BAD = (
    "Sure!! Great question. Here is everything:\n\n"
    "| Item | Price |\n|---|---|\n| Basic | $19 |\n| Premium | $99 |\n\n"
    "Everything is in stock and ships today. Buy now, this offer ends in one hour! "
    "I'll message you again next week with more deals."
)


class MockAgent:
    """Offline agents: 'mock:reference' and 'mock:bad' read hand-written replies."""

    kind = "mock"

    def __init__(self, name: str, home: Path):
        self.model = name
        variant = name.split(":", 1)[1] if ":" in name else ""
        files = {"reference": "reference_answers.json", "bad": "bad_answers.json"}
        if variant not in files:
            raise AgentError(f"unknown mock '{name}': use mock:reference or mock:bad")
        self.variant = variant
        path = home / "tests" / files[variant]
        with open(path, encoding="utf-8") as fh:
            self.answers: Dict[str, str] = json.load(fh)

    def reply(self, scenario: Dict[str, Any]) -> Dict[str, Any]:
        if scenario["id"] in self.answers:
            return {"reply": self.answers[scenario["id"]]}
        if self.variant == "bad":
            return {"reply": GENERIC_BAD}
        raise AgentError(f"no reference answer for {scenario['id']}")


def make_agent(model: Optional[str], home: Path, base_url: Optional[str] = None, api_key: Optional[str] = None,
               system_template: Optional[str] = None, http_agent: Optional[str] = None,
               temperature: float = 0.0, max_tokens: int = 600, timeout: float = 90.0):
    if http_agent:
        return HttpAgent(http_agent, token=os.environ.get("DMBENCH_AGENT_TOKEN"), timeout=timeout)
    if not model:
        raise AgentError("pass --model (or --http-agent URL)")
    if model.startswith("mock:"):
        return MockAgent(model, home)
    if system_template is None:
        system_template = (home / "prompts" / "agent_system.txt").read_text(encoding="utf-8")
    return ChatCompletionsAgent(
        model=model,
        base_url=base_url or os.environ.get("DMBENCH_BASE_URL", ""),
        api_key=api_key or os.environ.get("DMBENCH_API_KEY"),
        system_template=system_template,
        channel_rules=load_channel_rules(home),
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )
