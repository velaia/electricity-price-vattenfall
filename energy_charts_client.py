"""Thin wrapper around the energy-charts.info day-ahead price API.

Isolates all energy-charts specifics (endpoint, units, timezone bucketing)
behind a small interface so the rest of the codebase only ever sees
``{date_str: {HHMM_key: price_ct}}`` — the same shape the Vattenfall API
produces for Germany.

Prices are returned in EUR/MWh; the wrapper converts them to ct/kWh (÷10)
to match the Vattenfall data stored in the SQLite cache.
"""

import time
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

from icecream import ic

API_URL = "https://api.energy-charts.info/price"
_ZONE = ZoneInfo("Europe/Brussels")  # all 8 zones are CET/CEST

# Bidding zones covered by this tool. DK defaults to DK1 (Jutland), the zone
# directly coupled with Germany; DK2 is coupled with Sweden instead.
BIDDING_ZONES = {
    'FR': 'FR', 'NL': 'NL', 'BE': 'BE', 'AT': 'AT', 'CH': 'CH',
    'PL': 'PL', 'CZ': 'CZ', 'DK': 'DK1',
}

# Backoff (seconds) between retries after an HTTP 429 rate-limit response.
_RETRY_BACKOFFS = (0, 2, 4)


def eur_per_mwh_to_ct_per_kwh(value: float) -> float:
    """Convert a price from EUR/MWh to ct/kWh (1 EUR/MWh = 0.1 ct/kWh)."""
    return value / 10.0


def interval_key(hour: int, minute: int = 0) -> str:
    """Return the HHMM-style key used by the Vattenfall data (e.g. 1345)."""
    return str(hour * 100 + minute)


def _response_to_prices(payload: dict) -> dict[str, dict]:
    """Convert an energy-charts response to {date_str: {HHMM_key: price_ct}}.

    Timestamps are UNIX seconds; they are bucketed by local (CET/CEST) date.
    On the DST fall-back duplicate hour the last value wins (dict overwrite).
    """
    prices: dict[str, dict] = {}
    for unix_ts, price in zip(payload['unix_seconds'], payload['price']):
        dt = datetime.fromtimestamp(unix_ts, tz=_ZONE)
        date_str = dt.strftime('%Y-%m-%d')
        key = interval_key(dt.hour, dt.minute)
        prices.setdefault(date_str, {})[key] = eur_per_mwh_to_ct_per_kwh(price)
    return prices


def fetch_day_ahead_prices(country: str, start_date: str, end_date: str) -> dict[str, dict]:
    """Fetch day-ahead prices for a country between two dates (inclusive).

    Returns {date_str: {HHMM_key: price_ct}}. Degrades gracefully: a range
    with no data (HTTP 400) or a persistent rate limit returns {} so callers
    can fall back to a today-only chart.
    """
    params = {'bzn': BIDDING_ZONES[country], 'start': start_date, 'end': end_date}

    for attempt, backoff in enumerate(_RETRY_BACKOFFS):
        if attempt:
            ic(f"energy-charts rate limited (429), retrying in {backoff}s")
            time.sleep(backoff)
        resp = requests.get(API_URL, params=params, timeout=30)

        if resp.status_code == 200:
            return _response_to_prices(resp.json())
        if resp.status_code == 429:
            continue
        ic(f"energy-charts request failed: HTTP {resp.status_code} for {country} {start_date}..{end_date}")
        return {}

    ic(f"energy-charts rate limit persisted for {country} {start_date}..{end_date}")
    return {}
