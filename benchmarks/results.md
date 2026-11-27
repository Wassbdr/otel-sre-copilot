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

## Iteration 2: limit Nemotron reasoning and rank initiating faults (stopped early) (round2-iteration-2)

14 Astronomy Shop snapshots (development); 3 runs per method; nvidia/nemotron-3.5-lightning-30b-a3b; x86_64, 8 vCPU, Linux, no GPU.

| Method | Runs | Top-1 | Top-3 | Service top-1 | Service top-3 | Grounding | Citations | Calls/run | Tokens/run | Seconds/run | USD/run |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| SRE-Copilot | 2/42 | 0.0% | 0.0% | 50.0% | 100.0% | 87.5% | 8 | 3.0 | 11,318 | 9.160 | 0.0000 |
| ReAct without grounding verifier in the agent | 2/42 | 0.0% | 0.0% | 0.0% | 0.0% | 100.0% | 2 | 3.0 | 11,982 | 26.660 | 0.0000 |
| SRE-Copilot without anomaly prior | 1/42 | 0.0% | 0.0% | 0.0% | 0.0% | 66.7% | 6 | 3.0 | 9,215 | 6.388 | 0.0000 |
| HolmesGPT 0.48.0 (1 run per snapshot) | 1/14 | 0.0% | 0.0% | 0.0% | 0.0% | n/a | 0 | 1.0 | 15,857 | 8.152 | 0.0000 |
| RCAEval N-Sigma (metrics) | 2/42 | 100.0% | 100.0% | 100.0% | 100.0% | n/a | 0 | n/a | 0 | 0.006 | 0.0000 |
| Composite z-score | 2/42 | 0.0% | 0.0% | 50.0% | 100.0% | n/a | 0 | n/a | 0 | 0.004 | 0.0000 |
| RCAEval BARO (metrics) | 2/42 | 50.0% | 50.0% | 100.0% | 100.0% | n/a | 0 | n/a | 0 | 0.015 | 0.0000 |
| Error-rate z-score | 2/42 | 0.0% | 0.0% | 0.0% | 100.0% | n/a | 0 | n/a | 0 | 0.001 | 0.0000 |
| Random | 2/42 | 0.0% | 0.0% | 0.0% | 100.0% | n/a | 0 | n/a | 0 | 0.000 | 0.0000 |

## Iteration 3: reserve tool calls for new evidence and show incident peaks; reuse unchanged ReAct and HolmesGPT pilot checkpoints (superseded) (round2-iteration-3)

14 Astronomy Shop snapshots (development); 3 runs per method; nvidia/nemotron-3.5-lightning-30b-a3b; x86_64, 8 vCPU, Linux, no GPU.

| Method | Runs | Top-1 | Top-3 | Service top-1 | Service top-3 | Grounding | Citations | Calls/run | Tokens/run | Seconds/run | USD/run |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| SRE-Copilot | 1/42 | 100.0% | 100.0% | 100.0% | 100.0% | 83.3% | 6 | 3.0 | 11,766 | 8.296 | 0.0000 |
| ReAct without grounding verifier in the agent | 2/42 | 0.0% | 0.0% | 0.0% | 0.0% | 100.0% | 2 | 3.0 | 11,982 | 26.660 | 0.0000 |
| SRE-Copilot without anomaly prior | 1/42 | 0.0% | 0.0% | 0.0% | 0.0% | 100.0% | 3 | 3.0 | 8,793 | 15.584 | 0.0000 |
| HolmesGPT 0.48.0 (1 run per snapshot) | 1/14 | 0.0% | 0.0% | 0.0% | 0.0% | n/a | 0 | 1.0 | 15,857 | 8.152 | 0.0000 |
| RCAEval N-Sigma (metrics) | 2/42 | 100.0% | 100.0% | 100.0% | 100.0% | n/a | 0 | n/a | 0 | 0.006 | 0.0000 |
| Composite z-score | 2/42 | 0.0% | 0.0% | 50.0% | 100.0% | n/a | 0 | n/a | 0 | 0.004 | 0.0000 |
| RCAEval BARO (metrics) | 2/42 | 50.0% | 50.0% | 100.0% | 100.0% | n/a | 0 | n/a | 0 | 0.012 | 0.0000 |
| Error-rate z-score | 2/42 | 0.0% | 0.0% | 0.0% | 100.0% | n/a | 0 | n/a | 0 | 0.001 | 0.0000 |
| Random | 2/42 | 0.0% | 0.0% | 0.0% | 100.0% | n/a | 0 | n/a | 0 | 0.000 | 0.0000 |

## Iteration 4: grounded reranking and fill; pilot failed (prior 50% top-1, 100% top-3) (round2-iteration-4)

14 Astronomy Shop snapshots (development); 3 runs per method; nvidia/nemotron-3.5-lightning-30b-a3b; x86_64, 8 vCPU, Linux, no GPU.

