"""
The registered policies, by key (#306).

A key is the policy's id and version joined by a hyphen, for example ``band-v1``. The
registry holds one instance per policy, so every caller of ``get_policy`` gets the same
object.

The registry is its own module because it imports every policy module, and those import
``base.py``.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from backend.app.student.policy.band import BAND_V1
from backend.app.student.policy.base import Policy, policy_key

_POLICIES: Final[Mapping[str, Policy]] = MappingProxyType(
    {policy_key(policy): policy for policy in (BAND_V1,)}
)


def registered_policies() -> tuple[str, ...]:
    """The keys of the registered policies, sorted."""
    return tuple(sorted(_POLICIES))


def get_policy(key: str) -> Policy:
    """
    Get a registered policy.

    Args:
        key: Policy id and version, for example ``band-v1``

    Raises:
        KeyError: If no policy is registered under ``key``
    """
    try:
        return _POLICIES[key]
    except KeyError:
        registered = ", ".join(registered_policies())
        raise KeyError(f"Unknown policy {key!r}. Registered policies: {registered}") from None
