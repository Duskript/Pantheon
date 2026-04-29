"""Mnemosyne — Athenaeum semantic-search client."""

from .client import MnemosyneClient, partition_for
from .exceptions import MnemosyneUnavailableError

__all__ = ["MnemosyneClient", "MnemosyneUnavailableError", "partition_for"]
