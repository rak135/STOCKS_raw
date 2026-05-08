from __future__ import annotations

import json
import os
import time
import tomllib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from stock_tax_report.domain.portfolio import MarketPrice, MarketPriceSnapshot


TWELVE_DATA_PROVIDER = "twelvedata"
TWELVE_DATA_BASE_URL = "https://api.twelvedata.com/price"
DEFAULT_TWELVE_DATA_BATCH_SIZE = 8
DEFAULT_TWELVE_DATA_BATCH_SLEEP_SECONDS = 61.0


@dataclass
class MarketDataConfig:
    provider: str = TWELVE_DATA_PROVIDER
    twelve_data_api_key: str = ""
    twelve_data_batch_size: Optional[int] = None
    twelve_data_batch_sleep_seconds: Optional[float] = None


def _parse_decimal(value: object) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _chunked(items: List[str], chunk_size: int) -> Iterable[List[str]]:
    for index in range(0, len(items), chunk_size):
        yield items[index:index + chunk_size]


def _read_env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(1, parsed)


def _read_env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return max(0.0, parsed)


def _build_price_url(symbols: List[str], api_key: str) -> str:
    query = urlencode({"symbol": ",".join(symbols), "apikey": api_key, "dp": "8"}, safe=",")
    return f"{TWELVE_DATA_BASE_URL}?{query}"


def load_market_data_config(config_file: Optional[Path]) -> MarketDataConfig:
    config = MarketDataConfig()
    if config_file is None or not config_file.exists():
        return config

    try:
        data = tomllib.loads(config_file.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"market_data.toml: invalid TOML ({exc})") from exc

    provider = data.get("provider")
    if provider is not None:
        if not isinstance(provider, str):
            raise ValueError("market_data.toml: 'provider' must be a string")
        config.provider = provider.strip().lower()

    api_key = data.get("twelve_data_api_key")
    if api_key is not None:
        if not isinstance(api_key, str):
            raise ValueError("market_data.toml: 'twelve_data_api_key' must be a string")
        config.twelve_data_api_key = api_key.strip()

    batch_size = data.get("twelve_data_batch_size")
    if batch_size is not None:
        if not isinstance(batch_size, int):
            raise ValueError("market_data.toml: 'twelve_data_batch_size' must be an integer")
        config.twelve_data_batch_size = max(1, batch_size)

    batch_sleep = data.get("twelve_data_batch_sleep_seconds")
    if batch_sleep is not None:
        if not isinstance(batch_sleep, (int, float)):
            raise ValueError("market_data.toml: 'twelve_data_batch_sleep_seconds' must be a number")
        config.twelve_data_batch_sleep_seconds = max(0.0, float(batch_sleep))

    return config


def _decode_price_payload(symbols: List[str], payload: object, fetched_at: datetime) -> tuple[List[MarketPrice], List[str]]:
    prices: List[MarketPrice] = []
    errors: List[str] = []

    if not isinstance(payload, dict):
        return [], ["Twelve Data returned an unexpected response shape"]

    if len(symbols) == 1 and "price" in payload:
        price = _parse_decimal(payload.get("price"))
        if price is None:
            return [], [f"{symbols[0]}: Twelve Data returned an invalid price"]
        return [
            MarketPrice(
                ticker=symbols[0],
                price_usd=price,
                provider=TWELVE_DATA_PROVIDER,
                fetched_at=fetched_at,
            )
        ], []

    for symbol in symbols:
        item = payload.get(symbol)
        if not isinstance(item, dict):
            errors.append(f"{symbol}: Twelve Data returned no price data")
            continue
        if item.get("status") == "error":
            message = item.get("message") or "unknown Twelve Data error"
            errors.append(f"{symbol}: {message}")
            continue
        price = _parse_decimal(item.get("price"))
        if price is None:
            errors.append(f"{symbol}: Twelve Data returned an invalid price")
            continue
        prices.append(
            MarketPrice(
                ticker=symbol,
                price_usd=price,
                provider=TWELVE_DATA_PROVIDER,
                fetched_at=fetched_at,
            )
        )

    if payload.get("status") == "error":
        message = payload.get("message") or "unknown Twelve Data error"
        errors.append(f"Twelve Data request failed: {message}")

    return prices, errors


