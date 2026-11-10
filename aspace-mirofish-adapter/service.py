#!/usr/bin/env python3
"""Lanceur du service MiroFish — frontiere de service A'Space (D-N053, pas A).

MiroFish tourne comme un processus SEPARE, jamais lie au Runtime :
ce module ne fait qu'executer ``backend/run.py`` (le vrai backend amont)
comme processus fils, sur 127.0.0.1 uniquement, et attendre sa sante
HTTP. Il n'importe AUCUN module MiroFish (stdlib seule).

Usage operateur (cles via l'environnement, jamais dans ce depot) :
    export LLM_API_KEY=... ZEP_API_KEY=...
    python3 service.py start [--port 5150] [--timeout 180]
    python3 service.py status
    python3 service.py stop

Regles dures :
- hote force a 127.0.0.1 (toute autre valeur refusee) ;
- LLM_API_KEY et ZEP_API_KEY obligatoires et non vides (miroir de
  Config.validate() amont) ; ZEP_API_URL refuse (non supporte par
  l'amont) ; FLASK_DEBUG force a false ;
- aucune valeur de cle n'est jamais journalisee.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

ADAPTER_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(ADAPTER_DIR)
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
RUN_PY = os.path.join(BACKEND_DIR, "run.py")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5150
DEFAULT_TIMEOUT = 180.0
STOP_GRACE = 15.0

# Les cles ne vivent que dans l'environnement de l'operateur.
REQUIRED_KEYS = ("LLM_API_KEY", "ZEP_API_KEY")


def _tmpdir():
    return os.environ.get("TMPDIR") or "/tmp"


def default_pid_file():
    return os.environ.get(
        "MIROFISH_SERVICE_PIDFILE",
        os.path.join(_tmpdir(), "mirofish-service.pid"),
    )


def default_log_file():
    return os.environ.get(
        "MIROFISH_SERVICE_LOG",
        os.path.join(_tmpdir(), "mirofish-service.log"),
    )


def service_host():
    host = os.environ.get("MIROFISH_SERVICE_HOST", DEFAULT_HOST)
    if host != DEFAULT_HOST:
        raise ValueError(
            "MIROFISH_SERVICE_HOST=%r refuse : la frontiere de service "
            "est locale uniquement (127.0.0.1)" % host
        )
    return host


def service_port():
    raw = os.environ.get("MIROFISH_SERVICE_PORT", str(DEFAULT_PORT))
    try:
        port = int(raw)
    except ValueError:
        raise ValueError("MIROFISH_SERVICE_PORT=%r n'est pas un port" % raw)
    if not 1 <= port <= 65535:
        raise ValueError("MIROFISH_SERVICE_PORT=%r hors plage" % raw)
    return port


def validate_environment():
    """Controle pre-demarrage. Ne journalise jamais les valeurs."""
    errors = []
    if os.environ.get("ZEP_API_URL"):
        errors.append("ZEP_API_URL n'est pas supporte par MiroFish (Zep Cloud seul)")
    for key in REQUIRED_KEYS:
        if not (os.environ.get(key) or "").strip():
            errors.append("%s non configure (variable d'environnement requise)" % key)
    if not os.path.isfile(RUN_PY):
        errors.append("backend amont introuvable : %s" % RUN_PY)
    return errors


def health_url(host, port):
    return "http://%s:%d/health" % (host, port)


def _probe_health(host, port, timeout=5.0):
    try:
        with urllib.request.urlopen(health_url(host, port), timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def _read_pid(pid_file):
    try:
        with open(pid_file, "r", encoding="utf-8") as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


def _pid_alive(pid):
    """Vrai si le processus tourne. Un zombie (etat Z) est mort :
    il n'a simplement pas encore ete moissonne par son parent."""
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False
    try:
        with open("/proc/%d/stat" % pid, "r", encoding="utf-8") as fh:
            state = fh.read().rsplit(") ", 1)[1].split()[0]
        return state != "Z"
    except (OSError, IndexError):
        return True


# Processus demarres par CE processus (pour les moissonner a l'arret).
_PROCS = {}


