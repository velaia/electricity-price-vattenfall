"""Long-running MQTT publisher for Vattenfall electricity spot prices.

Publishes five sensors to Home Assistant via MQTT Discovery, updated on every
15-minute interval boundary.
"""

import os
from dataclasses import dataclass
from datetime import datetime, timedelta

from dotenv import load_dotenv


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


def seconds_until_next_boundary(now: datetime) -> int:
    """Return whole seconds until the next 15-minute wall-clock boundary."""
    minutes_into_quarter = now.minute % 15
    next_boundary = (
        now.replace(second=0, microsecond=0)
        + timedelta(minutes=15 - minutes_into_quarter)
    )
    return int((next_boundary - now).total_seconds())


@dataclass(frozen=True)
class MqttConfig:
    host: str
    port: int
    username: str | None
    password: str | None


def load_config() -> MqttConfig:
    """Load MQTT broker config from .env / environment."""
    load_dotenv()
    host = os.environ.get("MQTT_HOST")
    if not host:
        raise RuntimeError(
            "MQTT_HOST is required. Copy .env.example to .env and set the broker host."
        )
    port = int(os.environ.get("MQTT_PORT", "1883"))
    username = os.environ.get("MQTT_USER") or None
    password = os.environ.get("MQTT_PASS") or None
    return MqttConfig(host=host, port=port, username=username, password=password)
