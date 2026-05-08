# Stocks Tax Report

Repository obsahuje Python balíček pro export daňových reportů z normalizovaných broker CSV:

- PDF report pro každý ticker
- souhrnné PDF za všechny tickery po letech
- CSV summary exportu
- TXT výstrahy a poznámky z parsování
- volitelný evidence bundle `tax_<year>/`

Hlavní entrypoint:

- `python -m stock_tax_report`

Hlavní konfigurace:

- `tax_methods.toml`
- volitelně `report_paths.toml`

Výchozí vstupní CSV adresář:

- `C:\DATA\PROJECTS\STOCKS_raw\.csv`

Výchozí výstupní PDF/CSV/TXT adresář:

- `C:\DATA\PROJECTS\STOCKS_raw\.pdf exports tax methods`

Výchozí bundle adresář:

- `C:\DATA\PROJECTS\STOCKS_raw\.tax_bundles`

## Požadavky

- Python 3.12+
- `reportlab`
- `pytest` pro testy

Instalace `reportlab`:

```powershell
py -m pip install reportlab
```

## Co pipeline dělá

- načte všechny `*.csv` soubory ze vstupního adresáře
- z CSV vytáhne validní `BUY`/`SELL` transakce
- seskupí transakce globálně podle tickeru napříč brokery
- načte matching metody a FX nastavení z `tax_methods.toml`
- pro každý historický rok použije matching metodu nastavenou pro daný ticker/rok
- vytvoří jedno PDF pro každý ticker
- vytvoří souhrnné PDF za všechny tickery
- vytvoří `_export_summary.csv`
- vytvoří `_export_warnings.txt`
- pokud není vypnutý bundle, sestaví evidence bundle `tax_<current_year>/`

Podporované matching metody:

- `FIFO`
- `LIFO`
- `max_gains`
- `min_gains`
- `time_test_max`

Názvy metod jsou case-insensitive, v konfiguraci se ale používá hlavně lowercase zápis.

## Základní spuštění

Použití výchozích cest:

```powershell
py -m stock_tax_report
```

Zobrazení helpu:

```powershell
py -m stock_tax_report --help
```

Vlastní cesty:

```powershell
py -m stock_tax_report --input-dir "C:\DATA\PROJECTS\STOCKS_raw\.csv" --output-dir "C:\DATA\PROJECTS\STOCKS_raw\.pdf exports tax methods" --tax-methods-file "C:\DATA\PROJECTS\STOCKS_raw\tax_methods.toml"
```

Spuštění bez evidence bundlu:

```powershell
py -m stock_tax_report --no-bundle
```

Vlastní bundle root:

```powershell
py -m stock_tax_report --bundle-root "C:\DATA\PROJECTS\STOCKS_raw\.tax_bundles"
```

## Konfigurace cest

Pipeline používá výchozí cesty z kódu, ale pokud v rootu repa existuje `report_paths.toml`, automaticky ho načte.

Podporované sekce:

```toml
[sources]
normalized_csv_dir = "C:\\DATA\\PROJECTS\\STOCKS_raw\\.csv"
tax_methods_file = "C:\\DATA\\PROJECTS\\STOCKS_raw\\tax_methods.toml"
notes_dir = "C:\\DATA\\PROJECTS\\STOCKS_raw\\.notes"
original_broker_exports_dir = "C:\\DATA\\PROJECTS\\STOCKS_raw\\.original_broker_exports"

[outputs]
output_dir = "C:\\DATA\\PROJECTS\\STOCKS_raw\\.pdf exports tax methods"

[bundle]
output_root = "C:\\DATA\\PROJECTS\\STOCKS_raw\\.tax_bundles"
```

Explicitní CLI parametry mají přednost před `report_paths.toml`.

## Vygenerování šablony konfigurace

Pokud chceš nejdřív vytvořit šablonu všech tickerů a roků:

```powershell
py -m stock_tax_report --write-template
```

Pipeline zapíše šablonu do `tax_methods.toml` podle aktuálních CSV vstupů.

## Konfigurace `tax_methods.toml`

