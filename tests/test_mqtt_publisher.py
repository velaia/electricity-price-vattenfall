from datetime import datetime
import pytest

from mqtt_publisher import current_interval_index, compute_metrics, load_config, MqttConfig


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


from mqtt_publisher import seconds_until_next_boundary


class TestSecondsUntilNextBoundary:
    def test_just_after_boundary(self):
        now = datetime(2026, 5, 6, 12, 0, 0)
        assert seconds_until_next_boundary(now) == 900

    def test_one_second_before_boundary(self):
        now = datetime(2026, 5, 6, 12, 14, 59)
        assert seconds_until_next_boundary(now) == 1

    def test_mid_interval(self):
        now = datetime(2026, 5, 6, 12, 7, 30)
        assert seconds_until_next_boundary(now) == 450

    def test_crosses_hour(self):
        now = datetime(2026, 5, 6, 12, 50, 0)
        assert seconds_until_next_boundary(now) == 600

    def test_crosses_midnight(self):
        now = datetime(2026, 5, 6, 23, 50, 0)
        assert seconds_until_next_boundary(now) == 600


class TestLoadConfig:
    def test_minimal_config(self, monkeypatch):
        monkeypatch.setenv("MQTT_HOST", "broker.local")
        monkeypatch.delenv("MQTT_PORT", raising=False)
        monkeypatch.delenv("MQTT_USER", raising=False)
        monkeypatch.delenv("MQTT_PASS", raising=False)
        cfg = load_config()
        assert cfg == MqttConfig(host="broker.local", port=1883, username=None, password=None)

    def test_full_config(self, monkeypatch):
        monkeypatch.setenv("MQTT_HOST", "broker.local")
        monkeypatch.setenv("MQTT_PORT", "8883")
        monkeypatch.setenv("MQTT_USER", "ha")
        monkeypatch.setenv("MQTT_PASS", "secret")
        cfg = load_config()
        assert cfg == MqttConfig(host="broker.local", port=8883, username="ha", password="secret")

    def test_missing_host_raises(self, monkeypatch):
        monkeypatch.delenv("MQTT_HOST", raising=False)
        with pytest.raises(RuntimeError, match="MQTT_HOST"):
            load_config()
