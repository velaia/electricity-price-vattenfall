# Home Assistant MQTT Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish Vattenfall spot prices to an existing Home Assistant Mosquitto broker via MQTT Discovery, exposing five sensors that update every 15 minutes.

**Architecture:** Long-running async script (`mqtt_publisher.py`) reuses the existing `get_price_data()` from `main.py` to load today's prices (DB-cached, API fallback), computes five metrics, and publishes retained state messages aligned to 15-minute interval boundaries. Discovery configs are sent once on startup; LWT signals availability.

**Tech Stack:** Python 3.13, `paho-mqtt`, `python-dotenv`, existing `sqlite3`/`requests`/`icecream`, `asyncio` (stdlib).

**Spec:** `docs/superpowers/specs/2026-05-06-home-assistant-mqtt-design.md`

**Working branch:** `feature/home-assistant-mqtt`

---

## File Structure

| File | Status | Responsibility |
| ---- | ------ | -------------- |
| `mqtt_publisher.py` | Create | Long-running script: config, computations, scheduling, MQTT publishing |
| `.env.example` | Create | Documents required/optional env vars |
| `tests/__init__.py` | Create | Marks tests as a package |
| `tests/test_mqtt_publisher.py` | Create | Unit tests for pure logic (metrics, scheduling) |
| `pyproject.toml` | Modify | Add `paho-mqtt`, `python-dotenv`, `pytest` (dev) |
| `.gitignore` | Modify | Ensure `.env` is ignored |

`mqtt_publisher.py` is kept as a single file to match the project's existing single-file convention (per `CLAUDE.md`). Internally it has clear sections: config, metrics, scheduling, MQTT client, main loop.

---

## Task 1: Add dependencies and `.env.example`

**Files:**
- Modify: `pyproject.toml`
- Create: `.env.example`
- Modify: `.gitignore`

- [ ] **Step 1: Add dependencies to `pyproject.toml`**

In the `dependencies` array, add `paho-mqtt>=2.1.0` and `python-dotenv>=1.0.1`. The final array should look like:

```toml
dependencies = [
    "icecream>=2.2.0",
    "matplotlib>=3.10.9",
    "mcp[cli]>=1.0.0",
    "ollama>=0.6.2",
    "paho-mqtt>=2.1.0",
    "python-dotenv>=1.0.1",
    "requests>=2.33.1",
    "seaborn>=0.13.2",
]
```

Add a dev dependency group for pytest. After the `dependencies` array, add:

```toml
[dependency-groups]
dev = [
    "pytest>=8.3.0",
]
```

- [ ] **Step 2: Lock dependencies**

Run: `uv lock`
Expected: New entries for `paho-mqtt`, `python-dotenv`, `pytest`. No errors.

- [ ] **Step 3: Create `.env.example`**

```
# Vattenfall MQTT Publisher configuration
# Copy this file to .env and fill in the values for your environment.

# Required
MQTT_HOST=192.168.1.10

# Optional (defaults shown)
MQTT_PORT=1883

# Optional — only set both if your broker requires authentication
# MQTT_USER=homeassistant
# MQTT_PASS=changeme
```

- [ ] **Step 4: Confirm `.env` is gitignored**

Read `.gitignore`. If it does not already contain a line `.env`, append one:

```
.env
```

If it already contains `.env`, leave it alone.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock .env.example .gitignore
git commit -m "feat: add paho-mqtt and python-dotenv dependencies for HA integration"
```

---

## Task 2: Pure metric computations (TDD)

**Files:**
- Create: `tests/__init__.py` (empty file)
- Create: `tests/test_mqtt_publisher.py`
- Create: `mqtt_publisher.py`

The metrics logic is pure: given a dict of 96 interval prices and a current timestamp, return five floats. We'll TDD this first.

- [ ] **Step 1: Create empty test package marker**

Create `tests/__init__.py` with no content (zero bytes).

- [ ] **Step 2: Write failing tests for `current_interval_index`**

Create `tests/test_mqtt_publisher.py` with:

```python
from datetime import datetime
import pytest

