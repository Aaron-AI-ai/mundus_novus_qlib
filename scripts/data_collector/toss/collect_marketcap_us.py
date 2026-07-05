"""Merge US market cap / shares outstanding (via yfinance) into normalized toss CSVs.

Run AFTER `collector.py normalize_data` and BEFORE `dump_bin.py`:

    $ python collect_marketcap_us.py merge --normalize_dir ~/.qlib/toss_data_us/normalize --start 2018-01-01
    $ python ../../dump_bin.py dump_all ... --include_fields open,close,high,low,volume,change,factor,mcap,shares

Adds columns: mcap (market cap, USD; unadjusted close x shares outstanding), shares.
ponytail: yfinance shares history only reaches back a few years for many tickers;
earlier rows get NaN. If deeper history matters, switch to a paid fundamentals feed.
"""
import time
from pathlib import Path

import fire
import pandas as pd
from loguru import logger


def merge_us_marketcap_df(
    df: pd.DataFrame, shares: pd.Series, raw_close: pd.Series, date_field: str = "date"
) -> pd.DataFrame:
    """Join shares outstanding (sparse, tz-aware) and unadjusted close onto an OHLCV frame.

    mcap must use the UNADJUSTED close: our qlib close is split-adjusted while the
    shares series is actual point-in-time shares, so adjusted x shares is wrong.
    """
    df = df.copy()
    df = df.drop(columns=["mcap", "shares"], errors="ignore")  # idempotent re-run
    dates = pd.to_datetime(df[date_field])

    shares = shares.copy()
    shares.index = pd.to_datetime(shares.index).tz_localize(None).normalize()
    shares = shares[~shares.index.duplicated(keep="last")].sort_index()
    daily_shares = shares.reindex(pd.date_range(shares.index.min(), dates.max())).ffill()

    raw_close = raw_close.copy()
    raw_close.index = pd.to_datetime(raw_close.index).tz_localize(None).normalize()

    df["shares"] = dates.map(daily_shares)
    df["mcap"] = df["shares"] * dates.map(raw_close)
    return df


def merge(normalize_dir: str, start: str = "2018-01-01", delay: float = 0.5):
    """fetch shares outstanding + unadjusted close per symbol and merge into each csv"""
    import yfinance as yf

    normalize_dir = Path(normalize_dir).expanduser()
    for csv_path in sorted(normalize_dir.glob("*.csv")):
        symbol = csv_path.stem
        try:
            shares = yf.Ticker(symbol).get_shares_full(start=start)
            raw_close = yf.download(symbol, start=start, auto_adjust=False, progress=False)["Close"].squeeze()
        except Exception as e:
            logger.warning(f"{symbol}: yfinance error: {e}")
            continue
        if shares is None or len(shares) == 0 or raw_close.empty:
            logger.warning(f"{symbol}: no shares/close data")
            continue
        df = pd.read_csv(csv_path, dtype={"symbol": str})
        merge_us_marketcap_df(df, shares, raw_close).to_csv(csv_path, index=False)
        logger.info(f"{symbol}: merged (shares history from {shares.index.min().date()})")
        time.sleep(delay)


if __name__ == "__main__":
    fire.Fire({"merge": merge})
