"""Run scenarios against an agent and write results JSONL."""

import datetime as _dt
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from . import __version__
from .checks import has_handoff, run_checks


def make_run_id(model: str) -> str:
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", model).strip("-")[:60] or "run"
    return f"{stamp}_{slug}"


def evaluate(scenario: Dict[str, Any], agent: Any, judge: Any = None) -> Dict[str, Any]:
    """Get one reply and score it. Never raises: errors become a failed record."""
    rec: Dict[str, Any] = {
        "type": "result",
        "scenario_id": scenario["id"],
        "channel": scenario["channel"],
        "language": scenario["language"],
        "category": scenario["category"],
    }
    t0 = time.monotonic()
    try:
        out = agent.reply(scenario)
        reply = out.get("reply", "")
        rec["error"] = None
        if out.get("usage"):
            rec["usage"] = out["usage"]
    except Exception as exc:  # network errors, bad responses, missing mocks
        reply = ""
        rec["error"] = str(exc)
    rec["latency_ms"] = int((time.monotonic() - t0) * 1000)
    rec["reply"] = reply
    rec["handoff"] = has_handoff(reply)
    checks = run_checks(reply, scenario)
    if rec["error"]:
        checks.insert(0, {"check": "error", "passed": False, "detail": rec["error"][:300]})
    rec["checks"] = checks
    rec["passed"] = all(c["passed"] for c in checks)
    if judge is not None and not rec["error"]:
        try:
            rec["judge"] = judge.grade(scenario, reply, checks)
        except Exception as exc:
            rec["judge"] = {"error": str(exc)[:300]}
    return rec


def run(scenarios: List[Dict[str, Any]], agent: Any, out_path: Path, judge: Any = None, concurrency: int = 4,
        meta_extra: Optional[Dict[str, Any]] = None,
        progress: Optional[Callable[[int, int, Dict[str, Any]], None]] = None) -> List[Dict[str, Any]]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "type": "meta",
        "benchmark": "dm-bench",
        "version": __version__,
        "run_id": out_path.stem,
        "model": getattr(agent, "model", "?"),
        "agent_kind": getattr(agent, "kind", "?"),
        "judge_model": getattr(judge, "model", None) if judge is not None else None,
        "scenario_count": len(scenarios),
        "started_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
    }
    if meta_extra:
        meta.update(meta_extra)
    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = [pool.submit(evaluate, s, agent, judge) for s in scenarios]
        for i, fut in enumerate(futures, 1):
            rec = fut.result()
            results.append(rec)
            if progress:
                progress(i, len(scenarios), rec)
    meta["finished_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(meta, ensure_ascii=False) + "\n")
        for rec in results:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return results


def read_results(path: Path) -> Dict[str, Any]:
    meta: Dict[str, Any] = {}
    results: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("type") == "meta":
                meta = obj
            elif obj.get("type") == "result":
                results.append(obj)
    return {"meta": meta, "results": results}


def filter_scenarios(scenarios: Iterable[Dict[str, Any]], categories: Optional[List[str]] = None,
                     channels: Optional[List[str]] = None, languages: Optional[List[str]] = None,
                     ids: Optional[List[str]] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    out = []
    for s in scenarios:
        if categories and s["category"] not in categories:
            continue
        if channels and s["channel"] not in channels:
            continue
        if languages and s["language"] not in languages:
            continue
        if ids and s["id"] not in ids:
            continue
        out.append(s)
    return out[:limit] if limit else out
