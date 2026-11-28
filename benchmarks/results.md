# Benchmark results

<!-- final-comparison:start -->
## Final comparison

Astronomy Shop replay: 6 held-out, 12 new untuned development, 14 tuned development snapshots; `nvidia/nemotron-3.5-lightning-30b-a3b` via NVIDIA NIM; 3 runs per Copilot method and 1 per HolmesGPT snapshot; x86_64, 8 vCPU, Linux, no GPU.

Each accuracy cell is strict top-1 / top-3 (service and fault type). Multi-fault runs score the fraction of true causes covered. Grounding and per-run costs are pooled.

| Method | Held-out | New development | Tuned development | Pooled | Grounding | Tokens | Seconds | USD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **SRE-Copilot** | 63.9% / 86.1% | 61.1% / 80.6% | 69.0% / 100.0% | 65.1% / 90.1% | 100.0% | 9,859 | 9.86 | 0.0000 |
| Composite z-score | 50.0% / 58.3% | 16.7% / 50.0% | 28.6% / 50.0% | 28.1% / 51.6% | n/a | 0 | 0.00 | 0.0000 |
| RCAEval N-Sigma (metrics) | 8.3% / 25.0% | 33.3% / 50.0% | 35.7% / 50.0% | 29.7% / 45.3% | n/a | 0 | 0.01 | 0.0000 |
| ReAct without grounding verifier in the agent | 5.6% / 8.3% | 11.1% / 22.2% | 14.3% / 21.4% | 11.5% / 19.3% | 51.7% | 47,489 | 43.12 | 0.0000 |
| HolmesGPT 0.48.0 (1 run per snapshot) | 0.0% / 50.0% | 8.3% / 16.7% | 14.3% / 28.6% | 9.4% / 28.1% | 83.3% | 437,350 | 115.53 | 0.0000 |
| RCAEval BARO (metrics) | 0.0% / 25.0% | 16.7% / 58.3% | 28.6% / 42.9% | 18.8% / 45.3% | n/a | 0 | 0.01 | 0.0000 |
| SRE-Copilot without anomaly prior | 0.0% / 8.3% | 16.7% / 22.2% | 9.5% / 19.0% | 10.4% / 18.2% | 87.8% | 9,056 | 10.41 | 0.0000 |
| Random | 0.0% / 0.0% | 2.8% / 2.8% | 4.8% / 4.8% | 3.1% / 3.1% | n/a | 0 | 0.00 | 0.0000 |
| Error-rate z-score | 0.0% / 0.0% | 0.0% / 8.3% | 0.0% / 14.3% | 0.0% / 9.4% | n/a | 0 | 0.00 | 0.0000 |

RCAEval BARO (metrics) leads on service-only top-3 for new development (83.3% vs. 80.6%); the table uses strict matching.

Seconds exclude rate-limit waits. USD reflects NIM free-tier pricing. Grounding is the share of citations matched to tool calls; n/a means no citations.

### SRE-Copilot by cohort

| Cohort | Runs | Service top-1 | Service top-3 | Grounded citations | Tokens/run | Seconds/run | USD/run |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Held-out | 18 | 63.9% | 86.1% | 55/55 | 9,932 | 10.37 | 0.0000 |
| New development | 36 | 69.4% | 80.6% | 104/104 | 9,772 | 5.99 | 0.0000 |
| Tuned development | 42 | 83.3% | 100.0% | 142/142 | 9,903 | 12.95 | 0.0000 |
| Pooled | 96 | 74.5% | 90.1% | 301/301 | 9,859 | 9.86 | 0.0000 |

### SRE-Copilot misses

Runs missing any true cause, grouped by scenario across seeds (top-1 / top-3). For two-fault incidents, top-1 necessarily misses at least one cause.

