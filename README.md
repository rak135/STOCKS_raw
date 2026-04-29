# Stocks Tax Export

Repository obsahuje skript pro export daňových PDF reportů po tickerech a souhrnného PDF za všechny tickery.

Hlavní skript:

- `export_ticker_tax_method_pdfs.py`

Hlavní konfigurace:

- `tax_methods.toml`

Vstupní CSV adresář:

- `C:\DATA\PROJECTS\STOCKS_raw\.csv`

Výstupní PDF adresář:

- `C:\DATA\PROJECTS\STOCKS_raw\.pdf exports tax methods`

## Požadavky

- Python 3.12+
- `reportlab`
- `pytest` pro testy

Instalace `reportlab`:

```powershell
py -m pip install reportlab
```

## Co skript dělá

- načte všechny `*.csv` soubory ze vstupního adresáře
- seskupí transakce globálně podle tickeru napříč brokery
- pro každý rok použije metodu z `tax_methods.toml`
- vytvoří jedno PDF pro každý ticker
- vytvoří souhrnné PDF za všechny tickery
- vytvoří `_export_summary.csv`
- vytvoří `_export_warnings.txt`

Podporované matching metody:

- `FIFO`
- `LIFO`
- `max_gains`
- `min_gains`
- `TIME_TEST_MAX`

## Základní spuštění

Použití výchozích cest:

```powershell
py "export_ticker_tax_method_pdfs.py"
```

Zobrazení helpu:

```powershell
py "export_ticker_tax_method_pdfs.py" --help
```

Vlastní cesty:

```powershell
py "export_ticker_tax_method_pdfs.py" --input-dir "C:\DATA\PROJECTS\STOCKS_raw\.csv" --output-dir "C:\DATA\PROJECTS\STOCKS_raw\.pdf exports tax methods" --tax-methods-file "C:\DATA\PROJECTS\STOCKS_raw\tax_methods.toml"
```

## Vygenerování šablony konfigurace

Pokud chceš nejdřív vytvořit šablonu všech tickerů a roků:

```powershell
py "export_ticker_tax_method_pdfs.py" --write-template
```

Skript zapíše šablonu do `tax_methods.toml`.

## Konfigurace `tax_methods.toml`

Soubor obsahuje:

- `current_year`
- `fx_mode`
- `fx_daily_file`
- `[fx_annual_rates]`
- sekce po tickerech

Příklad:

```toml
current_year = 2026
fx_mode = "daily"
fx_daily_file = "C:\\DATA\\PROJECTS\\STOCKS_raw\\.csv\\fx\\cnb_2025.txt"

[fx_annual_rates]
2020 = 23.14
2021 = 21.72
2022 = 23.41
2023 = 22.14
2024 = 23.28
2025 = 21.84

[PLTR]
2021 = "FIFO"
2023 = "FIFO"
2024 = "max_gains"
2025 = "min_gains"
```

## FX režimy

### `fx_mode = "annual"`

- používá roční kurz z `[fx_annual_rates]`
- pro každý použitý historický rok musí být kurz vyplněný
- pokud kurz chybí, skript skončí chybou

### `fx_mode = "daily"`

- používá denní kurz z ČNB
- skript načítá všechny soubory `cnb_*.txt` ze stejné složky jako `fx_daily_file`
- když pro konkrétní den ČNB kurz nepublikovala, použije se poslední předchozí dostupný den
- pokud neexistuje žádný předchozí kurz, skript skončí chybou
- v denním režimu se nepoužívá fallback na roční kurz

Podporované formáty ČNB souborů:

- tabulka s více měnami a sloupcem `1 USD`
- starší formát `Měna: USD | Množství: 1` + `Datum|Kurz`

## Chování `current_year`

- `SELL` transakce v `current_year` se nezahrnují do tax matching výpočtu
- v PDF historii se ale stále zobrazují
- pro `current_year` se nevypisuje FX kurz ani CZK přepočet
- v PDF je rok označen jako `FX=n/a`

## Výstupy

Skript generuje:

- `TICKER.pdf`
- `_all_tickers_year_summary.pdf`
- `_export_summary.csv`
- `_export_warnings.txt`

### Ticker PDF

Každý rok obsahuje:

- rok
- použitou matching metodu
- `FX=daily`, `FX=annual` nebo `FX=n/a`
- roční summary v `USD/CZK`
- detailní historii BUY/SELL transakcí
- sloupec `FX`
- sloupec `Value USD/CZK`

### All Tickers Year Summary

Souhrnné PDF obsahuje po letech:

- `FX`
- `Income USD/CZK`
- `Profit/Loss USD/CZK`
- `3 years rule PASS USD/CZK`
- `3 years rule FAIL USD/CZK`

CZK součty se počítají z jednotlivých transakcí a matchů, ne jedním přepočtem agregované USD sumy.

### `_export_summary.csv`

Obsahuje základní přehled exportu po tickerech včetně sloupce `fx_mode`.

## Zaokrouhlování v PDF

- čísla zobrazovaná v PDF se formátují na 2 desetinná místa
- interní výpočty dál běží v `Decimal`

## Testy

Spuštění celé testovací sady:

```powershell
pytest
```

Testy pokrývají:

- parsování dat a čísel
- matching metody
- `TIME_TEST_MAX`
- agregace summary
- business rules
- end-to-end export
- FX načítání a denní fallback logiku

## Poznámky

- skript očekává USD transakce
- pokud chybí metoda pro ticker/rok, skript skončí validační chybou
- pokud `SELL` překročí dostupné `BUY` loty, skript skončí chybou