Soubor obsahuje:

- `current_year`
- `fx_daily_file`
- `[fx_mode_by_year]`
- `[fx_annual_rates]`
- sekce po tickerech

Aktuální model FX je po jednotlivých letech. Starý top-level klíč `fx_mode` už není podporovaný a loader s ním skončí chybou.

Příklad:

```toml
current_year = 2026
fx_daily_file = "C:\\DATA\\PROJECTS\\STOCKS_raw\\.csv\\fx\\cnb_2025.txt"

[fx_mode_by_year]
2020 = "daily"
2021 = "daily"
2022 = "daily"
2023 = "daily"
2024 = "daily"
2025 = "daily"

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
2025 = "time_test_max"
```

## FX režimy

### `fx_mode_by_year.<rok> = "annual"`

- používá roční kurz z `[fx_annual_rates]`
- pro každý použitý historický rok musí být kurz vyplněný
- pokud kurz chybí, pipeline skončí validační chybou

### `fx_mode_by_year.<rok> = "daily"`

- používá denní kurz z ČNB
- pipeline načítá všechny soubory `cnb_*.txt` ze stejné složky jako `fx_daily_file`
- když pro konkrétní den ČNB kurz nepublikovala, použije se poslední předchozí dostupný den
- pokud neexistuje žádný předchozí kurz, pipeline skončí chybou
- v denním režimu se nepoužívá fallback na roční kurz

Podporované formáty ČNB souborů:

- tabulka s více měnami a sloupcem `1 USD`
- starší formát `Měna: USD | Množství: 1` + `Datum|Kurz`

## Chování `current_year`

- `SELL` transakce v `current_year` se nezahrnují do tax matching výpočtu
- v PDF historii se ale stále zobrazují
- pro `current_year` se nevypisuje FX kurz ani CZK přepočet
- v PDF je rok označený jako `FX=n/a`
- ve summary CSV může mít aktuální rok FX mód `?`

## Výstupy

Pipeline generuje do výstupního adresáře:

- `TICKER.pdf`
- `_all_tickers_year_summary.pdf`
- `_export_summary.csv`
- `_export_warnings.txt`

Před exportem se předchozí exportní artefakty ve výstupním adresáři vyčistí.

### Ticker PDF

Každý rok obsahuje:

- rok
- použitou matching metodu
- `FX=daily`, `FX=annual` nebo `FX=n/a`
- roční summary v `USD/CZK`
- detailní historii `BUY`/`SELL` transakcí
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

Obsahuje přehled exportu po tickerech. Důležité sloupce:

- `ticker`
- `pdf_file`
- `fx_modes`
- `year_count`
- `sell_count`
- `ignored_current_year_sell_count`
- `open_qty`
- USD/CZK income, costs a profit součty
- rozdělení podle tříletého časového testu
- `source_files`

### `_export_warnings.txt`

Obsahuje warnings z CSV parsování, mapping poznámky a exportní poznámky z analýzy tickerů.

## Evidence Bundle

Pokud není použit `--no-bundle`, pipeline sestaví bundle do:

```text
.tax_bundles\tax_<current_year>
```

Bundle obsahuje výstupy, normalizovaná CSV, `tax_methods.toml`, dostupné FX soubory `cnb_*.txt`, volitelné poznámky a volitelné originální broker exporty. Součástí bundlu je také methodology README a manifest.

Volitelné vstupy pro bundle:

- `--notes-dir`
- `--broker-exports-dir`
- odpovídající hodnoty v `report_paths.toml`

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
- `time_test_max`
- agregace summary
- business rules
- end-to-end export
- FX načítání a denní fallback logiku
- skládání evidence bundlu

## Poznámky

- pipeline očekává USD transakce
- pokud chybí FX mód pro použitý historický rok, pipeline skončí validační chybou
- pokud je rok v módu `annual` a chybí roční kurz, pipeline skončí validační chybou
- pokud chybí metoda pro ticker/rok, pipeline skončí validační chybou
- pokud `SELL` překročí dostupné `BUY` loty, pipeline skončí chybou