- **Held-out:** `currency-cart-multi` 9/9 / 5/9.
- **New development:** `cart-memory_stress` 3/3 / 0/3; `product-catalog-cpu_stress` 2/9 / 0/9; `quote-http_abort` 9/9 / 7/9.
- **Tuned development:** `cart-memory_stress` 6/6 / 0/6; `payment-http_abort` 4/6 / 0/6; `recommendation-cpu_stress` 3/6 / 0/6.
<!-- final-comparison:end -->

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
| SRE-Copilot | 42/42 | 69.0% | 100.0% | 83.3% | 100.0% | 100.0% | 142 | 3.0 | 9,903 | 12.950 | 0.0000 |
| ReAct without grounding verifier in the agent | 42/42 | 0.0% | 0.0% | 2.4% | 7.1% | 95.7% | 47 | 3.0 | 12,812 | 38.747 | 0.0000 |
| SRE-Copilot without anomaly prior | 42/42 | 9.5% | 19.0% | 33.3% | 69.0% | 90.9% | 230 | 3.1 | 9,186 | 10.761 | 0.0000 |
| HolmesGPT 0.48.0 (1 run per snapshot) | 14/14 | 0.0% | 0.0% | 0.0% | 0.0% | n/a | 0 | 1.0 | 15,832 | 11.508 | 0.0000 |
| RCAEval N-Sigma (metrics) | 42/42 | 35.7% | 50.0% | 42.9% | 64.3% | n/a | 0 | n/a | 0 | 0.006 | 0.0000 |
| Composite z-score | 42/42 | 28.6% | 50.0% | 42.9% | 92.9% | n/a | 0 | n/a | 0 | 0.004 | 0.0000 |
| RCAEval BARO (metrics) | 42/42 | 28.6% | 42.9% | 42.9% | 57.1% | n/a | 0 | n/a | 0 | 0.008 | 0.0000 |
| Error-rate z-score | 42/42 | 0.0% | 14.3% | 14.3% | 50.0% | n/a | 0 | n/a | 0 | 0.001 | 0.0000 |
| Random | 42/42 | 4.8% | 4.8% | 9.5% | 23.8% | n/a | 0 | n/a | 0 | 0.000 | 0.0000 |

Change against round2-iteration-0:

| Change | Metric | Delta |
| --- | --- | ---: |
| Iteration 6: protect leading corroborated candidates; second attempt on symptom displacement | Top-1 | +33.3 pp |
| Iteration 6: protect leading corroborated candidates; second attempt on symptom displacement | Top-3 | +52.4 pp |
| Iteration 6: protect leading corroborated candidates; second attempt on symptom displacement | Service top-1 | +21.4 pp |
| Iteration 6: protect leading corroborated candidates; second attempt on symptom displacement | Service top-3 | +14.3 pp |

## Reference audit pilot: ReAct used full tool rounds; HolmesGPT reached incident tools but returned tool markup instead of a diagnosis (round2-reference-audit)

14 Astronomy Shop snapshots (development); 3 runs per method; nvidia/nemotron-3.5-lightning-30b-a3b; x86_64, 8 vCPU, Linux, no GPU.

| Method | Runs | Top-1 | Top-3 | Service top-1 | Service top-3 | Grounding | Citations | Calls/run | Tokens/run | Seconds/run | USD/run |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| SRE-Copilot | 1/42 | 0.0% | 100.0% | 100.0% | 100.0% | 100.0% | 4 | 3.0 | 9,225 | 18.160 | 0.0000 |
| ReAct without grounding verifier in the agent | 1/42 | 0.0% | 0.0% | 100.0% | 100.0% | 100.0% | 3 | 11.0 | 48,079 | 55.151 | 0.0000 |
| SRE-Copilot without anomaly prior | 1/42 | 0.0% | 0.0% | 0.0% | 0.0% | 100.0% | 3 | 3.0 | 8,793 | 15.584 | 0.0000 |
| HolmesGPT 0.48.0 (1 run per snapshot) | 1/14 | 0.0% | 0.0% | 0.0% | 0.0% | n/a | 0 | 10.0 | 284,537 | 62.685 | 0.0000 |
| RCAEval N-Sigma (metrics) | 1/42 | 100.0% | 100.0% | 100.0% | 100.0% | n/a | 0 | n/a | 0 | 0.007 | 0.0000 |
| Composite z-score | 1/42 | 0.0% | 0.0% | 100.0% | 100.0% | n/a | 0 | n/a | 0 | 0.004 | 0.0000 |
| RCAEval BARO (metrics) | 1/42 | 100.0% | 100.0% | 100.0% | 100.0% | n/a | 0 | n/a | 0 | 0.013 | 0.0000 |
| Error-rate z-score | 1/42 | 0.0% | 0.0% | 0.0% | 100.0% | n/a | 0 | n/a | 0 | 0.001 | 0.0000 |
| Random | 1/42 | 0.0% | 0.0% | 0.0% | 100.0% | n/a | 0 | n/a | 0 | 0.000 | 0.0000 |

