# Results

`dm-bench run` writes two files here per run:

- `<run>.jsonl`: one `meta` line, then one `result` line per scenario (reply, every check with its outcome, optional judge scores).
- `<run>.md`: the report, regenerated at any time with `dm-bench report results/<run>.jsonl`.

Local runs are ignored by git. To publish a run, add both files with `git add -f` and open a pull request. Please include the exact model or agent name, the endpoint type (hosted, local server, own agent), the dm-bench version and whether you used the default system prompt.
