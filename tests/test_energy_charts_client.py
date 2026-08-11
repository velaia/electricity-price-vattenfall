from datetime import datetime
from zoneinfo import ZoneInfo

from energy_charts_client import (
    BIDDING_ZONES,
    _response_to_prices,
    eur_per_mwh_to_ct_per_kwh,
    fetch_day_ahead_prices,
    interval_key,
)

_ZONE = ZoneInfo("Europe/Brussels")


class TestBiddingZones:
    def test_all_neighbor_countries_present(self):
        # DE is served by the Vattenfall API, not energy-charts
        assert set(BIDDING_ZONES) == {'FR', 'NL', 'BE', 'AT', 'CH', 'PL', 'CZ', 'DK'}

    def test_dk_maps_to_dk1(self):
        assert BIDDING_ZONES['DK'] == 'DK1'


class TestUnitConversion:
    def test_positive(self):
        assert eur_per_mwh_to_ct_per_kwh(100) == 10.0

    def test_zero(self):
        assert eur_per_mwh_to_ct_per_kwh(0) == 0.0

    def test_negative(self):
        assert eur_per_mwh_to_ct_per_kwh(-50) == -5.0


class TestIntervalKey:
    def test_midnight(self):
        assert interval_key(0, 0) == '0'

    def test_quarter_past_one(self):
        assert interval_key(13, 45) == '1345'

    def test_eleven_pm(self):
        assert interval_key(23, 0) == '2300'


class TestResponseToPrices:
    def _payload(self, points):
        unix_seconds = [datetime(*dt, tzinfo=_ZONE).timestamp() for dt, _ in points]
        prices = [price for _, price in points]
        return {'unix_seconds': unix_seconds, 'price': prices, 'unit': 'EUR / MWh'}

    def test_buckets_by_local_date_and_converts_units(self):
        payload = self._payload([
            ((2026, 8, 10, 0, 0), 100.0),
            ((2026, 8, 10, 0, 15), 50.0),
            ((2026, 8, 11, 13, 45), -20.0),
        ])
        assert _response_to_prices(payload) == {
            '2026-08-10': {'0': 10.0, '15': 5.0},
            '2026-08-11': {'1345': -2.0},
        }

    def test_dst_fallback_duplicate_hour_last_wins(self):
        # 2026-10-25 02:00 occurs twice (CEST then CET); the last value wins
        first = datetime(2026, 10, 25, 2, 0, tzinfo=_ZONE, fold=0).timestamp()
        second = datetime(2026, 10, 25, 2, 0, tzinfo=_ZONE, fold=1).timestamp()
        payload = {'unix_seconds': [first, second], 'price': [100.0, 200.0]}
        assert _response_to_prices(payload) == {'2026-10-25': {'200': 20.0}}


class FakeResponse:
    def __init__(self, status_code, json_data=None):
        self.status_code = status_code
        self._json = json_data

    def json(self):
        return self._json


class TestFetchDayAheadPrices:
    def _payload(self):
        ts = datetime(2026, 8, 10, 0, 0, tzinfo=_ZONE).timestamp()
        return {'unix_seconds': [ts], 'price': [100.0], 'unit': 'EUR / MWh'}

    def test_success_returns_bucketed_dict(self, monkeypatch):
        monkeypatch.setattr('energy_charts_client.requests.get',
                            lambda *a, **k: FakeResponse(200, self._payload()))
        assert fetch_day_ahead_prices('FR', '2026-08-10', '2026-08-10') == {'2026-08-10': {'0': 10.0}}

    def test_http_400_returns_empty(self, monkeypatch):
        monkeypatch.setattr('energy_charts_client.requests.get',
                            lambda *a, **k: FakeResponse(400))
        assert fetch_day_ahead_prices('FR', '2026-08-10', '2026-08-10') == {}

    def test_429_then_success_retries(self, monkeypatch):
        monkeypatch.setattr('energy_charts_client.time.sleep', lambda s: None)
        calls = []

        def fake_get(*a, **k):
            calls.append(1)
            if len(calls) == 1:
                return FakeResponse(429)
            return FakeResponse(200, self._payload())

        monkeypatch.setattr('energy_charts_client.requests.get', fake_get)
        assert fetch_day_ahead_prices('FR', '2026-08-10', '2026-08-10') == {'2026-08-10': {'0': 10.0}}
        assert len(calls) == 2

    def test_persistent_429_returns_empty(self, monkeypatch):
        monkeypatch.setattr('energy_charts_client.time.sleep', lambda s: None)
        monkeypatch.setattr('energy_charts_client.requests.get',
                            lambda *a, **k: FakeResponse(429))
        assert fetch_day_ahead_prices('FR', '2026-08-10', '2026-08-10') == {}
