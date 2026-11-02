"""Task 9 data-fetch entry point; the broader CLI belongs to the report task."""

import argparse
from pathlib import Path
import sys

import pandas as pd

from autopsy.data.schedule import combine_prices
from autopsy.data.store import save_snapshot
from autopsy.data.upstox import DEFAULT_TOKEN_PATH, TokenMissing, UpstoxClient, UpstoxError


def main(argv=None):
    parser = argparse.ArgumentParser(prog="autopsy")
    commands = parser.add_subparsers(dest="command", required=True)
    data = commands.add_parser("data").add_subparsers(dest="data_command", required=True)
    fetch = data.add_parser("fetch-upstox")
    fetch.add_argument("--symbols", required=True, help="text file: one instrument key per line")
    fetch.add_argument("--from", dest="start", required=True)
    fetch.add_argument("--to", dest="end", default=(pd.Timestamp.now(tz="Asia/Kolkata") - pd.Timedelta(days=1)).date().isoformat())
    fetch.add_argument("--unit", default="minutes")
    fetch.add_argument("--interval", type=int, default=5)
    fetch.add_argument("--token-path", default=DEFAULT_TOKEN_PATH)
    args = parser.parse_args(argv)
    try:
        client = UpstoxClient(token_path=args.token_path)
        symbols = [line.strip() for line in Path(args.symbols).read_text().splitlines() if line.strip()]
        prices = combine_prices([client.candles(symbol, args.unit, args.interval, args.start, args.end)
                                 for symbol in symbols])
        if prices.empty:
            raise ValueError("no historical candles returned")
        path = save_snapshot(prices, "raw", "Upstox V3 historical candles")
    except (TokenMissing, UpstoxError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (OSError, ValueError):
        print("Data setup error: check symbols file, dates, interval and snapshot directory.", file=sys.stderr)
        return 2
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
