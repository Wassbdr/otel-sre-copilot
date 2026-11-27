# Benchmark — run `bench-20261127b`

14 replayed Chaos Mesh snapshots (7 scenarios × seeds 42, 7) of the OpenTelemetry Astronomy Shop; agent = `nvidia/nemotron-3.5-lightning-30b-a3b` via NVIDIA NIM, temperature 0, 3 runs per snapshot; baseline RANDOM_SEED=42; x86_64 8 vCPU, Linux, no GPU.

| Method | Top-1 | Top-3 | Service top-1 / top-3 | Grounding | Latency / incident | Tokens / incident |
|---|---|---|---|---|---|---|
| **SRE-Copilot agent (LLM)** | 36% ± 12 | 48% ± 7 | 62% / 86% | 0.97 | 54.8 s | 85,770 |
| Composite z-score (5 signals) | 29% | 50% | 43% / 93% | n/a | 0 ms | 0 |
| Z-score on error_rate | 0% | 14% | 14% / 50% | n/a | 0 ms | 0 |
| Random | 0% | 0% | 0% / 29% | n/a | 0 ms | 0 |

Top-1 / top-3: the exact ground truth (service and fault type) is the first hypothesis / in the first three; service top-1 / top-3 count the service only. Agent figures are the mean over all runs; `± x` is the standard deviation of the benchmark-level score across the repeated passes. Grounding: share of the agent's cited evidence that the external verifier matched to a tool call it really made (< 0.8 = hallucination warning; 3 of 42 agent runs flagged). Latency is wall-clock per investigation, LLM calls included, minus time spent waiting out provider rate limits (HTTP 429). Tokens = prompt + completion over every LLM call.

## Per scenario

Strict top-1 / top-3 (service and fault type), pooled over seeds and runs.

| Scenario (ground truth) | seeds | SRE-Copilot agent top-1 / top-3 | Composite z-score top-1 / top-3 | Z-score on error_rate top-1 / top-3 | Random top-1 / top-3 |
|---|---|---|---|---|---|
| `cart-memory_stress` (cart, memory_stress) | 7,42 | 17% / 17% | 0% / 0% | 0% / 0% | 0% / 0% |
| `checkout-pod_crash` (checkout, pod_crash) | 7,42 | 100% / 100% | 100% / 100% | 0% / 0% | 0% / 0% |
| `frontend-pod_crash` (frontend, pod_crash) | 7,42 | 67% / 100% | 100% / 100% | 0% / 0% | 0% / 0% |
| `payment-http_abort` (payment, http_abort) | 7,42 | 0% / 0% | 0% / 0% | 0% / 0% | 0% / 0% |
| `product-catalog-high_latency` (product-catalog, high_latency) | 7,42 | 33% / 33% | 0% / 100% | 0% / 0% | 0% / 0% |
| `recommendation-cpu_stress` (recommendation, cpu_stress) | 7,42 | 33% / 67% | 0% / 50% | 0% / 0% | 0% / 0% |
| `shipping-high_latency` (shipping, high_latency) | 7,42 | 0% / 17% | 0% / 0% | 0% / 100% | 0% / 0% |

## Per snapshot (top-1 prediction of each run)

| Snapshot | truth | agent top-1 | composite_zscore top-1 | zscore top-1 | random top-1 |
|---|---|---|---|---|---|
| `checkout-pod_crash-seed42` | checkout | checkout, checkout, checkout | checkout | frontend | load-generator |
| `checkout-pod_crash-seed7` | checkout | checkout, checkout, checkout | checkout | frontend | load-generator |
| `product-catalog-high_latency-seed42` | product-catalog | none, none, recommendation | recommendation | frontend | load-generator |
| `product-catalog-high_latency-seed7` | product-catalog | product-catalog, product-catalog, product-catalog | recommendation | flagd | load-generator |
| `payment-http_abort-seed42` | payment | fraud-detection, fraud-detection, fraud-detection | fraud-detection | flagd | load-generator |
| `payment-http_abort-seed7` | payment | payment, quote, payment | quote | flagd | load-generator |
| `recommendation-cpu_stress-seed42` | recommendation | currency, recommendation, currency | currency | flagd | load-generator |
| `recommendation-cpu_stress-seed7` | recommendation | recommendation, recommendation, recommendation | recommendation | frontend | load-generator |
| `cart-memory_stress-seed42` | cart | cart, cart, cart | cart | frontend | load-generator |
| `cart-memory_stress-seed7` | cart | cart, cart, cart | email | frontend | load-generator |
| `shipping-high_latency-seed42` | shipping | payment, shipping, quote | quote | frontend | load-generator |
| `shipping-high_latency-seed7` | shipping | frontend, frontend, frontend | frontend | frontend | load-generator |
| `frontend-pod_crash-seed42` | frontend | payment, payment, frontend | frontend | frontend | load-generator |
| `frontend-pod_crash-seed7` | frontend | frontend, frontend, frontend | frontend | frontend | load-generator |

## Reproduce

```bash
python -m eval.scenario_runner --mode benchmark --repeats 3 --run-id bench-20261127b
python -m eval.report --run-id bench-20261127b
```
