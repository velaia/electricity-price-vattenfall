# Strom Börsenpreis

Get current German electricity prices from [Vattenfall Börsenpreise](https://www.vattenfall.de/strom/tarife/oekostrom-dynamik-boersenpreise) — plus day-ahead prices for Germany's neighbors from [energy-charts.info](https://www.energy-charts.info) — and consume them as charts, Home Assistant sensors, or via an MCP server.

Tomorrow's prices are published between noon and 3 PM each day and are not visible in the web UI of Vattenfall. But the API provides them, so they will appear in this app.

![Sample diagram](static/dual_timeline_plot.png)
*Sample diagram output of the program*

## Features

- Fetches 15-minute spot prices (ct/kWh) for today and tomorrow
- Covers Germany (Vattenfall API) plus FR, NL, BE, AT, CH, PL, CZ, DK (energy-charts.info, no API key needed)
- Caches prices in SQLite (`energy_prices.db`) so the API is only called when data is missing
- Renders charts in two styles: classic seaborn and synthwave "futuristic"
- Publishes price sensors to Home Assistant via MQTT Discovery
- Exposes the chart and data through an MCP server

## Usage

This assumes you have [Astral uv](https://github.com/astral-sh/uv) installed.

### Charts

```commandline
uv run main.py
```

Generates `dual_timeline_plot.png` in the project root — today's and tomorrow's
hourly prices.

Add `-a`/`--all` to also render the two summary plots:
- `price_distribution.png` — daily mean with a ±1σ band
- `price_hourly_profile.png` — per-interval mean over all days with ±1σ/±2σ bands

Add `-f`/`--futuristic` for the synthwave variants.

### European countries

Pass `-c`/`--country` to chart day-ahead prices for any supported market (default `DE`):

```commandline
uv run main.py -c FR
uv run main.py -c DK
```

Supported countries: `DE`, `FR`, `NL`, `BE`, `AT`, `CH`, `PL`, `CZ`, `DK`. Non-DE data comes from [energy-charts.info](https://www.energy-charts.info) (Fraunhofer ISE) — no registration or API key required. `DK` uses the DK1 bidding zone (Jutland, coupled with Germany). Prices are cached per country in the same SQLite database.

Non-DE runs write country-suffixed files, e.g. `dual_timeline_plot_fr.png`, `price_distribution_fr.png`, `price_hourly_profile_fr.png` (plus `_futuristic` variants with `-f`).

### Comparison chart

Pass `--compare` to render a single chart comparing the **top 5 countries by population** (DE, FR, PL, NL, BE):

```commandline
uv run main.py --compare
uv run main.py --compare -f   # synthwave variant
```

Each country gets its own color; today's line is solid, tomorrow's is dashed in a lighter shade of the same color. Legend shows all 10 series (5 countries × today/tomorrow). Output: `comparison_plot.png` or `comparison_plot_futuristic.png`.

Plots are written at 150 dpi (2100×1050 px). PNG encoding dominates the runtime,
so raising `PLOT_DPI` in `main.py` costs roughly linearly in wall-clock time.

### Home Assistant (MQTT)

```commandline
uv run mqtt_publisher.py
```

Publishes 8 sensors (current price, next-hour price, today min/max/avg, tomorrow min/max/avg) to Home Assistant via MQTT Discovery, updated on every 15-minute boundary. Copy `.env.example` to `.env` and set `MQTT_HOST` (plus `MQTT_USER`/`MQTT_PASS` if your broker requires authentication).

### MCP server

```commandline
uv run mcp_server.py
```

Exposes two tools: `get_price_chart` (returns the chart image) and `get_price_data` (raw prices as a text table). Runs on streamable-http by default; pass `--stdio` for stdio transport.

### Chat with Ollama

```commandline
uv run mcp_server.py   # terminal 1
uv run ollama_chat.py  # terminal 2
```

Lets a local Ollama model (gemma4) answer questions about prices by calling the MCP server's tools.

## Docker

```commandline
docker build -t vattenfall-prices-germany:0.1 .
docker run vattenfall-prices-germany:0.1
```

## Database

Prices are cached in `energy_prices.db` (SQLite). Inspect it with:

```commandline
sqlite3 energy_prices.db < stats.sql
```

## TODO

* [ ] Idea: Gradio app that can run in HF Spaces?
* [ ] package?
