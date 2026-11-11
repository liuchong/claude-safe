import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import unittest
import uuid
from unittest import mock

SPEC = importlib.util.spec_from_file_location("claude_safe", Path(__file__).resolve().parents[1] / "scripts/claude_safe.py")
safe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(safe)


class InspectionTests(unittest.TestCase):
    def test_secret_values_never_enter_report(self):
        secret = "never-output-this-password"
        with mock.patch.object(safe.platform, "system", return_value="Other"):
            result = safe.inspect_environment(environ={"HTTPS_PROXY": "https://user:" + secret + "@proxy.test/x?key=" + secret,
                "ANTHROPIC_API_KEY": secret, "CLAUDE_CODE_OAUTH_TOKEN": secret})
        self.assertNotIn(secret, json.dumps(result))
        self.assertEqual(result["environment"]["HTTPS_PROXY"], {"present": True})
        self.assertEqual(result["effective_claude_route"], "not_checked")
        self.assertEqual(result["account_status"], "not_checked")

    def test_http_response_never_proves_account_or_route(self):
        response = subprocess.CompletedProcess([], 0, "401", "")
        with mock.patch.object(safe.shutil, "which", return_value="curl"), mock.patch.object(safe.subprocess, "run", return_value=response) as run:
            result = safe.probe("https://example.com/", 2)
        self.assertEqual(result["http_status"], 401)
        self.assertFalse(result["account_verified"])
        self.assertFalse(result["route_verified"])
        self.assertEqual(run.call_args.kwargs["timeout"], 4)
        self.assertIn("--max-time", run.call_args.args[0])

    def test_probe_kills_wait_at_deadline(self):
        with mock.patch.object(safe.shutil, "which", return_value="curl"), mock.patch.object(safe.subprocess, "run", side_effect=subprocess.TimeoutExpired("curl", 3)):
            self.assertEqual(safe.probe("https://example.com/", 1)["status"], "connection_failed")

    def test_probe_rejects_credentials_and_non_https(self):
        for url in ("http://example.com/", "https://user:password@example.com/", "https://example.com/?token=secret", "https://example.com/#secret"):
            with self.subTest(url=url), self.assertRaises(safe.SafeError):
                safe.probe(url, 1)


