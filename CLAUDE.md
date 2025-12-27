# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python script that fetches German electricity spot prices from the Vattenfall Davis API and generates a visualization showing today's and tomorrow's hourly prices. The program outputs a PNG chart showing price trends over 24 hours for up to 2 days.

## Development Commands

### Running the Application

```bash
uv run main.py
```

This command:
- Creates/uses a virtual environment automatically
- Installs dependencies from `pyproject.toml` and `uv.lock`
- Executes the main script
- Generates `dual_timeline_plot.png` in the project root

### Docker Build

```bash
docker build -t vattenfall-prices-germany:0.1 .
```

### Docker Run

```bash
docker run vattenfall-prices-germany:0.1
```

## Architecture

### Single-File Application

This is a simple single-file Python application (`main.py`) with no complex module structure. All functionality is contained in one file with three main functions.

### API Flow

1. **Authentication**: `get_davis_token()` obtains an anonymous access token from Vattenfall's Davis API
   - No user credentials needed
   - Token is temporary and used for the session

2. **Data Retrieval**: `get_current_electricity_price(davis_token)` fetches spot prices
   - Requests 15-minute interval data (`Typ: "15MIN_STROM"`)
   - API returns both today and tomorrow's prices (tomorrow available after noon)
   - Data structure: JSON with nested `Result.Tage` array containing daily price data

3. **Visualization**: `main()` orchestrates the flow and generates the plot
   - Uses pandas DataFrame for data manipulation
   - Extracts `WerteNetto` (net prices in ct/kWh) from each day
   - Creates a dual-line seaborn plot comparing days
   - Saves as `dual_timeline_plot.png` at 300 DPI

### Data Structure

The API returns prices in this structure:
```
Result.Tage[
  {
    "Datum": "YYYY-MM-DD",
    "WerteBrutto": {hourly dict},
    "WerteNetto": {hourly dict}  # Used for plotting
  }
]
```

Each `WerteNetto` dict has keys "0" through "23" representing hours, with values as floats (ct/kWh).

### Dependencies

- `requests`: HTTP client for Vattenfall API calls
- `matplotlib` + `seaborn`: Plotting and visualization with seaborn theme
- `pandas`: DataFrame manipulation for plotting
- `icecream`: Debug printing (used throughout for development visibility)

## Key Implementation Details

### API Specifics

- Base URL: `https://davis.vattenfall.de/api/digitalinterface/1.3/`
- Subscription key: `b2b769e800fb49a7b685c49d050c825d` (included in headers)
- The script mimics browser requests with full headers to avoid API rejection

### Plot Characteristics

- Y-axis starts at 0 for price comparisons
- X-axis shows hours 0-23 (24-hour format)
- Automatically handles 1 or 2 days of data
- Output saved in project root, not `static/` directory
