import base64
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import unittest
import uuid

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import network_plan as network


@unittest.skipIf(os.name == "nt", "POSIX private-file adapter")
class NetworkPlans(unittest.TestCase):
    def setUp(self):
        self.root = Path.home() / "AI/caches/claude-safe/tests" / uuid.uuid4().hex
        self.root.mkdir(parents=True, mode=0o700)
        self.keys = {}
        for i, name in enumerate(("server.key", "server.pub", "client.key", "client.pub"), 1):
            self.keys[name] = base64.b64encode(bytes([i]) * 32).decode()
            (self.root / name).write_text(self.keys[name] + "\n")
            (self.root / name).chmod(0o600)
        self.config = {"schema_version": 1, "endpoint_ipv4": "8.8.8.8", "port": 51820,
                       "egress_interface": "ens3", "server_private_key_file": "server.key",
                       "server_public_key_file": "server.pub", "client_private_key_file": "client.key",
                       "client_public_key_file": "client.pub", "server_cidr": "10.77.0.1/24",
                       "client_cidr": "10.77.0.2/32", "dns_ipv4": "1.1.1.1", "mtu": 1380}
        self.path = self.root / "network.json"
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.config))

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_cli_renders_two_sides_without_network_or_secret_output(self):
        for side in ("server", "client"):
            result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "network_plan.py"),
                                     "--input", str(self.path), "--side", side,
                                     "--output-dir", str(self.root / side)],
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "rendered_runtime_unverified")
            self.assertNotIn("8.8.8.8", result.stdout)
            for key in self.keys.values():
                self.assertNotIn(key, result.stdout + result.stderr)
            for path in (self.root / side).iterdir():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        conf = (self.root / "server/server.conf").read_text()
        self.assertIn("AllowedIPs = 10.77.0.2/32", conf)
        self.assertIn("-o ens3", conf)
        self.assertNotIn("-F", conf)
        overlay = json.loads((self.root / "client/mihomo-merge.json").read_text())
        self.assertEqual(overlay["proxy-groups"][0]["proxies"], ["Claude-Safe-WG"])
        self.assertNotIn("DIRECT", json.dumps(overlay))
        self.assertIn("Endpoint = 8.8.8.8:51820", (self.root / "client/client.conf").read_text())

    def test_each_side_only_reads_its_own_private_key(self):
        (self.root / "client.key").unlink()
        network.render(self.path, "server")
        (self.root / "server.key").unlink()
        (self.root / "client.key").write_text(self.keys["client.key"])
        (self.root / "client.key").chmod(0o600)
        network.render(self.path, "client")

    def test_rejects_injection_invalid_subnet_and_unroutable_endpoint_before_write(self):
        changes = [("egress_interface", "eth0; touch bad"), ("port", True), ("mtu", 65535),
                   ("endpoint_ipv4", "127.0.0.1"), ("endpoint_ipv4", "224.0.0.1"),
                   ("server_cidr", "192.0.2.1/24"), ("client_cidr", "10.77.1.2/32"),
                   ("client_cidr", "10.77.0.0/32"), ("client_cidr", "10.77.0.1/32")]
        original = dict(self.config)
        for key, value in changes:
            self.config = {**original, key: value}
            self.save()
            with self.subTest(key=key, value=value), self.assertRaises((network.safe.SafeError, ValueError)):
                network.generate(self.path, self.root / "bad-output", "server")
            self.assertFalse((self.root / "bad-output").exists())

    def test_rejects_shared_and_symlink_private_key(self):
        key = self.root / "client.key"
        key.chmod(0o644)
        with self.assertRaises(network.safe.SafeError):
            network.render(self.path, "client")
        key.chmod(0o600)
        key.rename(self.root / "original.key")
        key.symlink_to("original.key")
        with self.assertRaises(network.safe.SafeError):
            network.render(self.path, "client")

    def test_no_overwrite_of_existing_output(self):
        output = self.root / "output"
        network.generate(self.path, output, "client")
        before = {p.name: p.read_bytes() for p in output.iterdir()}
        with self.assertRaises(network.safe.SafeError):
            network.generate(self.path, output, "server")
        self.assertEqual(before, {p.name: p.read_bytes() for p in output.iterdir()})

    def test_invalid_secret_does_not_escape_cli_error(self):
        (self.root / "client.key").write_text("sensitive-invalid-key")
        result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "network_plan.py"),
                                 "--input", str(self.path), "--side", "client",
                                 "--output-dir", str(self.root / "output")],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("sensitive-invalid-key", result.stdout + result.stderr)
        self.assertFalse((self.root / "output").exists())


if __name__ == "__main__":
    unittest.main()
