"""The whole pipeline, offline, through the CLI: reference answers must score
(close to) 100%, deliberately bad answers must score low."""

import json

from dm_bench.checks import run_checks
from dm_bench.cli import main
from dm_bench.runner import read_results


def test_every_scenario_has_reference_and_bad_answer(scenarios, reference_answers, bad_answers):
    ids = {s["id"] for s in scenarios}
    assert ids == set(reference_answers), sorted(ids ^ set(reference_answers))
    assert ids == set(bad_answers), sorted(ids ^ set(bad_answers))


def test_reference_answers_pass_every_check(scenarios, reference_answers):
    failures = {}
    for s in scenarios:
        bad = [c for c in run_checks(reference_answers[s["id"]], s) if not c["passed"]]
        if bad:
            failures[s["id"]] = bad
    assert failures == {}


def test_bad_answers_fail_at_least_one_check(scenarios, bad_answers):
    passing = [s["id"] for s in scenarios if all(c["passed"] for c in run_checks(bad_answers[s["id"]], s))]
    assert passing == []


def test_validate_command(home, capsys):
    assert main(["--home", str(home), "validate", "--strict"]) == 0
    assert "OK" in capsys.readouterr().out


def _run(home, tmp_path, model, *extra):
    code = main(["--home", str(home), "run", "--model", model, "--out-dir", str(tmp_path),
                 "--run-name", model.replace(":", "-"), "--quiet", *extra])
    assert code == 0
    path = tmp_path / (model.replace(":", "-") + ".jsonl")
    return read_results(path), path


def test_cli_mock_reference_scores_100(home, tmp_path, scenarios):
    data, path = _run(home, tmp_path, "mock:reference", "--concurrency", "8")
    assert data["meta"]["model"] == "mock:reference"
    assert len(data["results"]) == len(scenarios)
    assert all(r["passed"] for r in data["results"])
    md = path.with_suffix(".md").read_text(encoding="utf-8")
    assert "Overall deterministic score: 100.0%" in md


def test_cli_mock_bad_scores_low(home, tmp_path):
    data, path = _run(home, tmp_path, "mock:bad")
    passed = sum(r["passed"] for r in data["results"])
    assert passed / len(data["results"]) < 0.2
    md = path.with_suffix(".md").read_text(encoding="utf-8")
    assert "## Failed scenarios" in md


def test_cli_filters_and_mock_judge(home, tmp_path):
    data, path = _run(home, tmp_path, "mock:reference", "--categories", "handoff,privacy", "--judge",
                      "--judge-model", "mock:judge")
    cats = {r["category"] for r in data["results"]}
    assert cats == {"handoff", "privacy"}
    assert all(r["judge"]["verdict"] == "pass" for r in data["results"])
    assert data["meta"]["judge_model"] == "mock:judge"
    assert "Judged score: 100.0%" in path.with_suffix(".md").read_text(encoding="utf-8")


def test_results_jsonl_shape(home, tmp_path):
    data, path = _run(home, tmp_path, "mock:reference", "--limit", "3")
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["type"] == "meta" and len(lines) == 4
    r = data["results"][0]
    for key in ("scenario_id", "category", "channel", "language", "reply", "handoff", "checks", "passed", "latency_ms"):
        assert key in r


def test_fail_under_exit_code(home, tmp_path):
    code = main(["--home", str(home), "run", "--model", "mock:bad", "--out-dir", str(tmp_path), "--quiet",
                 "--fail-under", "50"])
    assert code == 3


def test_unreachable_endpoint_is_recorded_not_raised(home, tmp_path, monkeypatch):
    monkeypatch.setattr("dm_bench.agents.time.sleep", lambda s: None)
    code = main(["--home", str(home), "run", "--model", "some-model", "--base-url", "http://127.0.0.1:9/v1",
                 "--limit", "1", "--timeout", "2", "--out-dir", str(tmp_path), "--run-name", "down", "--quiet"])
    assert code == 0
    r = read_results(tmp_path / "down.jsonl")["results"][0]
    assert r["error"] and not r["passed"] and r["checks"][0]["check"] == "error"
