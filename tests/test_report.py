import json

from dm_bench.cli import main
from dm_bench.report import render_markdown, summarize
from dm_bench.runner import read_results


def rec(sid, category, channel="whatsapp", language="en", passed=True, judge=None, checks=None):
    r = {
        "type": "result", "scenario_id": sid, "category": category, "channel": channel, "language": language,
        "passed": passed, "error": None, "reply": "x",
        "checks": checks or [{"check": "must_include_any", "passed": passed, "detail": "" if passed else "none matched"}],
    }
    if judge:
        r["judge"] = judge
    return r


def test_overall_weighs_categories_equally():
    # 3/4 in handoff and 1/1 in privacy -> (0.75 + 1.0) / 2, not 4/5.
    results = [rec("a", "handoff"), rec("b", "handoff"), rec("c", "handoff"), rec("d", "handoff", passed=False),
               rec("e", "privacy")]
    s = summarize(results)
    assert abs(s["overall"] - 0.875) < 1e-9
    assert s["passed"] == 4 and s["n"] == 5
    assert s["check_failures"] == {"must_include_any": 1}


def test_judge_scores_are_separate():
    j = {"grounding": 5, "helpfulness": 5, "tone": 5, "policy": 5, "verdict": "pass", "reason": "", "score": 1.0}
    results = [rec("a", "sales", passed=False, judge=j), rec("b", "sales", judge=dict(j, score=0.5, verdict="fail"))]
    s = summarize(results)
    assert s["overall"] == 0.5
    assert s["judge_overall"] == 0.75
    md = render_markdown({"model": "m", "judge_model": "j"}, results)
    assert "Judged score: 75.0%" in md and "Judge pass" in md


def test_markdown_has_all_tables():
    results = [rec("a", "handoff", "x", "tr"), rec("b", "privacy", "instagram", "en", passed=False)]
    md = render_markdown({"model": "demo", "run_id": "r1"}, results)
    for heading in ("## By category", "## By channel", "## By language", "## Failed checks", "## Failed scenarios"):
        assert heading in md
    assert "| handoff | 1 | 1 | 100.0% |" in md
    assert "| tr | 1 | 1 | 100.0% |" in md
    assert "| b | privacy | instagram | en |" in md
    assert "Judge" not in md


def test_report_command_regenerates(tmp_path):
    path = tmp_path / "run.jsonl"
    lines = [{"type": "meta", "model": "demo", "run_id": "run"}, rec("a", "handoff"), rec("b", "sales", passed=False)]
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    out = tmp_path / "custom.md"
    assert main(["report", str(path), "-o", str(out)]) == 0
    md = out.read_text(encoding="utf-8")
    assert "# dm-bench report: demo" in md and "Overall deterministic score: 50.0%" in md
    data = read_results(path)
    assert data["meta"]["model"] == "demo" and len(data["results"]) == 2