## Reference replay comparison: full ReAct tool access, recorded query compatibility and structured HolmesGPT diagnosis (round2-reference-aligned)

14 Astronomy Shop snapshots (development); 3 runs per method; nvidia/nemotron-3.5-lightning-30b-a3b; x86_64, 8 vCPU, Linux, no GPU.

| Method | Runs | Top-1 | Top-3 | Service top-1 | Service top-3 | Grounding | Citations | Calls/run | Tokens/run | Seconds/run | USD/run |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| SRE-Copilot | 42/42 | 69.0% | 100.0% | 83.3% | 100.0% | 100.0% | 142 | 3.0 | 9,903 | 12.950 | 0.0000 |
| ReAct without grounding verifier in the agent | 42/42 | 14.3% | 21.4% | 33.3% | 52.4% | 43.8% | 96 | 11.0 | 47,774 | 43.982 | 0.0000 |
| SRE-Copilot without anomaly prior | 42/42 | 9.5% | 19.0% | 33.3% | 69.0% | 90.9% | 230 | 3.1 | 9,186 | 10.761 | 0.0000 |
| HolmesGPT 0.48.0 (1 run per snapshot) | 14/14 | 14.3% | 28.6% | 14.3% | 42.9% | 85.7% | 49 | 10.0 | 421,628 | 119.805 | 0.0000 |
| RCAEval N-Sigma (metrics) | 42/42 | 35.7% | 50.0% | 42.9% | 64.3% | n/a | 0 | n/a | 0 | 0.006 | 0.0000 |
| Composite z-score | 42/42 | 28.6% | 50.0% | 42.9% | 92.9% | n/a | 0 | n/a | 0 | 0.004 | 0.0000 |
| RCAEval BARO (metrics) | 42/42 | 28.6% | 42.9% | 42.9% | 57.1% | n/a | 0 | n/a | 0 | 0.008 | 0.0000 |
| Error-rate z-score | 42/42 | 0.0% | 14.3% | 14.3% | 50.0% | n/a | 0 | n/a | 0 | 0.001 | 0.0000 |
| Random | 42/42 | 4.8% | 4.8% | 9.5% | 23.8% | n/a | 0 | n/a | 0 | 0.000 | 0.0000 |

Change against round2-iteration-6:

| Change | Metric | Delta |
| --- | --- | ---: |
| Reference replay comparison: full ReAct tool access, recorded query compatibility and structured HolmesGPT diagnosis | Top-1 | +0.0 pp |
| Reference replay comparison: full ReAct tool access, recorded query compatibility and structured HolmesGPT diagnosis | Top-3 | +0.0 pp |
| Reference replay comparison: full ReAct tool access, recorded query compatibility and structured HolmesGPT diagnosis | Service top-1 | +0.0 pp |
| Reference replay comparison: full ReAct tool access, recorded query compatibility and structured HolmesGPT diagnosis | Service top-3 | +0.0 pp |

## Newly validated development snapshots: expanded services and third seeds; same methods (round2-new-development)

12 Astronomy Shop snapshots (development); 3 runs per method; nvidia/nemotron-3.5-lightning-30b-a3b; x86_64, 8 vCPU, Linux, no GPU.

