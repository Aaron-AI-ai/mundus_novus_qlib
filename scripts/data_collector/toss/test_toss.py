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
    print("OK")
