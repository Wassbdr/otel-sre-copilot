# DECISIONS — journal des décisions (ADR courts)

> Format : décision · pourquoi · alternative écartée. Append-only, daté en absolu.

## ADR-001 (2026-06-14) — Fiabiliser l'éval avant tout scaling ou polish

**Décision.** Prioriser la réparation de l'évaluation (capture télémétrie → vrais signaux →
run agent honnête vs baselines) avant M5 (35 scénarios), M6 (UI/Docker), ou cosmétique README.

**Pourquoi.** L'éval actuelle ne mesure rien de réel (snapshot sans signal discriminant ;
« Acc@1=1.0 » = hallucination flaggée à `grounding_score=0.0`). Scaler/polir maintenant
multiplierait des résultats vides. La rigueur d'éval honnête est la promesse du projet
(CLAUDE.md : « évaluation d'abord », « honnêteté »).

**Alternative écartée.** Suivre la roadmap M5/M6 telle quelle ; rejetée car elle reposerait
sur une base d'éval non validée.

## ADR-002 (2026-06-14) — Publier les résultats même si l'agent perd contre le Z-score

**Décision.** Rapporter les vrais chiffres (Acc@1/@3, MRR, fault_type, grounding, latency,
cost) sans filtre, agent vs random/zscore/composite_zscore — y compris si l'agent n'égale pas
la baseline composite Z-score.

**Pourquoi.** C'est l'angle différenciant et honnête : « on mesure l'hallucination, on publie
quand le LLM ne bat pas un Z-score ». Un résultat négatif documenté > un résultat gonflé.

**Alternative écartée.** Ne montrer que le happy-path ; rejetée (malhonnête, contraire aux
garde-fous CLAUDE.md).

## ADR-003 (2026-06-14) — Préserver le contexte via mémoire + docs versionnés

**Décision.** Maintenir l'état réel dans la mémoire projet (`memory/`) + `docs/PROGRESS.md`
(daté) + ce journal, mis à jour à chaque phase ; 1 commit par phase avec message clair.

**Pourquoi.** Éviter qu'une session future re-dérive le diagnostic « éval creuse » (coûteux).
`MEMORY.md` + `PROGRESS.md` = contexte rechargeable à bas coût et source de vérité partagée.

**Alternative écartée.** S'appuyer uniquement sur la mémoire auto / le code ; rejetée car la
mémoire affirmait à tort « M0-M4 COMPLETE, 50/50 tests ».

## ADR-004 (2026-06-18) — Gate spécifique pour les fautes de latence (rank-1 + saut vs baseline)

**Décision.** Pour `high_latency`, la gate ne teste PAS un outlier cross-service `|z|>=2`. Elle
exige : le service fauté est **top-3 par saut RELATIF de p99 (fault/baseline)** **ET** son saut
est **>= 3x son propre baseline**. Classement par RATIO, pas par p99 absolu. Implémenté dans
`_validate_latency`. (Révisé : la v1 « rank-1 absolu » échouait sur 006.)

**Pourquoi.** Un délai sur un service feuille **cascade** vers les SPAN SERVER de ses appelants ;
culprit et appelants montent ensemble → l'écart-type cross-service explose (product-catalog
z=1.16 alors qu'il est le pire à 23x son baseline). Mais le **p99 absolu** classe en tête les
agrégateurs lents déjà à 2-3s de baseline (frontend, checkout), PAS le culprit : sur 006,
shipping explose 129→5209ms (**40x**) mais n'est que rank-3 absolu derrière checkout (9347ms,
3.2x) et frontend (8811ms, 4.0x). Le signal honnête du culprit est le **saut relatif** : par
ratio, shipping est rank-1 (40x) et product-catalog rank-2 (23.5x, juste derrière recommendation
31.6x qui l'appelle) — les deux sont top-3 + >=3x. Le ratio isole le culprit des agrégateurs à
haut baseline. Pendant latence du symptôme error_rate qui remonte chez l'appelant (cf. 001).

**Alternative écartée.** (a) `|z|>=2` cross-service → exclurait toute latence (non-discriminative
par construction). (b) rank-1 sur p99 **absolu** → échoue quand un agrégateur lent dépasse le
culprit en absolu (mesuré 006 : shipping rank-3 absolu mais rank-1 en ratio). (c) Signal
« self/exclusive » isolant le délai propre → plus fidèle mais requête spanmetrics incertaine ;
reporté.

## ADR-005 (2026-06-19) — Gate spécifique pour http_abort (collapse request_rate vs baseline)

**Décision.** Pour `http_abort` (NetworkChaos `loss`), la gate exige que le request_rate du
service fauté soit tombé à **<= 50% de son propre baseline** (et que le baseline soit réel,
> 0.005 req/s). Implémenté dans `_validate_abort`. Pas de test d'outlier cross-service.

**Pourquoi.** Mesuré sur 003 (payment, loss:100) : la faute frappe réellement (request_rate
payment = 18.5% de son baseline), mais **non-discriminative** en z cross-service car (a) les
paquets droppés font que payment n'émet AUCUN span SERVER → `error_rate` spanmetrics (SERVER +
STATUS_CODE_ERROR) reste ~0 partout ; (b) le collapse de trafic de payment se confond avec 6
services naturellement inactifs (email/ad/accounting… à request_rate=0) → payment z=-0.49, pas
un outlier bas ; le seul outlier est frontend (+3.31, symptôme amont). Le signal honnête d'un
abort est l'effondrement du trafic du service ciblé vs sa propre normale.