from mqtt_publisher import current_interval_index, compute_metrics


class TestCurrentIntervalIndex:
    def test_midnight_is_zero(self):
        assert current_interval_index(datetime(2026, 5, 6, 0, 0)) == 0

    def test_first_quarter(self):
        assert current_interval_index(datetime(2026, 5, 6, 0, 14, 59)) == 0

    def test_second_quarter(self):
        assert current_interval_index(datetime(2026, 5, 6, 0, 15)) == 1

    def test_one_pm(self):
        assert current_interval_index(datetime(2026, 5, 6, 13, 0)) == 52

    def test_last_interval_of_day(self):
        assert current_interval_index(datetime(2026, 5, 6, 23, 45)) == 95
```

- [ ] **Step 3: Run tests — expect failure**

Run: `uv run pytest tests/test_mqtt_publisher.py::TestCurrentIntervalIndex -v`
Expected: ImportError or "function not defined" — `mqtt_publisher.py` does not exist yet.

- [ ] **Step 4: Create `mqtt_publisher.py` with `current_interval_index`**

```python
"""Long-running MQTT publisher for Vattenfall electricity spot prices.

Publishes five sensors to Home Assistant via MQTT Discovery, updated on every
15-minute interval boundary.
"""

from datetime import datetime


def current_interval_index(now: datetime) -> int:
    """Return the index (0-95) of the 15-minute interval containing ``now``."""
    return now.hour * 4 + now.minute // 15
```

- [ ] **Step 5: Run tests — expect pass**

Run: `uv run pytest tests/test_mqtt_publisher.py::TestCurrentIntervalIndex -v`
Expected: 5 passed.

- [ ] **Step 6: Write failing tests for `compute_metrics`**

Append to `tests/test_mqtt_publisher.py`:

```python
class TestComputeMetrics:
    def _prices(self, values: list[float]) -> dict[str, float]:
        return {str(i): v for i, v in enumerate(values)}

    def test_basic_metrics(self):
        # 96 intervals: index i has price float(i)
        prices = self._prices([float(i) for i in range(96)])
        metrics = compute_metrics(prices, datetime(2026, 5, 6, 0, 0))
        assert metrics["current_price"] == 0.0
        # Next hour = mean of intervals 1, 2, 3, 4
        assert metrics["next_hour_price"] == pytest.approx((1 + 2 + 3 + 4) / 4)
        assert metrics["today_min"] == 0.0
        assert metrics["today_max"] == 95.0
        assert metrics["today_avg"] == pytest.approx(sum(range(96)) / 96)

    def test_next_hour_at_end_of_day_clips(self):
        # When fewer than 4 intervals remain, average what's available
        prices = self._prices([float(i) for i in range(96)])
        # Now = 23:45 → current interval is 95, no next intervals → fall back to current
        metrics = compute_metrics(prices, datetime(2026, 5, 6, 23, 45))
        assert metrics["current_price"] == 95.0
        assert metrics["next_hour_price"] == 95.0

    def test_partial_next_hour(self):
        # Now = 23:30 → current = 94, next intervals = [95]
        prices = self._prices([float(i) for i in range(96)])
        metrics = compute_metrics(prices, datetime(2026, 5, 6, 23, 30))
        assert metrics["current_price"] == 94.0
        assert metrics["next_hour_price"] == 95.0

    def test_rounded_to_two_decimals(self):
        # All metrics should be rounded to 2 decimal places
        prices = self._prices([1.234567] * 96)
        metrics = compute_metrics(prices, datetime(2026, 5, 6, 12, 0))
        for value in metrics.values():
            assert value == 1.23
