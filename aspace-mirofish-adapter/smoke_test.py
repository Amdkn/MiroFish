#!/usr/bin/env python3
"""Smoke du service MiroFish — demarrage reel, appel client reel, arret propre.

Demarre le VRAI backend MiroFish (backend/run.py) comme processus separe
via service.py, verifie que son PID differe du notre, appelle /health
via client.py, appelle GET /api/simulation/list via client.py, puis
arrete proprement et verifie que le processus est mort.

Cles : LLM_API_KEY / ZEP_API_KEY doivent etre presentes dans
l'environnement. Des valeurs factices suffisent ici : /health et /list
n'appellent ni LLM ni Zep. Aucune simulation n'est lancee (elle
consommerait du quota) ; aucune valeur de cle n'est journalisee.

Usage : python3 smoke_test.py [--port 5151] [--timeout 180]
Sortie : rapport JSON sur stdout ; code 0 si tout passe.
"""

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import client as client_mod
import service as service_mod


def main():
    parser = argparse.ArgumentParser(description="Smoke du service MiroFish")
    parser.add_argument("--port", type=int, default=5151)
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    report = {
        "service": "MiroFish",
        "mode": "real_backend",
        "launcher_pid": os.getpid(),
        "checks": {},
        "ok": False,
    }
    pid_file = os.path.join(
        os.environ.get("TMPDIR") or "/tmp", "mirofish-smoke.pid"
    )
    log_file = os.path.join(
        os.environ.get("TMPDIR") or "/tmp", "mirofish-smoke.log"
    )
    started = None
    try:
        # 0. Pre-conditions : cles presentes (valeurs jamais journalisees).
        env_errors = service_mod.validate_environment()
        # validate_environment exige aussi run.py ; on filtre les cles.
        key_errors = [e for e in env_errors if "non configure" in e]
        report["checks"]["keys_present"] = not key_errors
        if key_errors:
            report["error"] = "cles operateur absentes : " + "; ".join(key_errors)
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 1

        # 1. Demarrage du vrai backend comme processus separe.
        host = "127.0.0.1"
        t0 = time.time()
        started = service_mod.start(
            host, args.port, timeout=args.timeout,
            pid_file=pid_file, log_file=log_file,
        )
        report["service_pid"] = started["pid"]
        report["checks"]["separate_process"] = started["pid"] != os.getpid()
        report["checks"]["started"] = started["status"] in ("started", "already_running")
        report["startup_seconds"] = round(time.time() - t0, 1)

        # 2. /health via l'interface cliente (HTTP local).
        cli = client_mod.MiroFishClient(
            "http://%s:%d" % (host, args.port), timeout=10.0
        )
        health = cli.health()
        report["health"] = health
        report["checks"]["health_ok"] = health.get("status") == "ok"

        # 3. Un appel d'API reel via l'interface cliente.
        try:
            listing = cli.list_simulations()
            report["list_simulations"] = listing
            report["checks"]["api_responds"] = listing.get("success") is True
        except client_mod.MiroFishError as exc:
            report["list_simulations_error"] = str(exc)
            report["checks"]["api_responds"] = False

        report["ok"] = all(report["checks"].values())
    except Exception as exc:  # noqa: BLE001 - le smoke rapporte, il ne plante pas
        report["error"] = str(exc)
    finally:
        # 4. Arret propre, verifie.
        t0 = time.time()
        stop = service_mod.stop(pid_file=pid_file)
        report["stop"] = stop
        deadline = time.time() + 15
        pid = (started or {}).get("pid")
        dead = pid is None or not service_mod._pid_alive(pid)
        while not dead and time.time() < deadline:
            time.sleep(0.25)
            dead = not service_mod._pid_alive(pid)
        report["checks"]["stopped_cleanly"] = dead
        report["stop_seconds"] = round(time.time() - t0, 1)
        report["ok"] = all(report["checks"].values()) and report.get("ok", False)

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
