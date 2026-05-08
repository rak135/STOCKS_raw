from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

import pytest

from stock_tax_report.io import market_data


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        if isinstance(self._payload, bytes):
            return self._payload
        if isinstance(self._payload, str):
            return self._payload.encode("utf-8")
        return json.dumps(self._payload).encode("utf-8")


@pytest.mark.unit
def test_fetch_twelve_data_prices_decodes_batch_response(monkeypatch):
    def fake_urlopen(request, timeout):
        return _FakeResponse(
            {
                "AAA": {"price": "12.34"},
                "BBB": {"price": "56.78"},
            }
        )

    monkeypatch.setattr(market_data, "urlopen", fake_urlopen)
    monkeypatch.setattr(market_data.time, "sleep", lambda seconds: None)

    fetched_at = datetime(2026, 5, 8, 12, 0, 0)
    snapshot = market_data.fetch_twelve_data_prices(
        ["AAA", "BBB"],
        api_key="secret",
        fetched_at=fetched_at,
        batch_size=8,
        sleep_between_batches_seconds=0,
    )

    assert snapshot.provider == "twelvedata"
    assert snapshot.errors == []
    assert {price.ticker: price.price_usd for price in snapshot.prices} == {
        "AAA": Decimal("12.34"),
        "BBB": Decimal("56.78"),
    }


@pytest.mark.unit
def test_fetch_twelve_data_prices_records_symbol_errors(monkeypatch):
    def fake_urlopen(request, timeout):
        return _FakeResponse(
            {
                "AAA": {"price": "12.34"},
                "BAD": {"status": "error", "message": "Invalid symbol"},
            }
        )

    monkeypatch.setattr(market_data, "urlopen", fake_urlopen)
    monkeypatch.setattr(market_data.time, "sleep", lambda seconds: None)

    snapshot = market_data.fetch_twelve_data_prices(
        ["AAA", "BAD"],
        api_key="secret",
        fetched_at=datetime(2026, 5, 8, 12, 0, 0),
        batch_size=8,
        sleep_between_batches_seconds=0,
    )

    assert [price.ticker for price in snapshot.prices] == ["AAA"]
    assert snapshot.errors == ["BAD: Invalid symbol"]


@pytest.mark.unit
def test_load_market_data_config_reads_twelve_data_settings(tmp_path):
    config_file = tmp_path / "market_data.toml"
    config_file.write_text(
        'provider = "twelvedata"\n'
        'twelve_data_api_key = "abc123"\n'
        'twelve_data_batch_size = 4\n'
        'twelve_data_batch_sleep_seconds = 0\n',
        encoding="utf-8",
    )

    config = market_data.load_market_data_config(config_file)

    assert config.provider == "twelvedata"
    assert config.twelve_data_api_key == "abc123"
    assert config.twelve_data_batch_size == 4
    assert config.twelve_data_batch_sleep_seconds == 0


@pytest.mark.unit
def test_fetch_market_prices_uses_toml_api_key(tmp_path, monkeypatch):
    config_file = tmp_path / "market_data.toml"
    config_file.write_text(
        'provider = "twelvedata"\n'
        'twelve_data_api_key = "from-file"\n'
        'twelve_data_batch_size = 8\n'
        'twelve_data_batch_sleep_seconds = 0\n',
        encoding="utf-8",
    )

    def fake_fetch(tickers, *, api_key, fetched_at, batch_size, sleep_between_batches_seconds):
        assert list(tickers) == ["AAA"]
        assert api_key == "from-file"
        assert batch_size == 8
        assert sleep_between_batches_seconds == 0
        return "snapshot"

    monkeypatch.setattr(market_data, "fetch_twelve_data_prices", fake_fetch)

    snapshot, warnings = market_data.fetch_market_prices(
        ["AAA"],
        fetched_at=datetime(2026, 5, 8, 12, 0, 0),
        config_file=config_file,
    )

    assert snapshot == "snapshot"
    assert warnings == []
