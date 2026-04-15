"""
mail/base.py — Abstract base class for all mail service clients.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class MailClient(ABC):
    """Unified interface for temporary-mailbox providers."""

    @abstractmethod
    async def generate_email(
        self,
        prefix: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> str:
        """Create a new temporary address and return it."""
        ...

    @abstractmethod
    async def poll_code(self, email: str, timeout: int = 120) -> Optional[str]:
        """
        Poll the inbox until a verification code arrives or *timeout* seconds elapse.
        Returns the 6-digit code string, or None on timeout.
        """
        ...

    def supports_fresh_message_tracking(self) -> bool:
        """
        Return True when ``poll_code()`` already deduplicates by message identity
        (UID / message id) rather than by code string alone.
        """
        return False
