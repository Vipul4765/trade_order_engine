"""IP / CIDR allowlist evaluation with safe reverse-proxy header handling."""

from __future__ import annotations

import ipaddress
from collections.abc import Sequence

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


def _normalize_ip(raw_ip: str) -> IPAddress | None:
    try:
        addr = ipaddress.ip_address(raw_ip.strip())
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


def _parse_networks(entries: Sequence[str]) -> tuple[IPNetwork, ...]:
    networks: list[IPNetwork] = []
    for entry in entries:
        cleaned = entry.strip()
        if not cleaned:
            continue
        networks.append(ipaddress.ip_network(cleaned, strict=False))
    return tuple(networks)


class IPAllowlist:
    """Restricts API access to explicitly approved IP addresses or CIDR ranges."""

    def __init__(
        self,
        allowed_entries: Sequence[str] = (),
        *,
        trust_proxy_headers: bool = False,
        trusted_proxies: Sequence[str] = ("127.0.0.1/32", "::1/128"),
    ) -> None:
        self._allowed = _parse_networks(allowed_entries)
        self._trust_proxy_headers = trust_proxy_headers
        self._trusted_proxies = _parse_networks(trusted_proxies)

    @property
    def enabled(self) -> bool:
        return bool(self._allowed)

    def resolve_client_ip(
        self,
        peer_host: str | None,
        *,
        x_forwarded_for: str | None = None,
        x_real_ip: str | None = None,
    ) -> str:
        """Resolve the effective client IP without trusting spoofable headers."""
        peer_ip = _normalize_ip(peer_host) if peer_host else None

        if self._trust_proxy_headers and peer_ip is not None and self._is_trusted_proxy(peer_ip):
            if x_forwarded_for:
                # Walk right-to-left skipping trusted proxies to prevent client-spoofed left entries
                hops = [hop.strip() for hop in x_forwarded_for.split(",") if hop.strip()]
                for hop in reversed(hops):
                    hop_ip = _normalize_ip(hop)
                    if hop_ip is not None and not self._is_trusted_proxy(hop_ip):
                        return str(hop_ip)
                if hops:
                    return hops[0]
            if x_real_ip and x_real_ip.strip():
                real_ip = _normalize_ip(x_real_ip)
                if real_ip is not None:
                    return str(real_ip)

        if peer_ip is not None:
            return str(peer_ip)
        return (peer_host or "unknown").strip() or "unknown"

    def is_allowed(self, client_ip: str) -> bool:
        """Return `True` if allowlist is disabled or `client_ip` matches an allowed network."""
        if not self._allowed:
            return True
        parsed = _normalize_ip(client_ip)
        if parsed is None:
            return False
        return any(parsed in network for network in self._allowed)

    def _is_trusted_proxy(self, ip_addr: IPAddress) -> bool:
        return any(ip_addr in network for network in self._trusted_proxies)
