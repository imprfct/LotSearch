"""Data model for tracked pages configuration."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TrackedPage:
    """Represents a page tracked by the monitoring service."""

    id: int | None
    label: str
    url: str
    enabled: bool = True
