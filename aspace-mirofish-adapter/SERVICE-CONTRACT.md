# Contrat de service — MiroFish (D-N053, pas A)

**Service :** MiroFish — moteur d'intelligence de swarm (OASIS + MindGraph),
« predicting anything ». **Licence : AGPL-3.0** (fork ET amont).
**Décision §D2 (tranchée) : isolé en service** — ni adapté en bibliothèque,
ni remplacé. Ce document est le contrat ; `contract.json` en est la forme
lisible par machine.

## Ce que le service offre

- Un moteur de simulation multi-agents : construction d'un graphe
  (ontologie + entités + mémoire), préparation d'une simulation OASIS
  (profils d'agents, configuration), exécution de la simulation
  (Twitter / Reddit en parallèle), génération d'un rapport d'analyse.
- Une API HTTP locale : sante (`GET /health`), graphe
  (`/api/graph/*`), simulation (`/api/simulation/*`), rapport
  (`/api/report/*`) — formes exactes dans `contract.json`.
- Un cycle de vie propre : démarrage, sante, arrêt propre (SIGTERM,
  15 s de grâce, puis SIGKILL).

## Ce que le service ne fait pas

- **Il n'est jamais importé par le Runtime.** Le Runtime l'appelle par
  HTTP sur 127.0.0.1, jamais par import, jamais par processus partagé.
  C'est le cœur du hold-out H-A5 : un import MiroFish dans le code du
  Runtime casserait l'isolation AGPL.
- **Il n'est jamais exposé sur le réseau.** Hôte forcé à 127.0.0.1 ;
  toute autre valeur est refusée par le lanceur. Pas d'usage en B2B
  sans arbitrage vision (AGPL).
- **Il ne démarre pas sans clés opérateur** (`LLM_API_KEY`,
  `ZEP_API_KEY`, variables d'environnement uniquement, jamais dans ce
  dépôt, jamais journalisées). Sans clés, le service refuse de
  démarrer — c'est le comportement amont (`Config.validate()`).
- **Il n'émet aucune télémétrie.** Aucun SDK d'analytique dans le
  backend. Les seuls appels sortants sont fonctionnels et déclenchés
  par l'opérateur : le LLM configuré (`LLM_BASE_URL`) et Zep Cloud
  (`https://api.getzep.com/api/v2`), uniquement pendant une simulation
  ou une construction de graphe, jamais par défaut (voir l'audit).
- **Il ne sert pas le frontend.** L'interface web (`frontend/`) n'est
  pas dans le périmètre de la frontière ; seul le backend est servi.
- **Il ne simule pas sans coût.** Une simulation consomme du LLM
  (l'amont recommande de commencer par moins de 40 tours) et du quota
  Zep. Aucune simulation n'est lancée par l'adapter lui-même.

## Forme des échanges

- Toutes les réponses sont JSON : `{"success": true, "data": ...}` ou
  `{"success": false, "error": ...}` ; erreurs HTTP 400 (requête
  invalide), 404 (projet / simulation / tâche / rapport introuvable),
  500 (erreur interne, journalisée côté service).
- Les opérations longues (`/prepare`, `/generate`) sont asynchrones :
  elles rendent un `task_id` immédiatement ; le progrès se suit par
  `/prepare/status` et `/generate/status`.
- Délais : santé 5 s, appel 30 s par défaut, démarrage 180 s,
  arrêt 15 s de grâce.

## Limites connues (dette de divergence)

- Le gel est `7657031` (tête amont au 2026-11-10) ; la dérive amont
  est 0 au gel. Toute évolution amont est une revisite par signal,
  jamais un fast-forward silencieux.
- Le backend exige Python 3.11–3.12 et ses dépendances
  (`backend/requirements.txt`) ; les simulations OASIS exigent en plus
  `camel-oasis` / `camel-ai` (imports paresseux, chargés seulement
  pendant une simulation).
- Propriétaire : cœur Buzz (lane Clara / 12e).
