# Benchmark results

Top-k is the fraction of true causes covered within the first k predictions. Strict accuracy requires both service and fault type. Grounding is matched citations divided by citations made; no citations is n/a. Latency excludes rate limit waits; cached responses retain the original request duration.

[RCAEval](https://github.com/phamquiluan/RCAEval) BARO and N-Sigma use the maximum incident value after median/IQR or mean/standard-deviation scaling. The table projects ranked metrics to unique services and maps the top signal for each service to a fault type. This is a metrics-only comparison.

## Baseline (verify-round2-baseline)

14 Astronomy Shop snapshots (development); 3 runs per method; nvidia/nemotron-3.5-lightning-30b-a3b; x86_64, 8 vCPU, Linux, no GPU.

| Method | Runs | Top-1 | Top-3 | Service top-1 | Service top-3 | Grounding | Citations | Calls/run | Tokens/run | Seconds/run | USD/run |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| RCAEval N-Sigma (metrics) | 42/42 | 35.7% | 50.0% | 42.9% | 64.3% | n/a | 0 | n/a | 0 | 0.006 | 0.0000 |
| Composite z-score | 42/42 | 28.6% | 50.0% | 42.9% | 92.9% | n/a | 0 | n/a | 0 | 0.004 | 0.0000 |
| RCAEval BARO (metrics) | 42/42 | 28.6% | 42.9% | 42.9% | 57.1% | n/a | 0 | n/a | 0 | 0.008 | 0.0000 |
| Error-rate z-score | 42/42 | 0.0% | 14.3% | 14.3% | 50.0% | n/a | 0 | n/a | 0 | 0.001 | 0.0000 |
| Random | 42/42 | 4.8% | 4.8% | 9.5% | 23.8% | n/a | 0 | n/a | 0 | 0.000 | 0.0000 |

## Iteration 0: rescore the recorded round-1 run (round2-iteration-0)

14 Astronomy Shop snapshots (development); 3 runs per method; nvidia/nemotron-3.5-lightning-30b-a3b; x86_64 8 vCPU, Linux, no GPU.

| Method | Runs | Top-1 | Top-3 | Service top-1 | Service top-3 | Grounding | Citations | Calls/run | Tokens/run | Seconds/run | USD/run |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| SRE-Copilot (recorded: bench-20261127b) | 42/42 | 35.7% | 47.6% | 61.9% | 85.7% | 96.8% | 190 | 11.3 | 85,770 | 54.807 | 0.0000 |
| RCAEval N-Sigma (metrics) | 42/42 | 35.7% | 50.0% | 42.9% | 64.3% | n/a | 0 | n/a | 0 | 0.005 | 0.0000 |
| Composite z-score | 42/42 | 28.6% | 50.0% | 42.9% | 92.9% | n/a | 0 | n/a | 0 | 0.004 | 0.0000 |
| RCAEval BARO (metrics) | 42/42 | 28.6% | 42.9% | 42.9% | 57.1% | n/a | 0 | n/a | 0 | 0.008 | 0.0000 |
| Error-rate z-score | 42/42 | 0.0% | 14.3% | 14.3% | 50.0% | n/a | 0 | n/a | 0 | 0.001 | 0.0000 |
| Random | 42/42 | 4.8% | 4.8% | 9.5% | 23.8% | n/a | 0 | n/a | 0 | 0.000 | 0.0000 |

## Iteration 1: seed compact telemetry and cap model rounds (stopped early) (round2-iteration-1)

14 Astronomy Shop snapshots (development); 3 runs per method; nvidia/nemotron-3.5-lightning-30b-a3b; x86_64, 8 vCPU, Linux, no GPU.

| Method | Runs | Top-1 | Top-3 | Service top-1 | Service top-3 | Grounding | Citations | Calls/run | Tokens/run | Seconds/run | USD/run |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| SRE-Copilot | 2/42 | 0.0% | 0.0% | 50.0% | 50.0% | 100.0% | 5 | 2.5 | 22,101 | 112.442 | 0.0000 |
| ReAct without grounding verifier in the agent | 2/42 | 0.0% | 0.0% | 0.0% | 0.0% | 100.0% | 2 | 3.0 | 12,791 | 26.636 | 0.0000 |
| SRE-Copilot without anomaly prior | 1/42 | 0.0% | 0.0% | 0.0% | 0.0% | 100.0% | 3 | 3.0 | 11,613 | 36.730 | 0.0000 |

## Iteration 2: limit Nemotron reasoning and rank initiating faults (round2-iteration-2)

14 Astronomy Shop snapshots (development); 3 runs per method; nvidia/nemotron-3.5-lightning-30b-a3b; x86_64, 8 vCPU, Linux, no GPU.

| Method | Runs | Top-1 | Top-3 | Service top-1 | Service top-3 | Grounding | Citations | Calls/run | Tokens/run | Seconds/run | USD/run |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| SRE-Copilot | 1/42 | 0.0% | 0.0% | 0.0% | 100.0% | 100.0% | 4 | 3.0 | 11,558 | 5.207 | 0.0000 |
| ReAct without grounding verifier in the agent | 1/42 | 0.0% | 0.0% | 0.0% | 0.0% | 100.0% | 1 | 3.0 | 10,928 | 33.421 | 0.0000 |
| SRE-Copilot without anomaly prior | 1/42 | 0.0% | 0.0% | 0.0% | 0.0% | 66.7% | 6 | 3.0 | 9,215 | 6.388 | 0.0000 |
| HolmesGPT 0.48.0 (1 run per snapshot) | 1/14 | 0.0% | 0.0% | 0.0% | 0.0% | n/a | 0 | 1.0 | 15,857 | 8.152 | 0.0000 |
| RCAEval N-Sigma (metrics) | 1/42 | 100.0% | 100.0% | 100.0% | 100.0% | n/a | 0 | n/a | 0 | 0.006 | 0.0000 |
| Composite z-score | 1/42 | 0.0% | 0.0% | 100.0% | 100.0% | n/a | 0 | n/a | 0 | 0.004 | 0.0000 |
| RCAEval BARO (metrics) | 1/42 | 100.0% | 100.0% | 100.0% | 100.0% | n/a | 0 | n/a | 0 | 0.016 | 0.0000 |
| Error-rate z-score | 1/42 | 0.0% | 0.0% | 0.0% | 100.0% | n/a | 0 | n/a | 0 | 0.001 | 0.0000 |
| Random | 1/42 | 0.0% | 0.0% | 0.0% | 100.0% | n/a | 0 | n/a | 0 | 0.000 | 0.0000 |
