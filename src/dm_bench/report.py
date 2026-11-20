"""Aggregate results and render the markdown report."""

from typing import Any, Dict, List, Optional

from .scenarios import CATEGORIES, CHANNELS, LANGUAGES


def _judged(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    j = rec.get("judge")
    return j if isinstance(j, dict) and "score" in j else None


def group(results: List[Dict[str, Any]], key: str, order: Optional[tuple] = None) -> List[Dict[str, Any]]:
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for r in results:
        buckets.setdefault(r.get(key, "?"), []).append(r)
    names = [n for n in (order or ()) if n in buckets] + sorted(n for n in buckets if n not in (order or ()))
    rows = []
    for name in names:
        rs = buckets[name]
        passed = sum(1 for r in rs if r.get("passed"))
        judged = [_judged(r) for r in rs if _judged(r)]
        rows.append({
            "name": name,
            "n": len(rs),
            "passed": passed,
            "rate": passed / len(rs),
            "judged": len(judged),
            "judge_score": sum(j["score"] for j in judged) / len(judged) if judged else None,
            "judge_pass": sum(1 for j in judged if j["verdict"] == "pass") / len(judged) if judged else None,
        })
    return rows


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Overall deterministic score = mean of per-category pass rates (each category weighs the same)."""
    cats = group(results, "category", CATEGORIES)
    overall = sum(r["rate"] for r in cats) / len(cats) if cats else 0.0
    judged_cats = [r for r in cats if r["judge_score"] is not None]
    judge_overall = sum(r["judge_score"] for r in judged_cats) / len(judged_cats) if judged_cats else None
    check_fail: Dict[str, int] = {}
    for r in results:
        for c in r.get("checks", []):
            if not c["passed"]:
                check_fail[c["check"]] = check_fail.get(c["check"], 0) + 1
    return {
        "n": len(results),
        "passed": sum(1 for r in results if r.get("passed")),
        "errors": sum(1 for r in results if r.get("error")),
        "overall": overall,
        "judge_overall": judge_overall,
        "judged": sum(1 for r in results if _judged(r)),
        "judge_errors": sum(1 for r in results if isinstance(r.get("judge"), dict) and "error" in r["judge"]),
        "categories": cats,
        "channels": group(results, "channel", CHANNELS),
        "languages": group(results, "language", LANGUAGES),
        "check_failures": dict(sorted(check_fail.items(), key=lambda kv: -kv[1])),
    }


def _pct(x: Optional[float]) -> str:
    return "-" if x is None else f"{100 * x:.1f}%"


def _table(title: str, rows: List[Dict[str, Any]], with_judge: bool) -> List[str]:
    head = f"| {title} | Scenarios | Passed | Deterministic |"
    sep = "|---|---:|---:|---:|"
    if with_judge:
        head += " Judge score | Judge pass |"
        sep += "---:|---:|"
    out = [head, sep]
    for r in rows:
        line = f"| {r['name']} | {r['n']} | {r['passed']} | {_pct(r['rate'])} |"
        if with_judge:
            line += f" {_pct(r['judge_score'])} | {_pct(r['judge_pass'])} |"
        out.append(line)
    return out


def render_markdown(meta: Dict[str, Any], results: List[Dict[str, Any]], max_failures: int = 200) -> str:
    s = summarize(results)
    with_judge = s["judged"] > 0
    lines = [
        f"# dm-bench report: {meta.get('model', '?')}",
        "",
        f"- Run: `{meta.get('run_id', '?')}`",
        f"- Agent: `{meta.get('model', '?')}` ({meta.get('agent_kind', '?')})",
        f"- Benchmark version: {meta.get('version', '?')}",
        f"- Started: {meta.get('started_at', '?')}",
        f"- Scenarios: {s['n']} (errors: {s['errors']})",
        "",
        f"**Overall deterministic score: {_pct(s['overall'])}** "
        "(mean of per-category pass rates, every category weighs the same).",
        "",
        f"Scenarios passing every check: {s['passed']}/{s['n']}.",
    ]
    if with_judge:
        lines += [
            "",
            f"**Judged score: {_pct(s['judge_overall'])}** (judge `{meta.get('judge_model')}`, "
            f"{s['judged']} judged, {s['judge_errors']} judge errors). Reported separately; "
            "it does not change the deterministic score.",
        ]
    lines += ["", "## By category", ""] + _table("Category", s["categories"], with_judge)
    lines += ["", "## By channel", ""] + _table("Channel", s["channels"], with_judge)
    lines += ["", "## By language", ""] + _table("Language", s["languages"], with_judge)
    lines += ["", "## Failed checks", ""]
    if s["check_failures"]:
        lines += ["| Check | Failures |", "|---|---:|"]
        lines += [f"| {k} | {v} |" for k, v in s["check_failures"].items()]
    else:
        lines.append("No check failed.")
    failed = [r for r in results if not r.get("passed")]
    if failed:
        lines += ["", "## Failed scenarios", "", "| Scenario | Category | Channel | Lang | Failed checks |", "|---|---|---|---|---|"]
        for r in sorted(failed, key=lambda r: (r["category"], r["scenario_id"]))[:max_failures]:
            fails = "; ".join(
                f"{c['check']}" + (f" ({c['detail']})" if c.get("detail") else "")
                for c in r.get("checks", []) if not c["passed"]
            ).replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {r['scenario_id']} | {r['category']} | {r['channel']} | {r['language']} | {fails} |")
        if len(failed) > max_failures:
            lines.append(f"| ... | | | | {len(failed) - max_failures} more |")
    lines.append("")
    return "\n".join(lines)
