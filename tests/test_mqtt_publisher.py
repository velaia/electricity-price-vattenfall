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


class TestComputeMetrics:
    def _prices(self, values: list[float]) -> dict[str, float]:
        return {str(i): v for i, v in enumerate(values)}

    def test_basic_metrics(self):
        prices = self._prices([float(i) for i in range(96)])
        metrics = compute_metrics(prices, datetime(2026, 5, 6, 0, 0))
        assert metrics["current_price"] == 0.0
        assert metrics["next_hour_price"] == pytest.approx((1 + 2 + 3 + 4) / 4)
        assert metrics["today_min"] == 0.0
        assert metrics["today_max"] == 95.0
        assert metrics["today_avg"] == pytest.approx(sum(range(96)) / 96)

    def test_next_hour_at_end_of_day_clips(self):
        prices = self._prices([float(i) for i in range(96)])
        metrics = compute_metrics(prices, datetime(2026, 5, 6, 23, 45))
        assert metrics["current_price"] == 95.0
        assert metrics["next_hour_price"] == 95.0

    def test_partial_next_hour(self):
        prices = self._prices([float(i) for i in range(96)])
        metrics = compute_metrics(prices, datetime(2026, 5, 6, 23, 30))
        assert metrics["current_price"] == 94.0
        assert metrics["next_hour_price"] == 95.0

    def test_rounded_to_two_decimals(self):
        prices = self._prices([1.234567] * 96)
        metrics = compute_metrics(prices, datetime(2026, 5, 6, 12, 0))
        for value in metrics.values():
            assert value == 1.23
