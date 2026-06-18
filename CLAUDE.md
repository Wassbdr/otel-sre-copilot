# OTel SRE-Copilot — CLAUDE.md

## Objectif

Agent LLM (NVIDIA NIM) d'investigation d'incidents pour microservices Kubernetes instrumentés
OpenTelemetry. Input : fenêtre temporelle d'incident. Output : top-k causes racines classées
(service + type de faute), remédiation, preuves grounded. Priorité absolue : évaluation
rigoureuse et reproductible — un MVP évalué honnêtement > un système ambitieux non évalué.

## Principes

- Évaluation d'abord : aucune metric gonflée, périmètre et limites documentés explicitement.
- Reproductibilité totale : seeds explicites, artefacts JSON/parquet pinnés dans le repo.
- Pas de sur-engineering : n'ajoute une abstraction que si elle simplifie l'éval ou la repro.
- Honnêteté : si l'agent ne bat pas la baseline Z-score, c'est un résultat, pas un échec caché.
- Pas de scope creep : toute nouvelle fonctionnalité → discussion avant implémentation.

## Stack

| Couche            | Choix                               | Raison                                        |
|-------------------|-------------------------------------|-----------------------------------------------|
| Cluster           | kind                                | Reproductible, CI-friendly, NodePort simple   |
| App cible         | OTel Astronomy Shop (helm)          | OTel-native, ~15 services, communauté active  |
| Métriques         | Prometheus (kube-prometheus-stack)  | Standard, PromQL expressif                    |
| Traces            | Tempo                               | OTLP-native, HTTP API simple, léger           |
| Logs              | Loki                                | LogQL, même écosystème Grafana                |
| Ingestion         | OTel Collector (DaemonSet)          | Single ingress → routes vers les 3 backends   |
| Fault injection   | Chaos Mesh                          | CRD YAML → vérité terrain machine-readable    |
| Agent             | LangGraph + langchain_openai        | StateGraph explicit, state sérialisable       |
| LLM               | NIM API meta/llama-3.1-70b-instruct | OpenAI-compat, qualité outil suffisante       |
| Évaluation        | Python custom                       | Contrôle total, pas de dépendance externe     |

## Commandes exactes

```bash
# ── Infrastructure ─────────────────────────────────────────────────────────
make setup          # installe dépendances Python + outils (kind, helm, kubectl)
make up             # crée cluster kind + déploie tous les backends + astronomy shop
make down           # détruit le cluster kind
make health-check   # vérifie Prometheus/Tempo/Loki + traces non-vides

# ── Injection de fautes ────────────────────────────────────────────────────
make fault SCENARIO=scenarios/mvp/001-checkoutservice-pod-crash.yaml
# → injecte le CRD Chaos Mesh, attend la recovery, snapshote la télémétrie,
#   écrit snapshots/<id>/ground_truth.json

# ── Agent (mode live) ─────────────────────────────────────────────────────
make investigate INCIDENT_ID=<id> START=<iso8601> END=<iso8601>

# ── Évaluation ────────────────────────────────────────────────────────────
make eval                               # 7 scénarios MVP sur snapshots existants
make eval SCENARIO_DIR=scenarios/full   # 35 scénarios (M5)
make eval-replay RUN_ID=<id>            # rejoue sans cluster depuis artefacts
make eval-baselines                     # 3 baselines sur les mêmes snapshots
make compare                            # table agent vs baselines (toutes métriques)

# ── Dev ───────────────────────────────────────────────────────────────────
make test           # pytest --cov=src --cov=eval
make lint           # ruff check + mypy --strict
make fmt            # ruff format
```

## Conventions de code

- Python 3.12, ruff + mypy strict, Pydantic v2 pour tous les schémas.
- Pas de `print()` → `structlog` (JSON structuré).
- Pas de secrets dans le code → `.env` (`.env.example` versionné, `.env` gitignored).
- Tests : pytest, couverture minimale sur `DataSource`, `metrics.py`, `grounding_verifier.py`.
- Pas de commentaires sauf WHY non-obvious.

## Workflow git

- 1 commit par jalon complété, message : `feat(M{N}): <description>`.
- `artifacts/` contient les résultats d'éval committés (JSON + métadonnées, pas les raw snapshots).
- Branche unique `main` (projet solo).

## Protocole d'évaluation

1. Scénarios définis en YAML (service, fault_type, seed, Chaos Mesh CRD embedded).
2. `make fault SCENARIO=...` → injecte, snapshote, écrit `ground_truth.json`.
3. `make eval` → agent sur ReplayDataSource (pas de cluster nécessaire).
4. 7 métriques : Accuracy@1, Accuracy@3, MRR, fault_type_accuracy, grounding_score, latency_s, cost_usd.
5. 3 baselines comparées : random, Z-score error_rate, composite Z-score (4 signaux).
6. `artifacts/<run_id>/` committé avec `config.json` contenant `snapshot_sha256`.

## Garde-fous

- Secrets : jamais dans le repo. `grep -r "NIM_API_KEY\|password\|secret" src/` doit retourner vide.
- Seeds : toujours explicites (`CHAOS_SEED`, `NUMPY_SEED`, `RANDOM_SEED`) dans config.
- Métriques : jamais auto-reportées par l'agent — toujours calculées par le harnais externe.
- Hallucination : `grounding_verifier.py` valide chaque EvidenceItem contre `tool_calls_log`.
  Un scénario avec `grounding_score < 0.8` est flaggé `[HALLUCINATION WARNING]`.
- Périmètre documenté : si un service manque un signal, on l'exclut du scénario et on le documente.

## Definition of Done par jalon

> Statut réel daté dans `docs/PROGRESS.md`. **Code écrit ≠ éval validée** : à ce jour le code
> M0-M4 existe mais l'éval est creuse (snapshot sans signal discriminant, run "Acc@1=1.0" =
> hallucination flaggée à grounding=0.0). DoD considéré atteint seulement sur vrais signaux.

| Jalon | Livrable principal           | DoD (critère binaire)                                                    | Statut 2026-06-14        |
|-------|------------------------------|-------------------------------------------------------------------------|--------------------------|
| M0    | Infra kind + backends        | `make health-check` exit 0, traces non-vides dans Tempo                 | code ✅ / cluster à relancer |
| M1    | DataSource + snapshots       | `pytest tests/test_datasources.py` vert, 1 snapshot replay reproductible| code ✅ / live non validé |
| M2    | Agent LangGraph              | Agent produit InvestigationReport valide (Pydantic) sur 1 scénario live | code ✅ / agent hallucine |
| M3    | Harnais d'évaluation         | `make eval` produit results.json avec 7 métriques, 7 scénarios MVP      | code ✅ / éval creuse ❌   |
| M4    | Baselines + résultats (MVP)  | `make compare` produit table complète, artifacts/ committé, README à jour| code ✅ / pas comparé ❌   |
| M5    | 35 scénarios × 3 seeds       | results_full.json committé, tous scénarios passent le harnais           | bloqué (éval-first)      |
| M6    | UI + déploiement             | `docker run otel-sre-copilot:latest` démarre en API mode                | non commencé             |
