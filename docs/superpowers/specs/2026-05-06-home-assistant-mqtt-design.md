# Home Assistant MQTT Integration — Design

**Date:** 2026-05-06
**Status:** Approved

## Goal

Publish German electricity spot prices from the Vattenfall Davis API to Home Assistant via MQTT Discovery, so HA users can build automations and dashboards on top of the data.

## Scope

Five sensors, exposed via MQTT Discovery to an existing Home Assistant Mosquitto broker:

1. `current_price` — active price for the current 15-minute interval (ct/kWh)
2. `next_hour_price` — average price across the next 4 intervals (ct/kWh)
3. `today_min` — minimum price across today's 96 intervals
4. `today_max` — maximum price across today's 96 intervals
5. `today_avg` — mean price across today's 96 intervals

All values in ct/kWh, `device_class: monetary`, `state_class: measurement`.

## Non-goals

- Tomorrow's metrics, full forecast attributes, "cheap hours" binary sensor, best-window finder — possible follow-ups, deferred.
- Docker packaging — script-only for now.
- HA-side automations or dashboards — provided by the user.

## Architecture

A new `mqtt_publisher.py` runs as a long-lived process. On startup it:

1. Loads broker config from `.env`.
2. Connects to MQTT, registers a Last Will on `vattenfall/prices/availability` (`offline`).
3. Publishes `online` to availability.
4. Publishes one retained Discovery config message per sensor.
5. Enters the scheduling loop: sleep until next 15-minute boundary (`:00`, `:15`, `:30`, `:45`), compute values, publish state, repeat.

The publisher reuses existing functions from `main.py` (DB lookup, Davis API fetch). It does not duplicate that logic.

## Components

### Config loader

Reads `.env` via `python-dotenv`:

| Variable     | Required | Default     |
| ------------ | -------- | ----------- |
| `MQTT_HOST`  | yes      | —           |
| `MQTT_PORT`  | no       | `1883`      |
| `MQTT_USER`  | no       | unset       |
| `MQTT_PASS`  | no       | unset       |

Auth is applied only if both `MQTT_USER` and `MQTT_PASS` are set.

### Price source

Thin wrapper around the existing SQLite cache. If today's intervals are missing from the DB, falls back to the existing `get_davis_token` + `get_current_electricity_price` flow and persists the result before returning.

### Computations

Given today's 96 interval values and the current timestamp:

- `current_price` — value at the active 15-minute interval
- `next_hour_price` — mean of the next 4 intervals (the API gives 15-min granularity, so "next hour" = 4 intervals)
- `today_min`, `today_max`, `today_avg` — straightforward aggregates over the 96 values

### MQTT client

`paho-mqtt` with:

- `client_id = "vattenfall-prices"`
- Last Will: topic `vattenfall/prices/availability`, payload `offline`, retained
- Auto-reconnect enabled (paho default)
- Auth applied conditionally based on env vars

### Discovery publisher

Sends one retained config message per sensor to `homeassistant/sensor/vattenfall_<name>/config` at startup. All five sensors share a single `device` block so HA groups them under one device:

```json
{
  "device": {
    "identifiers": ["vattenfall_prices"],
    "name": "Vattenfall Spot Prices",
    "manufacturer": "Vattenfall Davis API"
  },
  "unique_id": "vattenfall_<name>",
  "name": "Vattenfall <Human Name>",
  "state_topic": "vattenfall/prices/<name>/state",
  "availability_topic": "vattenfall/prices/availability",
  "unit_of_measurement": "ct/kWh",
  "device_class": "monetary",
  "state_class": "measurement",
  "suggested_display_precision": 2
}
```

### State publisher

Sends retained state messages (numeric strings, e.g., `"23.45"`) to `vattenfall/prices/<name>/state` on each 15-minute boundary.

### Scheduler

`asyncio` loop:

1. Compute seconds until the next `:00/:15/:30/:45` boundary.
2. `await asyncio.sleep(seconds)`.
3. Compute values, publish, log via `icecream`.
4. Loop.

## Topic layout

```
homeassistant/sensor/vattenfall_current_price/config    (retained, startup)
homeassistant/sensor/vattenfall_next_hour_price/config
homeassistant/sensor/vattenfall_today_min/config
homeassistant/sensor/vattenfall_today_max/config
homeassistant/sensor/vattenfall_today_avg/config

vattenfall/prices/current_price/state                   (retained, every 15min)
vattenfall/prices/next_hour_price/state
vattenfall/prices/today_min/state
vattenfall/prices/today_max/state
vattenfall/prices/today_avg/state

vattenfall/prices/availability                          (LWT: online/offline, retained)
```

## Error handling

| Failure                              | Behavior                                                                |
| ------------------------------------ | ----------------------------------------------------------------------- |
| Broker unreachable on startup        | Exponential backoff: 1s → 2s → 4s → … → 60s cap, retry forever          |
| Mid-run broker disconnect            | paho auto-reconnect; LWT marks entities `unavailable` until reconnected |
| API fetch fails when DB empty        | Log, skip publish for this interval, retry on next boundary             |
| Tomorrow's data missing (before ~13) | Not relevant — chosen sensors only use today's data                     |
| `.env` missing or no `MQTT_HOST`     | Fail fast with a clear error message                                    |

## Dependencies

Add to `pyproject.toml`:

- `paho-mqtt`
- `python-dotenv`

## File layout

- `mqtt_publisher.py` — new long-running script
- `.env.example` — documents required/optional env vars
- `.env` — gitignored (already covered by `.gitignore`)
- `pyproject.toml` — adds the two new deps