def fetch_twelve_data_prices(
    tickers: Iterable[str],
    *,
    api_key: str,
    fetched_at: datetime,
    timeout_seconds: float = 20.0,
    batch_size: Optional[int] = None,
    sleep_between_batches_seconds: Optional[float] = None,
) -> MarketPriceSnapshot:
    symbols = sorted({ticker.strip().upper() for ticker in tickers if ticker.strip()})
    if not symbols:
        return MarketPriceSnapshot(
            provider=TWELVE_DATA_PROVIDER,
            fetched_at=fetched_at,
            prices=[],
            errors=[],
        )

    resolved_batch_size = batch_size or _read_env_int(
        "TWELVE_DATA_BATCH_SIZE",
        DEFAULT_TWELVE_DATA_BATCH_SIZE,
    )
    resolved_sleep = (
        sleep_between_batches_seconds
        if sleep_between_batches_seconds is not None
        else _read_env_float(
            "TWELVE_DATA_BATCH_SLEEP_SECONDS",
            DEFAULT_TWELVE_DATA_BATCH_SLEEP_SECONDS,
        )
    )

    prices: List[MarketPrice] = []
    errors: List[str] = []
    batches = list(_chunked(symbols, resolved_batch_size))

    for batch_index, batch in enumerate(batches):
        url = _build_price_url(batch, api_key)
        request = Request(url, headers={"User-Agent": "stock-tax-report/1.0"})
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            errors.append(f"Twelve Data HTTP error {exc.code} for symbols {', '.join(batch)}")
            continue
        except URLError as exc:
            errors.append(f"Twelve Data network error for symbols {', '.join(batch)}: {exc.reason}")
            continue
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"Twelve Data response error for symbols {', '.join(batch)}: {exc}")
            continue

        batch_prices, batch_errors = _decode_price_payload(batch, payload, fetched_at)
        prices.extend(batch_prices)
        errors.extend(batch_errors)

        if batch_index < len(batches) - 1 and resolved_sleep > 0:
            time.sleep(resolved_sleep)

    return MarketPriceSnapshot(
        provider=TWELVE_DATA_PROVIDER,
        fetched_at=fetched_at,
        prices=prices,
        errors=errors,
    )


def fetch_market_prices(
    tickers: Iterable[str],
    *,
    fetched_at: datetime,
    config_file: Optional[Path] = None,
) -> Tuple[Optional[MarketPriceSnapshot], List[str]]:
    config = load_market_data_config(config_file)
    if config.provider in {"none", "off", "disabled"}:
        return None, ["Portfolio allocation skipped: market data provider is disabled"]
    if config.provider != TWELVE_DATA_PROVIDER:
        return None, [f"Portfolio allocation skipped: unsupported market data provider={config.provider}"]

    api_key = os.environ.get("TWELVE_DATA_API_KEY", "").strip() or config.twelve_data_api_key
    if not api_key:
        return None, ["Portfolio allocation skipped: TWELVE_DATA_API_KEY is not set"]

    return (
        fetch_twelve_data_prices(
            tickers,
            api_key=api_key,
            fetched_at=fetched_at,
            batch_size=config.twelve_data_batch_size,
            sleep_between_batches_seconds=config.twelve_data_batch_sleep_seconds,
        ),
        [],
    )


def write_market_price_snapshot(output_dir: Path, snapshot: MarketPriceSnapshot) -> Path:
    path = output_dir / "_market_prices_snapshot.json"
    payload = {
        "provider": snapshot.provider,
        "fetched_at": snapshot.fetched_at.isoformat(),
        "prices": [
            {
                "ticker": price.ticker,
                "price_usd": str(price.price_usd),
                "fetched_at": price.fetched_at.isoformat(),
            }
            for price in snapshot.prices
        ],
        "errors": snapshot.errors,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return path