| Method | Runs | Top-1 | Top-3 | Service top-1 | Service top-3 | Grounding | Citations | Calls/run | Tokens/run | Seconds/run | USD/run |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| SRE-Copilot | 36/36 | 61.1% | 80.6% | 69.4% | 80.6% | 100.0% | 104 | 3.0 | 9,772 | 5.991 | 0.0000 |
| ReAct without grounding verifier in the agent | 36/36 | 11.1% | 22.2% | 11.1% | 33.3% | 52.3% | 88 | 11.0 | 47,285 | 41.830 | 0.0000 |
| SRE-Copilot without anomaly prior | 36/36 | 16.7% | 22.2% | 19.4% | 44.4% | 84.8% | 184 | 3.0 | 8,981 | 9.874 | 0.0000 |
| HolmesGPT 0.48.0 (1 run per snapshot) | 12/12 | 8.3% | 16.7% | 8.3% | 25.0% | 72.5% | 51 | 9.5 | 418,084 | 103.953 | 0.0000 |
| RCAEval N-Sigma (metrics) | 36/36 | 33.3% | 50.0% | 50.0% | 66.7% | n/a | 0 | n/a | 0 | 0.007 | 0.0000 |
| Composite z-score | 36/36 | 16.7% | 50.0% | 33.3% | 75.0% | n/a | 0 | n/a | 0 | 0.005 | 0.0000 |
| RCAEval BARO (metrics) | 36/36 | 16.7% | 58.3% | 16.7% | 83.3% | n/a | 0 | n/a | 0 | 0.009 | 0.0000 |
| Error-rate z-score | 36/36 | 0.0% | 8.3% | 8.3% | 33.3% | n/a | 0 | n/a | 0 | 0.001 | 0.0000 |
| Random | 36/36 | 2.8% | 2.8% | 13.9% | 30.6% | n/a | 0 | n/a | 0 | 0.000 | 0.0000 |

## Held-out snapshots: unseen ad pod crashes and currency plus cart two-fault incidents (round2-held-out)

6 Astronomy Shop snapshots (held-out); 3 runs per method; nvidia/nemotron-3.5-lightning-30b-a3b; x86_64, 8 vCPU, Linux, no GPU.

| Method | Runs | Top-1 | Top-3 | Service top-1 | Service top-3 | Grounding | Citations | Calls/run | Tokens/run | Seconds/run | USD/run |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| SRE-Copilot | 18/18 | 63.9% | 86.1% | 63.9% | 86.1% | 100.0% | 55 | 3.0 | 9,932 | 10.366 | 0.0000 |
| ReAct without grounding verifier in the agent | 18/18 | 5.6% | 8.3% | 8.3% | 16.7% | 66.7% | 48 | 11.1 | 47,231 | 43.696 | 0.0000 |
| SRE-Copilot without anomaly prior | 18/18 | 0.0% | 8.3% | 0.0% | 8.3% | 86.3% | 95 | 3.0 | 8,903 | 10.640 | 0.0000 |
| HolmesGPT 0.48.0 (1 run per snapshot) | 6/6 | 0.0% | 50.0% | 0.0% | 75.0% | 100.0% | 26 | 10.0 | 512,568 | 128.708 | 0.0000 |
| RCAEval N-Sigma (metrics) | 18/18 | 8.3% | 25.0% | 33.3% | 75.0% | n/a | 0 | n/a | 0 | 0.007 | 0.0000 |
| Composite z-score | 18/18 | 50.0% | 58.3% | 58.3% | 66.7% | n/a | 0 | n/a | 0 | 0.005 | 0.0000 |
| RCAEval BARO (metrics) | 18/18 | 0.0% | 25.0% | 8.3% | 75.0% | n/a | 0 | n/a | 0 | 0.009 | 0.0000 |
| Error-rate z-score | 18/18 | 0.0% | 0.0% | 0.0% | 16.7% | n/a | 0 | n/a | 0 | 0.001 | 0.0000 |
| Random | 18/18 | 0.0% | 0.0% | 0.0% | 8.3% | n/a | 0 | n/a | 0 | 0.000 | 0.0000 |
