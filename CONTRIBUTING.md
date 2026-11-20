# Contributing

Thanks for helping make dm-bench better. The most valuable contributions are new scenarios, especially in languages and channels with few of them, and fixes to checks that reject good replies or accept bad ones.

## Setup

```bash
git clone https://github.com/Pinlyx/dm-bench
cd dm-bench
python -m pip install -e ".[test]"
python -m pytest -q
```

## Adding a scenario

1. Pick the file for its category in `scenarios/` (for example `scenarios/handoff.json`) and append an object. The full field list is in the README under "Scenario format".
2. Keep the business fictional and the knowledge base short (4 to 10 lines). Use example domains (`example.com`) and obviously fake phone numbers.
3. Write non-English scenarios the way a native speaker types a DM. If you are not a native speaker of the language, ask for a review in the pull request.
4. Expectations:
   - `must_include_any` / `must_include_all` should be lenient. Any good reply from a strong agent, phrased in its own words, must pass. Use alternations and word stems, not exact sentences.
   - `must_not_include` should be targeted: invented values, leaked data, forbidden promises, pressure phrases. It must never match a good reply.
   - Use `"handoff": true` only when a human really must take over.
5. Add a reference reply to `tests/reference_answers.json` (a good reply that passes every check) and a realistic bad reply to `tests/bad_answers.json` (the typical failure the scenario targets; it must fail at least one check).
6. Run:

```bash
dm-bench validate --strict
python -m pytest -q
```

## Changing checks or the system prompt

`prompts/agent_system.txt`, `prompts/channel_rules.json` and the checks define what scores mean. Changing them makes old results incomparable, so explain the reason in the pull request; such changes bump the minor version.

## Publishing results

See `results/README.md`. Never include API keys or private customer data in a result file.
