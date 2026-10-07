"""
Enforcement helpers for ``PRIVACY_LOCAL_ONLY``.

The settings validator uses the checks here to refuse configurations that would send
questions, textbook context or usage data off the machine (tracing, a remote or cloud
Ollama). The API calls the runtime guards at startup: Hugging Face Hub telemetry off,
offline mode once the models are cached, and LangSmith tracing disabled globally.

This module must not import ``backend.app.core.settings`` (the settings module imports it).
"""

from __future__ import annotations

import ipaddress
import os
import socket
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from backend.app.core.settings import Settings

# Variables that turn on LangSmith tracing in langsmith and langchain-core (0.3 and 1.x):
# langsmith reads ``{LANGSMITH,LANGCHAIN}_TRACING_V2``, then ``{LANGSMITH,LANGCHAIN}_TRACING``.
# The API key, endpoint and project variables send nothing unless one of these is on.
TRACING_ENV_VARS = (
    "LANGSMITH_TRACING",
    "LANGSMITH_TRACING_V2",
    "LANGCHAIN_TRACING",
    "LANGCHAIN_TRACING_V2",
)
_OFF_VALUES = frozenset({"", "false", "0", "no", "off"})

# Host names accepted for LLM_OLLAMA_HOST without a DNS lookup: this machine, the Compose
# service and the names Docker Desktop / Podman give the host.
LOCAL_OLLAMA_HOSTNAMES = frozenset(
    {"localhost", "ollama", "host.docker.internal", "host.containers.internal"}
)


def flag_is_on(value: str | None) -> bool:
    """Whether a tracing variable's value enables anything (stricter than langsmith)."""
    return value is not None and value.strip().lower() not in _OFF_VALUES


def is_local_address(address: str) -> bool:
    """Whether an IP literal is loopback or private (RFC 1918, ULA), excluding link-local."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])  # drop an IPv6 zone id
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_loopback:
        return True
    return ip.is_private and not ip.is_link_local


def ollama_host_problem(url: str) -> str | None:
    """Why ``LLM_OLLAMA_HOST`` is not allowed under PRIVACY_LOCAL_ONLY, or None if it is.

    Allowed: ``localhost`` (and ``*.localhost``), the Compose service ``ollama``,
    ``host.docker.internal``, ``host.containers.internal``, loopback or private IP
    literals, and other host names that resolve only to loopback or private addresses.
    """
    hostname = urlsplit(url if "://" in url else f"http://{url}").hostname
    if not hostname:
        return f"LLM_OLLAMA_HOST={url!r} has no host name"
    hostname = hostname.rstrip(".").lower()
    if hostname in LOCAL_OLLAMA_HOSTNAMES or hostname.endswith(".localhost"):
        return None
    try:
        ipaddress.ip_address(hostname.split("%", 1)[0])
    except ValueError:
        pass
    else:
        if is_local_address(hostname):
            return None
        return f"LLM_OLLAMA_HOST={url!r} is not a loopback or private address"

    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(hostname, None)}
    except OSError:
        return f"LLM_OLLAMA_HOST={url!r}: {hostname!r} could not be resolved to check it"
    remote = sorted(address for address in addresses if not is_local_address(str(address)))
    if not addresses or remote:
        return (
            f"LLM_OLLAMA_HOST={url!r}: {hostname!r} resolves to non-private addresses "
            f"({', '.join(str(address) for address in remote) or 'none'})"
        )
    return None


def is_cloud_model(model: str) -> bool:
    """Whether an Ollama model name is a cloud model (``gpt-oss:120b-cloud``, ``x:cloud``)."""
    tag = model.strip().lower().rpartition(":")[2]
    return tag == "cloud" or tag.endswith("-cloud")


def disable_hf_telemetry() -> None:
    """Turn Hugging Face Hub telemetry off; must run before ``huggingface_hub`` is imported."""
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"


def hf_hub_cache_dir() -> Path:
    """The Hugging Face Hub cache directory, resolved the way ``huggingface_hub`` does."""
    if os.environ.get("HF_HUB_CACHE"):
        return Path(os.environ["HF_HUB_CACHE"]).expanduser()
    if os.environ.get("HF_HOME"):
        return Path(os.environ["HF_HOME"]).expanduser() / "hub"
    xdg_cache = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(xdg_cache).expanduser() / "huggingface" / "hub"


def hf_model_is_cached(model: str, revision: str | None = None) -> bool:
    """Whether a model is available without the Hub: a local directory or a cached snapshot.

    With a revision, that revision must be cached: the snapshot of a commit, or the one a
    cached branch or tag ref (``refs/<name>``) points to.
    """
    if Path(model).expanduser().is_dir():
        return True
    repo = hf_hub_cache_dir() / f"models--{model.replace('/', '--')}"
    try:
        if revision:
            ref = repo / "refs" / revision
            commit = ref.read_text(encoding="utf-8").strip() if ref.is_file() else revision
            snapshot = repo / "snapshots" / commit
            return snapshot.is_dir() and any(snapshot.iterdir())
        return any(path.is_dir() and any(path.iterdir()) for path in (repo / "snapshots").iterdir())
    except OSError:
        return False


def configure_huggingface_hub(app_settings: Settings) -> str:
    """Set the Hugging Face Hub environment for the API process; returns a status line.

    Telemetry is always off. Under PRIVACY_LOCAL_ONLY, ``HF_HUB_OFFLINE=1`` is set when
    every model the API loads (the embedding model, plus the reranker when enabled) is
    already cached at the revision it loads, so the API never contacts huggingface.co. A
    first run without the cache (or after a revision change) stays online so the models can
    download. An explicit ``HF_HUB_OFFLINE`` is respected.
    Must run before ``huggingface_hub`` is imported (it reads these variables once).
    """
    disable_hf_telemetry()
    if "HF_HUB_OFFLINE" in os.environ:
        return f"HF_HUB_OFFLINE={os.environ['HF_HUB_OFFLINE']} (set explicitly)"
    if not app_settings.privacy_local_only:
        return "online (PRIVACY_LOCAL_ONLY=false)"
    models = [(app_settings.embedding_model, app_settings.effective_embedding_revision)]
    if app_settings.reranker_enabled:
        models.append((app_settings.reranker_model, app_settings.effective_reranker_revision))
    missing = [model for model, revision in models if not hf_model_is_cached(model, revision)]
    if missing:
        return (
            f"online: {', '.join(missing)} not cached yet and will be downloaded from "
            "huggingface.co on first use (offline mode starts once the models are cached)"
        )
    os.environ["HF_HUB_OFFLINE"] = "1"
    return "offline (HF_HUB_OFFLINE=1, models cached)"


def disable_langsmith_tracing() -> None:
    """Disable LangSmith tracing process-wide, whatever the environment says.

    Defence in depth behind the settings validator: ``langsmith.configure(enabled=False)``
    takes precedence over the tracing environment variables in langsmith and in
    langchain-core (0.3 and 1.x).
    """
    import langsmith

    langsmith.configure(enabled=False)
