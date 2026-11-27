# Baseline Comparison — run: bench-20261127b

| Method                 | Acc@1              | Acc@3              | MRR                | FT Acc             | Grounding          | Latency(s)         | Tokens             |
|------------------------|--------------------|--------------------|--------------------|--------------------|--------------------|--------------------|--------------------|
| Random                 | 0.000              | 0.000              | 0.000              | 0.286              | 0.000              | 0.0s               | 0                  |
| Z-score error_rate     | 0.000              | 0.143              | 0.071              | 0.286              | 0.000              | 0.0s               | 0                  |
| Composite Z-score      | 0.286              | 0.500              | 0.393              | 0.500              | 0.000              | 0.0s               | 0                  |
| **SRE-Copilot**        | 0.357              | 0.476              | 0.417              | 0.381              | 0.965              | 54.8s              | 85,770             |

## Notes
- Model: nvidia/nemotron-3.5-lightning-30b-a3b (3 runs/snapshot)
- Seed: 42
- Grounding score: fraction of evidence items verified against tool_calls_log
- Random baseline grounding_score=0.0 by design (no evidence items)
- Agent rows average every repeated run; see results/benchmark.md for variance
- Reproduce: `python -m eval.compare --run-id bench-20261127b`
