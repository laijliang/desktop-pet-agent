"""Centralised time utilities.

All code that needs the current time should import get_now() from here
rather than calling datetime.now() directly.
"""

from __future__ import annotations

from datetime import datetime


def get_now() -> datetime:
    """Return the current local datetime (naive, consistent with the rest of the codebase)."""
    return datetime.now()
