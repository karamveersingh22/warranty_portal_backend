"""
Warranty calculation logic.
"""

from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def calculate_warranty(warranty_start: datetime, warranty_end: datetime) -> dict:
    """
    Calculate warranty details from the persisted warranty window.
    """
    start = warranty_start
    end = warranty_end
    today = datetime.utcnow()

    remaining_days = (end - today).days
    remaining_months = remaining_days // 30
    total_days = (end - start).days

    if total_days > 0:
        percent_elapsed = max(0, min(100, int(((today - start).days / total_days) * 100)))
    else:
        percent_elapsed = 0

    return {
        "start": start,
        "end": end,
        "remaining_days": max(0, remaining_days),
        "remaining_months": max(0, remaining_months),
        "status": "active" if remaining_days > 0 else "expired",
        "percent_elapsed": percent_elapsed,
    }
