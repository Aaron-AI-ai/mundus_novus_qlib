"""Collect KR fundamentals from DART (OpenDartReader) into qlib PIT csv format.

Output: one CSV per symbol with columns [date, period, value, field]
  - date:   disclosure date (rcept_no[:8]) -> true point-in-time, no look-ahead
  - period: YYYYQQ (e.g. 202403 = 2024 Q3)
  - field:  revenue / operatingprofit / netincome / assets / liabilities / equity

Pipeline:
    $ export DART_API_KEY=...   # free key: https://opendart.fss.or.kr
    $ python collect_pit.py collect --save_dir ~/.qlib/toss_data/pit --start_year 2018
    $ cd ../.. && python dump_pit.py dump --csv_path ~/.qlib/toss_data/pit --qlib_dir ~/.qlib/qlib_data/kr_data --freq quarterly

Query in qlib: P($$revenue_q), P($$netincome_q), ...
NOTE: quarterly income-statement amounts are cumulative YTD as reported by DART.
"""
import os
import time
from pathlib import Path

import fire
import pandas as pd
from loguru import logger

# DART 요약재무(finstate) account_nm -> qlib PIT field
ACCOUNT_FIELDS = {
    "매출액": "revenue",
    "영업이익": "operatingprofit",
    "당기순이익": "netincome",
    "자산총계": "assets",
    "부채총계": "liabilities",
    "자본총계": "equity",
}
# reprt_code -> quarter
REPORT_CODES = {"11013": 1, "11012": 2, "11014": 3, "11011": 4}


def finstate_to_pit_rows(fs: pd.DataFrame, year: int, quarter: int) -> pd.DataFrame:
    """Convert an OpenDartReader finstate frame to PIT rows [date, period, value, field]."""
    if fs is None or fs.empty:
        return pd.DataFrame()
    # prefer consolidated (CFS) over separate (OFS) statements
    if "fs_div" in fs.columns and (fs["fs_div"] == "CFS").any():
        fs = fs[fs["fs_div"] == "CFS"]
    fs = fs[fs["account_nm"].isin(ACCOUNT_FIELDS)]
    rows = []
    for _, r in fs.iterrows():
        value = pd.to_numeric(str(r.get("thstrm_amount", "")).replace(",", ""), errors="coerce")
        if pd.isna(value):
            continue
        rcept_no = str(r.get("rcept_no", ""))
        if len(rcept_no) < 8:
            continue
        rows.append(
            {
                "date": f"{rcept_no[:4]}-{rcept_no[4:6]}-{rcept_no[6:8]}",
                "period": year * 100 + quarter,
                "value": float(value),
                "field": ACCOUNT_FIELDS[r["account_nm"]],
            }
        )
    return pd.DataFrame(rows).drop_duplicates(["period", "field"])


def collect(
    save_dir: str,
    symbols=None,
    start_year: int = 2018,
    end_year: int = None,
    delay: float = 0.7,
):
    """collect DART fundamentals into PIT csv per symbol

    symbols: same formats as collector.py (default symbols_kr.txt; "KOSPI" for full market)
    delay: DART rate limit is ~100 req/min; 0.7s keeps us under it
    """
    import OpenDartReader

    from collector import parse_symbols  # noqa: E402  (same dir)

    api_key = os.environ.get("DART_API_KEY")
    if not api_key:
        raise ValueError("DART_API_KEY env var is required (free key: https://opendart.fss.or.kr)")
    dart = OpenDartReader(api_key)

    save_dir = Path(save_dir).expanduser()
    save_dir.mkdir(parents=True, exist_ok=True)
    end_year = end_year or pd.Timestamp.now().year
    symbols = parse_symbols(symbols)

    for symbol in symbols:
        dfs = []
        for year in range(start_year, end_year + 1):
            for reprt_code, quarter in REPORT_CODES.items():
                try:
                    fs = dart.finstate(symbol, year, reprt_code=reprt_code)
                except Exception as e:
                    logger.warning(f"{symbol} {year}Q{quarter}: {e}")
                    continue
                finally:
                    time.sleep(delay)
                df = finstate_to_pit_rows(fs, year, quarter)
                if not df.empty:
                    dfs.append(df)
        if not dfs:
            logger.warning(f"{symbol}: no fundamental data")
            continue
        out = pd.concat(dfs).sort_values(["period", "field"]).reset_index(drop=True)
        out.to_csv(save_dir.joinpath(f"{symbol}.csv"), index=False)
        logger.info(f"{symbol}: {len(out)} rows -> {save_dir}/{symbol}.csv")


if __name__ == "__main__":
    fire.Fire({"collect": collect})
