# Benchmark results

Top-k is the fraction of true causes covered within the first k predictions. Strict accuracy requires both service and fault type. Grounding is matched citations divided by citations made; no citations is n/a. Latency excludes rate limit waits; cached responses retain the original request duration.

[RCAEval](https://github.com/phamquiluan/RCAEval) BARO and N-Sigma use the maximum incident value after median/IQR or mean/standard-deviation scaling. The table projects ranked metrics to unique services and maps the top signal for each service to a fault type. This is a metrics-only comparison.

## Baseline (verify-round2-baseline)

14 Astronomy Shop snapshots (development); 3 runs per method; nvidia/nemotron-3.5-lightning-30b-a3b; x86_64, 8 vCPU, Linux, no GPU.

| Method | Runs | Top-1 | Top-3 | Service top-1 | Service top-3 | Grounding | Citations | Tokens/run | Seconds/run | USD/run |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| RCAEval N-Sigma (metrics) | 42/42 | 35.7% | 50.0% | 42.9% | 64.3% | n/a | 0 | 0 | 0.006 | 0.0000 |
| Composite z-score | 42/42 | 28.6% | 50.0% | 42.9% | 92.9% | n/a | 0 | 0 | 0.004 | 0.0000 |
| RCAEval BARO (metrics) | 42/42 | 28.6% | 42.9% | 42.9% | 57.1% | n/a | 0 | 0 | 0.008 | 0.0000 |
| Error-rate z-score | 42/42 | 0.0% | 14.3% | 14.3% | 50.0% | n/a | 0 | 0 | 0.001 | 0.0000 |
| Random | 42/42 | 4.8% | 4.8% | 9.5% | 23.8% | n/a | 0 | 0 | 0.000 | 0.0000 |