```

- [ ] **Step 7: Run tests — expect failure**

Run: `uv run pytest tests/test_mqtt_publisher.py::TestComputeMetrics -v`
Expected: ImportError or AttributeError — `compute_metrics` not defined.

- [ ] **Step 8: Implement `compute_metrics`**

Append to `mqtt_publisher.py`:

```python
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
```

- [ ] **Step 9: Run tests — expect pass**

Run: `uv run pytest tests/test_mqtt_publisher.py -v`
Expected: 9 passed.

- [ ] **Step 10: Commit**

```bash
git add tests/__init__.py tests/test_mqtt_publisher.py mqtt_publisher.py
git commit -m "feat(mqtt): add metric computations with tests"
```

---

## Task 3: Scheduling helper (TDD)

**Files:**
- Modify: `tests/test_mqtt_publisher.py`
- Modify: `mqtt_publisher.py`

- [ ] **Step 1: Write failing tests for `seconds_until_next_boundary`**

Append to `tests/test_mqtt_publisher.py`:

```python
from mqtt_publisher import seconds_until_next_boundary


class TestSecondsUntilNextBoundary:
    def test_just_after_boundary(self):
        # 12:00:00.000 → next boundary is 12:15 → 900s
        now = datetime(2026, 5, 6, 12, 0, 0)
        assert seconds_until_next_boundary(now) == 900

    def test_one_second_before_boundary(self):
        # 12:14:59 → 1 second
        now = datetime(2026, 5, 6, 12, 14, 59)
        assert seconds_until_next_boundary(now) == 1

    def test_mid_interval(self):
        # 12:07:30 → next boundary is 12:15 → 7m30s = 450s
        now = datetime(2026, 5, 6, 12, 7, 30)
        assert seconds_until_next_boundary(now) == 450

    def test_crosses_hour(self):
        # 12:50:00 → next boundary is 13:00 → 600s
        now = datetime(2026, 5, 6, 12, 50, 0)
        assert seconds_until_next_boundary(now) == 600

    def test_crosses_midnight(self):
        # 23:50:00 → next boundary is 00:00 next day → 600s
        now = datetime(2026, 5, 6, 23, 50, 0)
        assert seconds_until_next_boundary(now) == 600
```

- [ ] **Step 2: Run tests — expect failure**

Run: `uv run pytest tests/test_mqtt_publisher.py::TestSecondsUntilNextBoundary -v`
Expected: ImportError — `seconds_until_next_boundary` not defined.

- [ ] **Step 3: Implement `seconds_until_next_boundary`**

Append to `mqtt_publisher.py` (after `compute_metrics`):

```python
from datetime import timedelta


def seconds_until_next_boundary(now: datetime) -> int:
    """Return whole seconds until the next 15-minute wall-clock boundary."""
    minutes_into_quarter = now.minute % 15
    next_boundary = (
        now.replace(second=0, microsecond=0)
        + timedelta(minutes=15 - minutes_into_quarter)
    )
    return int((next_boundary - now).total_seconds())
```

Move the `from datetime import timedelta` up to merge with the existing `from datetime import datetime` import at the top of the file:

```python
from datetime import datetime, timedelta
```

- [ ] **Step 4: Run tests — expect pass**

Run: `uv run pytest tests/test_mqtt_publisher.py -v`
Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/test_mqtt_publisher.py mqtt_publisher.py
git commit -m "feat(mqtt): add 15-minute boundary scheduler helper"
```

---

## Task 4: Config loader

**Files:**
- Modify: `mqtt_publisher.py`
- Modify: `tests/test_mqtt_publisher.py`

- [ ] **Step 1: Write failing tests for `load_config`**

Append to `tests/test_mqtt_publisher.py`:

