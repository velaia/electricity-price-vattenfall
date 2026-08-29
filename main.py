import argparse
import requests
import json
import numpy as np
import seaborn as sns
import pandas as pd
from matplotlib import pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patheffects as path_effects
from matplotlib.colors import LinearSegmentedColormap, to_rgb
from datetime import date, datetime, timedelta
from icecream import ic
import sqlite3
import hashlib
import os

from energy_charts_client import fetch_day_ahead_prices

sns.set_theme()

# Top 5 supported markets by population: DE, FR, PL, NL, BE (same as the top 5
# by electricity consumption). Used by the --compare chart.
TOP5_COUNTRIES = ['DE', 'FR', 'PL', 'NL', 'BE']
TOMORROW_LIGHTEN = 0.5  # blend toward white for the tomorrow line of each country


def lighten_color(color, amount: float = TOMORROW_LIGHTEN):
    """Blend a matplotlib color toward white; amount=1 returns white."""
    r, g, b = to_rgb(color)
    return (r + (1 - r) * amount, g + (1 - g) * amount, b + (1 - b) * amount)


# Timeout for Vattenfall Davis API calls. The API is hosted in Germany and the
# script is expected to run on a domestic fiber connection, so 10 seconds is
# generous for both connect and read phases.
REQUEST_TIMEOUT = 10

# Plots are viewed on screen, not printed: 150 dpi gives a 2100x1050 px image,
# already beyond most displays. Dropping from 300 dpi cuts savefig from ~540 ms
# to ~160 ms per plot, since the cost is PNG-encoding the raster, not drawing it.
PLOT_DPI = 150
# compress_level 3 encodes as fast as level 1 but produces a smaller file than
# either 1 or Pillow's default 6 costs in time (~110 ms vs ~160 ms per plot).
PNG_KWARGS = {'compress_level': 3}


def init_database(db_path: str) -> None:
    """Initialize the SQLite database with required tables."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Migrate the legacy (pre-country) schema if present: price_days.date was
    # UNIQUE, which can only hold one market. Recreate both tables so the
    # price_intervals FK stays intact, copying rows with country='DE'.
    cols = {row[1] for row in cursor.execute('PRAGMA table_info(price_days)')}
    if cols and 'country' not in cols:
        ic("Migrating legacy price_days schema (adding country/granularity)")
        cursor.execute('ALTER TABLE price_days RENAME TO price_days_old')
        cursor.execute('ALTER TABLE price_intervals RENAME TO price_intervals_old')
        cursor.execute('''
            CREATE TABLE price_days (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                country TEXT NOT NULL DEFAULT 'DE',
                granularity TEXT NOT NULL DEFAULT '15MIN',
                fetched_at TEXT NOT NULL,
                UNIQUE (country, date)
            )
        ''')
        cursor.execute('''
            CREATE TABLE price_intervals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day_id INTEGER NOT NULL,
                interval_index INTEGER NOT NULL,
                price_netto REAL NOT NULL,
                FOREIGN KEY (day_id) REFERENCES price_days (id),
                UNIQUE (day_id, interval_index)
            )
        ''')
        cursor.execute('''
            INSERT INTO price_days (id, date, country, granularity, fetched_at)
            SELECT id, date, 'DE', '15MIN', fetched_at FROM price_days_old
        ''')
        cursor.execute('''
            INSERT INTO price_intervals (id, day_id, interval_index, price_netto)
            SELECT id, day_id, interval_index, price_netto FROM price_intervals_old
        ''')
        cursor.execute('DROP TABLE price_intervals_old')
        cursor.execute('DROP TABLE price_days_old')

    # Create price_days table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS price_days (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            country TEXT NOT NULL DEFAULT 'DE',
            granularity TEXT NOT NULL DEFAULT '15MIN',
            fetched_at TEXT NOT NULL,
            UNIQUE (country, date)
        )
    ''')

    # Create price_intervals table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS price_intervals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day_id INTEGER NOT NULL,
            interval_index INTEGER NOT NULL,
            price_netto REAL NOT NULL,
            FOREIGN KEY (day_id) REFERENCES price_days (id),
            UNIQUE (day_id, interval_index)
        )
    ''')

    conn.commit()
    conn.close()
    ic(f"Database initialized at {db_path}")


def date_exists_in_db(db_path: str, date_str: str, country: str = "DE") -> bool:
    """Check if a date already exists in the database for a country."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute('SELECT COUNT(*) FROM price_days WHERE date = ? AND country = ?',
                   (date_str, country))
    count = cursor.fetchone()[0]

    conn.close()
    return count > 0


def store_price_data(db_path: str, date_str: str, price_values: dict,
                     country: str = "DE", granularity: str = "15MIN") -> None:
    """Store price data for a specific date in the database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Insert into price_days table
        fetched_at = datetime.now().isoformat()
        cursor.execute(
            'INSERT INTO price_days (date, country, granularity, fetched_at) VALUES (?, ?, ?, ?)',
            (date_str, country, granularity, fetched_at)
        )
        day_id = cursor.lastrowid

        # Insert all intervals into price_intervals table
        for interval_index, price in price_values.items():
            cursor.execute(
                'INSERT INTO price_intervals (day_id, interval_index, price_netto) VALUES (?, ?, ?)',
                (day_id, int(interval_index), float(price))
            )

        conn.commit()
        ic(f"Stored data for {date_str} ({len(price_values)} intervals)")
    except Exception as e:
        conn.rollback()
        ic(f"Error storing data for {date_str}: {e}")
        raise
    finally:
        conn.close()


def load_price_data(db_path: str, date_str: str, country: str = "DE") -> dict:
    """Load price data for a specific date from the database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Get day_id for the date
        cursor.execute('SELECT id FROM price_days WHERE date = ? AND country = ?',
                       (date_str, country))
        result = cursor.fetchone()

        if result is None:
            return None

        day_id = result[0]

        # Get all intervals for this day
        cursor.execute(
            'SELECT interval_index, price_netto FROM price_intervals WHERE day_id = ? ORDER BY interval_index',
            (day_id,)
        )
        intervals = cursor.fetchall()

        # Convert to dict format matching API response
        price_values = {str(interval_index): price for interval_index, price in intervals}
        ic(f"Loaded data for {date_str} from database ({len(price_values)} intervals)")
        return price_values
    finally:
        conn.close()