def start(host, port, timeout=DEFAULT_TIMEOUT, pid_file=None, log_file=None):
    """Demarre le vrai backend MiroFish comme processus separe."""
    pid_file = pid_file or default_pid_file()
    log_file = log_file or default_log_file()
    errors = validate_environment()
    if errors:
        raise RuntimeError("refus de demarrage : " + "; ".join(errors))

    existing = _read_pid(pid_file)
    if existing and _pid_alive(existing) and _probe_health(host, port):
        return {"status": "already_running", "pid": existing, "host": host, "port": port}

    env = dict(os.environ)
    env["FLASK_HOST"] = host
    env["FLASK_PORT"] = str(port)
    env["FLASK_DEBUG"] = "false"
    env["PYTHONUNBUFFERED"] = "1"
    env.pop("ZEP_API_URL", None)

    log_fh = open(log_file, "ab")
    proc = subprocess.Popen(
        [sys.executable, RUN_PY],
        cwd=BACKEND_DIR,
        env=env,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    _PROCS[proc.pid] = proc
    with open(pid_file, "w", encoding="utf-8") as fh:
        fh.write(str(proc.pid))

    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            tail = ""
            try:
                with open(log_file, "rb") as fh:
                    fh.seek(max(0, os.path.getsize(log_file) - 4000))
                    tail = fh.read().decode("utf-8", "replace")
            except OSError:
                pass
            raise RuntimeError(
                "le service MiroFish s'est arrete (rc=%d) avant d'etre pret ; "
                "fin du journal :\n%s" % (proc.returncode, tail)
            )
        if _probe_health(host, port):
            return {"status": "started", "pid": proc.pid, "host": host, "port": port}
        time.sleep(1.0)
    stop(pid_file=pid_file)
    raise RuntimeError(
        "delai de demarrage depasse (%ss) : /health n'a pas repondu" % timeout
    )


def stop(pid_file=None, grace=STOP_GRACE):
    """Arret propre : SIGTERM au groupe, puis SIGKILL apres delai."""
    pid_file = pid_file or default_pid_file()
    pid = _read_pid(pid_file)
    if pid is None:
        return {"status": "not_running", "pid": None}
    if not _pid_alive(pid):
        try:
            os.unlink(pid_file)
        except OSError:
            pass
        return {"status": "not_running", "pid": pid}
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    proc = _PROCS.pop(pid, None)
    killed = False
    if proc is not None:
        # On est le parent : on moissonne (sinon le fils reste zombie
        # et kill(pid, 0) reussit alors qu'il est mort).
        try:
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
            killed = True
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
    else:
        deadline = time.time() + grace
        while time.time() < deadline and _pid_alive(pid):
            time.sleep(0.25)
        if _pid_alive(pid):
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
            killed = True
            time.sleep(0.5)
    try:
        os.unlink(pid_file)
    except OSError:
        pass
    return {"status": "stopped", "pid": pid, "killed": killed}


def status(host, port, pid_file=None):
    pid_file = pid_file or default_pid_file()
    pid = _read_pid(pid_file)
    alive = bool(pid and _pid_alive(pid))
    healthy = _probe_health(host, port)
    return {"pid": pid, "alive": alive, "healthy": healthy, "host": host, "port": port}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Lanceur du service MiroFish")
    sub = parser.add_subparsers(dest="command", required=True)
    p_start = sub.add_parser("start", help="demarre le service")
    p_start.add_argument("--port", type=int, default=None)
    p_start.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    p_start.add_argument("--pid-file", default=None)
    p_start.add_argument("--log-file", default=None)
    sub.add_parser("stop", help="arrete le service proprement")
    sub.add_parser("status", help="etat du service")
    sub.add_parser("restart", help="redemarre le service")
    args = parser.parse_args(argv)

    try:
        host = service_host()
        port = args.port if getattr(args, "port", None) else service_port()
    except ValueError as exc:
        print("erreur : %s" % exc, file=sys.stderr)
        return 2

    try:
        if args.command == "start":
            print(json.dumps(start(host, port, args.timeout, args.pid_file, args.log_file)))
        elif args.command == "stop":
            print(json.dumps(stop()))
        elif args.command == "status":
            print(json.dumps(status(host, port)))
        elif args.command == "restart":
            stop()
            print(json.dumps(start(host, port, args.timeout, args.pid_file, args.log_file)))
    except (RuntimeError, ValueError, OSError) as exc:
        print("erreur : %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