@unittest.skipIf(os.name == "nt", "POSIX file transaction adapter; Windows write support is intentionally unavailable")
class FileTransactions(unittest.TestCase):
    def setUp(self):
        self.root = Path.home() / "AI/caches/claude-safe/tests" / uuid.uuid4().hex
        self.root.mkdir(parents=True, mode=0o700)
        self.state = self.root / "state"
        self.target = self.root / "config.json"
        self.target.write_bytes(b"original\n")
        self.target.chmod(0o640)

    def tearDown(self):
        shutil.rmtree(self.root)

    def plan(self, entries=None, authorized=None):
        if entries is None:
            staged = self.root / "new.txt"
            staged.write_bytes(b"updated\n")
            entries = [{"path": "config.json", "before_sha256": hashlib.sha256(b"original\n").hexdigest(), "content_file": "new.txt"}]
        if authorized is None:
            authorized = [x["path"] for x in entries]
        path = self.root / "plan.json"
        path.write_text(json.dumps({"schema_version": 1, "authorized_files": authorized, "files": entries}))
        return str(path)

    def test_apply_repeat_and_restore_preserve_content_and_mode(self):
        plan = self.plan()
        result = safe.apply_files(plan, str(self.state))
        self.assertEqual(self.target.read_bytes(), b"updated\n")
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o640)
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o700)
        backup = self.state / result["transaction"] / "0.backup"
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
        self.assertEqual(safe.apply_files(plan, str(self.state))["status"], "unchanged")
        self.assertEqual(len(list(self.state.iterdir())), 1)
        self.assertEqual(safe.rollback(str(self.state), result["transaction"])["status"], "rolled_back")
        self.assertEqual(self.target.read_bytes(), b"original\n")
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o640)

    def test_complete_preflight_prevents_partial_write(self):
        self.plan()
        second = self.root / "second.txt"
        second.write_bytes(b"someone else changed it")
        entries = [{"path": "config.json", "before_sha256": safe.digest(self.target.read_bytes()), "content_file": "new.txt"},
                   {"path": "second.txt", "before_sha256": "0" * 64, "content_file": "new.txt"}]
        with self.assertRaises(safe.SafeError):
            safe.apply_files(self.plan(entries), str(self.state))
        self.assertEqual(self.target.read_bytes(), b"original\n")
        self.assertEqual(second.read_bytes(), b"someone else changed it")

    def test_unknown_file_and_extra_authorization_are_rejected(self):
        for authorized in ([], ["config.json", "unrelated.json"]):
            with self.subTest(authorized=authorized), self.assertRaises(safe.SafeError):
                safe.apply_files(self.plan(authorized=authorized), str(self.state))
        self.assertEqual(self.target.read_bytes(), b"original\n")

    def test_duplicate_target_is_rejected(self):
        plan = self.plan()
        value = json.loads(Path(plan).read_text())
        value["files"] *= 2
        Path(plan).write_text(json.dumps(value))
        with self.assertRaises(safe.SafeError):
            safe.apply_files(plan, str(self.state))

    def test_symlink_target_and_parent_are_rejected(self):
        link = self.root / "link"
        link.symlink_to(self.target)
        with self.assertRaises(safe.SafeError):
            safe.exact_path(str(link))
        parent = self.root / "linked-parent"
        parent.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(safe.SafeError):
            safe.exact_path(str(parent / "config.json"))

    def test_new_file_is_removed_only_by_its_own_rollback(self):
        self.plan()
        result = safe.apply_files(self.plan([{"path": "created.json", "before_sha256": None, "content_file": "new.txt"}]), str(self.state))
        self.assertEqual(stat.S_IMODE((self.root / "created.json").stat().st_mode), 0o600)
        self.assertEqual(safe.rollback(str(self.state), result["transaction"])["status"], "rolled_back")
        self.assertFalse((self.root / "created.json").exists())

    def test_rollback_preserves_later_user_edits(self):
        result = safe.apply_files(self.plan(), str(self.state))
        self.target.write_bytes(b"new user work")
        restored = safe.rollback(str(self.state), result["transaction"])
        self.assertEqual(restored["status"], "rollback_conflict")
        self.assertEqual(self.target.read_bytes(), b"new user work")

    def test_corrupt_backup_is_not_restored(self):
        result = safe.apply_files(self.plan(), str(self.state))
        (self.state / result["transaction"] / "0.backup").write_bytes(b"corrupt")
        self.assertEqual(safe.rollback(str(self.state), result["transaction"])["status"], "rollback_conflict")
        self.assertEqual(self.target.read_bytes(), b"updated\n")

    def test_rollback_preserves_later_permission_change(self):
        result = safe.apply_files(self.plan(), str(self.state))
        self.target.chmod(0o600)
        self.assertEqual(safe.rollback(str(self.state), result["transaction"])["status"], "rollback_conflict")
        self.assertEqual(self.target.read_bytes(), b"updated\n")
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o600)

    def test_plan_cannot_overwrite_its_own_recovery_state(self):
        self.plan()
        self.state.mkdir(mode=0o700)
        entries = [{"path": "state/manifest.json", "before_sha256": None, "content_file": "new.txt"}]
        with self.assertRaises(safe.SafeError):
            safe.apply_files(self.plan(entries), str(self.state))
        self.assertFalse((self.state / "manifest.json").exists())

    def test_write_failure_restores_already_changed_files(self):
        self.plan()
        second = self.root / "second.txt"
        second.write_bytes(b"second original")
        entries = [{"path": "config.json", "before_sha256": safe.digest(self.target.read_bytes()), "content_file": "new.txt"},
                   {"path": "second.txt", "before_sha256": safe.digest(second.read_bytes()), "content_file": "new.txt"}]
        write = safe.atomic_write
        def failing_write(path, data, mode=0o600):
            if path == second and data == b"updated\n":
                raise OSError("simulated failure")
            return write(path, data, mode)
        with mock.patch.object(safe, "atomic_write", side_effect=failing_write):
            result = safe.apply_files(self.plan(entries), str(self.state))
        self.assertEqual(result["status"], "apply_failed")
        self.assertEqual(result["recovery"]["status"], "rolled_back")
        self.assertEqual(self.target.read_bytes(), b"original\n")
        self.assertEqual(second.read_bytes(), b"second original")

    def test_busy_lock_is_not_removed_or_overwritten(self):
        self.state.mkdir(mode=0o700)
        lock = self.state / "write.lock"
        lock.write_text("existing owner")
        with self.assertRaises(safe.SafeError):
            safe.apply_files(self.plan(), str(self.state))
        self.assertEqual(lock.read_text(), "existing owner")
        self.assertEqual(self.target.read_bytes(), b"original\n")

    def test_world_readable_state_is_rejected(self):
        self.state.mkdir(mode=0o755)
        self.state.chmod(0o755)
        with self.assertRaises(safe.SafeError):
            safe.apply_files(self.plan(), str(self.state))

    def test_oversized_staged_content_is_rejected(self):
        plan = self.plan()
        (self.root / "new.txt").write_bytes(b"x" * (safe.MAX_FILE + 1))
        with self.assertRaises(safe.SafeError):
            safe.apply_files(plan, str(self.state))
        self.assertEqual(self.target.read_bytes(), b"original\n")


if __name__ == "__main__":
    unittest.main()