**Alternative écartée.** (a) Garder error_rate cross-service → exclurait http_abort de l'éval
(signal structurellement absent avec loss). (b) Remplacer loss par un mécanisme générant de
vrais spans ERROR → risque de faire remonter l'erreur chez l'appelant (checkout) et coûte des
cycles de capture sur ce cluster saturé ; rejeté.

## ADR-006 (2026-06-19) — Gate self-relative pour cpu_stress / memory_stress

**Décision.** Pour `cpu_stress` et `memory_stress`, la gate exige que l'usage du service fauté
ait sauté **>= 3x son propre baseline** ET qu'il soit dans le **top-3 absolu** des consommateurs.
Implémenté dans `_validate_self_relative`. Pas de test d'outlier z cross-service. Stresseur
maintenu **modéré** (cpu : 2 workers @ 90%).

**Pourquoi.** L'usage cpu/mem est pod-labellisé → isolé au culprit (pas de cascade), MAIS sur cet
hôte WSL2 contraint **load-generator est le roi permanent des ressources** (cpu z=+3.49, 2.9
cores) : le culprit ne peut pas atteindre |z|>=2 cross-service même quand la faute frappe fort.
Mesuré 004 : 1 worker @ 80% → recommendation 0.93 cores = **30x son baseline** mais z=0.76,
rank 2. Pire, monter à 4 workers @ 100% a **crashé Prometheus** (OOM/restart #316, plan
d'observabilité indisponible ~2.5 min) → capture vide. Le signal honnête d'un stress est le saut
vs sa propre normale + rang absolu élevé, pas l'outlier de population.

**Alternative écartée.** (a) Exclure load-generator de la population z → garde le test de
population mais ad hoc et fragile (généralisation non vérifiée). (b) Stresseur agressif pour
forcer l'outlier → casse l'hôte (mesuré). (c) Exclure les fautes de stress de l'éval → réduit
l'éval à ~4-5 scénarios. Le self-relative est cohérent avec ADR-004/005.

## ADR-007 (2026-06-19) — memory_stress validé par l'OOMKill (pod_restarts), pas le working_set

**Décision.** Pour `memory_stress`, la gate accepte **soit** un saut working_set >= 3x baseline
(ADR-006) **soit** un outlier `pod_restarts` |z|>=2 top-3 (l'OOMKill). Le scénario 005 alloue
400MB sur cart dont la limite est **160Mi** → dépasse la limite → OOMKill + restart.

**Pourquoi.** cart a une limite mémoire dure de 160Mi : le working_set ne peut PAS spiker (le
noyau plafonne ; pousser plus fort ne fait qu'OOMKill). Mesuré 005 @256MB : working_set
107→119 MB = 1.11x, rank 8. De plus cart (160MB max) ne peut JAMAIS être top-3 absolu face aux
pods infra multi-Go (load-generator 2GB, opensearch 1.6GB, kafka 1.1GB). Le signal honnête d'une
faute mémoire qui atteint la limite EST l'OOMKill : un outlier de redémarrages, exactement comme
pod_crash. C'est plus fidèle au monde réel (un service qui fuit/sature sa RAM est OOMKillé).

**Alternative écartée.** (a) Abaisser le seuil working_set à 1.3x → signal trop faible et non
généralisable (dépend de la marge sous la limite). (b) Exclure memory_stress → l'OOMKill est un
mode de panne réel et important à couvrir. (c) Augmenter la limite mémoire de cart via helm →
modifie l'app cible, hors périmètre et fausse la repro.
