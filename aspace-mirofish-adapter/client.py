#!/usr/bin/env python3
"""Interface cliente HTTP locale du service MiroFish — frontiere de service.

Le Runtime n'appelle JAMAIS MiroFish par import : il passe par cette
interface, en HTTP sur 127.0.0.1 uniquement. Stdlib seule (urllib) :
aucune dependance, aucun import d'un module MiroFish.

Routes couvertes (relevees sur le backend amont au gel) :
    GET  /health
    GET  /api/graph/project/<id>      GET  /api/graph/project/list
    POST /api/graph/build             POST /api/graph/ontology/generate
    GET  /api/simulation/list         GET  /api/simulation/<id>
    POST /api/simulation/create       POST /api/simulation/prepare
    POST /api/report/generate         POST /api/report/generate/status
    GET  /api/report/list             GET  /api/report/<id>

Erreurs : MiroFishUnavailable (service injoignable), MiroFishTimeout,
MiroFishError (reponse HTTP d'erreur, statut + corps conserves).
"""

import json
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = "http://127.0.0.1:5150"
DEFAULT_TIMEOUT = 30.0


class MiroFishError(Exception):
    def __init__(self, status, payload=None, message=None):
        self.status = status
        self.payload = payload
        super().__init__(message or "MiroFish HTTP %s : %s" % (status, payload))


class MiroFishUnavailable(MiroFishError):
    def __init__(self, reason):
        self.status = None
        self.payload = None
        super().__init__(None, None, "service MiroFish injoignable : %s" % reason)


class MiroFishTimeout(MiroFishError):
    def __init__(self, reason):
        self.status = None
        self.payload = None
        super().__init__(None, None, "delai depasse vers le service MiroFish : %s" % reason)


def _check_loopback(base_url):
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("base_url %r : schema http(s) requis" % base_url)
    if parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError(
            "base_url %r refuse : la frontiere de service est locale "
            "uniquement (127.0.0.1)" % base_url
        )
    return base_url.rstrip("/")


class MiroFishClient:
    """Client HTTP local du service MiroFish. Aucun import MiroFish."""

    def __init__(self, base_url=DEFAULT_BASE_URL, timeout=DEFAULT_TIMEOUT):
        self.base_url = _check_loopback(base_url)
        self.timeout = timeout

    def request(self, method, path, body=None, params=None):
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None}
            )
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                payload = json.loads(raw) if raw else None
            except ValueError:
                payload = raw
            raise MiroFishError(exc.code, payload)
        except urllib.error.URLError as exc:
            raise MiroFishUnavailable(str(exc.reason))
        except TimeoutError as exc:
            raise MiroFishTimeout(str(exc))

    def get(self, path, params=None):
        return self.request("GET", path, params=params)

    def post(self, path, body=None):
        return self.request("POST", path, body=body or {})

    # -- sante ---------------------------------------------------------
    def health(self):
        """GET /health -> {'status': 'ok', 'service': 'MiroFish Backend'}."""
        return self.get("/health")

    # -- graphe --------------------------------------------------------
    def list_projects(self, limit=50):
        return self.get("/api/graph/project/list", params={"limit": limit})

    def get_project(self, project_id):
        return self.get("/api/graph/project/%s" % urllib.parse.quote(project_id))

    def build_graph(self, project_id, graph_name=None, chunk_size=500,
                    chunk_overlap=50):
        body = {"project_id": project_id, "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap}
        if graph_name:
            body["graph_name"] = graph_name
        return self.post("/api/graph/build", body)

    # -- simulation ----------------------------------------------------
    def list_simulations(self, project_id=None):
        return self.get("/api/simulation/list",
                        params={"project_id": project_id})

    def get_simulation(self, simulation_id):
        return self.get("/api/simulation/%s" % urllib.parse.quote(simulation_id))

    def create_simulation(self, project_id, graph_id=None,
                          enable_twitter=True, enable_reddit=True):
        body = {"project_id": project_id, "enable_twitter": enable_twitter,
                "enable_reddit": enable_reddit}
        if graph_id:
            body["graph_id"] = graph_id
        return self.post("/api/simulation/create", body)

    def prepare_simulation(self, simulation_id, **kwargs):
        body = {"simulation_id": simulation_id}
        body.update(kwargs)
        return self.post("/api/simulation/prepare", body)

    # -- rapport -------------------------------------------------------
    def generate_report(self, simulation_id, force_regenerate=False):
        return self.post("/api/report/generate",
                         {"simulation_id": simulation_id,
                          "force_regenerate": force_regenerate})

    def report_generate_status(self, task_id=None, simulation_id=None):
        body = {}
        if task_id:
            body["task_id"] = task_id
        if simulation_id:
            body["simulation_id"] = simulation_id
        return self.post("/api/report/generate/status", body)

    def list_reports(self, simulation_id=None, limit=50):
        return self.get("/api/report/list",
                        params={"simulation_id": simulation_id, "limit": limit})

    def get_report(self, report_id):
        return self.get("/api/report/%s" % urllib.parse.quote(report_id))


if __name__ == "__main__":
    import sys

    client = MiroFishClient()
    if len(sys.argv) < 2 or sys.argv[1] not in ("health", "list", "reports"):
        print("usage: client.py {health|list|reports}", file=sys.stderr)
        sys.exit(2)
    try:
        if sys.argv[1] == "health":
            print(json.dumps(client.health()))
        elif sys.argv[1] == "list":
            print(json.dumps(client.list_simulations()))
        else:
            print(json.dumps(client.list_reports()))
    except MiroFishError as exc:
        print("erreur : %s" % exc, file=sys.stderr)
        sys.exit(1)
