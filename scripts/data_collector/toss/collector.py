import os
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

TOSS_BASE_URL = "https://openapi.tossinvest.com"
MAX_CANDLE_COUNT = 200  # API max per request
MARKET_KEYWORDS = ("KRX", "KOSPI", "KOSDAQ")


def parse_symbols(symbols=None) -> list:
    """Resolve a symbols argument into a list of KRX codes.

    Accepts: None (-> symbols_kr.txt), a market keyword ("KOSPI"/"KOSDAQ"/"KRX",
    resolved to the full listing via FinanceDataReader), a comma-separated
    string, a list, or a path to a text file (one symbol per line, # comments).
    """
    if symbols is None:
        symbols = CUR_DIR.joinpath("symbols_kr.txt")
    if isinstance(symbols, str) and symbols.upper() in MARKET_KEYWORDS:
        import FinanceDataReader as fdr

        listing = fdr.StockListing(symbols.upper())
        code_col = "Code" if "Code" in listing.columns else "Symbol"
        return sorted(c for c in listing[code_col].astype(str) if len(c) == 6)
    if isinstance(symbols, str) and Path(symbols).expanduser().exists():
        symbols = Path(symbols).expanduser()
    if isinstance(symbols, Path):
        symbols = [_l.split("#")[0].strip() for _l in symbols.read_text().splitlines()]
    if isinstance(symbols, str):
        symbols = symbols.split(",")
    return [str(s).strip() for s in symbols if str(s).strip()]


class TossSession:
    """Toss Securities Open API session (OAuth2 client credentials).

    Only one token is valid per client at a time (re-issuing invalidates the
    previous one), so keep a single session and use max_workers=1.
    Credentials come from env vars: TOSS_CLIENT_ID, TOSS_CLIENT_SECRET.
    """

    def __init__(self):
        self._token = None
        self._expires_at = 0
        self._session = requests.Session()

    def _refresh_token(self):
        client_id = os.environ.get("TOSS_CLIENT_ID")
        client_secret = os.environ.get("TOSS_CLIENT_SECRET")
        if not (client_id and client_secret):
            raise ValueError(
                "TOSS_CLIENT_ID / TOSS_CLIENT_SECRET env vars are required "
                "(issue them in Toss Securities WTS > settings > Open API)"
            )
        resp = self._session.post(
            f"{TOSS_BASE_URL}/oauth2/token",
            data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._expires_at = time.time() + int(data.get("expires_in", 3600)) - 60

    def get(self, path: str, **params) -> dict:
        for attempt in range(3):
            if self._token is None or time.time() >= self._expires_at:
                self._refresh_token()
            resp = self._session.get(
                f"{TOSS_BASE_URL}{path}",
                params=params,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=30,
            )
            if resp.status_code == 429:
                time.sleep(float(resp.headers.get("Retry-After", 1)))
                continue
            if resp.status_code == 401:
                self._token = None
                continue
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()
        return resp.json()


def candles_to_df(candles: list) -> pd.DataFrame:
    """Map Toss candle records to qlib source columns."""
    df = pd.DataFrame(candles)
    df = df.rename(
        columns={
            "openPrice": "open",
            "highPrice": "high",
            "lowPrice": "low",
            "closePrice": "close",
        }
    )
    ts = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601").dt.tz_convert("Asia/Seoul")
    df["date"] = ts.dt.strftime("%Y-%m-%d")
    return df[["date", "open", "high", "low", "close", "volume"]]


class TossCollector(BaseCollector):
    def __init__(
        self,
        save_dir: [str, Path],
        symbols=None,
        start=None,
        end=None,
        interval="1d",
        max_workers=1,
        max_collector_count=2,
        delay=0.2,
        check_data_length: int = None,
        limit_nums: int = None,
    ):
        """
        Parameters
        ----------
        symbols:
            KRX symbols to collect: a market keyword ("KOSPI"/"KOSDAQ"/"KRX",
            full listing via FinanceDataReader), a comma-separated string
            ("005930,000660"), a list, or a path to a text file (one symbol
            per line). Default: <this dir>/symbols_kr.txt
        """
        self._symbols = symbols
        self.session = TossSession()
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
        # `before` is an exclusive upper bound; page backwards via nextBefore
        before = pd.Timestamp(end_datetime).tz_localize("Asia/Seoul").isoformat()
        while True:
            resp = self.session.get(
                "/api/v1/candles",
                symbol=symbol,
                interval="1d",
                count=MAX_CANDLE_COUNT,
                before=before,
                adjusted=True,
            )
            result = resp.get("result") or {}
            page = result.get("candles") or []
            candles.extend(page)
            next_before = result.get("nextBefore")
            if not page or not next_before:
                break
            if pd.Timestamp(next_before).tz_convert("Asia/Seoul").tz_localize(None) <= start_datetime:
                break
            before = next_before
            self.sleep()

        if not candles:
            return pd.DataFrame()
        df = candles_to_df(candles)
        df = df[(df["date"] >= start_datetime.strftime("%Y-%m-%d")) & (df["date"] <= end_datetime.strftime("%Y-%m-%d"))]
        return df.drop_duplicates("date").sort_values("date").reset_index(drop=True)


class TossCollector1d(TossCollector):
    pass


class TossNormalize(BaseNormalize):
    def _get_calendar_list(self):
        # calendar is built from the data itself by dump_bin.py
        return None

    def normalize(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        df = df.copy()
        df[self._date_field_name] = pd.to_datetime(df[self._date_field_name])
        df = df.drop_duplicates(self._date_field_name).sort_values(self._date_field_name)
        df["change"] = df["close"] / df["close"].shift(1) - 1
        # ponytail: API already returns adjusted prices (adjusted=true), so factor is constant 1
        df["factor"] = 1.0
        return df.reset_index(drop=True)


class TossNormalize1d(TossNormalize):
    pass


class Run(BaseRun):
    @property
    def collector_class_name(self):
        return f"TossCollector{self.interval}"

    @property
    def normalize_class_name(self):
        return f"TossNormalize{self.interval}"

    @property
    def default_base_dir(self) -> [Path, str]:
        return CUR_DIR

    def download_data(
        self,
        max_collector_count=2,
        delay=0.2,
        start=None,
        end=None,
        check_data_length: int = None,
        limit_nums=None,
        symbols=None,
    ):
        """download KRX daily candles from Toss Securities Open API

        Examples
        ---------
            $ export TOSS_CLIENT_ID=... TOSS_CLIENT_SECRET=...
            $ python collector.py download_data --source_dir ~/.qlib/toss_data/source --start 2018-01-01 --end 2026-07-01 --symbols "005930,000660,069500"
        """
        super(Run, self).download_data(
            max_collector_count, delay, start, end, check_data_length, limit_nums, symbols=symbols
        )


if __name__ == "__main__":
    fire.Fire(Run)
