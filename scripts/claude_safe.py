"""Inspection, bounded HTTPS probing and reversible exact-file writes; no account setup."""

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import time
import urllib.parse
import uuid

MAX_FILE = 2 * 1024 * 1024
MAX_TOTAL = 8 * 1024 * 1024
MAX_FILES = 16


class SafeError(Exception):
    pass


def exact_path(value, base=None):
    p = Path(value).expanduser()
    if not p.is_absolute():
        p = (base or Path.cwd()) / p
    p = Path(os.path.abspath(p))
    for component in (p, *p.parents):
        if component.is_symlink():
            raise SafeError("symlink_path")
    return p


def read_bytes(p, limit=MAX_FILE):
    try:
        info = p.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
        raise SafeError("nonregular_or_oversized_file")
    with p.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise SafeError("oversized_file")
    return data


def digest(data):
    return None if data is None else hashlib.sha256(data).hexdigest()


def read_json(p, limit=MAX_FILE):
    data = read_bytes(p, limit)
    if data is None:
        raise SafeError("missing_json")
    return json.loads(data.decode("utf-8"))


def atomic_write(p, data, mode=0o600):
    exact_path(str(p))
    if not p.parent.is_dir():
        raise SafeError("missing_target_parent")
    temporary = p.with_name("." + p.name + ".claude-safe-" + uuid.uuid4().hex)
    try:
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, p)
    finally:
        if temporary.exists():
            temporary.unlink()


def save_json(p, value):
    atomic_write(p, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def private_state(value):
    if os.name == "nt":
        raise SafeError("windows_write_adapter_requires_verified_acl_support")
    p = exact_path(value)
    if p.exists() and not p.is_dir():
        raise SafeError("state_not_directory")
    if not p.exists():
        p.mkdir(parents=True, mode=0o700)
    if os.name != "nt":
        if p.stat().st_uid != os.geteuid() or stat.S_IMODE(p.stat().st_mode) & 0o077:
            raise SafeError("state_requires_owner_only_permissions")
    return p


@contextlib.contextmanager
def state_lock(root):
    lock = root / "write.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise SafeError("state_busy_do_not_remove_active_lock")
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        lock.unlink()


def inspect_environment(home=None, environ=None):
    home = Path.home() if home is None else Path(home)
    environ = os.environ if environ is None else environ
    keys = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy",
            "https_proxy", "all_proxy", "no_proxy", "ANTHROPIC_BASE_URL",
            "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")
    env = {key: {"present": bool(environ.get(key))} for key in keys}
    # Values are deliberately omitted, even URLs: userinfo, query and path can be secrets.
    configs = {}
    for relative in (".claude/settings.json", ".claude/settings.local.json", ".claude.json",
                     ".npmrc", ".gitconfig", ".zshrc", ".bashrc", ".profile"):
        path = home / relative
        configs[relative] = {"exists": path.exists(), "symlink": path.is_symlink()}
    result = {"schema_version": 1, "os": platform.system(), "python": platform.python_version(),
              "timezone_names": list(time.tzname), "environment": env, "configs": configs,
              "executables": {key: bool(shutil.which(key)) for key in
                              ("claude", "mihomo", "clash", "sing-box", "curl", "ssh")},
              "system_proxy_flags": {"status": "not_checked"},
              "account_status": "not_checked", "dns_route": "not_checked",
              "webrtc": "not_checked", "effective_claude_route": "not_checked"}
    if platform.system() == "Darwin" and shutil.which("scutil"):
        try:
            r = subprocess.run(["scutil", "--proxy"], capture_output=True, text=True, timeout=5)
            result["system_proxy_flags"] = {"status": "ok" if r.returncode == 0 else "failed",
                "flags": dict(re.findall(r"(HTTPEnable|HTTPSEnable|SOCKSEnable|ProxyAutoConfigEnable)\s*:\s*([01])", r.stdout))}
        except (OSError, subprocess.TimeoutExpired):
            result["system_proxy_flags"] = {"status": "unavailable"}
    return result


def validated_plan(plan_path):
    plan_path = exact_path(plan_path)
    plan = read_json(plan_path, 128 * 1024)
    if plan.get("schema_version") != 1:
        raise SafeError("unsupported_plan_schema")
    files = plan.get("files")
    authorized = plan.get("authorized_files")
    if not isinstance(files, list) or not isinstance(authorized, list) or not 1 <= len(files) <= MAX_FILES:
        raise SafeError("invalid_plan_files")
    allowed = {str(exact_path(p, plan_path.parent)) for p in authorized}
    seen = set()
    prepared = []
    total = 0
    for change in files:
        if set(change) != {"path", "before_sha256", "content_file"}:
            raise SafeError("invalid_change_fields")
        target = exact_path(change["path"], plan_path.parent)
        if str(target) not in allowed or str(target) in seen:
            raise SafeError("unauthorized_or_duplicate_target")
        seen.add(str(target))
        expected = change["before_sha256"]
        if expected is not None and not re.fullmatch(r"[0-9a-f]{64}", str(expected)):
            raise SafeError("invalid_before_sha256")
        new = read_bytes(exact_path(change["content_file"], plan_path.parent))
        if new is None:
            raise SafeError("missing_staged_content")
        old = read_bytes(target)
        total += len(new) + len(old or b"")
        if total > MAX_TOTAL:
            raise SafeError("plan_total_too_large")
        if not target.parent.is_dir():
            raise SafeError("missing_target_parent")
        if old == new:
            continue
        if digest(old) != expected:
            raise SafeError("target_changed_since_plan")
        mode = stat.S_IMODE(target.stat().st_mode) if old is not None else 0o600
        prepared.append((target, old, new, mode))
    if allowed != seen:
        raise SafeError("authorization_must_match_exact_target_set")
    return prepared


