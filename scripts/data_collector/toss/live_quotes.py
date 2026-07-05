"""Poll current prices from Toss Open API (GET /api/v1/prices, max 200 symbols).

Toss has no public WebSocket yet — REST polling down to ~1s is the supported way.

    $ export TOSS_CLIENT_ID=... TOSS_CLIENT_SECRET=...
    $ python live_quotes.py poll --symbols "005930,000660" --interval_sec 1 --out quotes.csv

Ctrl-C to stop. Rows are appended to --out (if given) with a poll timestamp.
"""
from pathlib import Path

import time

import fire
import pandas as pd
from loguru import logger

from collector import TossSession, parse_symbols  # noqa: E402  (same dir)


def poll(symbols=None, interval_sec: float = 1.0, out: str = None, once: bool = False):
    """poll prices for symbols every interval_sec; append to `out` csv if given"""
    symbols = parse_symbols(symbols)
    if len(symbols) > 200:
        raise ValueError(f"prices API allows max 200 symbols per call, got {len(symbols)}")
    session = TossSession()
    out_path = Path(out).expanduser() if out else None
    query = ",".join(symbols)
    while True:
        resp = session.get("/api/v1/prices", symbols=query)
        result = resp.get("result") or {}
        rows = result if isinstance(result, list) else result.get("prices") or result.get("items") or []
        df = pd.json_normalize(rows)
        df.insert(0, "polled_at", pd.Timestamp.now().isoformat())
        print(df.to_string(index=False))
        if out_path is not None and not df.empty:
            df.to_csv(out_path, mode="a", index=False, header=not out_path.exists())
        if once:
            return
        time.sleep(interval_sec)


if __name__ == "__main__":
    fire.Fire({"poll": poll})
