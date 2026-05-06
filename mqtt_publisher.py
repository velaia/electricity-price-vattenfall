"""Long-running MQTT publisher for Vattenfall electricity spot prices.

Publishes five sensors to Home Assistant via MQTT Discovery, updated on every
15-minute interval boundary.
"""

from datetime import datetime


def current_interval_index(now: datetime) -> int:
    """Return the index (0-95) of the 15-minute interval containing ``now``."""
    return now.hour * 4 + now.minute // 15


def compute_metrics(prices: dict[str, float], now: datetime) -> dict[str, float]:
    """Compute the five published metrics from a dict of 96 interval prices.

    ``prices`` maps stringified interval index ("0".."95") to ct/kWh value.
    """
    values = [float(prices[str(i)]) for i in range(96)]
    idx = current_interval_index(now)

    current = values[idx]
    next_intervals = values[idx + 1 : idx + 5]
    next_hour = sum(next_intervals) / len(next_intervals) if next_intervals else current

    return {
        "current_price": round(current, 2),
        "next_hour_price": round(next_hour, 2),
        "today_min": round(min(values), 2),
        "today_max": round(max(values), 2),
        "today_avg": round(sum(values) / len(values), 2),
    }
