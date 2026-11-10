#!/usr/bin/env python3
"""Suite de l'adapter MiroFish — stdlib seule, sans cles, sans reseau.

Couvre : contrat valide et fidele aux routes amont ; client refuse les
hotes non locaux et mappe les erreurs HTTP ; lanceur refuse de demarrer
sans cles, refuse les hotes non locaux et ZEP_API_URL ; aucun import
MiroFish dans l'adapter (H-A5, cote adapter).

Usage : python3 test_adapter.py [-v]
"""

import json
import os
import re
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import client as client_mod
import service as service_mod


def _load_contract():
    with open(os.path.join(HERE, "contract.json"), encoding="utf-8") as fh:
        return json.load(fh)


class ContractTests(unittest.TestCase):
    def test_contract_is_valid_json_with_required_sections(self):
        c = _load_contract()
        for key in ("service", "gel", "isolation", "endpoints", "errors",
                    "timeouts_seconds", "launcher", "client"):
            self.assertIn(key, c)
        self.assertEqual(c["service"], "MiroFish")
        self.assertEqual(c["gel"]["license"], "AGPL-3.0")
        self.assertEqual(c["gel"]["frozen_commit"],
                         "7657031ac01184afe2cb220f5ee3545573b5e843")
        self.assertEqual(c["gel"]["bind_commit"],
                         "9b49ac4fc6823ee033cf5c3f6e589e8cb721eff5")

    def test_contract_endpoints_match_upstream_routes(self):
        c = _load_contract()
        paths = {(e["method"], e["path"]) for e in c["endpoints"]}
        # Releve sur backend/app/__init__.py + api/*.py au gel.
        for expected in {
            ("GET", "/health"),
            ("GET", "/api/graph/project/list"),
            ("POST", "/api/graph/build"),
            ("POST", "/api/graph/ontology/generate"),
            ("GET", "/api/simulation/list"),
            ("POST", "/api/simulation/create"),
            ("POST", "/api/simulation/prepare"),
            ("POST", "/api/report/generate"),
            ("POST", "/api/report/generate/status"),
            ("GET", "/api/report/list"),
        }:
            self.assertIn(expected, paths)

    def test_isolation_is_loopback_only(self):
        c = _load_contract()
        self.assertEqual(c["isolation"]["host"], "127.0.0.1")
        self.assertEqual(c["isolation"]["mode"], "service_separe")

    def test_config_example_has_no_real_secret(self):
        with open(os.path.join(HERE, "config.example"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("LLM_API_KEY=", text)
        self.assertNotRegex(text, r"(?m)^(LLM_API_KEY|ZEP_API_KEY)=[^\s]{8,}$")


class ClientTests(unittest.TestCase):
    def test_refuses_non_loopback_host(self):
        for bad in ("http://192.168.1.10:5150", "https://mirofish.example.com",
                    "http://10.0.0.5:5150"):
            with self.assertRaises(ValueError):
                client_mod.MiroFishClient(bad)

    def test_accepts_loopback_hosts(self):
        for ok in ("http://127.0.0.1:5150", "http://localhost:5150"):
            self.assertTrue(client_mod.MiroFishClient(ok).base_url.startswith("http://"))

    def test_maps_http_error_and_unavailable(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/health":
                    body = b'{"status": "ok", "service": "MiroFish Backend"}'
                    self.send_response(200)
                else:
                    body = b'{"success": false, "error": "nope"}'
                    self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            cli = client_mod.MiroFishClient(
                "http://127.0.0.1:%d" % server.server_address[1], timeout=5.0
            )
            self.assertEqual(cli.health()["status"], "ok")
            with self.assertRaises(client_mod.MiroFishError) as ctx:
                cli.get("/api/simulation/nonexistent")
            self.assertEqual(ctx.exception.status, 404)
        finally:
            server.shutdown()
            server.server_close()
        with self.assertRaises(client_mod.MiroFishUnavailable):
            client_mod.MiroFishClient("http://127.0.0.1:1", timeout=2.0).health()


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self._saved = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved)

    def test_refuses_start_without_keys(self):
        os.environ.pop("LLM_API_KEY", None)
        os.environ.pop("ZEP_API_KEY", None)
        errors = service_mod.validate_environment()
        self.assertTrue(any("LLM_API_KEY" in e for e in errors))
        self.assertTrue(any("ZEP_API_KEY" in e for e in errors))

    def test_refuses_zep_api_url(self):
        os.environ["LLM_API_KEY"] = "dummy"
        os.environ["ZEP_API_KEY"] = "dummy"
        os.environ["ZEP_API_URL"] = "https://example.invalid"
        errors = service_mod.validate_environment()
        self.assertTrue(any("ZEP_API_URL" in e for e in errors))

    def test_refuses_non_loopback_host(self):
        os.environ["MIROFISH_SERVICE_HOST"] = "0.0.0.0"
        with self.assertRaises(ValueError):
            service_mod.service_host()

    def test_start_without_keys_raises(self):
        os.environ.pop("LLM_API_KEY", None)
        os.environ.pop("ZEP_API_KEY", None)
        with self.assertRaises(RuntimeError):
            service_mod.start("127.0.0.1", 5159, timeout=1.0)


class NoImportTests(unittest.TestCase):
    def test_adapter_imports_no_mirofish_module(self):
        """H-A5, cote adapter : stdlib seule, aucun import amont.

        Ne lit que les vraies lignes d'import (pas les commentaires ni
        les chaines) : le module importe de chaque ligne `import` /
        `from` doit etre stdlib ou un module de l'adapter lui-meme.
        """
        banned_toplevel = {
            "app", "backend", "flask", "flask_cors", "zep_cloud",
            "camel", "camel_ai", "oasis", "openai",
        }
        import_line = re.compile(r"(?m)^\s*(?:from\s+(\S+)|import\s+(\S+))")
        for name in ("service.py", "client.py", "smoke_test.py", "test_adapter.py"):
            with open(os.path.join(HERE, name), encoding="utf-8") as fh:
                text = fh.read()
            for match in import_line.finditer(text):
                module = (match.group(1) or match.group(2)).split(".")[0]
                self.assertNotIn(
                    module, banned_toplevel,
                    "import interdit dans %s : %s" % (name, match.group(0).strip()),
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
