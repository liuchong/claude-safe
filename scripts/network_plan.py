"""Render exact WireGuard/Mihomo files locally; never provision or connect."""

import argparse
import base64
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys

import claude_safe as safe


def read_key(value, base, secret=False):
    path = safe.exact_path(value, base)
    data = safe.read_bytes(path, 128)
    if data is None:
        raise safe.SafeError("missing_key_file")
    if secret and (path.stat().st_uid != os.geteuid() or
                   stat.S_IMODE(path.stat().st_mode) & 0o077):
        raise safe.SafeError("private_key_requires_owner_only_permissions")
    key = data.decode("ascii").strip()
    try:
        raw = base64.b64decode(key, validate=True)
    except ValueError:
        raise safe.SafeError("invalid_wireguard_key")
    if len(raw) != 32 or not any(raw) or base64.b64encode(raw).decode() != key:
        raise safe.SafeError("invalid_wireguard_key")
    return key


def render(config_path, side):
    path = safe.exact_path(config_path)
    config = safe.read_json(path, 16 * 1024)
    fields = {"schema_version", "endpoint_ipv4", "port", "egress_interface",
              "server_private_key_file", "server_public_key_file",
              "client_private_key_file", "client_public_key_file",
              "server_cidr", "client_cidr", "dns_ipv4", "mtu"}
    if set(config) != fields or config["schema_version"] != 1:
        raise safe.SafeError("invalid_network_schema")
    if side not in ("server", "client"):
        raise safe.SafeError("invalid_render_side")
    endpoint = ipaddress.IPv4Address(config["endpoint_ipv4"])
    if not endpoint.is_global or endpoint.is_multicast:
        raise safe.SafeError("endpoint_requires_public_ipv4")
    dns = ipaddress.IPv4Address(config["dns_ipv4"])
    if not dns.is_global or dns.is_multicast:
        raise safe.SafeError("dns_requires_public_ipv4")
    port, mtu = config["port"], config["mtu"]
    if type(port) is not int or not 1024 <= port <= 65535:
        raise safe.SafeError("invalid_udp_port")
    if type(mtu) is not int or not 1280 <= mtu <= 1420:
        raise safe.SafeError("invalid_mtu")
    interface = config["egress_interface"]
    if not isinstance(interface, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,14}", interface):
        raise safe.SafeError("invalid_egress_interface")
    if interface in ("lo", "cs0"):
        raise safe.SafeError("invalid_egress_interface")
    server = ipaddress.IPv4Interface(config["server_cidr"])
    client = ipaddress.IPv4Interface(config["client_cidr"])
    private_blocks = [ipaddress.IPv4Network(v) for v in
                      ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
    if not 24 <= server.network.prefixlen <= 30 or client.network.prefixlen != 32 or not any(
            server.network.subnet_of(block) for block in private_blocks):
        raise safe.SafeError("invalid_tunnel_subnet")
    excluded = {server.network.network_address, server.network.broadcast_address}
    if server.ip in excluded or client.ip in excluded or client.ip not in server.network or server.ip == client.ip:
        raise safe.SafeError("invalid_peer_addresses")
    if side == "server":
        private = read_key(config["server_private_key_file"], path.parent, True)
        peer = read_key(config["client_public_key_file"], path.parent)
        forward = [f"-i cs0 -o {interface} -s {client} -j ACCEPT",
                   f"-i {interface} -o cs0 -d {client} -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT"]
        nat = f"-s {client} -o {interface} -j MASQUERADE"
        up = [f"iptables -I FORWARD 1 {rule}" for rule in forward]
        up.append(f"iptables -t nat -A POSTROUTING {nat}")
        down = [f"iptables -D FORWARD {rule}" for rule in forward]
        down.append(f"iptables -t nat -D POSTROUTING {nat}")
        content = (f"[Interface]\nAddress = {server}\nListenPort = {port}\n"
                   f"PrivateKey = {private}\nMTU = {mtu}\n"
                   f"PostUp = {'; '.join(up)}\nPostDown = {'; '.join(down)}\n\n"
                   f"[Peer]\nPublicKey = {peer}\nAllowedIPs = {client}\n")
        return {"server.conf": content}
    private = read_key(config["client_private_key_file"], path.parent, True)
    peer = read_key(config["server_public_key_file"], path.parent)
    overlay = {
        "proxies": [{"name": "Claude-Safe-WG", "type": "wireguard",
                     "server": str(endpoint), "port": port, "ip": str(client.ip),
                     "private-key": private, "public-key": peer, "udp": True,
                     "allowed-ips": ["0.0.0.0/0"], "mtu": mtu,
                     "persistent-keepalive": 25, "remote-dns-resolve": True,
                     "dns": [str(dns)]}],
        "proxy-groups": [{"name": "Claude-Safe", "type": "select",
                          "proxies": ["Claude-Safe-WG"]}],
        "rules": [f"DOMAIN-SUFFIX,{domain},Claude-Safe" for domain in
                  ("claude.ai", "claude.com", "anthropic.com")]
    }
    native = (f"[Interface]\nPrivateKey = {private}\nAddress = {client}\n"
              f"DNS = {dns}\nMTU = {mtu}\n\n[Peer]\nPublicKey = {peer}\n"
              f"Endpoint = {endpoint}:{port}\nAllowedIPs = 0.0.0.0/0, ::/0\n"
              "PersistentKeepalive = 25\n")
    return {"mihomo-merge.json": json.dumps(overlay, indent=2) + "\n",
            "client.conf": native}


def generate(config_path, output_dir, side):
    if os.name == "nt":
        raise safe.SafeError("windows_write_adapter_requires_verified_acl_support")
    # Validate all parameters and secrets before creating any output.
    files = render(config_path, side)
    root = safe.exact_path(output_dir)
    if not root.parent.is_dir():
        raise safe.SafeError("missing_output_parent")
    try:
        root.mkdir(mode=0o700)
    except FileExistsError:
        raise safe.SafeError("output_exists_choose_new_directory")
    try:
        for name, content in files.items():
            safe.atomic_write(root / name, content.encode(), 0o600)
    except Exception:
        shutil.rmtree(root)
        raise
    return {"status": "rendered_runtime_unverified", "side": side, "file_count": len(files)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--side", choices=("server", "client"), required=True)
    args = parser.parse_args(argv)
    try:
        result = generate(args.input, args.output_dir, args.side)
        print(json.dumps(result))
        return 0
    except safe.SafeError as error:
        print(json.dumps({"status": "error", "reason": str(error)}))
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        print(json.dumps({"status": "error", "reason": "invalid_or_unavailable_network_input"}))
    return 2


if __name__ == "__main__":
    sys.exit(main())
