import requests
import json
import seaborn as sns
import pandas as pd
from matplotlib import pyplot as plt
from datetime import date, datetime, timedelta
from icecream import ic
import sqlite3

sns.set_theme()


def init_database(db_path: str) -> None:
    """Initialize the SQLite database with required tables."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create price_days table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS price_days (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE NOT NULL,
            fetched_at TEXT NOT NULL
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


def date_exists_in_db(db_path: str, date_str: str) -> bool:
    """Check if a date already exists in the database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute('SELECT COUNT(*) FROM price_days WHERE date = ?', (date_str,))
    count = cursor.fetchone()[0]

    conn.close()
    return count > 0


def store_price_data(db_path: str, date_str: str, price_values: dict) -> None:
    """Store price data for a specific date in the database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Insert into price_days table
        fetched_at = datetime.now().isoformat()
        cursor.execute(
            'INSERT INTO price_days (date, fetched_at) VALUES (?, ?)',
            (date_str, fetched_at)
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


def load_price_data(db_path: str, date_str: str) -> dict:
    """Load price data for a specific date from the database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Get day_id for the date
        cursor.execute('SELECT id FROM price_days WHERE date = ?', (date_str,))
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


def main():
    DB_PATH = "energy_prices.db"

    # Initialize database
    init_database(DB_PATH)

    # Determine which dates we need (today and tomorrow)
    today = date.today()
    tomorrow = today + timedelta(days=1)
    today_str = today.strftime("%Y-%m-%d")
    tomorrow_str = tomorrow.strftime("%Y-%m-%d")

    # Try to load data from database first
    today_data = load_price_data(DB_PATH, today_str)
    tomorrow_data = load_price_data(DB_PATH, tomorrow_str)

    # Build list of dates we have and need to fetch
    dates_data = {}

    if today_data is not None:
        dates_data[today_str] = today_data
        ic(f"Using cached data for {today_str}")

    if tomorrow_data is not None:
        dates_data[tomorrow_str] = tomorrow_data
        ic(f"Using cached data for {tomorrow_str}")

    # Only fetch from API if we're missing any dates
    if today_data is None or tomorrow_data is None:
        ic("Fetching missing data from API")
        davis_token = get_davis_token()
        response_json = get_current_electricity_price(davis_token)
        ic(response_json)

        # Store and use data from API for missing dates
        for tag in response_json['Result']['Tage']:
            date_str = tag['Datum']
            if date_str not in dates_data:
                # Store in database
                if not date_exists_in_db(DB_PATH, date_str):
                    store_price_data(DB_PATH, date_str, tag['WerteNetto'])
                dates_data[date_str] = tag['WerteNetto']
    else:
        ic("All data available in database, skipping API call")

    # generate plot and save to file
    # Convert dates_data to list format for DataFrame
    dates_list = sorted(dates_data.keys())
    df = pd.DataFrame([dates_data[date_str] for date_str in dates_list],
                      index=dates_list)

    # Create figure with better size
    plt.figure(figsize=(14, 7))

    # Use a cleaner style
    sns.set_style("whitegrid")

    # Create line plot with enhanced styling
    ax = sns.lineplot(data=df.transpose(), linewidth=2.5, marker='o', markersize=4,
                     markeredgewidth=0, alpha=0.9, palette='Set2')

    # Set Y-axis to start at 0 with some padding at top
    plt.ylim(bottom=0, top=df.max().max() * 1.1)

    # Show only hourly labels (every 4th tick for 15-minute data)
    num_intervals = len(df.columns)
    intervals_per_hour = 4  # 15-minute intervals
    hourly_ticks = range(0, num_intervals, intervals_per_hour)
    hourly_labels = [str(i // intervals_per_hour) for i in hourly_ticks]
    ax.set_xticks(hourly_ticks)
    ax.set_xticklabels(hourly_labels, fontsize=10)

    # Add title and labels
    plt.title('German Electricity Spot Prices', fontsize=18, fontweight='bold', pad=20)
    plt.xlabel('Hour of Day', fontsize=13, fontweight='bold')
    plt.ylabel('Price (ct/kWh)', fontsize=13, fontweight='bold')

    # Enhance grid
    ax.grid(True, alpha=0.3, linestyle='--', linewidth=0.7)
    ax.set_axisbelow(True)

    # Improve legend
    legend_labels = [pd.to_datetime(date).strftime('%A, %d %B %Y') for date in df.index]
    plt.legend(labels=legend_labels, loc='upper left', fontsize=11, framealpha=0.95)

    # Add subtle background color
    ax.set_facecolor('#f8f9fa')

    plt.tight_layout()
    plt.savefig('dual_timeline_plot.png', dpi=300, bbox_inches='tight', facecolor='white')

    ic(df)


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
    response = requests.request("POST", url, headers=headers, data=payload)
    response_json = response.json()
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
    davis_token = requests.request("POST", url, headers=headers, data=payload).json()['Result']['AccessToken']
    ic(davis_token)
    return davis_token


if __name__ == "__main__":
    main()
