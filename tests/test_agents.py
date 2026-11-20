import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from conftest import make_scenario

from dm_bench.agents import (
    AgentError, ChatCompletionsAgent, HttpAgent, MockAgent, build_messages, http_agent_payload,
    load_channel_rules, make_agent, render_system_prompt,
)
from dm_bench.judge import make_judge, parse_verdict
from dm_bench.scenarios import CHANNELS


@pytest.fixture()
def local_server():
    """A loopback HTTP server; tests never touch the real network."""
    state = {"requests": [], "response": {}, "status": 200}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            state["requests"].append({"path": self.path, "headers": dict(self.headers), "body": json.loads(body)})
            data = json.dumps(state["response"]).encode()
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["url"] = f"http://127.0.0.1:{server.server_address[1]}"
    yield state
    server.shutdown()
    server.server_close()


def test_system_prompt_template_is_fully_rendered(home, scenarios):
    template = (home / "prompts" / "agent_system.txt").read_text(encoding="utf-8")
    rules = load_channel_rules(home)
    for s in scenarios:
        out = render_system_prompt(template, s, rules)
        assert "{{" not in out and "}}" not in out
        assert s["business"]["name"] in out
        assert "[HANDOFF]" in out


def test_channel_rules_cover_every_channel(home):
    assert set(load_channel_rules(home)) == set(CHANNELS)


def test_build_messages_maps_roles():
    s = make_scenario(history=[{"role": "customer", "text": "hi"}, {"role": "agent", "text": "hello"}])
    msgs = build_messages("SYS", s)
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
    assert msgs[-1]["content"] == s["message"]


def test_http_payload_hides_expectations():
    payload = http_agent_payload(make_scenario(context={"hours_since_last_customer_message": 30}))
    assert "expect" not in payload and "language" not in payload and "category" not in payload
    assert "judge_notes" not in payload
    assert payload["protocol"]["handoff_marker"] == "[HANDOFF]"
    assert payload["context"]["hours_since_last_customer_message"] == 30


def test_chat_completions_agent(local_server, home):
    local_server["response"] = {"choices": [{"message": {"content": "We open at 8:00."}}], "usage": {"total_tokens": 5}}
    agent = ChatCompletionsAgent("test-model", local_server["url"] + "/v1/", "secret", "Hi {{business_name}}",
                                 load_channel_rules(home))
    out = agent.reply(make_scenario())
    assert out["reply"] == "We open at 8:00."
    req = local_server["requests"][0]
    assert req["path"] == "/v1/chat/completions"
    assert req["headers"]["Authorization"] == "Bearer secret"
    assert req["body"]["model"] == "test-model"
    assert req["body"]["temperature"] == 0.0
    assert req["body"]["messages"][0]["content"] == "Hi Test Cafe"


def test_chat_agent_bad_shape_raises(local_server, home):
    local_server["response"] = {"nope": True}
    agent = ChatCompletionsAgent("m", local_server["url"], None, "x", load_channel_rules(home))
    with pytest.raises(AgentError):
        agent.reply(make_scenario())


def test_http_agent_contract(local_server):
    local_server["response"] = {"reply": "Someone from the team will take over.", "handoff": True}
    out = HttpAgent(local_server["url"] + "/dm").reply(make_scenario())
    assert out["reply"].endswith("[HANDOFF]")
    body = local_server["requests"][0]["body"]
    assert body["benchmark"] == "dm-bench" and body["message"] == "When do you open?"


def test_http_agent_error_status_is_not_retried(local_server):
    local_server["status"] = 400
    local_server["response"] = {"error": "bad"}
    with pytest.raises(AgentError, match="HTTP 400"):
        HttpAgent(local_server["url"]).reply(make_scenario())
    assert len(local_server["requests"]) == 1


def test_make_agent(home, monkeypatch):
    monkeypatch.delenv("DMBENCH_BASE_URL", raising=False)
    with pytest.raises(AgentError):
        make_agent("some-model", home)
    with pytest.raises(AgentError):
        make_agent("mock:unknown", home)
    assert isinstance(make_agent("mock:reference", home), MockAgent)
    monkeypatch.setenv("DMBENCH_BASE_URL", "http://127.0.0.1:9/v1")
    agent = make_agent("some-model", home)
    assert agent.url == "http://127.0.0.1:9/v1/chat/completions"


def test_parse_verdict():
    v = parse_verdict('```json\n{"grounding": 5, "helpfulness": 4, "tone": 4, "policy": 5, "verdict": "pass", "reason": "ok"}\n```')
    assert v["verdict"] == "pass" and v["score"] == pytest.approx(0.9)
    with pytest.raises(AgentError):
        parse_verdict('{"grounding": 9, "helpfulness": 4, "tone": 4, "policy": 5, "verdict": "pass"}')
    with pytest.raises(AgentError):
        parse_verdict('{"grounding": 5, "helpfulness": 4, "tone": 4, "policy": 5, "verdict": "maybe"}')
    with pytest.raises(AgentError):
        parse_verdict("no json here")


def test_judge_over_http(local_server, home):
    content = json.dumps({"grounding": 4, "helpfulness": 4, "tone": 5, "policy": 5, "verdict": "pass", "reason": "fine"})
    local_server["response"] = {"choices": [{"message": {"content": content}}]}
    judge = make_judge("judge-model", home, base_url=local_server["url"])
    v = judge.grade(make_scenario(), "We open at 8:00.", [])
    assert v["verdict"] == "pass"
    prompt = local_server["requests"][0]["body"]["messages"][0]["content"]
    assert "We open at 8:00." in prompt and "{{" not in prompt and "Gives the opening hours." in prompt
