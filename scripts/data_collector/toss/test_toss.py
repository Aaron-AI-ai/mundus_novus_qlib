# offline self-check: candle mapping + normalize (no API calls)
import sys
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent))
sys.path.append(str(Path(__file__).resolve().parents[3]))  # repo root for `import qlib`
from collector import candles_to_df, TossNormalize1d


def test_candles_to_df():
    candles = [
        {"timestamp": "2026-07-02T00:00:00+09:00", "openPrice": 80000, "highPrice": 81000,
         "lowPrice": 79500, "closePrice": 80500, "volume": 1000, "currency": "KRW"},
        {"timestamp": "2026-07-01T00:00:00+09:00", "openPrice": 79000, "highPrice": 80100,
         "lowPrice": 78900, "closePrice": 80000, "volume": 2000, "currency": "KRW"},
    ]
    df = candles_to_df(candles)
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"]
    assert df["date"].tolist() == ["2026-07-02", "2026-07-01"]
    assert df.iloc[1]["close"] == 80000


def test_normalize():
    df = pd.DataFrame(
        {
            "date": ["2026-07-01", "2026-07-02", "2026-07-02"],  # dup on purpose
            "open": [1.0, 2.0, 2.0],
            "high": [1.0, 2.0, 2.0],
            "low": [1.0, 2.0, 2.0],
            "close": [100.0, 110.0, 110.0],
            "volume": [10, 20, 20],
            "symbol": ["005930"] * 3,
        }
    )
    out = TossNormalize1d().normalize(df)
    assert len(out) == 2
    assert abs(out.iloc[1]["change"] - 0.1) < 1e-9
    assert (out["factor"] == 1.0).all()


def test_parse_symbols():
    from collector import parse_symbols

    assert parse_symbols("005930, 000660") == ["005930", "000660"]
    assert parse_symbols(["069500"]) == ["069500"]
    assert "005930" in parse_symbols(None)  # default symbols_kr.txt, comments stripped


def test_finstate_to_pit_rows():
    from collect_pit import finstate_to_pit_rows

    fs = pd.DataFrame(
        {
            "account_nm": ["매출액", "당기순이익", "기타항목", "매출액"],
            "thstrm_amount": ["1,000", "200", "999", "900"],
            "fs_div": ["CFS", "CFS", "CFS", "OFS"],  # OFS row must be ignored
            "rcept_no": ["20240515000123"] * 4,
        }
    )
    out = finstate_to_pit_rows(fs, 2024, 1)
    assert len(out) == 2
    assert set(out["field"]) == {"revenue", "netincome"}
    assert out.iloc[0]["date"] == "2024-05-15"
    assert (out["period"] == 202401).all()


def test_us_timezone():
    from collector import market_timezone

    assert market_timezone("005930") == "Asia/Seoul"
    assert market_timezone("AAPL") == "America/New_York"
    # US candle stamped midnight UTC must stay on the US trading date, not shift a day
    candles = [{"timestamp": "2026-07-02T00:00:00Z", "openPrice": 1, "highPrice": 1,
                "lowPrice": 1, "closePrice": 1, "volume": 1, "currency": "USD"}]
    assert candles_to_df(candles, tz="America/New_York")["date"].iloc[0] == "2026-07-01"


def test_facts_to_pit_rows():
    from collect_pit_us import facts_to_pit_rows

    facts = {
        "facts": {
            "us-gaap": {
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {"frame": "CY2024Q1", "val": 100.0, "filed": "2024-05-01"},
                            {"frame": "CY2024Q1", "val": 101.0, "filed": "2024-08-01"},  # restated, must lose
                            {"frame": "CY2024", "val": 400.0, "filed": "2025-02-01"},  # annual -> Q4
                            {"val": 999.0, "filed": "2024-05-01"},  # no frame -> skipped
                        ]
                    }
                },
                "Assets": {
                    "units": {"USD": [{"frame": "CY2024Q1I", "val": 5000.0, "filed": "2024-05-01"}]}
                },
            }
        }
    }
    out = facts_to_pit_rows(facts)
    assert len(out) == 3
    ni_q1 = out[(out["field"] == "netincome") & (out["period"] == 202401)]
    assert ni_q1["value"].iloc[0] == 100.0  # earliest filing wins
    assert out[out["field"] == "netincome"]["period"].tolist() == [202401, 202404]
    assert out[out["field"] == "assets"]["period"].iloc[0] == 202401


def test_merge_us_marketcap_df():
    from collect_marketcap_us import merge_us_marketcap_df

    df = pd.DataFrame({"date": ["2026-07-01", "2026-07-02"], "close": [10.0, 11.0]})
    shares = pd.Series(
        [1000.0],
        index=pd.to_datetime(["2026-06-15 12:00:00"]).tz_localize("America/New_York"),
    )
    raw_close = pd.Series([20.0, 22.0], index=pd.to_datetime(["2026-07-01", "2026-07-02"]))
    out = merge_us_marketcap_df(df, shares, raw_close)
    assert out["shares"].tolist() == [1000.0, 1000.0]  # sparse shares forward-filled
    assert out["mcap"].tolist() == [20000.0, 22000.0]  # unadjusted close, not df close


def test_merge_marketcap_df():
    from collect_marketcap import merge_marketcap_df

    df = pd.DataFrame({"date": ["2026-07-01", "2026-07-02"], "close": [100.0, 110.0]})
    cap = pd.DataFrame(
        {"시가총액": [5e12, 5.1e12], "상장주식수": [1e8, 1e8], "거래량": [1, 2]},
        index=pd.to_datetime(["2026-07-01", "2026-07-02"]),
    )
    out = merge_marketcap_df(df, cap)
    assert list(out.columns) == ["date", "close", "mcap", "shares"]
    assert out.iloc[1]["mcap"] == 5.1e12


if __name__ == "__main__":
    test_candles_to_df()
    test_normalize()
    test_parse_symbols()
    test_finstate_to_pit_rows()
    test_merge_marketcap_df()
    test_us_timezone()
    test_facts_to_pit_rows()
    test_merge_us_marketcap_df()
    print("OK")
