"""dm-bench command line: run, report, validate, list."""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .agents import AgentError, make_agent
from .judge import make_judge
from .report import render_markdown, summarize
from .runner import filter_scenarios, make_run_id, read_results, run
from .scenarios import CATEGORIES, CHANNELS, LANGUAGES, coverage, find_home, load_scenarios, validate_all


def _csv(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


def _scenario_dir(args, home: Path) -> Path:
    return Path(args.scenarios) if getattr(args, "scenarios", None) else home / "scenarios"


def cmd_validate(args) -> int:
    home = find_home(args.home)
    sdir = _scenario_dir(args, home)
    try:
        scenarios = load_scenarios(sdir)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    errors, warnings = validate_all(scenarios)
    for e in errors:
        print(f"error: {e}")
    for w in warnings:
        print(f"warning: {w}")
    cov = coverage(scenarios)
    print(f"{len(scenarios)} scenarios in {sdir.name}/")
    for dim, order in (("category", CATEGORIES), ("channel", CHANNELS), ("language", LANGUAGES)):
        counts = cov[dim]
        print(f"  {dim}: " + ", ".join(f"{k}={counts.get(k, 0)}" for k in order))
    if errors:
        print(f"FAILED: {len(errors)} error(s)")
        return 1
    if warnings and args.strict:
        print("FAILED: warnings are errors with --strict")
        return 1
    print("OK")
    return 0


def cmd_run(args) -> int:
    home = find_home(args.home)
    scenarios = load_scenarios(_scenario_dir(args, home))
    errors, _ = validate_all(scenarios)
    if errors:
        print("Scenario files are invalid; run `dm-bench validate`.", file=sys.stderr)
        return 1
    scenarios = filter_scenarios(
        scenarios,
        categories=_csv(args.categories),
        channels=_csv(args.channels),
        languages=_csv(args.languages),
        ids=_csv(args.ids),
        limit=args.limit,
    )
    if not scenarios:
        print("No scenarios match the filters.", file=sys.stderr)
        return 1
    template = None
    if args.system_prompt:
        template = Path(args.system_prompt).read_text(encoding="utf-8")
    try:
        agent = make_agent(
            args.model, home, base_url=args.base_url, system_template=template, http_agent=args.http_agent,
            temperature=args.temperature, max_tokens=args.max_tokens, timeout=args.timeout,
        )
        judge = make_judge(args.judge_model, home, base_url=args.judge_base_url, timeout=args.timeout) if args.judge else None
    except AgentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    model_label = getattr(agent, "model", "run")
    run_id = args.run_name or make_run_id(model_label if not args.http_agent else "http-agent")
    out_dir = Path(args.out_dir) if args.out_dir else Path.cwd() / "results"
    out_path = out_dir / f"{run_id}.jsonl"
    extra = {
        "system_prompt": "custom" if args.system_prompt else ("n/a" if args.http_agent or str(args.model).startswith("mock:") else "prompts/agent_system.txt"),
        "temperature": args.temperature,
        "filters": {k: v for k, v in {"categories": args.categories, "channels": args.channels,
                                      "languages": args.languages, "ids": args.ids, "limit": args.limit}.items() if v},
    }

    def progress(i, n, rec):
        if not args.quiet:
            mark = "PASS" if rec["passed"] else ("ERR " if rec.get("error") else "FAIL")
            print(f"[{i:>3}/{n}] {mark} {rec['scenario_id']}", file=sys.stderr)

    results = run(scenarios, agent, out_path, judge=judge, concurrency=args.concurrency, meta_extra=extra, progress=progress)
    data = read_results(out_path)
    md_path = out_path.with_suffix(".md")
    md_path.write_text(render_markdown(data["meta"], data["results"]), encoding="utf-8")
    s = summarize(results)
    print(f"Overall deterministic score: {100 * s['overall']:.1f}% ({s['passed']}/{s['n']} scenarios pass every check)")
    if s["judge_overall"] is not None:
        print(f"Judged score: {100 * s['judge_overall']:.1f}%")
    print(f"Results: {out_path}")
    print(f"Report:  {md_path}")
    if args.fail_under is not None and 100 * s["overall"] < args.fail_under:
        return 3
    return 0


def cmd_report(args) -> int:
    path = Path(args.results)
    data = read_results(path)
    if not data["results"]:
        print(f"error: no results in {path}", file=sys.stderr)
        return 1
    md = render_markdown(data["meta"], data["results"])
    out = Path(args.output) if args.output else path.with_suffix(".md")
    out.write_text(md, encoding="utf-8")
    s = summarize(data["results"])
    print(f"Overall deterministic score: {100 * s['overall']:.1f}%")
    print(f"Report: {out}")
    return 0


def cmd_list(args) -> int:
    home = find_home(args.home)
    scenarios = filter_scenarios(load_scenarios(_scenario_dir(args, home)), categories=_csv(args.categories))
    for s in scenarios:
        print(f"{s['id']:<44} {s['category']:<18} {s['channel']:<10} {s['language']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dm-bench", description="Benchmark AI agents that answer customer direct messages.")
    p.add_argument("--version", action="version", version=f"dm-bench {__version__}")
    p.add_argument("--home", help="benchmark data folder (default: DMBENCH_HOME, the current folder, or the source checkout)")
    sub = p.add_subparsers(dest="command")

    r = sub.add_parser("run", help="run the benchmark against a model endpoint, your own agent, or a mock")
    r.add_argument("--model", help="model name sent to the endpoint, or mock:reference / mock:bad")
    r.add_argument("--base-url", help="OpenAI-compatible base URL, e.g. http://localhost:8000/v1 (default: DMBENCH_BASE_URL)")
    r.add_argument("--http-agent", metavar="URL", help="POST each scenario to your own agent instead of a model endpoint")
    r.add_argument("--system-prompt", metavar="FILE", help="override prompts/agent_system.txt (results are then not comparable)")
    r.add_argument("--concurrency", type=int, default=4)
    r.add_argument("--categories", help=f"comma list from: {', '.join(CATEGORIES)}")
    r.add_argument("--channels", help=f"comma list from: {', '.join(CHANNELS)}")
    r.add_argument("--languages", help=f"comma list from: {', '.join(LANGUAGES)}")
    r.add_argument("--ids", help="comma list of scenario ids")
    r.add_argument("--limit", type=int, help="run only the first N matching scenarios")
    r.add_argument("--temperature", type=float, default=0.0)
    r.add_argument("--max-tokens", type=int, default=600)
    r.add_argument("--timeout", type=float, default=90.0, help="seconds per request")
    r.add_argument("--judge", action="store_true", help="also grade replies with an LLM judge (reported separately)")
    r.add_argument("--judge-model", help="judge model (default: DMBENCH_JUDGE_MODEL)")
    r.add_argument("--judge-base-url", help="judge base URL (default: DMBENCH_JUDGE_BASE_URL)")
    r.add_argument("--run-name", help="file name for the run (default: timestamp_model)")
    r.add_argument("--out-dir", help="where to write results (default: ./results)")
    r.add_argument("--scenarios", help="scenario folder (default: <home>/scenarios)")
    r.add_argument("--fail-under", type=float, help="exit with code 3 if the overall score (percent) is below this")
    r.add_argument("--quiet", action="store_true")
    r.set_defaults(func=cmd_run)

    rp = sub.add_parser("report", help="regenerate the markdown report from a results .jsonl")
    rp.add_argument("results")
    rp.add_argument("-o", "--output", help="output .md path (default: next to the .jsonl)")
    rp.set_defaults(func=cmd_report)

    v = sub.add_parser("validate", help="check scenario files against the schema")
    v.add_argument("--scenarios", help="scenario folder (default: <home>/scenarios)")
    v.add_argument("--strict", action="store_true", help="treat coverage warnings as errors")
    v.set_defaults(func=cmd_validate)

    ls = sub.add_parser("list", help="list scenarios")
    ls.add_argument("--categories")
    ls.add_argument("--scenarios")
    ls.set_defaults(func=cmd_list)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
