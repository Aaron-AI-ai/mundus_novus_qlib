# 업비트 암호화폐 데이터 수집기

업비트 공개 시세 API로 KRW 마켓 일봉(OHLCV)을 수집해 qlib 포맷으로 변환·백테스트하는 파이프라인. **API 키·계정 불필요, 무료.**

## 사용법

```bash
cd scripts/data_collector/upbit

# 1) 수집 (기본: symbols_upbit.txt 주요 15개 코인. --symbols KRW 로 전체 KRW 마켓 ~140개)
python collector.py download_data --source_dir ~/.qlib/upbit_data/source --start 2018-01-01

# 2) 정규화 (change/factor 컬럼 추가)
python collector.py normalize_data --source_dir ~/.qlib/upbit_data/source --normalize_dir ~/.qlib/upbit_data/normalize

# 3) qlib 변환
cd ../..
python dump_bin.py dump_all --data_path ~/.qlib/upbit_data/normalize --qlib_dir ~/.qlib/qlib_data/upbit_data --freq day --include_fields open,close,high,low,volume,change,factor

# 4) 백테스트 (Alpha158 + LightGBM, 벤치마크 KRW-BTC)
cd scripts/data_collector/upbit && qrun workflow_config_upbit_lightgbm.yaml
```

## 주식 파이프라인과 다른 점

- **별도 qlib 디렉토리 필수** (`upbit_data`): 365일 24시간 거래라 캘린더가 주식과 다름. 연환산 스케일러도 365 사용 (yaml에 반영).
- 가격은 KRW 기준, 일봉 경계는 UTC 00:00 (업비트 일봉 기준).
- `factor=1` 고정 (수정주가 개념 없음), 상하한가 없음, 소수점 거래(`trade_unit: null`).
- 수수료: 업비트 KRW 마켓 0.05% (yaml `open_cost`/`close_cost: 0.0005`).

## 참고

- 캔들은 회당 최대 200개, `to` 파라미터(UTC, exclusive)로 과거 방향 페이지네이션. 429는 0.5초 대기 후 재시도 (공개 API 한도 ~초당 10회, 기본 `--delay 0.15`).
- 상장폐지 코인은 마켓 목록에서 빠지므로 `--symbols KRW` 전체 수집에도 생존 편향이 있음 — 주식 README의 동일 이슈 참고.
- 히스토리는 코인별 업비트 상장 시점부터 (BTC/ETH ≈ 2017-10).
- 오프라인 검증: `python test_upbit.py`

Sources: [업비트 개발자 센터 (시세 API)](https://docs.upbit.com/kr/reference/list-candles-days)
