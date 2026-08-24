from __future__ import annotations

import argparse
import json
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path('.local-data')
OBJECTS = ROOT / 'objects'
PARQUET_ROOT = OBJECTS / 'prices' / 'daily'
JSON_ROOT = OBJECTS / 'prices' / 'daily-json'
CLOSED_ROOT = ROOT / 'history-closed'
LATEST_FEATURE = OBJECTS / 'metadata' / 'latest-feature-state.json'
MASSIVE_BASE_URL = 'https://api.massive.com'
DEFAULT_REQUIRED_SESSIONS = 337
PACE_SECONDS = 13.0
MAX_RETRIES = 4


def load_dev_vars() -> dict[str, str]:
    path = Path('.dev.vars')
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        value = value.strip().strip('"').strip("'")
        out[key.strip()] = value
    return out


def massive_api_key() -> str | None:
    return os.getenv('MASSIVE_API_KEY') or load_dev_vars().get('MASSIVE_API_KEY')


def latest_completed_session() -> date:
    if not LATEST_FEATURE.exists():
        raise SystemExit('latest feature state missing; run npm run local:sync first or pass --end=YYYY-MM-DD')
    payload = json.loads(LATEST_FEATURE.read_text())
    value = payload.get('as_of') or payload.get('date')
    if not value:
        raise SystemExit('latest feature state has no as_of/date; pass --end=YYYY-MM-DD')
    return date.fromisoformat(str(value))


def json_path(day: date) -> Path:
    return JSON_ROOT / f'date={day.isoformat()}' / 'bars.json'


def parquet_path(day: date) -> Path:
    return PARQUET_ROOT / f'date={day.isoformat()}' / 'bars.parquet'


def closed_path(day: date) -> Path:
    return CLOSED_ROOT / f'{day.isoformat()}.json'


def normalize_document(day: date, rows: list[dict[str, object]], *, source: str, producer: str) -> dict[str, object]:
    bars: list[dict[str, object]] = []
    for row in rows:
        symbol = row.get('symbol') or row.get('T')
        values = [row.get('open', row.get('o')), row.get('high', row.get('h')), row.get('low', row.get('l')), row.get('close', row.get('c')), row.get('volume', row.get('v'))]
        if not symbol or any(value is None for value in values):
            continue
        try:
            nums = [float(value) for value in values]
        except (TypeError, ValueError):
            continue
        bars.append({
            'symbol': str(symbol),
            'date': day.isoformat(),
            'open': nums[0],
            'high': nums[1],
            'low': nums[2],
            'close': nums[3],
            'volume': nums[4],
        })
    return {
        'date': day.isoformat(),
        'adjusted': True,
        'source': source,
        'producer': producer,
        'count': len(bars),
        'bars': bars,
    }


def write_json_document(day: date, payload: dict[str, object]) -> None:
    path = json_path(day)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(',', ':')))


def materialize_parquet(day: date) -> bool:
    source = parquet_path(day)
    target = json_path(day)
    if target.exists():
        return True
    if not source.exists():
        return False
    try:
        import polars as pl
    except ImportError as exc:
        raise SystemExit('polars is required to materialize existing parquet history; run npm run local:history:setup') from exc
    frame = pl.read_parquet(source)
    payload = normalize_document(day, frame.to_dicts(), source='r2-parquet-mirror', producer='codespaces-history-materializer')
    if not payload['count']:
        raise RuntimeError(f'parquet file contained no valid bars: {source}')
    write_json_document(day, payload)
    return True


def existing_session_dates(end: date | None = None) -> list[date]:
    dates: set[date] = set()
    if JSON_ROOT.exists():
        for path in JSON_ROOT.glob('date=*/bars.json'):
            try:
                day = date.fromisoformat(path.parent.name.removeprefix('date='))
            except ValueError:
                continue
            if end is not None and day > end:
                continue
            try:
                payload = json.loads(path.read_text())
            except Exception:
                continue
            if payload.get('bars'):
                dates.add(day)
    return sorted(dates)


def materialize_all_parquet(end: date | None = None) -> int:
    if not PARQUET_ROOT.exists():
        return 0
    converted = 0
    for path in sorted(PARQUET_ROOT.glob('date=*/bars.parquet')):
        try:
            day = date.fromisoformat(path.parent.name.removeprefix('date='))
        except ValueError:
            continue
        if end is not None and day > end:
            continue
        if json_path(day).exists():
            continue
        if materialize_parquet(day):
            converted += 1
            if converted % 25 == 0:
                print(f'[local:history] materialized {converted} parquet sessions')
    return converted


