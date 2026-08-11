# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repository fetches German electricity spot prices from the Vattenfall Davis API — plus day-ahead prices for Germany's neighbors (FR, NL, BE, AT, CH, PL, CZ, DK) from energy-charts.info — and provides several ways to consume them:

- **`main.py`** — fetches 15-minute spot prices (ct/kWh) for today and tomorrow, caches them in SQLite, and renders charts (classic seaborn or synthwave "futuristic" style). `-c/--country` selects the market (default `DE`).
- **`energy_charts_client.py`** — thin wrapper around the energy-charts.info day-ahead price API (no key needed); converts EUR/MWh to ct/kWh and buckets timestamps into `{date: {HHMM: price}}`.
- **`mqtt_publisher.py`** — long-running daemon that publishes price metrics to Home Assistant via MQTT Discovery, updating on every 15-minute boundary (Germany only).
- **`mcp_server.py`** — MCP server exposing the price chart and raw data as tools (Germany only).
- **`ollama_chat.py`** — chat client that lets a local Ollama model call the MCP server's tools.

## Development Commands

### Fetch prices and generate plots

```bash
uv run main.py
```

Generates three plots in the project root (classic style):
- `dual_timeline_plot.png` — today's and tomorrow's hourly prices
- `price_distribution.png` — daily mean with ±1σ band
- `price_hourly_profile.png` — per-interval mean over all days with ±1σ/±2σ bands

Add `-f`/`--futuristic` for the synthwave variants (`*_futuristic.png`).

Chart any supported market with `-c/--country` (default `DE`):

```bash
uv run main.py -c FR
uv run main.py -c DK
```

Supported: `DE`, `FR`, `NL`, `BE`, `AT`, `CH`, `PL`, `CZ`, `DK`. Non-DE data comes from energy-charts.info (no key); `DK` uses the DK1 zone. Non-DE runs write country-suffixed files (`dual_timeline_plot_fr.png`, `.plot_hash_fr`, …); DE keeps unsuffixed names so the MCP server's chart paths stay valid.

### Comparison chart

```bash
uv run main.py --compare
uv run main.py --compare -f   # synthwave variant
```

Renders a single chart comparing the top 5 countries by population (DE, FR, PL, NL, BE). Each country gets its own color; today = solid line, tomorrow = dashed lighter variant. Output: `comparison_plot.png` / `comparison_plot_futuristic.png`.

### Publish to Home Assistant via MQTT

```bash
uv run mqtt_publisher.py
```

Requires `MQTT_HOST` (see `.env.example`). Runs forever, publishing on every 15-minute boundary.

### MCP server

```bash
uv run mcp_server.py            # streamable-http transport (default)
uv run mcp_server.py --stdio    # stdio transport
```

### Chat with Ollama through the MCP server

```bash
uv run mcp_server.py            # terminal 1
uv run ollama_chat.py           # terminal 2 (needs Ollama running with gemma4)
```

### Tests

```bash
uv run pytest
```

### Docker

```bash
docker build -t vattenfall-prices-germany:0.1 .
docker run vattenfall-prices-germany:0.1
```

## Architecture

### Data Flow

1. **Authentication** (DE only): `get_davis_token()` obtains an anonymous access token from Vattenfall's Davis API. No user credentials needed; the token is temporary and used for the session.
2. **Data Retrieval**: For DE, `get_current_electricity_price(davis_token)` fetches 15-minute spot prices (`Typ: "15MIN_STROM"`), returning today's and tomorrow's prices (tomorrow available after ~noon). For other countries, `get_price_data(db_path, country)` calls `energy_charts_client.fetch_day_ahead_prices(country, start, end)` per date — the API returns 15-min data in EUR/MWh, converted to ct/kWh (÷10) and bucketed by local CET/CEST date.
3. **Caching**: `get_price_data(db_path, country)` stores each day's prices in SQLite (`energy_prices.db`) and only calls the API when today's or tomorrow's data is missing for that country. A missing date (e.g. tomorrow not yet published) degrades gracefully to a today-only chart.
4. **Visualization**: `main()` loads cached data plus per-day and per-interval statistics, then generates the plots.

### SQLite Schema

- `price_days` — one row per date and country (`UNIQUE(country, date)`, `granularity`, `fetched_at`)
- `price_intervals` — one row per 15-minute interval (`day_id` FK, `interval_index`, `price_netto`)

`init_database()` migrates the legacy schema (where `date` was UNIQUE) in place: it renames both tables, recreates them with the new columns, and copies rows as `country='DE'`/`granularity='15MIN'`. The migration is idempotent because `init_database` runs on every `get_price_data` call.

### Data Structure

The API returns prices in this structure:
```
Result.Tage[
  {
    "Datum": "YYYY-MM-DD",
    "WerteBrutto": {HHMM: price},
    "WerteNetto": {HHMM: price}  # Used for storage/plotting
  }
]
```

Each `WerteNetto` dict uses HHMM-style keys ("0", "15", "30", "45", "100", ..., "2345") — 96 intervals per day. `get_price_data()` returns `{date_str: {key: price}}`.

### Plot Change Detection

Each plot has a companion hash file (`.plot_hash`, `.dist_hash`, `.hourly_hash`, plus `_futuristic` variants). `plot_is_current()` skips regeneration when the data hash matches the stored one.

### MQTT Publisher

- Publishes 8 sensors via Home Assistant MQTT Discovery: current price, next-hour price, today min/max/avg, tomorrow min/max/avg.
- Updates on every 15-minute wall-clock boundary (`seconds_until_next_boundary`).
- Config via environment variables (`MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASS`), loaded from `.env`.
- Registers a Last Will so the broker publishes `offline` to the availability topic if the process dies.

### MCP Server

- `get_price_chart` — returns the `dual_timeline_plot.png` image (regenerates it first).
- `get_price_data` — returns today's/tomorrow's prices as a text table (no chart).

## Dependencies

- `requests`: HTTP client for Vattenfall API and energy-charts.info calls (no extra dependency for European prices)
- `matplotlib` + `seaborn`: Plotting and visualization
- `pandas` + `numpy`: Data manipulation
- `sqlite3` (stdlib): Local price cache
- `paho-mqtt`: MQTT publishing for Home Assistant
- `mcp[cli]`: MCP server framework
- `ollama`: Ollama chat client
- `python-dotenv`: `.env` config loading
- `icecream`: Debug printing (used throughout for development visibility)

## Key Implementation Details

### API Specifics

- Base URL: `https://davis.vattenfall.de/api/digitalinterface/1.3/`
- Subscription key: `b2b769e800fb49a7b685c49d050c825d` (included in headers)
- The script mimics browser requests with full headers to avoid API rejection

### Plot Characteristics

- Y-axis starts at 0 for price comparisons (except when prices go negative)
- X-axis shows hours 0-23 (24-hour format)
- Automatically handles 1 or 2 days of data
- Output saved in project root, not `static/` directory
