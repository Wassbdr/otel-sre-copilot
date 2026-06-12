.PHONY: setup up down health-check fault investigate eval eval-replay eval-baselines compare test lint fmt demo help

CLUSTER_NAME      := otel-sre-copilot
KUBECONFIG_PATH   := $(HOME)/.kube/config
NAMESPACE         := otel-demo
CHAOS_NAMESPACE   := chaos-mesh

SCENARIO          ?= scenarios/mvp/001-checkoutservice-pod-crash.yaml
SCENARIO_DIR      ?= scenarios/mvp
RUN_ID            ?=
INCIDENT_ID       ?=
START             ?=
END               ?=

# ── Setup ──────────────────────────────────────────────────────────────────
setup:
	@echo "==> WSL2 preflight (inotify limits)"
	@bash scripts/wsl2_preflight.sh
	@echo "==> Installing Python dependencies"
	pip install -e ".[dev]"
	@echo "==> Checking kind"
	@which kind || (echo "Install kind: https://kind.sigs.k8s.io/docs/user/quick-start/#installation" && exit 1)
	@echo "==> Checking helm"
	@which helm || (echo "Install helm: https://helm.sh/docs/intro/install/" && exit 1)
	@echo "==> Checking kubectl"
	@which kubectl || (echo "Install kubectl: https://kubernetes.io/docs/tasks/tools/" && exit 1)
	@echo "==> Checking chaos-mesh CLI (optional)"
	@which chaos-mesh || true
	@echo "Setup complete."

# ── Cluster lifecycle ──────────────────────────────────────────────────────
up:
	@echo "==> WSL2 preflight (inotify limits — resets on WSL2 restart)"
	@bash scripts/wsl2_preflight.sh
	@echo "==> Creating kind cluster: $(CLUSTER_NAME)"
	kind create cluster --name $(CLUSTER_NAME) --config infra/kind-config.yaml \
		--kubeconfig $(KUBECONFIG_PATH) 2>/dev/null || \
		echo "  (cluster already exists, skipping)"
	@echo "==> Adding Helm repos"
	helm repo add prometheus-community https://prometheus-community.github.io/helm-charts 2>/dev/null || true
	helm repo add grafana https://grafana.github.io/helm-charts 2>/dev/null || true
	helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts 2>/dev/null || true
	helm repo add chaos-mesh https://charts.chaos-mesh.org 2>/dev/null || true
	helm repo update
	@echo "==> Installing Prometheus"
	helm upgrade --install prometheus prometheus-community/kube-prometheus-stack \
		--namespace monitoring --create-namespace \
		--values infra/helm/prometheus-values.yaml \
		--wait --timeout 5m
	@echo "==> Installing Tempo"
	helm upgrade --install tempo grafana/tempo \
		--namespace monitoring \
		--values infra/helm/tempo-values.yaml \
		--wait --timeout 3m
	@echo "==> Installing Loki"
	helm upgrade --install loki grafana/loki \
		--namespace monitoring \
		--values infra/helm/loki-values.yaml \
		--wait --timeout 3m
	@echo "==> Deploying OTel Collector"
	kubectl apply -f infra/collector/otelcol-config.yaml
	kubectl apply -f infra/collector/otelcol-daemonset.yaml
	kubectl -n monitoring rollout status daemonset/otel-collector --timeout=120s
	@echo "==> Installing OTel Astronomy Shop"
	helm upgrade --install astronomy-shop open-telemetry/opentelemetry-demo \
		--namespace $(NAMESPACE) --create-namespace \
		--values infra/helm/astronomy-shop-values.yaml \
		--wait --timeout 10m
	@echo "==> Installing Chaos Mesh"
	helm upgrade --install chaos-mesh chaos-mesh/chaos-mesh \
		--namespace $(CHAOS_NAMESPACE) --create-namespace \
		--set chaosDaemon.runtime=containerd \
		--set chaosDaemon.socketPath=/run/containerd/containerd.sock \
		--wait --timeout 3m
	@echo ""
	@echo "Cluster ready. Run: make health-check"

down:
	kind delete cluster --name $(CLUSTER_NAME)
	@echo "Cluster deleted."

# ── Health check ───────────────────────────────────────────────────────────
health-check:
	@python3 scripts/health_check.py

# ── Fault injection ────────────────────────────────────────────────────────
fault:
	@test -f "$(SCENARIO)" || (echo "ERROR: SCENARIO not found: $(SCENARIO)" && exit 1)
	@python scripts/inject_and_snapshot.py --scenario $(SCENARIO)

# ── Agent (live mode) ─────────────────────────────────────────────────────
investigate:
	@test -n "$(INCIDENT_ID)" || (echo "ERROR: INCIDENT_ID required" && exit 1)
	@test -n "$(START)"       || (echo "ERROR: START required (ISO-8601)" && exit 1)
	@test -n "$(END)"         || (echo "ERROR: END required (ISO-8601)" && exit 1)
	@python -m src.agent.run \
		--incident-id "$(INCIDENT_ID)" \
		--start "$(START)" \
		--end "$(END)" \
		--namespace "$(NAMESPACE)"

# ── Evaluation ────────────────────────────────────────────────────────────
eval:
	@python -m eval.scenario_runner \
		--scenario-dir "$(SCENARIO_DIR)" \
		--mode replay

eval-replay:
	@test -n "$(RUN_ID)" || (echo "ERROR: RUN_ID required" && exit 1)
	@python -m eval.scenario_runner \
		--scenario-dir "$(SCENARIO_DIR)" \
		--mode replay \
		--run-id "$(RUN_ID)"

eval-baselines:
	@python -m eval.scenario_runner \
		--scenario-dir "$(SCENARIO_DIR)" \
		--mode baselines-only

compare:
	@python -m eval.compare

# ── Dev ───────────────────────────────────────────────────────────────────
test:
	pytest --cov=src --cov=eval --cov-report=term-missing -q

lint:
	ruff check src/ eval/ scripts/ tests/
	mypy src/ eval/ --ignore-missing-imports

fmt:
	ruff format src/ eval/ scripts/ tests/

# ── Demo ──────────────────────────────────────────────────────────────────
demo:
	@echo "Running demo on most recent snapshot..."
	@LATEST=$$(ls -td snapshots/*/ground_truth.json 2>/dev/null | head -1 | xargs dirname); \
	test -n "$$LATEST" || (echo "No snapshots found. Run: make fault SCENARIO=..." && exit 1); \
	SCENARIO_ID=$$(basename $$LATEST); \
	python -m eval.scenario_runner \
		--snapshot-dir "$$LATEST" \
		--mode single \
		--print-report

help:
	@echo ""
	@echo "OTel SRE-Copilot — available targets:"
	@echo ""
	@echo "  make setup          Install dependencies + check tools"
	@echo "  make up             Create kind cluster + deploy all backends"
	@echo "  make down           Destroy cluster"
	@echo "  make health-check   Verify all backends healthy"
	@echo ""
	@echo "  make fault SCENARIO=<path>     Inject fault + snapshot telemetry"
	@echo "  make investigate INCIDENT_ID=<id> START=<ts> END=<ts>"
	@echo ""
	@echo "  make eval                      Run 7 MVP scenarios (replay mode)"
	@echo "  make eval SCENARIO_DIR=...     Custom scenario dir"
	@echo "  make eval-replay RUN_ID=<id>   Replay from artifacts"
	@echo "  make eval-baselines            Run 3 baselines"
	@echo "  make compare                   Agent vs baselines table"
	@echo ""
	@echo "  make test / make lint / make fmt"
	@echo ""