def country_granularity(country: str) -> str:
    """Return the stored granularity for a country's price data.

    All current markets are 15-minute; 'HOURLY' is reserved for historical
    data (pre-2025-10-01) as future-proofing.
    """
    return '15MIN'


def get_price_data(db_path: str = "energy_prices.db", country: str = "DE") -> dict[str, dict]:
    """Fetch price data for today and tomorrow (from cache or API).

    Returns a dict mapping date strings to their price dicts,
    e.g. {"2026-04-12": {"0": 5.12, "1": 4.98, ...}, ...}

    For DE this uses the Vattenfall Davis API (both days in one call). For
    other countries it fetches day-ahead prices from energy-charts.info per
    date, degrading gracefully when a date (e.g. tomorrow) isn't published yet.
    """
    init_database(db_path)

    today = date.today()
    tomorrow = today + timedelta(days=1)
    today_str = today.strftime("%Y-%m-%d")
    tomorrow_str = tomorrow.strftime("%Y-%m-%d")

    today_data = load_price_data(db_path, today_str, country)
    tomorrow_data = load_price_data(db_path, tomorrow_str, country)

    dates_data = {}

    if today_data is not None:
        dates_data[today_str] = today_data
        ic(f"Using cached data for {today_str} ({country})")

    if tomorrow_data is not None:
        dates_data[tomorrow_str] = tomorrow_data
        ic(f"Using cached data for {tomorrow_str} ({country})")

    if country == "DE":
        if today_data is None or tomorrow_data is None:
            ic("Fetching missing data from API")
            davis_token = get_davis_token()
            response_json = get_current_electricity_price(davis_token)
            ic(response_json)

            for tag in response_json['Result']['Tage']:
                date_str = tag['Datum']
                if date_str not in dates_data:
                    if not date_exists_in_db(db_path, date_str, country):
                        store_price_data(db_path, date_str, tag['WerteNetto'], country)
                    dates_data[date_str] = tag['WerteNetto']
        else:
            ic("All data available in database, skipping API call")
    else:
        for date_str in (today_str, tomorrow_str):
            if date_str in dates_data:
                continue
            try:
                fetched = fetch_day_ahead_prices(country, date_str, date_str)
            except Exception as e:
                ic(f"energy-charts fetch failed for {country} {date_str}: {e}")
                continue
            if date_str in fetched:
                if not date_exists_in_db(db_path, date_str, country):
                    store_price_data(db_path, date_str, fetched[date_str], country)
                dates_data[date_str] = fetched[date_str]

    return dates_data


def load_daily_price_stats(db_path: str, country: str = "DE") -> pd.DataFrame:
    """Load all stored days for a country and compute per-day mean and std."""
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(
            'SELECT d.date, i.price_netto '
            'FROM price_days d JOIN price_intervals i ON i.day_id = d.id '
            'WHERE d.country = ?',
            conn, params=(country,))
    finally:
        conn.close()

    stats = df.groupby('date')['price_netto'].agg(['mean', 'std']).reset_index()
    stats['std'] = stats['std'].fillna(0.0)
    stats = stats.sort_values('date')
    stats['date'] = pd.to_datetime(stats['date'])
    ic(f"Loaded daily stats for {len(stats)} days")
    return stats


def stats_hash_data(stats: pd.DataFrame) -> dict:
    """Serializable view of the daily stats, for plot change detection."""
    return {d.strftime('%Y-%m-%d'): [m, s]
            for d, m, s in zip(stats['date'], stats['mean'], stats['std'])}


