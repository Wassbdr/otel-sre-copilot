# PROGRESS — état réel du projet

> Source de vérité datée (dates absolues). Mise à jour à chaque phase. But : qu'une nouvelle
> session comprenne l'état réel sans relire le code ni les snapshots. Distinguer toujours
> **code écrit** de **éval validée**.

## TL;DR (2026-06-14, mis à jour en fin de session)

L'**éval est maintenant RÉELLE** sur le scénario 001 (checkout pod_crash) : signal discriminant
validé (gate PASS, checkout outlier z=2.58 sur pod_restarts), snapshot 168/180 requêtes non
vides, et résultat de baselines HONNÊTE et interprétable :
- random → load-generator (faux), zscore error-rate → **frontend** (faux : le symptôme erreur
  remonte chez l'appelant), composite_zscore 5-signaux → **checkout / pod_crash (Acc@1=1)**.
C'est exactement la thèse du projet : la heuristique naïve échoue, le composite Z-score (avec
pod_restarts) réussit et constitue la vraie baseline que l'agent LLM doit battre.

5 causes racines de l'« éval creuse » corrigées : (1) `.env` ports morts, (2) `service.name`
non défini (helm), (3) sélecteurs Chaos invalides (fautes jamais injectées), (4) naming 1.x↔2.x,
(5) ReplayDataSource ignorait la fenêtre temporelle → Z-scores toujours nuls. Ajouts : connecteur
spanmetrics (RED uniformes), gate de validation snapshot, cohérence ground_truth, agent forcé
d'investiguer avant de conclure. 51 tests offline verts.

**Reste à faire** : capturer 002-007 (gate), run agent live + éval honnête vs baselines sur les
7 scénarios, puis README/CI/LICENSE (Phase 4).

## État par jalon

| Jalon | Code | Éval validée | Note |
|-------|------|--------------|------|
| M0 infra | ✅ | ✅ | cluster relancé, health-check exit 0, service.name + spanmetrics fixés |
| M1 datasource | ✅ | ✅ | Replay fixé (match fenêtre) ; Live validé (capture 001 réelle) |
| M2 agent | ✅ | ⚠️ à re-tester | forcé d'investiguer avant conclusion ; run live à refaire |
| M3 harnais éval | ✅ | ⚠️ 1/7 | métriques OK ; 001 capturé+validé, 002-007 à capturer |
| M4 baselines | ✅ | ⚠️ 1/7 | comparaison réelle sur 001 (composite gagne) ; étendre aux 7 |
| M5 35 scénarios | ❌ | ❌ | `scenarios/full/` vide — après MVP fiable |
| M6 UI/Docker | ❌ | ❌ | non commencé |

## Preuves (artefacts committés)

- Snapshot `checkoutservice-pod_crash-seed42` : Prometheus 12/180 requêtes non vides
  (CPU/mem only). error_rate HTTP **0/60**, p99 latency **0/30**, logs Loki **0/30**,
  events K8s « Normal » uniquement. Restarts capturés pour frontend+flagd, **pas**
  checkoutservice (le service fauté).
- `artifacts/20260612T215219Z` : run agent Acc@1=1.0 **mais** 1 seul appel outil
  (`get_service_topology`), evidence error_rate fabriquée → `grounding_score=0.0`,
  `hallucination_warning=true`.
- Incohérence repro : `ground_truth.injection_ts=2026-06-13T07:10` vs fenêtre télémétrie
  `2026-06-12T21:45` (deux injections différentes).

## Plan actif (validé 2026-06-14)

Phase 0 cluster + health-check → Phase 1 réparer capture télémétrie (vrais noms de métriques,
faire atterrir HTTP/logs dans Prometheus/Loki, cohérence ground_truth, gate de validation
snapshot) → Phase 2 recapturer 7 snapshots → Phase 3 corriger agent + **run éval honnête vs
baselines** → Phase 4 README/CI/LICENSE. Détail dans le plan d'implémentation.

## Journal des phases

- **2026-06-14** — Audit honnête du repo : diagnostic « éval creuse » documenté ci-dessus.
  Mémoire projet corrigée, docs PROGRESS/DECISIONS créés. Démarrage Phase 0.
- **2026-06-14** — Phase 0 OK : cluster kind relancé (`docker start` du node, pas de recréation)
  + `make health-check` exit 0. Cause racine de l'échec health-check : `.env` pointait sur des
  ports morts `19090/13200/13100` au lieu de `9090/3200/3100` (corrigé, .env est gitignored).
- **2026-06-14** — Phase 1a (découverte) : root causes de l'éval creuse identifiées sur cluster live.
  L'app déployée est **OTel Demo 2.2.0** (noms courts `checkout`, `cart`, `product-catalog`…),
  alors que le code suppose la 1.x (`checkoutservice`…). Trois bugs structurels :
  1. **Sélecteurs Chaos Mesh invalides** : `app: checkoutservice` matche 0 pod (label réel
     `app.kubernetes.io/component: checkout`) → la faute n'a JAMAIS été injectée.
  2. **`service.name` non défini** : `default.env` dans astronomy-shop-values.yaml écrase la
     liste env du chart et supprime `OTEL_SERVICE_NAME`/`OTEL_RESOURCE_ATTRIBUTES` → toutes les
     métriques ET traces sont labellisées `unknown_service:*` (Node.js tous fusionnés en
     `unknown_service:/nodejs/bin/node`). Seuls cart/flagd ont une identité propre.
  3. **Naming 1.x→2.x** à propager partout (queries, pod regex, topo, baselines, scénarios).
  Signaux fiables malgré tout : métriques pod-labellisées (cpu/mem/restarts via `pod=~"<svc>-.*"`,
  ns otel-demo) et — une fois service.name corrigé — les traces Tempo par service.
  Fix en cours : (a) restaurer OTEL_SERVICE_NAME (helm), (b) corriger sélecteurs chaos,
  (c) migration de nommage + templates de requêtes.