| Method | Runs | Top-1 | Top-3 | Service top-1 | Service top-3 | Grounding | Citations | Calls/run | Tokens/run | Seconds/run | USD/run |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| SRE-Copilot | 4/42 | 0.0% | 50.0% | 50.0% | 50.0% | 100.0% | 13 | 3.0 | 9,446 | 6.480 | 0.0000 |
| ReAct without grounding verifier in the agent | 4/42 | 0.0% | 0.0% | 0.0% | 0.0% | 100.0% | 4 | 3.0 | 12,768 | 28.015 | 0.0000 |
| SRE-Copilot without anomaly prior | 4/42 | 0.0% | 0.0% | 0.0% | 50.0% | 95.2% | 21 | 3.0 | 8,898 | 12.416 | 0.0000 |
| HolmesGPT 0.48.0 (1 run per snapshot) | 4/14 | 0.0% | 0.0% | 0.0% | 0.0% | n/a | 0 | 1.0 | 15,809 | 10.346 | 0.0000 |
| RCAEval N-Sigma (metrics) | 4/42 | 50.0% | 50.0% | 50.0% | 50.0% | n/a | 0 | n/a | 0 | 0.006 | 0.0000 |
| Composite z-score | 4/42 | 50.0% | 50.0% | 75.0% | 100.0% | n/a | 0 | n/a | 0 | 0.004 | 0.0000 |
| RCAEval BARO (metrics) | 4/42 | 25.0% | 25.0% | 50.0% | 50.0% | n/a | 0 | n/a | 0 | 0.009 | 0.0000 |
| Error-rate z-score | 4/42 | 0.0% | 0.0% | 0.0% | 75.0% | n/a | 0 | n/a | 0 | 0.001 | 0.0000 |
| Random | 4/42 | 0.0% | 0.0% | 0.0% | 50.0% | n/a | 0 | n/a | 0 | 0.000 | 0.0000 |

## Iteration 5: protect the top direct-evidence pair; pilot failed when a corroborated memory candidate was omitted (round2-iteration-5)

14 Astronomy Shop snapshots (development); 3 runs per method; nvidia/nemotron-3.5-lightning-30b-a3b; x86_64, 8 vCPU, Linux, no GPU.

| Method | Runs | Top-1 | Top-3 | Service top-1 | Service top-3 | Grounding | Citations | Calls/run | Tokens/run | Seconds/run | USD/run |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| SRE-Copilot | 4/42 | 50.0% | 75.0% | 100.0% | 100.0% | 100.0% | 13 | 3.0 | 9,487 | 8.714 | 0.0000 |
| ReAct without grounding verifier in the agent | 4/42 | 0.0% | 0.0% | 0.0% | 0.0% | 100.0% | 4 | 3.0 | 12,768 | 28.015 | 0.0000 |
| SRE-Copilot without anomaly prior | 4/42 | 0.0% | 0.0% | 0.0% | 50.0% | 95.2% | 21 | 3.0 | 8,898 | 12.416 | 0.0000 |
| HolmesGPT 0.48.0 (1 run per snapshot) | 4/14 | 0.0% | 0.0% | 0.0% | 0.0% | n/a | 0 | 1.0 | 15,809 | 10.346 | 0.0000 |
| RCAEval N-Sigma (metrics) | 4/42 | 50.0% | 50.0% | 50.0% | 50.0% | n/a | 0 | n/a | 0 | 0.006 | 0.0000 |
| Composite z-score | 4/42 | 50.0% | 50.0% | 75.0% | 100.0% | n/a | 0 | n/a | 0 | 0.004 | 0.0000 |
| RCAEval BARO (metrics) | 4/42 | 25.0% | 25.0% | 50.0% | 50.0% | n/a | 0 | n/a | 0 | 0.009 | 0.0000 |
| Error-rate z-score | 4/42 | 0.0% | 0.0% | 0.0% | 75.0% | n/a | 0 | n/a | 0 | 0.001 | 0.0000 |
| Random | 4/42 | 0.0% | 0.0% | 0.0% | 50.0% | n/a | 0 | n/a | 0 | 0.000 | 0.0000 |

## Iteration 6: protect leading corroborated candidates; second attempt on symptom displacement (round2-iteration-6)

14 Astronomy Shop snapshots (development); 3 runs per method; nvidia/nemotron-3.5-lightning-30b-a3b; x86_64, 8 vCPU, Linux, no GPU.

| Method | Runs | Top-1 | Top-3 | Service top-1 | Service top-3 | Grounding | Citations | Calls/run | Tokens/run | Seconds/run | USD/run |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| SRE-Copilot | 4/42 | 50.0% | 100.0% | 100.0% | 100.0% | 100.0% | 13 | 3.0 | 9,476 | 9.648 | 0.0000 |
| ReAct without grounding verifier in the agent | 4/42 | 0.0% | 0.0% | 0.0% | 0.0% | 100.0% | 4 | 3.0 | 12,768 | 28.015 | 0.0000 |
| SRE-Copilot without anomaly prior | 4/42 | 0.0% | 0.0% | 0.0% | 50.0% | 95.2% | 21 | 3.0 | 8,898 | 12.416 | 0.0000 |
| HolmesGPT 0.48.0 (1 run per snapshot) | 4/14 | 0.0% | 0.0% | 0.0% | 0.0% | n/a | 0 | 1.0 | 15,809 | 10.346 | 0.0000 |
| RCAEval N-Sigma (metrics) | 4/42 | 50.0% | 50.0% | 50.0% | 50.0% | n/a | 0 | n/a | 0 | 0.006 | 0.0000 |
| Composite z-score | 4/42 | 50.0% | 50.0% | 75.0% | 100.0% | n/a | 0 | n/a | 0 | 0.004 | 0.0000 |
| RCAEval BARO (metrics) | 4/42 | 25.0% | 25.0% | 50.0% | 50.0% | n/a | 0 | n/a | 0 | 0.009 | 0.0000 |
| Error-rate z-score | 4/42 | 0.0% | 0.0% | 0.0% | 75.0% | n/a | 0 | n/a | 0 | 0.001 | 0.0000 |
| Random | 4/42 | 0.0% | 0.0% | 0.0% | 50.0% | n/a | 0 | n/a | 0 | 0.000 | 0.0000 |
