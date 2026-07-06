# offline self-check: candle mapping + normalize + symbol parsing (no API calls)
import sys
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent))
sys.path.append(str(Path(__file__).resolve().parents[3]))  # repo root for `import qlib`
from collector import candles_to_df, parse_symbols, UpbitNormalize1d


def test_candles_to_df():
    candles = [
        {"market": "KRW-BTC", "candle_date_time_utc": "2026-07-02T00:00:00",
         "opening_price": 100000000.0, "high_price": 101000000.0, "low_price": 99000000.0,
         "trade_price": 100500000.0, "candle_acc_trade_volume": 1234.5, "timestamp": 0},
        {"market": "KRW-BTC", "candle_date_time_utc": "2026-07-01T00:00:00",
         "opening_price": 99000000.0, "high_price": 100100000.0, "low_price": 98900000.0,
         "trade_price": 100000000.0, "candle_acc_trade_volume": 2000.0, "timestamp": 0},
    ]
    df = candles_to_df(candles)
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"]
    assert df["date"].tolist() == ["2026-07-02", "2026-07-01"]
    assert df.iloc[1]["close"] == 100000000.0


def test_parse_symbols():
    assert parse_symbols("krw-btc, krw-eth") == ["KRW-BTC", "KRW-ETH"]
    assert "KRW-BTC" in parse_symbols(None)  # default symbols_upbit.txt


def test_normalize():
    df = pd.DataFrame(
        {
            "date": ["2026-07-01", "2026-07-02", "2026-07-02"],  # dup on purpose
            "open": [1.0] * 3, "high": [1.0] * 3, "low": [1.0] * 3,
            "close": [100.0, 110.0, 110.0],
            "volume": [10, 20, 20],
            "symbol": ["KRW-BTC"] * 3,
        }
    )
    out = UpbitNormalize1d().normalize(df)
    assert len(out) == 2
    assert abs(out.iloc[1]["change"] - 0.1) < 1e-9
    assert (out["factor"] == 1.0).all()


if __name__ == "__main__":
    test_candles_to_df()
    test_parse_symbols()
    test_normalize()
    print("OK")