def restore_transaction(folder):
    manifest = read_json(folder / "manifest.json")
    conflicts = []
    # Check each exact current hash; a later edit must never be overwritten.
    for change in reversed(manifest["files"]):
        try:
            target = exact_path(change["path"])
            current = digest(read_bytes(target))
            if current == change["before_sha256"]:
                continue
            if current != change["after_sha256"]:
                conflicts.append(change["index"])
                continue
            if stat.S_IMODE(target.stat().st_mode) != change["mode"]:
                conflicts.append(change["index"])
                continue
            backup = read_bytes(folder / (str(change["index"]) + ".backup"))
            if digest(backup) != change["before_sha256"]:
                raise SafeError("backup_digest_mismatch")
            if backup is None:
                target.unlink()
            else:
                atomic_write(target, backup, change["mode"])
        except (SafeError, OSError):
            conflicts.append(change["index"])
    manifest["status"] = "rollback_conflict" if conflicts else "rolled_back"
    manifest["conflicts"] = conflicts
    save_json(folder / "manifest.json", manifest)
    return {"transaction": folder.name, "status": manifest["status"], "conflict_indexes": conflicts}


def apply_files(plan_path, state_dir):
    root = private_state(state_dir)
    with state_lock(root):
        prepared = validated_plan(plan_path)
        if any(root == target or root in target.parents for target, _, _, _ in prepared):
            raise SafeError("target_overlaps_recovery_state")
        if not prepared:
            return {"status": "unchanged", "changed_files": 0}
        folder = root / uuid.uuid4().hex
        folder.mkdir(mode=0o700)
        manifest = {"schema_version": 1, "status": "prepared", "files": []}
        for index, (target, old, new, mode) in enumerate(prepared):
            if old is not None:
                atomic_write(folder / (str(index) + ".backup"), old)
            manifest["files"].append({"index": index, "path": str(target), "mode": mode,
                                      "before_sha256": digest(old), "after_sha256": digest(new)})
        save_json(folder / "manifest.json", manifest)
        try:
            for target, old, new, mode in prepared:
                if digest(read_bytes(exact_path(str(target)))) != digest(old):
                    raise SafeError("concurrent_target_change")
                atomic_write(target, new, mode)
                if digest(read_bytes(target)) != digest(new):
                    raise SafeError("write_readback_mismatch")
        except (SafeError, OSError):
            recovered = restore_transaction(folder)
            return {"transaction": folder.name, "status": "apply_failed", "recovery": recovered}
        manifest["status"] = "files_applied_runtime_unverified"
        save_json(folder / "manifest.json", manifest)
        return {"transaction": folder.name, "status": manifest["status"], "changed_files": len(prepared)}


def rollback(state_dir, transaction):
    if not re.fullmatch(r"[0-9a-f]{32}", transaction):
        raise SafeError("invalid_transaction_id")
    root = private_state(state_dir)
    with state_lock(root):
        return restore_transaction(exact_path(str(root / transaction)))


def probe(url, timeout):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise SafeError("probe_requires_https_without_userinfo")
    executable = shutil.which("curl")
    if executable is None:
        raise SafeError("curl_required_for_deadline_bounded_probe")
    started = time.monotonic()
    result = {"host": parsed.hostname, "account_verified": False,
              "route_verified": False, "elapsed_seconds": None}
    try:
        response = subprocess.run([executable, "--silent", "--show-error", "--head", "--location",
            "--max-redirs", "3", "--proto", "=https", "--proto-redir", "=https",
            "--max-time", str(timeout), "--connect-timeout", str(min(timeout, 5)),
            "--output", os.devnull, "--write-out", "%{http_code}", "--url", url],
            capture_output=True, text=True, timeout=timeout + 2)
        code = response.stdout.strip()
        if response.returncode == 0 and re.fullmatch(r"[1-5][0-9]{2}", code):
            result.update({"status": "http_response", "http_status": int(code)})
        else:
            result.update({"status": "connection_failed"})
    except (OSError, subprocess.TimeoutExpired):
        result.update({"status": "connection_failed"})
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inspect", help="Read metadata only; never output secret values")
    hashed = sub.add_parser("hash", help="Current digest or null for exact missing file")
    hashed.add_argument("file")
    applied = sub.add_parser("apply-files", help="Apply an authorized, validated exact-file plan")
    applied.add_argument("--plan", required=True)
    applied.add_argument("--state-dir", required=True)
    restored = sub.add_parser("rollback", help="Restore only unchanged files from one transaction")
    restored.add_argument("--state-dir", required=True)
    restored.add_argument("--transaction", required=True)
    checked = sub.add_parser("probe", help="Bounded HTTPS check; not route/account acceptance")
    checked.add_argument("--url", required=True)
    checked.add_argument("--timeout", type=float, default=10)
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            result = inspect_environment()
        elif args.command == "hash":
            result = {"sha256": digest(read_bytes(exact_path(args.file)))}
        elif args.command == "apply-files":
            result = apply_files(args.plan, args.state_dir)
        elif args.command == "rollback":
            result = rollback(args.state_dir, args.transaction)
        else:
            if not 0 < args.timeout <= 30:
                raise SafeError("timeout_out_of_range")
            result = probe(args.url, args.timeout)
        print(json.dumps(result, ensure_ascii=False))
        if result.get("status") in ("apply_failed", "rollback_conflict", "connection_failed"):
            return 2
        return 0
    except SafeError as error:
        print(json.dumps({"status": "error", "reason": str(error)}))
        return 2
    except (OSError, ValueError, KeyError, TypeError):
        # Exception text can contain config values or credential-bearing URLs.
        print(json.dumps({"status": "error", "reason": "operation_rejected_or_unavailable"}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