def interval_to_position(interval_index: int, granularity: str) -> int:
    """Map a stored interval index (HHMM-style) to a sequential position.

    15-min data: 0, 15, ..., 2345 -> 0..95. Hourly data: 0, 100, ..., 2300 -> 0..23.
    """
    if granularity == 'HOURLY':
        return interval_index // 100
    return (interval_index // 100) * 4 + (interval_index % 100) // 15


def load_hourly_price_stats(db_path: str, country: str = "DE") -> pd.DataFrame:
    """Compute per-interval mean and std across all stored days for a country."""
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(
            'SELECT i.interval_index, i.price_netto '
            'FROM price_intervals i JOIN price_days d ON i.day_id = d.id '
            'WHERE d.country = ?',
            conn, params=(country,))
    finally:
        conn.close()

    # interval_index is stored in HHMM format (0, 15, ..., 2345); map it to a
    # sequential position so the hour axis is uniform for the country's granularity
    df['interval_index'] = df['interval_index'].apply(
        lambda idx: interval_to_position(idx, country_granularity(country)))

    stats = df.groupby('interval_index')['price_netto'].agg(['mean', 'std']).reset_index()
    stats['std'] = stats['std'].fillna(0.0)
    stats = stats.sort_values('interval_index')
    ic(f"Loaded hourly profile stats for {len(stats)} intervals")
    return stats


def hourly_stats_hash_data(stats: pd.DataFrame) -> dict:
    """Serializable view of the hourly profile stats, for plot change detection."""
    return {str(i): [m, s]
            for i, m, s in zip(stats['interval_index'], stats['mean'], stats['std'])}


def plot_is_current(dates_data: dict, plot_path: str, hash_path: str) -> str:
    """Return the data hash, or None if the existing plot already matches it."""
    data_hash = hashlib.md5(json.dumps(dates_data, sort_keys=True).encode()).hexdigest()

    hash_matches = False
    if os.path.exists(hash_path):
        with open(hash_path, 'r') as f:
            hash_matches = f.read().strip() == data_hash

    if os.path.exists(plot_path) and hash_matches:
        return None
    return data_hash


def build_dataframe(dates_data: dict) -> pd.DataFrame:
    dates_list = sorted(dates_data.keys())
    return pd.DataFrame([dates_data[date_str] for date_str in dates_list],
                        index=dates_list)


def comparison_series(countries_data: dict, today_str: str, tomorrow_str: str) -> list[dict]:
    """Build plot-ready series for every country x day that has data.

    countries_data maps country code to {date_str: {HHMM_key: price_ct}}.
    Returns [{country, day ('today'|'tomorrow'), x: [0..95], y: [price_ct]}],
    sorted by country, skipping a country's tomorrow when it isn't published yet.
    """
    series = []
    for country in sorted(countries_data):
        dates_data = countries_data[country]
        for day, date_str in (('today', today_str), ('tomorrow', tomorrow_str)):
            prices = dates_data.get(date_str)
            if not prices:
                continue
            ordered = sorted(prices, key=int)
            x = [interval_to_position(int(k), '15MIN') for k in ordered]
            y = [prices[k] for k in ordered]
            series.append({'country': country, 'day': day, 'x': x, 'y': y})
    return series


def set_hourly_ticks(ax, num_intervals: int, fontsize: int = 10, color: str = None,
                     intervals_per_hour: int = 4):
    """Show only hourly labels (every `intervals_per_hour`-th tick).

    15-minute data has 4 intervals per hour; hourly data has 1.
    """
    hourly_ticks = range(0, num_intervals, intervals_per_hour)
    hourly_labels = [str(i // intervals_per_hour) for i in hourly_ticks]
    ax.set_xticks(hourly_ticks)
    kwargs = {'fontsize': fontsize}
    if color:
        kwargs['color'] = color
    ax.set_xticklabels(hourly_labels, **kwargs)


def generate_plot(dates_data: dict, plot_path: str, hash_path: str,
                  country_name: str = "German", intervals_per_hour: int = 4) -> None:
    """Generate the classic seaborn plot."""
    data_hash = plot_is_current(dates_data, plot_path, hash_path)
    if data_hash is None:
        ic("Plot is up to date, skipping regeneration")
        return

    df = build_dataframe(dates_data)

    # Create figure with better size
    plt.figure(figsize=(14, 7))

    # Use a cleaner style
    sns.set_style("whitegrid")

    # Create line plot with enhanced styling
    ax = sns.lineplot(data=df.transpose(), linewidth=2.5, marker='o', markersize=4,
                     markeredgewidth=0, alpha=0.9, palette='Set1')

    # Set Y-axis to start at 0 with some padding at top
    plt.ylim(bottom=0, top=df.max().max() * 1.1)

    set_hourly_ticks(ax, len(df.columns), intervals_per_hour=intervals_per_hour)

    # Add title and labels
    plt.title(f'{country_name} Electricity Spot Prices', fontsize=18, fontweight='bold', pad=20)
    plt.xlabel('Hour of Day', fontsize=13, fontweight='bold')
    plt.ylabel('Price (ct/kWh)', fontsize=13, fontweight='bold')

    # Enhance grid
    ax.grid(True, alpha=0.3, linestyle='--', linewidth=0.7)
    ax.set_axisbelow(True)

    # Improve legend
    plt.legend(loc='upper left', fontsize=11, framealpha=0.95)

    # Add subtle background color
    ax.set_facecolor('#f8f9fa')

    plt.tight_layout()
    plt.savefig(plot_path, dpi=PLOT_DPI, bbox_inches='tight', facecolor='white',
                pil_kwargs=PNG_KWARGS)

    # Save data hash for change detection
    with open(hash_path, 'w') as f:
        f.write(data_hash)

    ic("Plot regenerated")
    ic(df)


def generate_distribution_plot(stats: pd.DataFrame, plot_path: str, hash_path: str,
                               country_name: str = "German") -> None:
    """Generate the classic seaborn distribution plot (daily mean with a ±1 sigma band)."""
    data_hash = plot_is_current(stats_hash_data(stats), plot_path, hash_path)
    if data_hash is None:
        ic("Distribution plot is up to date, skipping regeneration")
        return

    lower = stats['mean'] - stats['std']
    upper = stats['mean'] + stats['std']

    plt.figure(figsize=(14, 7))
    sns.set_style("whitegrid")
    ax = plt.gca()

    color = sns.color_palette('Set1')[0]
    ax.fill_between(stats['date'], lower, upper, color=color, alpha=0.5,
                    linewidth=0, label='±1σ range')
    ax.plot(stats['date'], stats['mean'], color=color, linewidth=2.5,
            alpha=0.9, label='Daily mean')

    # Spot prices can go negative, so only pin the bottom at 0 when the band stays above it
    plt.ylim(bottom=min(0, lower.min() * 1.1), top=upper.max() * 1.1)
    if lower.min() < 0:
        ax.axhline(0, color='black', alpha=0.4, linewidth=1)

    locator = mdates.AutoDateLocator()
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))

    plt.title(f'{country_name} Electricity Spot Prices — Daily Distribution',
              fontsize=18, fontweight='bold', pad=20)
    plt.xlabel('Date', fontsize=13, fontweight='bold')
    plt.ylabel('Price (ct/kWh)', fontsize=13, fontweight='bold')

    ax.grid(True, alpha=0.3, linestyle='--', linewidth=0.7)
    ax.set_axisbelow(True)

    plt.legend(loc='upper left', fontsize=11, framealpha=0.95)

    ax.set_facecolor('#f8f9fa')

    plt.tight_layout()
    plt.savefig(plot_path, dpi=PLOT_DPI, bbox_inches='tight', facecolor='white',
                pil_kwargs=PNG_KWARGS)

    with open(hash_path, 'w') as f:
        f.write(data_hash)

    ic("Distribution plot regenerated")


def generate_hourly_profile_plot(stats: pd.DataFrame, plot_path: str, hash_path: str,
                                 country_name: str = "German", intervals_per_hour: int = 4) -> None:
    """Generate the classic seaborn hourly profile plot (per-interval mean over all days with a ±1 sigma band)."""
    data_hash = plot_is_current(hourly_stats_hash_data(stats), plot_path, hash_path)
    if data_hash is None:
        ic("Hourly profile plot is up to date, skipping regeneration")
        return

    x = stats['interval_index'].values
    lower = stats['mean'] - stats['std']
    upper = stats['mean'] + stats['std']
    lower2 = stats['mean'] - 2 * stats['std']
    upper2 = stats['mean'] + 2 * stats['std']

    plt.figure(figsize=(14, 7))
    sns.set_style("whitegrid")
    ax = plt.gca()

    color = sns.color_palette('Set1')[1]
    ax.fill_between(x, lower2, upper2, color=color, alpha=0.25,
                    linewidth=0, label='±2σ range')
    ax.fill_between(x, lower, upper, color=color, alpha=0.5,
                    linewidth=0, label='±1σ range')
    ax.plot(x, stats['mean'], color=color, linewidth=2.5,
            alpha=0.9, label='Mean over all days')

    # Spot prices can go negative, so only pin the bottom at 0 when the band stays above it
    plt.ylim(bottom=min(0, lower2.min() * 1.1), top=upper2.max() * 1.1)
    if lower2.min() < 0:
        ax.axhline(0, color='black', alpha=0.4, linewidth=1)
    plt.xlim(x[0], x[-1])

    set_hourly_ticks(ax, len(stats), intervals_per_hour=intervals_per_hour)

    plt.title(f'{country_name} Electricity Spot Prices — Hourly Profile',
              fontsize=18, fontweight='bold', pad=20)
    plt.xlabel('Hour of Day', fontsize=13, fontweight='bold')
    plt.ylabel('Price (ct/kWh)', fontsize=13, fontweight='bold')

    ax.grid(True, alpha=0.3, linestyle='--', linewidth=0.7)
    ax.set_axisbelow(True)

    plt.legend(loc='upper left', fontsize=11, framealpha=0.95)

    ax.set_facecolor('#f8f9fa')

    plt.tight_layout()
    plt.savefig(plot_path, dpi=PLOT_DPI, bbox_inches='tight', facecolor='white',
                pil_kwargs=PNG_KWARGS)

    with open(hash_path, 'w') as f:
        f.write(data_hash)

    ic("Hourly profile plot regenerated")


def generate_futuristic_plot(dates_data: dict, plot_path: str, hash_path: str,
                             country_name: str = "German", intervals_per_hour: int = 4) -> None:
    """Generate a synthwave/retro-future styled plot."""
    data_hash = plot_is_current(dates_data, plot_path, hash_path)
    if data_hash is None:
        ic("Futuristic plot is up to date, skipping regeneration")
        return

    df = build_dataframe(dates_data)

    bg_dark = '#0d0221'
    bg_purple = '#2b0a4e'
    line_colors = ['#ff2975', '#ff9e00']  # hot pink, sunset orange
    grid_pink = '#ff2975'
    text_light = '#f0e6ff'
    title_cyan = '#9df9ff'

    fig, ax = plt.subplots(figsize=(14, 7))
    fig.patch.set_facecolor(bg_dark)

    num_intervals = len(df.columns)
    y_top = df.max().max() * 1.1

    # Vertical purple-to-black gradient background
    gradient = np.linspace(0, 1, 256).reshape(-1, 1)
    bg_cmap = LinearSegmentedColormap.from_list('synthwave_bg', [bg_purple, bg_dark])
    ax.imshow(gradient, aspect='auto', cmap=bg_cmap,
              extent=[-0.5, num_intervals - 0.5, 0, y_top], zorder=0)

    # Retro grid: horizontal lines more prominent than vertical
    ax.grid(False)
    for y in np.linspace(0, y_top, 12):
        ax.axhline(y, color=grid_pink, alpha=0.18, linewidth=0.9, zorder=1)
    for x in range(0, num_intervals, 4):
        ax.axvline(x, color=grid_pink, alpha=0.08, linewidth=0.7, zorder=1)

    # Neon glow lines: layered strokes with increasing width and low alpha
    for color, (date_str, row) in zip(line_colors, df.iterrows()):
        x = range(num_intervals)
        y = row.values.astype(float)
        for lw, alpha in [(10, 0.06), (7, 0.1), (4.5, 0.18)]:
            ax.plot(x, y, color=color, linewidth=lw, alpha=alpha,
                    solid_capstyle='round', zorder=2)
        ax.plot(x, y, color=color, linewidth=2, alpha=0.95, label=date_str,
                solid_capstyle='round', zorder=3)

    ax.set_xlim(-0.5, num_intervals - 0.5)
    ax.set_ylim(0, y_top)

    set_hourly_ticks(ax, num_intervals, color=text_light, intervals_per_hour=intervals_per_hour)
    ax.tick_params(colors=text_light)
    for spine in ax.spines.values():
        spine.set_color(grid_pink)
        spine.set_alpha(0.4)

    glow = [path_effects.withStroke(linewidth=3, foreground=grid_pink, alpha=0.6)]
    title = ax.set_title(f'{country_name} Electricity Spot Prices', fontsize=20,
                         fontweight='bold', fontstyle='italic', pad=20, color=title_cyan)
    title.set_path_effects(glow)
    ax.set_xlabel('Hour of Day', fontsize=13, fontweight='bold', color=text_light)
    ax.set_ylabel('Price (ct/kWh)', fontsize=13, fontweight='bold', color=text_light)
    plt.setp(ax.get_yticklabels(), color=text_light)

    legend = ax.legend(loc='upper left', fontsize=11, framealpha=0.6,
                       facecolor=bg_dark, edgecolor=grid_pink, labelcolor=text_light)

    plt.tight_layout()
    plt.savefig(plot_path, dpi=PLOT_DPI, bbox_inches='tight', facecolor=bg_dark,
                pil_kwargs=PNG_KWARGS)

    with open(hash_path, 'w') as f:
        f.write(data_hash)

    ic("Futuristic plot regenerated")
    ic(df)


def generate_futuristic_distribution_plot(stats: pd.DataFrame, plot_path: str, hash_path: str,
                                          country_name: str = "German") -> None:
    """Generate a synthwave/retro-future distribution plot (daily mean with a ±1 sigma band)."""
    data_hash = plot_is_current(stats_hash_data(stats), plot_path, hash_path)
    if data_hash is None:
        ic("Futuristic distribution plot is up to date, skipping regeneration")
        return

    bg_dark = '#0d0221'
    bg_purple = '#2b0a4e'
    line_pink = '#ff2975'
    band_orange = '#ff9e00'
    grid_pink = '#ff2975'
    text_light = '#f0e6ff'
    title_cyan = '#9df9ff'

    x = mdates.date2num(stats['date'])
    mean = stats['mean'].values
    lower = mean - stats['std'].values
    upper = mean + stats['std'].values

    y_top = upper.max() * 1.1
    y_bottom = min(0, lower.min() * 1.1)

    fig, ax = plt.subplots(figsize=(14, 7))
    fig.patch.set_facecolor(bg_dark)

    # Vertical purple-to-black gradient background
    gradient = np.linspace(0, 1, 256).reshape(-1, 1)
    bg_cmap = LinearSegmentedColormap.from_list('synthwave_bg', [bg_purple, bg_dark])
    ax.imshow(gradient, aspect='auto', cmap=bg_cmap,
              extent=[x[0], x[-1], y_bottom, y_top], zorder=0)

    # Retro grid: horizontal lines more prominent than vertical (one per month)
    ax.grid(False)
    for y in np.linspace(y_bottom, y_top, 12):
        ax.axhline(y, color=grid_pink, alpha=0.18, linewidth=0.9, zorder=1)
    for xv in mdates.MonthLocator().tick_values(stats['date'].min(), stats['date'].max()):
        ax.axvline(xv, color=grid_pink, alpha=0.08, linewidth=0.7, zorder=1)

    # Sigma band as a glowing sunset-orange area with faint edge lines
    ax.fill_between(x, lower, upper, color=band_orange, alpha=0.35,
                    linewidth=0, label='±1σ range', zorder=2)
    for edge in (lower, upper):
        ax.plot(x, edge, color=band_orange, linewidth=1, alpha=0.5,
                solid_capstyle='round', zorder=2)

    # Neon glow mean line: layered strokes with increasing width and low alpha
    for lw, alpha in [(10, 0.06), (7, 0.1), (4.5, 0.18)]:
        ax.plot(x, mean, color=line_pink, linewidth=lw, alpha=alpha,
                solid_capstyle='round', zorder=3)
    ax.plot(x, mean, color=line_pink, linewidth=2, alpha=0.95, label='Daily mean',
            solid_capstyle='round', zorder=4)

    if lower.min() < 0:
        ax.axhline(0, color=title_cyan, alpha=0.5, linewidth=1, zorder=1)

    ax.set_xlim(x[0], x[-1])
    ax.set_ylim(y_bottom, y_top)

    locator = mdates.AutoDateLocator()
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    ax.tick_params(colors=text_light)
    plt.setp(ax.get_xticklabels(), color=text_light)
    for spine in ax.spines.values():
        spine.set_color(grid_pink)
        spine.set_alpha(0.4)

    glow = [path_effects.withStroke(linewidth=3, foreground=grid_pink, alpha=0.6)]
    title = ax.set_title(f'{country_name} Electricity Spot Prices — Daily Distribution', fontsize=20,
                         fontweight='bold', fontstyle='italic', pad=20, color=title_cyan)
    title.set_path_effects(glow)
    ax.set_xlabel('Date', fontsize=13, fontweight='bold', color=text_light)
    ax.set_ylabel('Price (ct/kWh)', fontsize=13, fontweight='bold', color=text_light)
    plt.setp(ax.get_yticklabels(), color=text_light)

    ax.legend(loc='upper left', fontsize=11, framealpha=0.6,
              facecolor=bg_dark, edgecolor=grid_pink, labelcolor=text_light)

    plt.tight_layout()
    plt.savefig(plot_path, dpi=PLOT_DPI, bbox_inches='tight', facecolor=bg_dark,
                pil_kwargs=PNG_KWARGS)

    with open(hash_path, 'w') as f:
        f.write(data_hash)

    ic("Futuristic distribution plot regenerated")


def generate_futuristic_hourly_profile_plot(stats: pd.DataFrame, plot_path: str, hash_path: str,
                                            country_name: str = "German", intervals_per_hour: int = 4) -> None:
    """Generate a synthwave/retro-future hourly profile plot (per-interval mean over all days with a ±1 sigma band)."""
    data_hash = plot_is_current(hourly_stats_hash_data(stats), plot_path, hash_path)
    if data_hash is None:
        ic("Futuristic hourly profile plot is up to date, skipping regeneration")
        return

    bg_dark = '#0d0221'
    bg_purple = '#2b0a4e'
    line_pink = '#ff2975'
    band_orange = '#ff9e00'
    grid_pink = '#ff2975'
    text_light = '#f0e6ff'
    title_cyan = '#9df9ff'

    x = stats['interval_index'].values
    mean = stats['mean'].values
    lower = mean - stats['std'].values
    upper = mean + stats['std'].values
    lower2 = mean - 2 * stats['std'].values
    upper2 = mean + 2 * stats['std'].values

    num_intervals = len(stats)
    y_top = upper2.max() * 1.1
    y_bottom = min(0, lower2.min() * 1.1)

    fig, ax = plt.subplots(figsize=(14, 7))
    fig.patch.set_facecolor(bg_dark)

    # Vertical purple-to-black gradient background
    gradient = np.linspace(0, 1, 256).reshape(-1, 1)
    bg_cmap = LinearSegmentedColormap.from_list('synthwave_bg', [bg_purple, bg_dark])
    ax.imshow(gradient, aspect='auto', cmap=bg_cmap,
              extent=[-0.5, num_intervals - 0.5, y_bottom, y_top], zorder=0)

    # Retro grid: horizontal lines more prominent than vertical
    ax.grid(False)
    for y in np.linspace(y_bottom, y_top, 12):
        ax.axhline(y, color=grid_pink, alpha=0.18, linewidth=0.9, zorder=1)
    for xv in range(0, num_intervals, 4):
        ax.axvline(xv, color=grid_pink, alpha=0.08, linewidth=0.7, zorder=1)

    # Sigma bands as glowing sunset-orange areas with faint edge lines
    ax.fill_between(x, lower2, upper2, color=band_orange, alpha=0.18,
                    linewidth=0, label='±2σ range', zorder=2)
    for edge in (lower2, upper2):
        ax.plot(x, edge, color=band_orange, linewidth=1, alpha=0.3,
                solid_capstyle='round', zorder=2)
    ax.fill_between(x, lower, upper, color=band_orange, alpha=0.35,
                    linewidth=0, label='±1σ range', zorder=2)
    for edge in (lower, upper):
        ax.plot(x, edge, color=band_orange, linewidth=1, alpha=0.5,
                solid_capstyle='round', zorder=2)

    # Neon glow mean line: layered strokes with increasing width and low alpha
    for lw, alpha in [(10, 0.06), (7, 0.1), (4.5, 0.18)]:
        ax.plot(x, mean, color=line_pink, linewidth=lw, alpha=alpha,
                solid_capstyle='round', zorder=3)
    ax.plot(x, mean, color=line_pink, linewidth=2, alpha=0.95,
            label='Mean over all days', solid_capstyle='round', zorder=4)

    if lower2.min() < 0:
        ax.axhline(0, color=title_cyan, alpha=0.5, linewidth=1, zorder=1)

    ax.set_xlim(-0.5, num_intervals - 0.5)
    ax.set_ylim(y_bottom, y_top)

    set_hourly_ticks(ax, num_intervals, color=text_light, intervals_per_hour=intervals_per_hour)
    ax.tick_params(colors=text_light)
    for spine in ax.spines.values():
        spine.set_color(grid_pink)
        spine.set_alpha(0.4)

    glow = [path_effects.withStroke(linewidth=3, foreground=grid_pink, alpha=0.6)]
    title = ax.set_title(f'{country_name} Electricity Spot Prices — Hourly Profile', fontsize=20,
                         fontweight='bold', fontstyle='italic', pad=20, color=title_cyan)
    title.set_path_effects(glow)
    ax.set_xlabel('Hour of Day', fontsize=13, fontweight='bold', color=text_light)
    ax.set_ylabel('Price (ct/kWh)', fontsize=13, fontweight='bold', color=text_light)
    plt.setp(ax.get_yticklabels(), color=text_light)

    ax.legend(loc='upper left', fontsize=11, framealpha=0.6,
              facecolor=bg_dark, edgecolor=grid_pink, labelcolor=text_light)

    plt.tight_layout()
    plt.savefig(plot_path, dpi=PLOT_DPI, bbox_inches='tight', facecolor=bg_dark,
                pil_kwargs=PNG_KWARGS)

    with open(hash_path, 'w') as f:
        f.write(data_hash)

    ic("Futuristic hourly profile plot regenerated")


NEON_PALETTE = ['#ff2975', '#ff9e00', '#00e5ff', '#b8ff29', '#9b51ff']


def _comparison_dates() -> tuple[str, str]:
    today_str = date.today().strftime("%Y-%m-%d")
    tomorrow_str = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
    return today_str, tomorrow_str


def generate_comparison_plot(countries_data: dict, plot_path: str, hash_path: str) -> None:
    """Generate a classic chart comparing today vs tomorrow for the top countries."""
    data_hash = plot_is_current(countries_data, plot_path, hash_path)
    if data_hash is None:
        ic("Comparison plot is up to date, skipping regeneration")
        return

    series = comparison_series(countries_data, *_comparison_dates())
    if not series:
        ic("No comparison data available, skipping regeneration")
        return

    color_by_country = {c: sns.color_palette('Set1', len(TOP5_COUNTRIES))[i]
                        for i, c in enumerate(TOP5_COUNTRIES)}

    plt.figure(figsize=(14, 7))
    sns.set_style("whitegrid")
    ax = plt.gca()

    for s in series:
        base = color_by_country[s['country']]
        if s['day'] == 'today':
            ax.plot(s['x'], s['y'], color=base, linewidth=2.5, alpha=0.9,
                    label=f"{s['country']} today")
        else:
            ax.plot(s['x'], s['y'], color=lighten_color(base), linewidth=2,
                    linestyle='--', alpha=0.9, label=f"{s['country']} tomorrow")

    set_hourly_ticks(ax, 96, intervals_per_hour=4)

    plt.title('European Electricity Spot Prices — Top 5 by Population',
              fontsize=18, fontweight='bold', pad=20)
    plt.xlabel('Hour of Day', fontsize=13, fontweight='bold')
    plt.ylabel('Price (ct/kWh)', fontsize=13, fontweight='bold')

    ax.grid(True, alpha=0.3, linestyle='--', linewidth=0.7)
    ax.set_axisbelow(True)
    plt.legend(loc='upper left', fontsize=11, framealpha=0.95)
    ax.set_facecolor('#f8f9fa')

    plt.tight_layout()
    plt.savefig(plot_path, dpi=300, bbox_inches='tight', facecolor='white')

    with open(hash_path, 'w') as f:
        f.write(data_hash)

    ic("Comparison plot regenerated")


def generate_futuristic_comparison_plot(countries_data: dict, plot_path: str, hash_path: str) -> None:
    """Generate a synthwave comparison chart (today vs tomorrow) for the top countries."""
    data_hash = plot_is_current(countries_data, plot_path, hash_path)
    if data_hash is None:
        ic("Futuristic comparison plot is up to date, skipping regeneration")
        return

    series = comparison_series(countries_data, *_comparison_dates())
    if not series:
        ic("No comparison data available, skipping regeneration")
        return

    bg_dark = '#0d0221'
    bg_purple = '#2b0a4e'
    grid_pink = '#ff2975'
    text_light = '#f0e6ff'
    title_cyan = '#9df9ff'

    num_intervals = 96
    y_top = max(max(s['y']) for s in series) * 1.1

    fig, ax = plt.subplots(figsize=(14, 7))
    fig.patch.set_facecolor(bg_dark)

    # Vertical purple-to-black gradient background
    gradient = np.linspace(0, 1, 256).reshape(-1, 1)
    bg_cmap = LinearSegmentedColormap.from_list('synthwave_bg', [bg_purple, bg_dark])
    ax.imshow(gradient, aspect='auto', cmap=bg_cmap,
              extent=[-0.5, num_intervals - 0.5, 0, y_top], zorder=0)

    # Retro grid: horizontal lines more prominent than vertical
    ax.grid(False)
    for y in np.linspace(0, y_top, 12):
        ax.axhline(y, color=grid_pink, alpha=0.18, linewidth=0.9, zorder=1)
    for x in range(0, num_intervals, 4):
        ax.axvline(x, color=grid_pink, alpha=0.08, linewidth=0.7, zorder=1)

    color_by_country = {c: NEON_PALETTE[i] for i, c in enumerate(TOP5_COUNTRIES)}

    # Neon glow lines: layered strokes with increasing width and low alpha
    for s in series:
        color = color_by_country[s['country']]
        if s['day'] == 'tomorrow':
            color = lighten_color(color)
        linestyle = '-' if s['day'] == 'today' else '--'
        for lw, alpha in [(10, 0.06), (7, 0.1), (4.5, 0.18)]:
            ax.plot(s['x'], s['y'], color=color, linewidth=lw, alpha=alpha,
                    linestyle=linestyle, solid_capstyle='round', zorder=2)
        ax.plot(s['x'], s['y'], color=color, linewidth=2, alpha=0.95, linestyle=linestyle,
                label=f"{s['country']} {s['day']}", solid_capstyle='round', zorder=3)

    ax.set_xlim(-0.5, num_intervals - 0.5)
    ax.set_ylim(0, y_top)

    set_hourly_ticks(ax, num_intervals, color=text_light, intervals_per_hour=4)
    ax.tick_params(colors=text_light)
    for spine in ax.spines.values():
        spine.set_color(grid_pink)
        spine.set_alpha(0.4)

    glow = [path_effects.withStroke(linewidth=3, foreground=grid_pink, alpha=0.6)]
    title = ax.set_title('European Electricity Spot Prices — Top 5 by Population', fontsize=20,
                         fontweight='bold', fontstyle='italic', pad=20, color=title_cyan)
    title.set_path_effects(glow)
    ax.set_xlabel('Hour of Day', fontsize=13, fontweight='bold', color=text_light)
    ax.set_ylabel('Price (ct/kWh)', fontsize=13, fontweight='bold', color=text_light)
    plt.setp(ax.get_yticklabels(), color=text_light)

    ax.legend(loc='upper left', fontsize=11, framealpha=0.6,
              facecolor=bg_dark, edgecolor=grid_pink, labelcolor=text_light)

    plt.tight_layout()
    plt.savefig(plot_path, dpi=300, bbox_inches='tight', facecolor=bg_dark)

    with open(hash_path, 'w') as f:
        f.write(data_hash)

    ic("Futuristic comparison plot regenerated")


COUNTRY_NAMES = {'DE': 'German', 'FR': 'French', 'NL': 'Dutch', 'BE': 'Belgian',
                 'AT': 'Austrian', 'CH': 'Swiss', 'PL': 'Polish', 'CZ': 'Czech', 'DK': 'Danish'}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Fetch electricity spot prices and plot them.')
    parser.add_argument('-f', '--futuristic', action='store_true',
                        help='Render the plot in a synthwave/retro-future style')
    parser.add_argument('-c', '--country', choices=list(COUNTRY_NAMES), default='DE',
                        help='Bidding zone / country to plot (default: DE)')
    parser.add_argument('--compare', action='store_true',
                        help='Render a top-5 population comparison chart (today vs tomorrow)')
    # parse_args(None) reads sys.argv[1:], preserving CLI behavior; callers
    # that run main() as a library (e.g. the MCP chart tool) pass argv=[]
    # so unrelated process args like --stdio don't trip argparse.
    args = parser.parse_args(argv)

    DB_PATH = "energy_prices.db"
    country = args.country

    if args.compare:
        countries_data = {c: get_price_data(DB_PATH, c) for c in TOP5_COUNTRIES}
        if args.futuristic:
            generate_futuristic_comparison_plot(countries_data, 'comparison_plot_futuristic.png',
                                                '.comparison_hash_futuristic')
        else:
            generate_comparison_plot(countries_data, 'comparison_plot.png', '.comparison_hash')
        return

    # DE keeps unsuffixed filenames so the MCP server's chart paths stay valid
    suffix = '' if country == 'DE' else f'_{country.lower()}'
    intervals_per_hour = 4 if country_granularity(country) == '15MIN' else 1
    country_name = COUNTRY_NAMES[country]

    dates_data = get_price_data(DB_PATH, country)
    daily_stats = load_daily_price_stats(DB_PATH, country)
    hourly_stats = load_hourly_price_stats(DB_PATH, country)

    if args.futuristic:
        generate_futuristic_plot(dates_data, f'dual_timeline_plot_futuristic{suffix}.png',
                                 f'.plot_hash_futuristic{suffix}',
                                 country_name=country_name, intervals_per_hour=intervals_per_hour)
        generate_futuristic_distribution_plot(daily_stats, f'price_distribution_futuristic{suffix}.png',
                                              f'.dist_hash_futuristic{suffix}', country_name=country_name)
        generate_futuristic_hourly_profile_plot(hourly_stats, f'price_hourly_profile_futuristic{suffix}.png',
                                                f'.hourly_hash_futuristic{suffix}',
                                                country_name=country_name, intervals_per_hour=intervals_per_hour)
    else:
        generate_plot(dates_data, f'dual_timeline_plot{suffix}.png', f'.plot_hash{suffix}',
                      country_name=country_name, intervals_per_hour=intervals_per_hour)
        generate_distribution_plot(daily_stats, f'price_distribution{suffix}.png', f'.dist_hash{suffix}',
                                   country_name=country_name)
        generate_hourly_profile_plot(hourly_stats, f'price_hourly_profile{suffix}.png', f'.hourly_hash{suffix}',
                                     country_name=country_name, intervals_per_hour=intervals_per_hour)


def get_current_electricity_price(davis_token):
    current_date = date.today().strftime("%Y-%m-%d")

    url = "https://davis.vattenfall.de/api/digitalinterface/1.3/Produkt/GetSpotPreis"
    payload = json.dumps({
        "Client": "WEB",
        "Mandant": "VESALES",
        "Timeout": None,
        "ParentLogId": "DBB70020199043F1A1FD07BC75801BD0",
        "TransaktionsId": "f7354700-31b1-41f8-a3cb-d41b2acaf1a4",
        "ReferenzId": "lpProducts",
        "StandVom": None,
        "Sprache": "EN",
        "Priority": "High",
        "Request": {
            "Typ": "15MIN_STROM",
            "Von": current_date,
            "Bis": current_date
        }
    })
    headers = {
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9,de;q=0.8,et;q=0.7,sl;q=0.6,it;q=0.5',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'Content-Type': 'application/json',
        'DNT': '1',
        'Ocp-Apim-Subscription-Key': 'b2b769e800fb49a7b685c49d050c825d',
        'Origin': 'https://www.vattenfall.de',
        'Pragma': 'no-cache',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-site',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
        'davis-token': davis_token,
        'sec-ch-ua': '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"',
        'sec-gpc': '1'
    }
    response = requests.request("POST", url, headers=headers, data=payload, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    response_json = response.json()
    if 'Result' not in response_json or 'Tage' not in response_json['Result']:
        raise ValueError(f"Unexpected API response structure: {response_json}")
    return response_json


def get_davis_token() -> str:
    url = "https://davis.vattenfall.de/api/digitalinterface/1.3/Account/GetTokenAnonym"
    payload = json.dumps({
        "Client": "WEB",
        "Mandant": "VESALES",
        "Timeout": None,
        "StandVom": None,
        "ParentLogId": None,
        "TransaktionsId": "5f1920d2-22d2-4c54-ae0f-a71ecbb9f4eb",
        "Sprache": "DE",
        "ReferenzId": "optin",
        "Priority": None,
        "RequestKeyValues": {},
        "Request": {
            "Tenant": None,
            "Werte": {}
        }
    })
    headers = {
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'Content-Type': 'application/json',
        'DNT': '1',
        'Ocp-Apim-Subscription-Key': 'b2b769e800fb49a7b685c49d050c825d',
        'Origin': 'https://www.vattenfall.de',
        'Pragma': 'no-cache',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-site',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
        'sec-ch-ua': '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"'
    }
    response = requests.request("POST", url, headers=headers, data=payload, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    response_json = response.json()
    if 'Result' not in response_json or 'AccessToken' not in response_json['Result']:
        raise ValueError(f"Unexpected token response structure: {response_json}")
    davis_token = response_json['Result']['AccessToken']
    ic(davis_token)
    return davis_token


if __name__ == "__main__":
    main()