```python
from mqtt_publisher import load_config, MqttConfig


class TestLoadConfig:
    def test_minimal_config(self, monkeypatch):
        monkeypatch.setenv("MQTT_HOST", "broker.local")
        monkeypatch.delenv("MQTT_PORT", raising=False)
        monkeypatch.delenv("MQTT_USER", raising=False)
        monkeypatch.delenv("MQTT_PASS", raising=False)
        cfg = load_config()
        assert cfg == MqttConfig(host="broker.local", port=1883, username=None, password=None)

    def test_full_config(self, monkeypatch):
        monkeypatch.setenv("MQTT_HOST", "broker.local")
        monkeypatch.setenv("MQTT_PORT", "8883")
        monkeypatch.setenv("MQTT_USER", "ha")
        monkeypatch.setenv("MQTT_PASS", "secret")
        cfg = load_config()
        assert cfg == MqttConfig(host="broker.local", port=8883, username="ha", password="secret")

    def test_missing_host_raises(self, monkeypatch):
        monkeypatch.delenv("MQTT_HOST", raising=False)
        with pytest.raises(RuntimeError, match="MQTT_HOST"):
            load_config()
```

- [ ] **Step 2: Run tests — expect failure**

Run: `uv run pytest tests/test_mqtt_publisher.py::TestLoadConfig -v`
Expected: ImportError.

- [ ] **Step 3: Implement `load_config` and `MqttConfig`**

Append to `mqtt_publisher.py`:

```python
import os
from dataclasses import dataclass

from dotenv import load_dotenv


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
```

Note: `import os` and `from dataclasses import dataclass` go at the top of the file with the other imports — group them with the existing imports rather than mid-file.

- [ ] **Step 4: Run tests — expect pass**

Run: `uv run pytest tests/test_mqtt_publisher.py -v`
Expected: 17 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/test_mqtt_publisher.py mqtt_publisher.py
git commit -m "feat(mqtt): add .env config loader"
```

---

## Task 5: MQTT client wrapper

**Files:**
- Modify: `mqtt_publisher.py`

This task adds the MQTT plumbing: connection (with auth + LWT), Discovery config publishing, and state publishing. We do not unit-test paho itself; the integration is verified manually in Task 7.

- [ ] **Step 1: Add sensor metadata constants**

Append to `mqtt_publisher.py`:

```python
AVAILABILITY_TOPIC = "vattenfall/prices/availability"