def massive_grouped_daily(day: date, api_key: str) -> dict[str, object]:
    params = urlencode({'adjusted': 'true', 'apiKey': api_key})
    url = f'{MASSIVE_BASE_URL}/v2/aggs/grouped/locale/us/market/stocks/{day.isoformat()}?{params}'
    request = Request(url, headers={'Accept': 'application/json', 'User-Agent': 'FutureView-History-Recovery/1.0'})
    for attempt in range(MAX_RETRIES):
        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310
                payload = json.loads(response.read().decode('utf-8'))
            if not isinstance(payload, dict):
                raise RuntimeError('Massive returned non-object JSON')
            return payload
        except HTTPError as exc:
            body = exc.read().decode('utf-8', errors='replace')
            retryable = exc.code == 429 or 500 <= exc.code < 600
            if retryable and attempt + 1 < MAX_RETRIES:
                retry_after = exc.headers.get('Retry-After')
                delay = float(retry_after) if retry_after else 15.0 * (attempt + 1)
                print(f'[local:history] Massive HTTP {exc.code}; retry after {delay:.1f}s')
                time.sleep(delay)
                continue
            raise RuntimeError(f'Massive HTTP {exc.code} for {day}: {body[:300]}') from exc
        except URLError as exc:
            if attempt + 1 < MAX_RETRIES:
                delay = 2.0 * (attempt + 1)
                time.sleep(delay)
                continue
            raise RuntimeError(f'Massive transport error for {day}: {exc.reason}') from exc
    raise RuntimeError(f'Massive request exhausted retries for {day}')


def recover_until_sessions(required: int, end: date) -> tuple[int, int]:
    sessions = existing_session_dates(end)
    if len(sessions) >= required:
        return 0, len(sessions)
    api_key = massive_api_key()
    if not api_key:
        raise SystemExit(f'need {required - len(sessions)} more sessions but MASSIVE_API_KEY is unavailable')

    cursor = sessions[0] - timedelta(days=1) if sessions else end
    fetched = 0
    while len(sessions) < required:
        if cursor.weekday() >= 5:
            cursor -= timedelta(days=1)
            continue
        if json_path(cursor).exists():
            try:
                payload = json.loads(json_path(cursor).read_text())
                if payload.get('bars'):
                    sessions.append(cursor)
            except Exception:
                pass
            cursor -= timedelta(days=1)
            continue
        if materialize_parquet(cursor):
            sessions.append(cursor)
            cursor -= timedelta(days=1)
            continue
        if closed_path(cursor).exists():
            cursor -= timedelta(days=1)
            continue

        payload = massive_grouped_daily(cursor, api_key)
        raw_rows = payload.get('results') if isinstance(payload.get('results'), list) else []
        document = normalize_document(cursor, raw_rows, source='massive', producer='codespaces-history-recovery')
        fetched += 1
        if document['count']:
            write_json_document(cursor, document)
            sessions.append(cursor)
            sessions.sort()
            print(f"[local:history] recovered {cursor}: {document['count']} bars ({len(sessions)}/{required} sessions)")
        else:
            CLOSED_ROOT.mkdir(parents=True, exist_ok=True)
            closed_path(cursor).write_text(json.dumps({'date': cursor.isoformat(), 'status': 'no_market_data', 'checked_at': datetime.utcnow().isoformat() + 'Z'}))
            print(f'[local:history] no market data {cursor}; marked closed/unavailable')
        cursor -= timedelta(days=1)
        if len(sessions) < required:
            time.sleep(PACE_SECONDS)
    return fetched, len(sessions)


def main() -> None:
    parser = argparse.ArgumentParser(description='Build/recover canonical local daily history without coupling backtests to Massive')
    parser.add_argument('--mode', choices=('ensure', 'materialize'), default='ensure')
    parser.add_argument('--sessions', type=int, default=DEFAULT_REQUIRED_SESSIONS)
    parser.add_argument('--end', type=date.fromisoformat, default=None)
    args = parser.parse_args()
    if args.sessions < 1:
        raise SystemExit('--sessions must be positive')
    end = args.end or latest_completed_session()

    print(f'[local:history] target end={end} mode={args.mode}')
    converted = materialize_all_parquet(end)
    print(f'[local:history] parquet materialized: {converted}')
    if args.mode == 'materialize':
        sessions = existing_session_dates(end)
        print(f'[local:history] READY: {len(sessions)} local sessions through {end}')
        return

    fetched, total = recover_until_sessions(args.sessions, end)
    sessions = existing_session_dates(end)
    print('\n[local:history] READY')
    print(f'[local:history] sessions: {total} ({sessions[-args.sessions]} -> {sessions[-1]})')
    print(f'[local:history] Massive recovery requests this run: {fetched}')
    print(f'[local:history] canonical history: {JSON_ROOT}/')


if __name__ == '__main__':
    main()
