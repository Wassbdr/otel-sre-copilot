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

**Décision.** Pour `high_latency`, la gate de validation snapshot ne teste PAS un outlier
cross-service `|z|>=2` (comme les autres fautes). Elle exige : le service fauté est **rank-1**
sur p99 (le pire) **ET** son p99 fenêtre-faute est **>= 2x son propre baseline** (la faute a
démonstrablement explosé au-dessus de sa normale). Implémenté dans `_validate_latency`.

**Pourquoi.** Un délai injecté sur un service feuille **cascade** vers les SPAN SERVER de tous
ses appelants (frontend/checkout/recommendation accumulent l'attente downstream). Culprit et
appelants montent ensemble → l'écart-type cross-service explose et même le rang 1 n'atteint pas
2σ (mesuré : product-catalog z=1.16 à 1.5s de délai, alors qu'il EST le pire à 7717ms = 23x son
baseline de 329ms). Augmenter le délai pousse toute la cascade ensemble (treadmill). Le test
honnête de « la faute de latence a fiéllement frappé ce service » est rank-1 + saut vs sa propre
baseline, pas l'outlier de population. C'est le pendant latence du symptôme error_rate qui
remonte chez l'appelant (cf. 001).

**Alternative écartée.** (a) Garder `|z|>=2` cross-service → exclurait toute faute de latence de
l'éval (non-discriminative par construction en topologie microservices). (b) Signal de latence
« self/exclusive » isolant le délai propre du culprit → plus fidèle mais nécessite une requête
spanmetrics possiblement non exportée et plus de cycles de capture ; reporté.

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
