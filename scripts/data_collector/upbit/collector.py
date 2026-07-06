"""Upbit crypto daily-candle collector for qlib (KRW markets, free public API, no key).

    $ python collector.py download_data --source_dir ~/.qlib/upbit_data/source --start 2018-01-01
    $ python collector.py normalize_data --source_dir ~/.qlib/upbit_data/source --normalize_dir ~/.qlib/upbit_data/normalize
    $ cd ../.. && python dump_bin.py dump_all --data_path ~/.qlib/upbit_data/normalize --qlib_dir ~/.qlib/qlib_data/upbit_data --freq day --include_fields open,close,high,low,volume,change,factor

symbols: default <this dir>/symbols_upbit.txt; "KRW" keyword = all KRW markets (~140);
or comma-separated Upbit market codes ("KRW-BTC,KRW-ETH").
"""
import sys
import time
from pathlib import Path

import fire
import requests
import pandas as pd
from loguru import logger

CUR_DIR = Path(__file__).resolve().parent
sys.path.append(str(CUR_DIR.parent.parent))
from data_collector.base import BaseCollector, BaseNormalize, BaseRun

UPBIT_BASE_URL = "https://api.upbit.com/v1"
MAX_CANDLE_COUNT = 200  # API max per request


def upbit_get(path: str, **params):
    for _ in range(5):
        resp = requests.get(f"{UPBIT_BASE_URL}{path}", params=params, timeout=30)
        if resp.status_code == 429:
            time.sleep(0.5)
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()


def get_krw_markets() -> list:
    markets = upbit_get("/market/all", is_details="false")
    return sorted(m["market"] for m in markets if m["market"].startswith("KRW-"))


def candles_to_df(candles: list) -> pd.DataFrame:
    """Map Upbit day-candle records to qlib source columns (UTC daily boundary)."""
    df = pd.DataFrame(candles)
    df = df.rename(
        columns={
            "opening_price": "open",
            "high_price": "high",
            "low_price": "low",
            "trade_price": "close",
            "candle_acc_trade_volume": "volume",
        }
    )
    df["date"] = df["candle_date_time_utc"].str[:10]
    return df[["date", "open", "high", "low", "close", "volume"]]


def parse_symbols(symbols=None) -> list:
    if symbols is None:
        symbols = CUR_DIR.joinpath("symbols_upbit.txt")
    if isinstance(symbols, str) and symbols.upper() in ("KRW", "ALL"):
        return get_krw_markets()
    if isinstance(symbols, str) and Path(symbols).expanduser().exists():
        symbols = Path(symbols).expanduser()
    if isinstance(symbols, Path):
        symbols = [_l.split("#")[0].strip() for _l in symbols.read_text().splitlines()]
    if isinstance(symbols, str):
        symbols = symbols.split(",")
    return [str(s).strip().upper() for s in symbols if str(s).strip()]


class UpbitCollector(BaseCollector):
    DEFAULT_START_DATETIME_1D = pd.Timestamp("2017-10-01")  # Upbit launch

    def __init__(
        self,
        save_dir: [str, Path],
        symbols=None,
        start=None,
        end=None,
        interval="1d",
        max_workers=1,
        max_collector_count=2,
        delay=0.15,  # public rate limit ~10 req/s
        check_data_length: int = None,
        limit_nums: int = None,
    ):
        self._symbols = symbols
        super().__init__(
            save_dir=save_dir,
            start=start,
            end=end,
            interval=interval,
            max_workers=max_workers,
            max_collector_count=max_collector_count,
            delay=delay,
            check_data_length=check_data_length,
            limit_nums=limit_nums,
        )

    def get_instrument_list(self):
        symbols = parse_symbols(self._symbols)
        logger.info(f"get {len(symbols)} symbols.")
        return symbols

    def normalize_symbol(self, symbol: str):
        return symbol

    def get_data(
        self, symbol: str, interval: str, start_datetime: pd.Timestamp, end_datetime: pd.Timestamp
    ) -> pd.DataFrame:
        if interval != self.INTERVAL_1d:
            raise ValueError(f"cannot support {interval}")

        candles = []
        # `to` is an exclusive upper bound (UTC); page backwards from end_datetime
        to = pd.Timestamp(end_datetime).strftime("%Y-%m-%dT%H:%M:%SZ")
        while True:
            page = upbit_get("/candles/days", market=symbol, count=MAX_CANDLE_COUNT, to=to)
            if not page:
                break
            candles.extend(page)
            oldest = page[-1]["candle_date_time_utc"]
            if len(page) < MAX_CANDLE_COUNT or pd.Timestamp(oldest) <= start_datetime:
                break
            to = oldest + "Z"
            self.sleep()

        if not candles:
            return pd.DataFrame()
        df = candles_to_df(candles)
        df = df[(df["date"] >= start_datetime.strftime("%Y-%m-%d")) & (df["date"] <= end_datetime.strftime("%Y-%m-%d"))]
        return df.drop_duplicates("date").sort_values("date").reset_index(drop=True)


class UpbitCollector1d(UpbitCollector):
    pass


class UpbitNormalize(BaseNormalize):
    def _get_calendar_list(self):
        # 24/7 market; calendar is built from the data itself by dump_bin.py
        return None

    def normalize(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        df = df.copy()
        df[self._date_field_name] = pd.to_datetime(df[self._date_field_name])
        df = df.drop_duplicates(self._date_field_name).sort_values(self._date_field_name)
        df["change"] = df["close"] / df["close"].shift(1) - 1
        df["factor"] = 1.0  # no corporate actions in crypto
        return df.reset_index(drop=True)


class UpbitNormalize1d(UpbitNormalize):
    pass


class Run(BaseRun):
    @property
    def collector_class_name(self):
        return f"UpbitCollector{self.interval}"

    @property
    def normalize_class_name(self):
        return f"UpbitNormalize{self.interval}"

    @property
    def default_base_dir(self) -> [Path, str]:
        return CUR_DIR

    def download_data(
        self,
        max_collector_count=2,
        delay=0.15,
        start=None,
        end=None,
        check_data_length: int = None,
        limit_nums=None,
        symbols=None,
    ):
        """download daily candles from Upbit public API (no key required)

        Examples
        ---------
            $ python collector.py download_data --source_dir ~/.qlib/upbit_data/source --start 2018-01-01
            $ python collector.py download_data --source_dir ~/.qlib/upbit_data/source --symbols KRW   # all KRW markets
        """
        super(Run, self).download_data(
            max_collector_count, delay, start, end, check_data_length, limit_nums, symbols=symbols
        )


if __name__ == "__main__":
    fire.Fire(Run)
