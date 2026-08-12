import sqlite3

from main import (
    TOP5_COUNTRIES,
    comparison_series,
    country_granularity,
    init_database,
    interval_to_position,
    lighten_color,
    load_price_data,
    store_price_data,
)


class TestIntervalToPosition:
    def test_15min(self):
        assert interval_to_position(0, '15MIN') == 0
        assert interval_to_position(15, '15MIN') == 1
        assert interval_to_position(100, '15MIN') == 4
        assert interval_to_position(2345, '15MIN') == 95

    def test_hourly(self):
        assert interval_to_position(0, 'HOURLY') == 0
        assert interval_to_position(100, 'HOURLY') == 1
        assert interval_to_position(2300, 'HOURLY') == 23


class TestCountryGranularity:
    def test_all_countries_are_15min(self):
        for country in ('DE', 'FR', 'NL', 'BE', 'AT', 'CH', 'PL', 'CZ', 'DK'):
            assert country_granularity(country) == '15MIN'


class TestInitDatabaseMigration:
    def _create_legacy_schema(self, db_path):
        conn = sqlite3.connect(db_path)
        conn.execute('''
            CREATE TABLE price_days (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                fetched_at TEXT NOT NULL
            )
        ''')
        conn.execute('''
            CREATE TABLE price_intervals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day_id INTEGER NOT NULL,
                interval_index INTEGER NOT NULL,
                price_netto REAL NOT NULL,
                FOREIGN KEY (day_id) REFERENCES price_days (id),
                UNIQUE (day_id, interval_index)
            )
        ''')
        conn.execute("INSERT INTO price_days (date, fetched_at) VALUES ('2026-08-10', '2026-08-10T12:00:00')")
        day_id = conn.execute("SELECT id FROM price_days WHERE date = '2026-08-10'").fetchone()[0]
        conn.execute('INSERT INTO price_intervals (day_id, interval_index, price_netto) VALUES (?, 0, 5.5)', (day_id,))
        conn.execute('INSERT INTO price_intervals (day_id, interval_index, price_netto) VALUES (?, 15, 6.5)', (day_id,))
        conn.commit()
        conn.close()

    def test_migrates_legacy_schema_preserving_data(self, tmp_path):
        db_path = str(tmp_path / 'energy.db')
        self._create_legacy_schema(db_path)

        init_database(db_path)

        conn = sqlite3.connect(db_path)
        cols = {row[1] for row in conn.execute('PRAGMA table_info(price_days)')}
        assert 'country' in cols
        assert 'granularity' in cols
        row = conn.execute(
            "SELECT date, country, granularity FROM price_days WHERE date = '2026-08-10'").fetchone()
        assert row == ('2026-08-10', 'DE', '15MIN')
        intervals = conn.execute(
            'SELECT interval_index, price_netto FROM price_intervals ORDER BY interval_index').fetchall()
        assert intervals == [(0, 5.5), (15, 6.5)]
        conn.close()

    def test_migration_is_idempotent(self, tmp_path):
        db_path = str(tmp_path / 'energy.db')
        self._create_legacy_schema(db_path)
        init_database(db_path)
        init_database(db_path)  # second call must be a no-op

        conn = sqlite3.connect(db_path)
        assert conn.execute('SELECT COUNT(*) FROM price_days').fetchone()[0] == 1
        assert conn.execute('SELECT COUNT(*) FROM price_intervals').fetchone()[0] == 2
        conn.close()

    def test_fresh_db_gets_new_schema(self, tmp_path):
        db_path = str(tmp_path / 'energy.db')
        init_database(db_path)

        conn = sqlite3.connect(db_path)
        cols = {row[1] for row in conn.execute('PRAGMA table_info(price_days)')}
        assert 'country' in cols
        assert 'granularity' in cols
        conn.close()

    def test_store_and_load_roundtrip_with_country(self, tmp_path):
        db_path = str(tmp_path / 'energy.db')
        init_database(db_path)
        store_price_data(db_path, '2026-08-10', {'0': 5.5, '15': 6.5}, country='FR')
        assert load_price_data(db_path, '2026-08-10', 'FR') == {'0': 5.5, '15': 6.5}
        assert load_price_data(db_path, '2026-08-10', 'DE') is None


class TestTop5Countries:
    def test_ordered_by_population(self):
        assert TOP5_COUNTRIES == ['DE', 'FR', 'PL', 'NL', 'BE']


class TestLightenColor:
    def test_amount_zero_keeps_original(self):
        assert lighten_color('black', amount=0) == (0, 0, 0)

    def test_amount_one_is_white(self):
        assert lighten_color('black', amount=1) == (1, 1, 1)

    def test_halfway_toward_white(self):
        assert lighten_color('black', amount=0.5) == (0.5, 0.5, 0.5)

    def test_white_stays_white(self):
        assert lighten_color('white', amount=0.5) == (1, 1, 1)


class TestComparisonSeries:
    def _full_day(self, offset=0.0):
        return {str(hour * 100 + quarter * 15): hour + quarter * 0.25 + offset
                for hour in range(24) for quarter in range(4)}

    def test_builds_today_and_tomorrow_and_skips_missing(self):
        today, tomorrow = '2026-08-10', '2026-08-11'
        countries_data = {
            'DE': {today: self._full_day(), tomorrow: self._full_day(offset=1.0)},
            'FR': {today: self._full_day(offset=2.0)},  # no tomorrow published
        }
        series = comparison_series(countries_data, today, tomorrow)

        assert [s['country'] for s in series] == ['DE', 'DE', 'FR']
        assert [s['day'] for s in series] == ['today', 'tomorrow', 'today']
        assert all(s['x'] == list(range(96)) for s in series)
        assert series[0]['y'] == list(self._full_day().values())
        assert series[1]['y'] == list(self._full_day(offset=1.0).values())
        assert series[2]['y'] == list(self._full_day(offset=2.0).values())

    def test_empty_day_is_skipped(self):
        countries_data = {'DE': {}}  # no data at all
        assert comparison_series(countries_data, '2026-08-10', '2026-08-11') == []

    def test_sorted_by_country(self):
        today = '2026-08-10'
        countries_data = {'NL': {today: self._full_day()}, 'BE': {today: self._full_day()}}
        series = comparison_series(countries_data, today, '2026-08-11')
        assert [s['country'] for s in series] == ['BE', 'NL']
