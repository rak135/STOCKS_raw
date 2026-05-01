from __future__ import annotations

import sys

from stock_tax_report.cli import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
