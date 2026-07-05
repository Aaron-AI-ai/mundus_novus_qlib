"""Merge KRX market cap / listed shares (via pykrx) into normalized toss CSVs.

Requires a free KRX data portal account: set KRX_ID / KRX_PW env vars
(https://data.krx.co.kr — recent pykrx versions need this login).

Run AFTER `collector.py normalize_data` and BEFORE `dump_bin.py`:

    $ python collect_marketcap.py merge --normalize_dir ~/.qlib/toss_data/normalize --start 2018-01-01 --end 2026-07-01
    $ python dump_bin.py dump_all ... --include_fields open,close,high,low,volume,change,factor,mcap,shares

Adds columns: mcap (시가총액, KRW), shares (상장주식수).
Usable in qlib expressions, e.g. "$close*0+$mcap" or turnover "$volume/$shares".
"""
import os
import time
from pathlib import Path

import fire
import pandas as pd
from loguru import logger
from pykrx import stock

MCAP_COLUMNS = {"시가총액": "mcap", "상장주식수": "shares"}


def merge_marketcap_df(df: pd.DataFrame, cap: pd.DataFrame, date_field: str = "date") -> pd.DataFrame:
    """Left-join pykrx market-cap columns onto a normalized OHLCV frame."""
    cap = cap.rename(columns=MCAP_COLUMNS)[list(MCAP_COLUMNS.values())]
    cap.index = pd.to_datetime(cap.index)
    df = df.copy()
    df[date_field] = pd.to_datetime(df[date_field])
    return df.merge(cap, how="left", left_on=date_field, right_index=True)


def merge(normalize_dir: str, start: str = "2018-01-01", end: str = None, delay: float = 0.3):
    """fetch market cap per symbol and merge into each <symbol>.csv in normalize_dir"""
    if not (os.environ.get("KRX_ID") and os.environ.get("KRX_PW")):
        raise ValueError(
            "recent pykrx requires a KRX data portal login: sign up (free) at "
            "https://data.krx.co.kr and set KRX_ID / KRX_PW env vars"
        )
    normalize_dir = Path(normalize_dir).expanduser()
    end = end or pd.Timestamp.now().strftime("%Y-%m-%d")
    fromdate, todate = start.replace("-", ""), end.replace("-", "")
    for csv_path in sorted(normalize_dir.glob("*.csv")):
        symbol = csv_path.stem
        try:
            cap = stock.get_market_cap(fromdate, todate, symbol)
        except Exception as e:
            logger.warning(f"{symbol}: pykrx error: {e}")
            continue
        if cap is None or cap.empty:
            logger.warning(f"{symbol}: no market cap data")
            continue
        df = pd.read_csv(csv_path, dtype={"symbol": str})
        df = df.drop(columns=list(MCAP_COLUMNS.values()), errors="ignore")  # idempotent re-run
        merge_marketcap_df(df, cap).to_csv(csv_path, index=False)
        logger.info(f"{symbol}: merged {len(cap)} rows")
        time.sleep(delay)  # ponytail: be nice to KRX; parallelize if it ever matters


if __name__ == "__main__":
    fire.Fire({"merge": merge})
