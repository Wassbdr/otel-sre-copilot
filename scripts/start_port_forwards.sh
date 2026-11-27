#!/usr/bin/env bash
# Start kubectl port-forwards for Prometheus, Tempo, Loki.
# Only needed when the kind NodePort mappings (9090/3200/3100) are unavailable, e.g. a remote
# cluster. Then export PROMETHEUS_URL=http://localhost:19090 TEMPO_URL=... LOKI_URL=...
set -euo pipefail

CONTEXT="${KUBE_CONTEXT:-kind-otel-sre-copilot}"
LOG_DIR="/tmp/otel-sre-pf"
mkdir -p "$LOG_DIR"

pkill -f "kubectl.*port-forward.*monitoring" 2>/dev/null || true
sleep 1

# Use 19090/13200/13100 — Docker extraPortMappings already hold 9090/3200/3100
nohup kubectl --context "$CONTEXT" port-forward svc/prometheus-server 19090:80 \
  -n monitoring --address 127.0.0.1 >"$LOG_DIR/prometheus.log" 2>&1 &
echo "Prometheus  → localhost:19090  (PID $!)"

nohup kubectl --context "$CONTEXT" port-forward svc/tempo 13200:3200 \
  -n monitoring --address 127.0.0.1 >"$LOG_DIR/tempo.log" 2>&1 &
echo "Tempo       → localhost:13200  (PID $!)"

nohup kubectl --context "$CONTEXT" port-forward svc/loki 13100:3100 \
  -n monitoring --address 127.0.0.1 >"$LOG_DIR/loki.log" 2>&1 &
echo "Loki        → localhost:13100  (PID $!)"

echo ""
echo "Logs: $LOG_DIR/"
echo "Stop: pkill -f 'kubectl.*port-forward'"
