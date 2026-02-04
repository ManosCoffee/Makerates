"""Centralized timezone utilities for makerates system."""
from datetime import datetime, timezone
from typing import Optional


def get_utc_now() -> datetime:
    """
    Get current datetime in UTC with timezone awareness.

    Returns:
        datetime: Current UTC time as timezone-aware datetime
    """
    return datetime.now(timezone.utc)


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """
    Ensure datetime is UTC-aware. Converts naive to UTC if needed.

    Args:
        dt: Datetime to convert (can be None, naive, or aware)

    Returns:
        datetime: UTC-aware datetime or None

    Note:
        Naive datetimes are ASSUMED to be UTC (defensive conversion)
    """
    if dt is None:
        return None

    if dt.tzinfo is None:
        # Naive datetime - assume UTC and localize
        return dt.replace(tzinfo=timezone.utc)

    # Already aware - convert to UTC if needed
    return dt.astimezone(timezone.utc)


def to_iso_utc(dt: datetime) -> str:
    """
    Convert datetime to ISO 8601 string in UTC.

    Args:
        dt: Datetime to convert

    Returns:
        str: ISO 8601 formatted string with UTC timezone (e.g., '2024-01-01T12:00:00+00:00')
    """
    utc_dt = ensure_utc(dt)
    return utc_dt.isoformat() if utc_dt else None
