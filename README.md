# ARC Prize 2026 — ARC-AGI-3 "Prometheus" agent

Open-source release of the two sibling projects behind our ARC Prize 2026 submission
(ARC-AGI-3 track), published under MIT-0 as the competition rules require.

## Layout

- `arc-agi3-kaggle-agent/` — the Kaggle submission. An offline agent (Python stdlib only at
  inference time: no network, no LLM calls). `submission/build_agent.py` bundles the
  `arc_agent/` core into the single-file `agent/my_agent.py` that the notebook ships.
- `arc-agi-runner/` — the TypeScript research runner: the canonical world-model DSL engine
  and its test corpus. The Python side is a hand-written port; the parity fixture
  `arc-agi-runner/src/worldModel/__fixtures__/dslParity.json` keeps both sides honest
  (`arc-agi3-kaggle-agent/tests/test_dsl_parity.py` resolves it through this sibling layout).

## Reproducing

```
cd arc-agi3-kaggle-agent
python3 -m pytest -q   # unit suite, no network needed
make setup             # Python 3.12 venv + competition dataset (needs your Kaggle token)
make notebook          # rebuilds notebooks/submission.ipynb from agent/my_agent.py
```

This repository is a generated mirror: history starts fresh on every publication.

## License

MIT No Attribution (MIT-0) — see [LICENSE](LICENSE).
