import base64
import binascii
import json
from typing import Any
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey


def _wireguard_key(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is missing")

    encoded = value.strip()
    try:
        raw = base64.urlsafe_b64decode(
            encoded.encode("ascii") + b"=" * (-len(encoded) % 4)
        )
    except (UnicodeEncodeError, ValueError, binascii.Error) as error:
        raise ValueError(f"{label} is not valid Base64") from error

    if len(raw) != 32:
        raise ValueError(f"{label} must contain 32 bytes")
    return base64.b64encode(raw).decode("ascii")


def _wireguard_settings(inbound: dict[str, Any]) -> dict[str, Any]:
    settings = inbound.get("settings", {})
    if isinstance(settings, str):
        try:
            settings = json.loads(settings)
        except json.JSONDecodeError as error:
            raise ValueError("WireGuard inbound settings are invalid JSON") from error
    if not isinstance(settings, dict):
        raise ValueError("WireGuard inbound settings are invalid")
    return settings


def _server_public_key(settings: dict[str, Any]) -> str:
    for field in ("serverPublicKey", "pubKey", "publicKey"):
        value = settings.get(field)
        if value:
            return _wireguard_key(value, "server public key")

    private_key = settings.get("secretKey") or settings.get("privateKey")
    private_key = _wireguard_key(private_key, "server private key")
    key = X25519PrivateKey.from_private_bytes(
        base64.b64decode(private_key, validate=True)
    )
    public_key = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(public_key).decode("ascii")


def _endpoint(inbound: dict[str, Any], settings: dict[str, Any], panel_host: str) -> str:
    strategy = str(inbound.get("shareAddrStrategy", "node") or "node").lower()
    custom_host = inbound.get("shareAddr")
    node_host = inbound.get("nodeAddress")
    listen_host = inbound.get("listen")

    candidates = []
    if strategy == "custom":
        candidates.extend(
            (custom_host, node_host, listen_host, settings.get("endpoint"), settings.get("server"))
        )
    elif strategy == "listen":
        candidates.extend((listen_host, node_host, custom_host))
    else:
        candidates.extend(
            (node_host, listen_host, custom_host, settings.get("endpoint"), settings.get("server"))
        )

    candidates.extend((settings.get("endpoint"), settings.get("server"), panel_host))
    host = None
    for candidate in candidates:
        if not isinstance(candidate, str) or not candidate.strip():
            continue
        parsed_candidate = urlsplit(
            candidate.strip()
            if "://" in candidate
            else f"//{candidate.strip()}"
        )
        candidate_host = parsed_candidate.hostname
        if candidate_host and candidate_host.lower() not in {
            "0.0.0.0", "::", "*", "127.0.0.1", "::1", "localhost"
        }:
            host = candidate_host
            break
    if not host:
        raise ValueError("WireGuard public server hostname is missing")

    port_value = inbound.get("port")
    try:
        port = int(port_value)
    except (TypeError, ValueError) as error:
        raise ValueError("WireGuard inbound port is invalid") from error
    if not 1 <= port <= 65535:
        raise ValueError("WireGuard inbound port is invalid")

    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{host}:{port}"


def build_wireguard_config(
    inbound: dict[str, Any],
    client: dict[str, Any],
    panel_url: str,
) -> str:
    settings = _wireguard_settings(inbound)
    private_key = _wireguard_key(client.get("privateKey"), "client private key")
    server_public_key = _server_public_key(settings)
    parsed_panel_url = urlsplit(
        panel_url if "://" in panel_url else f"//{panel_url}"
    )
    panel_host = parsed_panel_url.hostname or ""

    allowed_ips = client.get("allowedIPs")
    if isinstance(allowed_ips, str):
        addresses = [item.strip() for item in allowed_ips.split(",") if item.strip()]
    elif isinstance(allowed_ips, list):
        addresses = [
            item.strip()
            for item in allowed_ips
            if isinstance(item, str) and item.strip()
        ]
    else:
        addresses = []
    if not addresses:
        raise ValueError("WireGuard client address is missing")

    endpoint = _endpoint(inbound, settings, panel_host)
    lines = [
        "[Interface]",
        f"PrivateKey = {private_key}",
        f"Address = {', '.join(addresses)}",
    ]

    dns = settings.get("dns") or "1.1.1.1, 1.0.0.1"
    if isinstance(dns, list):
        dns_values = [str(item).strip() for item in dns if str(item).strip()]
        dns = ", ".join(dns_values)
    if isinstance(dns, str) and dns.strip():
        lines.append(f"DNS = {dns.strip()}")

    mtu = settings.get("mtu")
    try:
        mtu = int(mtu)
    except (TypeError, ValueError):
        mtu = 0
    if mtu > 0:
        lines.append(f"MTU = {mtu}")

    remark = inbound.get("remark")
    client_name = client.get("email")
    client_id = client.get("tgId") or client.get("id")
    if remark or client_name or client_id:
        label = " - ".join(
            str(value).strip()
            for value in (remark, client_name)
            if isinstance(value, str) and value.strip()
        )
        if client_id:
            label = f"{label} (ID:{client_id})"
        lines.append(f"# {label}")

    lines.extend(
        [
            "",
            "[Peer]",
            f"PublicKey = {server_public_key}",
        ]
    )

    preshared_key = client.get("preSharedKey")
    if preshared_key:
        lines.append(
            f"PresharedKey = {_wireguard_key(preshared_key, 'client preshared key')}"
        )

    lines.extend(
        [
            "AllowedIPs = 0.0.0.0/0, ::/0",
            f"Endpoint = {endpoint}",
        ]
    )

    keep_alive = client.get("keepAlive")
    try:
        keep_alive = int(keep_alive)
    except (TypeError, ValueError):
        keep_alive = 0
    if keep_alive > 0:
        lines.append(f"PersistentKeepalive = {keep_alive}")

    return "\n".join(lines) + "\n"
