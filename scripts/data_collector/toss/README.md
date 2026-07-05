# 한국 주식 데이터 수집기 (토스증권 Open API + KRX/DART)

[토스증권 Open API](https://developers.tossinvest.com/docs)로 KRX 일봉을 수집해 qlib 포맷으로 변환·백테스트하고, pykrx(시가총액)·DART(재무제표)·토스 현재가 폴링(실시간)까지 붙이는 파이프라인.

## 파일 구성

| 파일 | 역할 | 필요한 키 (환경변수) |
|---|---|---|
| `collector.py` | 토스 API 일봉(OHLCV, 수정주가) 수집 → 정규화 | `TOSS_CLIENT_ID`, `TOSS_CLIENT_SECRET` |
| `collect_marketcap.py` | pykrx 시가총액/상장주식수 → 일봉 CSV에 병합 | `KRX_ID`, `KRX_PW` ([data.krx.co.kr](https://data.krx.co.kr) 무료 가입) |
| `collect_pit.py` | DART 분기/연간 재무제표 → qlib PIT 포맷 | `DART_API_KEY` ([opendart.fss.or.kr](https://opendart.fss.or.kr) 무료 발급) |
| `live_quotes.py` | 토스 현재가 REST 폴링 (WebSocket 미공개) | `TOSS_CLIENT_ID`, `TOSS_CLIENT_SECRET` |
| `symbols_kr.txt` | 기본 종목 (KOSPI 대형주 24 + KODEX 200) | - |
| `workflow_config_toss_lightgbm.yaml` | Alpha158 + LightGBM 백테스트 설정 | - |
| `test_toss.py` | 오프라인 자체 검증 (`python test_toss.py`) | - |

종목 지정(`--symbols`)은 모든 스크립트 공통: 미지정 시 `symbols_kr.txt`, `"005930,000660"` 콤마 문자열, 파일 경로, 또는 시장 키워드 `KOSPI`/`KOSDAQ`/`KRX`(FinanceDataReader로 전종목 자동 조회, KOSPI ≈ 945종목).

## 1. 일봉 수집 → qlib 변환 → 백테스트

```bash
export TOSS_CLIENT_ID=... TOSS_CLIENT_SECRET=...   # WTS > 설정 > Open API
cd scripts/data_collector/toss

python collector.py download_data --source_dir ~/.qlib/toss_data/source --start 2018-01-01 --end 2026-07-01
python collector.py normalize_data --source_dir ~/.qlib/toss_data/source --normalize_dir ~/.qlib/toss_data/normalize

cd ../..
python dump_bin.py dump_all --data_path ~/.qlib/toss_data/normalize --qlib_dir ~/.qlib/qlib_data/kr_data --freq day --include_fields open,close,high,low,volume,change,factor

cd scripts/data_collector/toss && qrun workflow_config_toss_lightgbm.yaml
```

전종목으로 수집하려면 `--symbols KOSPI` 추가 (945종목 × 페이지네이션이라 오래 걸림, `--delay 0.2` 기본 유지).

> 토스 API는 클라이언트당 유효 토큰 1개 (재발급 시 기존 토큰 무효화). 수집 중 같은 키로 다른 프로그램 사용 금지, `max_workers=1` 유지.

## 2. 시가총액 병합 (pykrx)

normalize 후, dump_bin 전에 실행:

```bash
export KRX_ID=... KRX_PW=...   # data.krx.co.kr 무료 계정
python collect_marketcap.py merge --normalize_dir ~/.qlib/toss_data/normalize --start 2018-01-01 --end 2026-07-01

# dump_bin 재실행 시 필드 추가
python ../../dump_bin.py dump_all --data_path ~/.qlib/toss_data/normalize --qlib_dir ~/.qlib/qlib_data/kr_data --freq day --include_fields open,close,high,low,volume,change,factor,mcap,shares
```

qlib 표현식에서 `$mcap`(시가총액), `$shares`(상장주식수) 사용 가능 — 예: 회전율 `$volume/$shares`, 시총 상위 유니버스 필터.

## 3. 재무제표 → PIT (DART)

```bash
export DART_API_KEY=...   # opendart.fss.or.kr 무료 발급
python collect_pit.py collect --save_dir ~/.qlib/toss_data/pit --start_year 2018
python ../../dump_pit.py dump --csv_path ~/.qlib/toss_data/pit --qlib_dir ~/.qlib/qlib_data/kr_data --freq quarterly
```

date=공시일(rcept_no) 기준의 진짜 point-in-time 데이터라 look-ahead bias가 없음. qlib에서 `P($$revenue_q)`, `P($$netincome_q)`, `P($$equity_q)` 등으로 조회 (필드: revenue, operatingprofit, netincome, assets, liabilities, equity). 분기 손익 항목은 DART 공시 그대로 누적(YTD) 값.

## 4. 실시간 현재가 폴링

```bash
python live_quotes.py poll --symbols "005930,000660" --interval_sec 1 --out quotes.csv
```

토스 API는 아직 WebSocket 미공개(2026-06 기준)라 REST 폴링(1초 간격까지)이 공식 방법. 회당 최대 200종목. 밀리초 단위 실시간이 필요하면 [KIS Open API](https://github.com/koreainvestment/open-trading-api) WebSocket 병용.

## 참고

- 토스 캔들은 회당 최대 200봉, `nextBefore` 커서로 자동 페이지네이션. 429는 `Retry-After` 대기 후 재시도.
- `adjusted=true` 수정주가 기준이므로 `factor=1` 고정.
- 백테스트 거래비용(yaml `open_cost`/`close_cost`)은 근사치 — 실제 계좌 조건에 맞게 조정.
- DART 레이트리밋 ~100회/분 → `--delay 0.7` 기본. 전종목(KOSPI) 재무 수집은 945종목 × 9년 × 4분기 ≈ 3.4만 요청이라 일일 한도(2만)에 걸림: `--start_year`를 좁히거나 이틀에 나눠 실행.

Sources: [토스증권 Open API](https://developers.tossinvest.com/docs) · [MarketDataApi](https://openapi.tossinvest.com/openapi-docs/latest/api-reference/Apis/MarketDataApi.md) · [OpenDartReader](https://github.com/FinanceData/OpenDartReader) · [pykrx](https://github.com/sharebook-kr/pykrx) · [FinanceDataReader](https://github.com/FinanceData/FinanceDataReader)
