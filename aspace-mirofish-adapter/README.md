# aspace-mirofish-adapter — frontière de service MiroFish

**D-N053, pas A — MiroFish, isolé en service (§D2 du design Clara).**
MiroFish (AGPL-3.0, seul copyleft du Runtime) tourne comme un **service
séparé** : son propre processus, derrière une interface HTTP locale.
Le Runtime l'appelle par l'interface — **jamais lié : aucun import,
aucun processus partagé**. L'obligation AGPL est confinée au service
lui-même (sa source est offerte sous AGPL — le fork, déjà AGPL, inchangé).

## Fichiers

| Fichier | Rôle |
|---|---|
| `service.py` | Lanceur : démarre `backend/run.py` comme processus séparé (127.0.0.1, port 5150 par défaut), attend `/health`, arrêt propre |
| `client.py` | Interface cliente HTTP locale (stdlib seule, `urllib`) : santé, graphe, simulation, rapport |
| `contract.json` | Contrat de service lisible par machine (endpoints, formes, délais, erreurs) |
| `SERVICE-CONTRACT.md` | Contrat de service (ce que le service offre, ce qu'il ne fait pas) |
| `config.example` | Configuration opérateur (exemple, sans secret) |
| `smoke_test.py` | Smoke : démarrage réel, `/health` par le client, arrêt propre |
| `test_adapter.py` | Suite de l'adapter (stdlib, `unittest`) |

**Seul code A'Space du fork** — le code amont est byte-identique au gel
(diff gel → adapter = ces fichiers seuls, H-M2).

## Usage opérateur

```bash
# Cles via l'environnement uniquement (jamais dans ce depot) :
export LLM_API_KEY=... ZEP_API_KEY=...

python3 aspace-mirofish-adapter/service.py start    # demarre, attend /health
python3 aspace-mirofish-adapter/service.py status   # pid + sante
python3 aspace-mirofish-adapter/client.py health    # {'status': 'ok', ...}
python3 aspace-mirofish-adapter/service.py stop     # arret propre
```

Port par défaut 5150 (`MIROFISH_SERVICE_PORT`), hôte forcé 127.0.0.1.
Sans clés, le service refuse de démarrer (comportement amont).

## Tests

```bash
python3 aspace-mirofish-adapter/test_adapter.py   # suite (stdlib, sans cles)
python3 aspace-mirofish-adapter/smoke_test.py     # smoke (demarre le vrai backend)
```

Le smoke exige les clés en variables d'environnement (des valeurs
factices suffisent pour `/health` : la santé n'appelle ni LLM ni Zep ;
une simulation réelle exige des clés valides et consomme du quota —
elle n'est jamais lancée par ces tests).

## Preuves d'isolation (H-A5)

1. **Aucun import MiroFish dans le code du Runtime** : `service.py` et
   `client.py` sont stdlib seule ; le client ne connaît MiroFish que par
   HTTP. Vérifié par scan (`grep` sur l'adapter + sur le Runtime).
2. **Processus séparé** : le lanceur exécute `backend/run.py` comme
   processus fils (`subprocess.Popen`, `start_new_session=True`) avec
   son propre PID, vérifié par le smoke.
3. **Interface HTTP-locale** : tous les appels passent par HTTP sur
   127.0.0.1 (le client refuse tout autre hôte).
