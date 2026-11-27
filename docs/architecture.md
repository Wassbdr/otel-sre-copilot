# Architecture

The investigation graph takes an incident time window and namespace. It queries metrics, traces,
logs and Kubernetes events through the same data-source interface in live and replay modes.
The live implementation reads Prometheus, Tempo, Loki and Kubernetes. Replay reads the
corresponding recorded queries and data from a snapshot without connecting to a cluster.

The graph uses an OpenAI-compatible model to select tools and produce ranked service and
fault-type hypotheses. Each hypothesis can cite tool evidence. The evaluation harness checks
those citations against the tool call log independently of the model and computes accuracy,
grounding, latency and cost. A report can have no citations, so read grounding alongside
evidence count.

## Evaluation decisions

- Compare methods on the same snapshots and report losses as well as wins. A snapshot without
  a measurable fault signal cannot distinguish detection from guessing.
- Record the scenario seed, snapshot hash and model so a comparison can be reproduced.
- Keep capture validation separate from diagnosis. Validation knows the injected fault;
  diagnosis only receives the telemetry and incident window.

## Capture validation

Chaos Mesh injects faults into the OpenTelemetry Astronomy Shop. The capture script records
telemetry and ground truth, then validates that the expected signal is present:

| Fault | Validation | Rationale |
| --- | --- | --- |
| Latency (ADR-004) | A top-three p99 increase relative to the service's own baseline, at least threefold. | Caller spans inherit the delay. Ranking by absolute p99 favors already slow callers. |
| HTTP abort (ADR-005) | Request rate falls to at most half of a baseline above 0.005 requests/s. | Packet loss can prevent the target from emitting server spans, so server error rate can remain flat. |
| CPU stress (ADR-006) | Usage grows at least threefold against the service's baseline and ranks among the three highest consumers. | Comparing only absolute usage masks spikes in services that normally use fewer resources than the load generator. |
| Memory stress (ADR-006, ADR-007) | Apply the CPU-style rule to working set, or accept a pod restart outlier. | A tight memory limit can trigger an OOM kill before working set rises enough to pass. |

Keep stress moderate enough that the telemetry backends stay up. Capture a healthy window
before the fault so the observed change can be compared with the service's own baseline.
