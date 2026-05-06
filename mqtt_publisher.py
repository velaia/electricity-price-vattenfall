"""Long-running MQTT publisher for Vattenfall electricity spot prices.

Publishes five sensors to Home Assistant via MQTT Discovery, updated on every
15-minute interval boundary.
"""

import asyncio
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

import paho.mqtt.client as mqtt
from dotenv import load_dotenv
from icecream import ic

from main import get_price_data


def current_interval_index(now: datetime) -> int:
    """Return the index (0-95) of the 15-minute interval containing ``now``."""
    return now.hour * 4 + now.minute // 15


def _ordered_values(prices: dict[str, float]) -> list[float]:
    """Return a chronologically ordered list of 96 prices.

    The Vattenfall API uses HHMM-style keys ("0", "15", "30", "45", "100",
    ..., "2345"), so keys are sorted numerically.
    """
    return [float(prices[k]) for k in sorted(prices.keys(), key=int)]


def compute_metrics(prices: dict[str, float], now: datetime) -> dict[str, float]:
    """Compute today's five published metrics from a dict of 96 interval prices."""
    values = _ordered_values(prices)
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


def compute_tomorrow_metrics(prices: dict[str, float]) -> dict[str, float]:
    """Compute tomorrow's three aggregate metrics from a dict of 96 interval prices."""
    values = _ordered_values(prices)
    return {
        "tomorrow_min": round(min(values), 2),
        "tomorrow_max": round(max(values), 2),
        "tomorrow_avg": round(sum(values) / len(values), 2),
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
    """Load MQTT broker config from environment variables."""
    host = os.environ.get("MQTT_HOST")
    if not host:
        raise RuntimeError(
            "MQTT_HOST is required. Copy .env.example to .env and set the broker host."
        )
    port = int(os.environ.get("MQTT_PORT", "1883"))
    username = os.environ.get("MQTT_USER") or None
    password = os.environ.get("MQTT_PASS") or None
    return MqttConfig(host=host, port=port, username=username, password=password)


AVAILABILITY_TOPIC = "vattenfall/prices/availability"

SENSORS: list[tuple[str, str]] = [
    ("current_price", "Current Price"),
    ("next_hour_price", "Next Hour Price"),
    ("today_min", "Today Min"),
    ("today_max", "Today Max"),
    ("today_avg", "Today Avg"),
    ("tomorrow_min", "Tomorrow Min"),
    ("tomorrow_max", "Tomorrow Max"),
    ("tomorrow_avg", "Tomorrow Avg"),
]


def _state_topic(key: str) -> str:
    return f"vattenfall/prices/{key}/state"


def _discovery_topic(key: str) -> str:
    return f"homeassistant/sensor/vattenfall_{key}/config"


def _discovery_payload(key: str, name: str) -> dict:
    return {
        "device": {
            "identifiers": ["vattenfall_prices"],
            "name": "Vattenfall Spot Prices",
            "manufacturer": "Vattenfall Davis API",
        },
        "unique_id": f"vattenfall_{key}",
        "name": f"Vattenfall {name}",
        "state_topic": _state_topic(key),
        "availability_topic": AVAILABILITY_TOPIC,
        "unit_of_measurement": "ct/kWh",
        "device_class": "monetary",
        "state_class": "measurement",
        "suggested_display_precision": 2,
    }


def connect_mqtt(cfg: MqttConfig) -> mqtt.Client:
    """Connect to the broker, retrying with exponential backoff. Returns a connected client.

    Last Will is registered so that the broker publishes ``offline`` to the
    availability topic if this process dies unexpectedly.
    """
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="vattenfall-prices",
    )
    if cfg.username and cfg.password:
        client.username_pw_set(cfg.username, cfg.password)
    client.will_set(AVAILABILITY_TOPIC, payload="offline", qos=1, retain=True)

    delay = 1
    while True:
        try:
            client.connect(cfg.host, cfg.port, keepalive=60)
            client.loop_start()
            ic(f"Connected to MQTT broker at {cfg.host}:{cfg.port}")
            return client
        except OSError as exc:
            ic(f"MQTT connect failed: {exc}; retrying in {delay}s")
            time.sleep(delay)
            delay = min(delay * 2, 60)


def publish_discovery(client: mqtt.Client) -> None:
    """Publish retained Discovery config for all five sensors."""
    for key, name in SENSORS:
        client.publish(
            _discovery_topic(key),
            payload=json.dumps(_discovery_payload(key, name)),
            qos=1,
            retain=True,
        )
    client.publish(AVAILABILITY_TOPIC, payload="online", qos=1, retain=True)
    ic("Published discovery configs and availability=online")


def publish_state(client: mqtt.Client, metrics: dict[str, float]) -> None:
    """Publish a retained state message for each metric in ``metrics``.

    Sensors not present in ``metrics`` are skipped — useful when tomorrow's
    data isn't yet available from the API.
    """
    for key, _name in SENSORS:
        if key not in metrics:
            continue
        client.publish(
            _state_topic(key),
            payload=f"{metrics[key]:.2f}",
            qos=1,
            retain=True,
        )
    ic(f"Published state: {metrics}")


def publish_for_now(client: mqtt.Client, db_path: str, now: datetime) -> None:
    """Compute metrics for ``now`` and publish them. Skip on data error.

    Tomorrow's aggregates are published only when tomorrow's data is available
    (typically after ~13:00 local time when the Vattenfall API releases it).
    """
    try:
        dates_data = get_price_data(db_path)
        today_str = now.date().strftime("%Y-%m-%d")
        tomorrow_str = (now.date() + timedelta(days=1)).strftime("%Y-%m-%d")
        if today_str not in dates_data:
            ic(f"No data for {today_str}; skipping publish")
            return
        metrics = compute_metrics(dates_data[today_str], now)
        if tomorrow_str in dates_data:
            metrics.update(compute_tomorrow_metrics(dates_data[tomorrow_str]))
        publish_state(client, metrics)
    except Exception as exc:
        ic(f"publish_for_now failed: {exc}")


async def run(db_path: str = "energy_prices.db") -> None:
    """Main loop: connect, publish discovery + initial state, then publish on every
    15-minute boundary forever."""
    cfg = load_config()
    client = connect_mqtt(cfg)
    publish_discovery(client)

    publish_for_now(client, db_path, datetime.now())

    while True:
        delay = seconds_until_next_boundary(datetime.now())
        ic(f"Sleeping {delay}s until next 15-minute boundary")
        await asyncio.sleep(delay)
        publish_for_now(client, db_path, datetime.now())


def main() -> None:
    load_dotenv()
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        ic("Shutting down")


if __name__ == "__main__":
    main()
