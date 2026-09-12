"""Named refusals. Exact mode never approximates."""

from __future__ import annotations


class BoughError(Exception):
    reason: str

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(f"{reason}: {message}")


class BoughRefusal(BoughError):
    """A model or query that Bough v0 will not compile or answer."""
