"""Chain data model and file I/O.

Each chain represents: one user + one inbound + one outbound strategy + one route binding.

Stored as <workdir>/sites/<site-id>/chains/<chain-id>.json
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


CHAIN_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")


@dataclass
class ClientConfig:
    uuid: str = ""
    password: str = ""
    volume: int = 0
    expiry: int = 0


@dataclass
class InboundConfig:
    type: str = "vless"
    tag: str = ""
    listen_port: int = 0
    tls_tag: str = ""
    transport: dict[str, Any] = field(default_factory=dict)
    addrs: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class OutboundConfig:
    mode: str = "direct"  # direct | shared | dedicated
    tag: str = ""
    type: str = "socks"
    server: str = ""
    server_port: int = 0
    username: str = ""
    password: str = ""


@dataclass
class ChainConfig:
    chain_id: str = ""
    name: str = ""
    client: ClientConfig = field(default_factory=ClientConfig)
    inbound: InboundConfig = field(default_factory=InboundConfig)
    outbound: OutboundConfig = field(default_factory=OutboundConfig)
    metadata: dict[str, Any] = field(default_factory=dict)


def chains_dir(config_path: str) -> Path:
    """Return the chains/ directory for a site."""
    return Path(config_path).parent / "chains"


def list_chain_ids(config_path: str) -> list[str]:
    """List chain IDs by scanning chains/*.json files, sorted by name."""
    cdir = chains_dir(config_path)
    if not cdir.is_dir():
        return []
    files = sorted(cdir.glob("*.json"))
    ids: list[str] = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            chain_id = data.get("chain_id") or f.stem
            if isinstance(chain_id, str):
                ids.append(chain_id)
        except (json.JSONDecodeError, OSError):
            continue
    return ids


def load_chain(config_path: str, chain_id: str) -> dict[str, Any]:
    """Load a single chain JSON by chain_id. Raises FileNotFoundError if missing."""
    cdir = chains_dir(config_path)
    # Try exact filename first
    path = cdir / f"{chain_id}.json"
    if not path.exists():
        # Fallback: search by chain_id field
        for f in cdir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("chain_id") == chain_id:
                    return data
            except (json.JSONDecodeError, OSError):
                continue
        raise FileNotFoundError(f"Chain not found: {chain_id} (searched in {cdir})")
    return json.loads(path.read_text(encoding="utf-8"))


def save_chain(config_path: str, chain_id: str, data: dict[str, Any]) -> Path:
    """Save a chain JSON to chains/<chain-id>.json. Creates chains/ if needed."""
    cdir = chains_dir(config_path)
    cdir.mkdir(parents=True, exist_ok=True)
    path = cdir / f"{chain_id}.json"
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def delete_chain_file(config_path: str, chain_id: str) -> bool:
    """Delete a chain JSON file by chain_id. Returns True if deleted."""
    cdir = chains_dir(config_path)
    path = cdir / f"{chain_id}.json"
    if path.exists():
        path.unlink()
        return True
    # Fallback: search by chain_id field
    for f in cdir.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("chain_id") == chain_id:
                f.unlink()
                return True
        except (json.JSONDecodeError, OSError):
            continue
    return False


def validate_chain_id(chain_id: str) -> list[str]:
    """Validate a chain ID string."""
    errors: list[str] = []
    if not chain_id:
        errors.append("chain_id cannot be empty")
    elif not CHAIN_ID_PATTERN.match(chain_id):
        errors.append(
            f"chain_id must start with alphanumeric, contain only "
            f"alphanumeric/./-/_ characters, max 64 chars: {chain_id!r}"
        )
    return errors


def validate_chain_dict(data: dict[str, Any]) -> list[str]:
    """Validate a chain dict loaded from JSON. Returns list of error messages."""
    errors: list[str] = []

    chain_id = data.get("chain_id", "")
    errors.extend(validate_chain_id(chain_id))

    name = data.get("name", "")
    if not name:
        errors.append("chain missing required field: name")

    inbound = data.get("inbound", {})
    if not isinstance(inbound, dict):
        errors.append("inbound must be a dict")
    else:
        inbound_type = inbound.get("type", "")
        if not inbound_type:
            errors.append("inbound.type is required")
        inbound_tag = inbound.get("tag", "")
        if not inbound_tag:
            errors.append("inbound.tag is required")
        inbound_port = inbound.get("listen_port", 0)
        if not isinstance(inbound_port, int) or inbound_port < 1 or inbound_port > 65535:
            errors.append(f"inbound.listen_port must be a valid port 1-65535, got {inbound_port!r}")
        inbound_tls = inbound.get("tls_tag", "")
        if not inbound_tls:
            errors.append("inbound.tls_tag is required (reference an existing TLS template name)")

    outbound = data.get("outbound", {})
    if not isinstance(outbound, dict):
        errors.append("outbound must be a dict")
    else:
        mode = outbound.get("mode", "")
        if mode not in ("direct", "shared", "dedicated"):
            errors.append(f"outbound.mode must be 'direct', 'shared', or 'dedicated', got {mode!r}")
        if mode in ("shared", "dedicated"):
            tag = outbound.get("tag", "")
            if not tag:
                errors.append(f"outbound.tag is required for mode={mode!r}")
        if mode == "dedicated":
            server = outbound.get("server", "")
            if not server:
                errors.append("outbound.server is required for mode='dedicated'")
            server_port = outbound.get("server_port", 0)
            if not isinstance(server_port, int) or server_port < 1 or server_port > 65535:
                errors.append(
                    f"outbound.server_port must be a valid port 1-65535 for mode='dedicated', "
                    f"got {server_port!r}"
                )

    return errors


def make_chain_id_from_name(name: str) -> str:
    """Generate a safe chain_id from a name string."""
    safe = re.sub(r"[^a-zA-Z0-9._-]", "-", name)
    safe = safe.strip("-.")[:64]
    if not safe or not safe[0].isalnum():
        safe = "chain-" + safe
    return safe


def dict_to_chain(data: dict[str, Any]) -> ChainConfig:
    """Convert a raw dict to a ChainConfig dataclass."""
    client_raw = data.get("client", {})
    inbound_raw = data.get("inbound", {})
    outbound_raw = data.get("outbound", {})
    return ChainConfig(
        chain_id=data.get("chain_id", ""),
        name=data.get("name", ""),
        client=ClientConfig(
            uuid=client_raw.get("uuid", ""),
            password=client_raw.get("password", ""),
            volume=client_raw.get("volume", 0),
            expiry=client_raw.get("expiry", 0),
        ),
        inbound=InboundConfig(
            type=inbound_raw.get("type", "vless"),
            tag=inbound_raw.get("tag", ""),
            listen_port=inbound_raw.get("listen_port", 0),
            tls_tag=inbound_raw.get("tls_tag", ""),
            transport=inbound_raw.get("transport", {}),
            addrs=inbound_raw.get("addrs", []),
        ),
        outbound=OutboundConfig(
            mode=outbound_raw.get("mode", "direct"),
            tag=outbound_raw.get("tag", ""),
            type=outbound_raw.get("type", "socks"),
            server=outbound_raw.get("server", ""),
            server_port=outbound_raw.get("server_port", 0),
            username=outbound_raw.get("username", ""),
            password=outbound_raw.get("password", ""),
        ),
        metadata=data.get("metadata", {}),
    )


def chain_to_dict(chain: ChainConfig) -> dict[str, Any]:
    """Convert a ChainConfig dataclass back to a dict for serialization."""
    return {
        "chain_id": chain.chain_id,
        "name": chain.name,
        "client": asdict(chain.client),
        "inbound": asdict(chain.inbound),
        "outbound": asdict(chain.outbound),
        "metadata": chain.metadata,
    }
