"""Collect US fundamentals from SEC EDGAR (XBRL companyfacts API) into qlib PIT csv.

Output matches collect_pit.py: [date, period, value, field] per symbol
  - date:   filing date -> true point-in-time, no look-ahead
  - period: YYYYQQ from the SEC calendar frame (annual facts land on Q4)
  - field:  revenue / operatingprofit / netincome / assets / liabilities / equity

SEC is free but requires a User-Agent identifying you (name + email):

    $ export SEC_EDGAR_USER_AGENT="Your Name your@email.com"
    $ python collect_pit_us.py collect --save_dir ~/.qlib/toss_data_us/pit --symbols symbols_us.txt
    $ cd ../.. && python dump_pit.py dump --csv_path ~/.qlib/toss_data_us/pit --qlib_dir ~/.qlib/qlib_data/us_data --freq quarterly

Query in qlib: P($$revenue_q), P($$netincome_q), ...
ponytail: only facts carrying an SEC calendar `frame` are used (canonical, deduped
by SEC); the rare unframed facts are skipped. Annual income facts are full-year
totals stored at Q4 — same YTD caveat as the DART collector.
"""
import os
import re
import time
from pathlib import Path

import fire
import pandas as pd
import requests
from loguru import logger

# us-gaap concept aliases (first present wins) -> qlib PIT field
CONCEPT_FIELDS = [
    (
        ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"),
        "revenue",
    ),
    (("OperatingIncomeLoss",), "operatingprofit"),
    (("NetIncomeLoss",), "netincome"),
    (("Assets",), "assets"),
    (("Liabilities",), "liabilities"),
    (
        ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
        "equity",
    ),
]
FRAME_RE = re.compile(r"^CY(\d{4})(?:Q([1-4]))?I?$")


def facts_to_pit_rows(facts: dict) -> pd.DataFrame:
    """Convert an EDGAR companyfacts JSON to PIT rows [date, period, value, field]."""
    gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    rows = []
    # collect from ALL present aliases (companies switch concepts over time,
    # e.g. Apple reports Revenues sparsely but RevenueFromContractWith... fully);
    # the (period, field) dedup below keeps the earliest filing
    for aliases, field in CONCEPT_FIELDS:
        items = [i for c in aliases if c in gaap for i in gaap[c].get("units", {}).get("USD", [])]
        for item in items:
            m = FRAME_RE.match(item.get("frame") or "")
            if not m or item.get("val") is None or not item.get("filed"):
                continue
            year, quarter = int(m.group(1)), int(m.group(2) or 4)  # annual frame -> Q4
            rows.append(
                {
                    "date": item["filed"],
                    "period": year * 100 + quarter,
                    "value": float(item["val"]),
                    "field": field,
                }
            )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).sort_values("date")
    return df.drop_duplicates(["period", "field"], keep="first").sort_values(["period", "field"]).reset_index(drop=True)


class EdgarClient:
    def __init__(self):
        ua = os.environ.get("SEC_EDGAR_USER_AGENT")
        if not ua:
            raise ValueError('SEC_EDGAR_USER_AGENT env var is required, e.g. "Your Name your@email.com"')
        self.session = requests.Session()
        self.session.headers["User-Agent"] = ua

    def get_json(self, url: str) -> dict:
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        time.sleep(0.15)  # SEC fair-use limit: 10 req/s
        return resp.json()

    def ticker_cik_map(self) -> dict:
        data = self.get_json("https://www.sec.gov/files/company_tickers.json")
        return {v["ticker"].upper(): int(v["cik_str"]) for v in data.values()}

    def company_facts(self, cik: int) -> dict:
        return self.get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")


def collect(save_dir: str, symbols=None, start_year: int = 2018):
    """collect SEC EDGAR fundamentals into PIT csv per symbol

    symbols: same formats as collector.py, e.g. "AAPL,MSFT", symbols_us.txt, or "S&P500"
    """
    from collector import parse_symbols  # noqa: E402  (same dir)

    save_dir = Path(save_dir).expanduser()
    save_dir.mkdir(parents=True, exist_ok=True)
    client = EdgarClient()
    cik_map = client.ticker_cik_map()

    for symbol in parse_symbols(symbols):
        cik = cik_map.get(symbol.upper())
        if cik is None:
            logger.warning(f"{symbol}: not found in SEC ticker map (ETFs have no filings)")
            continue
        try:
            facts = client.company_facts(cik)
        except Exception as e:
            logger.warning(f"{symbol}: EDGAR error: {e}")
            continue
        df = facts_to_pit_rows(facts)
        if df.empty:
            logger.warning(f"{symbol}: no usable facts")
            continue
        df = df[df["period"] >= start_year * 100]
        df.to_csv(save_dir.joinpath(f"{symbol}.csv"), index=False)
        logger.info(f"{symbol}: {len(df)} rows -> {save_dir}/{symbol}.csv")


if __name__ == "__main__":
    fire.Fire({"collect": collect})