# Each sensor: (key used in compute_metrics, human-readable name)
SENSORS: list[tuple[str, str]] = [
    ("current_price", "Current Price"),
    ("next_hour_price", "Next Hour Price"),
    ("today_min", "Today Min"),
    ("today_max", "Today Max"),
    ("today_avg", "Today Avg"),
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
```

- [ ] **Step 2: Add MQTT connect helper**

Append to `mqtt_publisher.py`:

```python
import json
import time

import paho.mqtt.client as mqtt
from icecream import ic


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
```

Move `import json`, `import time`, `import paho.mqtt.client as mqtt`, and `from icecream import ic` up to the top of the file with the existing imports.

- [ ] **Step 3: Add discovery publisher**

Append to `mqtt_publisher.py`:

```python
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
```

- [ ] **Step 4: Add state publisher**

Append to `mqtt_publisher.py`:

```python
def publish_state(client: mqtt.Client, metrics: dict[str, float]) -> None:
    """Publish a retained state message for each sensor."""
    for key, _name in SENSORS:
        client.publish(
            _state_topic(key),
            payload=f"{metrics[key]:.2f}",
            qos=1,
            retain=True,
        )
    ic(f"Published state: {metrics}")
```

- [ ] **Step 5: Verify the file imports cleanly**

Run: `uv run python -c "import mqtt_publisher; print('ok')"`
Expected: `ok`

- [ ] **Step 6: Re-run unit tests to confirm nothing broke**

Run: `uv run pytest tests/test_mqtt_publisher.py -v`
Expected: 17 passed.

- [ ] **Step 7: Commit**

```bash
git add mqtt_publisher.py
git commit -m "feat(mqtt): add paho client, discovery, and state publishers"
```

---

## Task 6: Main async loop

**Files:**
- Modify: `mqtt_publisher.py`

- [ ] **Step 1: Add the publish-once helper**

Append to `mqtt_publisher.py`:

```python
from datetime import date

from main import get_price_data


def publish_for_now(client: mqtt.Client, db_path: str, now: datetime) -> None:
    """Compute metrics for ``now`` and publish them. Skip on data error."""
    try:
        dates_data = get_price_data(db_path)
        today_str = date.today().strftime("%Y-%m-%d")
        if today_str not in dates_data:
            ic(f"No data for {today_str}; skipping publish")
            return
        metrics = compute_metrics(dates_data[today_str], now)
        publish_state(client, metrics)
    except Exception as exc:
        ic(f"publish_for_now failed: {exc}")
```

Move `from datetime import date` to merge with the existing `from datetime import datetime, timedelta` line:

```python
from datetime import date, datetime, timedelta
```

- [ ] **Step 2: Add the async scheduling loop**

Append to `mqtt_publisher.py`:

```python
import asyncio


async def run(db_path: str = "energy_prices.db") -> None:
    """Main loop: connect, publish discovery + initial state, then publish on every
    15-minute boundary forever."""
    cfg = load_config()
    client = connect_mqtt(cfg)
    publish_discovery(client)

    # Publish current state immediately so HA shows values right away.
    publish_for_now(client, db_path, datetime.now())

    while True:
        delay = seconds_until_next_boundary(datetime.now())
        ic(f"Sleeping {delay}s until next 15-minute boundary")
        await asyncio.sleep(delay)
        publish_for_now(client, db_path, datetime.now())


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        ic("Shutting down")


if __name__ == "__main__":
    main()
```

Move `import asyncio` to the top of the file with the other imports.

- [ ] **Step 3: Verify the file still imports**

Run: `uv run python -c "import mqtt_publisher; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Re-run unit tests**

Run: `uv run pytest tests/test_mqtt_publisher.py -v`
Expected: 17 passed.

- [ ] **Step 5: Commit**

```bash
git add mqtt_publisher.py
git commit -m "feat(mqtt): add async main loop tying it all together"
```

---

## Task 7: End-to-end manual verification

**Files:** none modified — this task is verification only.

The unit tests cover pure logic. This task verifies that the full publisher actually talks to a real broker and that HA discovers the sensors.

- [ ] **Step 1: Create local `.env`**

```bash
cp .env.example .env
```

Then edit `.env` and set `MQTT_HOST` (and `MQTT_USER`/`MQTT_PASS` if your broker requires auth) to match your Home Assistant Mosquitto add-on.

- [ ] **Step 2: Run the publisher**

Run: `uv run mqtt_publisher.py`

Expected output (icecream lines):
```
ic| 'Connected to MQTT broker at <host>:<port>'
ic| 'Published discovery configs and availability=online'
ic| 'Database initialized at energy_prices.db'
ic| 'Using cached data for <today>' (or 'Fetching missing data from API')
ic| 'Published state: {...}'
ic| 'Sleeping <N>s until next 15-minute boundary'
```

- [ ] **Step 3: Verify in Home Assistant**

In HA, open Settings → Devices & Services → MQTT. A new device "Vattenfall Spot Prices" should appear with five entities:

- `sensor.vattenfall_current_price`
- `sensor.vattenfall_next_hour_price`
- `sensor.vattenfall_today_min`
- `sensor.vattenfall_today_max`
- `sensor.vattenfall_today_avg`

Each should show a numeric value in `ct/kWh`.

- [ ] **Step 4: Verify availability behaviour**

Stop the publisher (Ctrl-C). Within ~30 seconds, all five sensors in HA should show as `unavailable` (Last Will fired).

Restart the publisher; the sensors should return to numeric values within seconds.

- [ ] **Step 5: Verify boundary update**

Leave the publisher running across a `:00`/`:15`/`:30`/`:45` boundary. The `current_price` sensor's `last_changed` in HA should update at that boundary.

- [ ] **Step 6: Commit any final cleanup (only if needed)**

If you discovered any bug during verification and fixed it:

```bash
git add mqtt_publisher.py
git commit -m "fix(mqtt): <describe the bug fixed during verification>"
```

Otherwise, no commit needed — verification only.
