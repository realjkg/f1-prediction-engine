#!/usr/bin/env python3
"""Rebuild the pinned dataset snapshot from Jolpica — an explicit offline tool.

Never a runtime dependency: the app runs entirely from the committed snapshot
under data/snapshot/. This script exists so a human can regenerate that
snapshot deliberately, with provenance captured at generation time.

Behavior contract (spec, "One command, identical every time"):

- Fetches Jolpica (Ergast-compatible) season schedules and, per round, race
  results, qualifying, and sprint results where a sprint exists (2021+).
- Resumable: every HTTP response is cached per URL under the cache directory;
  a re-run skips anything already cached and never re-requests it.
- Rate-aware: at most one request per --min-interval seconds (default 0.25 =
  4 req/s, the Jolpica limit). Honors Retry-After on 429 with bounded retries.
- Budget-aware: the Jolpica unauthenticated budget is 500 requests/hour.
  Requests are logged with wall-clock timestamps in the cache directory; when
  the rolling-hour budget is exhausted the script stops cleanly and reports
  what remains (exit 3) rather than hammering.
- Deterministic output: rows are canonically sorted before writing; provenance
  records per-table sha256 plus a combined dataset hash (canonical order, see
  f1engine/dataset.py); data/snapshot/DATASET_VERSION pins the dataset id.

The generated snapshot is then re-loaded through the real ingestion loaders
(self-check) so format drift fails here, at generation time, not later.

Usage:
    python3 scripts/refresh-data.py [--seasons 2020-2024]
        [--data-dir data/snapshot] [--cache-dir .cache/jolpica]
        [--dataset-id 2026.10.0] [--min-interval 0.25] [--budget 500]
        [--as-of 2026-10-10] [--fresh-seasons 2026]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_ENGINE_SRC = REPO_ROOT / "engine"
if str(_ENGINE_SRC) not in sys.path:
    sys.path.insert(0, str(_ENGINE_SRC))

from f1engine.dataset import (
    SNAPSHOT_TABLE_NAMES,
    combined_table_hash,
    sha256_file,
)

DEFAULT_BASE_URL = "https://api.jolpi.ca/ergast/f1"
PAGE_LIMIT = 100  # outer page size; every round's rows fit one page
DEFAULT_MIN_INTERVAL = 0.25  # 4 req/s (Jolpica unauthenticated limit)
DEFAULT_BUDGET = 500  # 500 requests/hour (Jolpica unauthenticated budget)
DEFAULT_DATASET_ID = "2026.10.0"
DEFAULT_SEASONS = "2020-2024"
MAX_FETCH_ATTEMPTS = 3
USER_AGENT = "f1-prediction-engine-refresh/0.1 (offline pinned-snapshot builder)"

EXIT_OK = 0
EXIT_STOPPED = 3  # clean stop: budget or rate limit; safe to re-run later

LICENSE_JOLPICA = "CC-BY-NC-SA-4.0"
DATA_LIMITATIONS = [
    "no in-race telemetry in the pinned window",
    "no weather features before the 2023 rounds in the snapshot",
    "sprint results exist only from the 2021 season onward",
]


class RefreshError(RuntimeError):
    """Base failure for the refresh run."""


class BudgetExhausted(RefreshError):
    """The rolling-hour request budget is spent; stop cleanly, resume later."""


class RateLimited(RefreshError):
    """Upstream kept answering 429 after bounded backoff; stop cleanly."""


class UpstreamError(RefreshError):
    """Upstream returned a non-recoverable response."""


class UnexpectedShape(RefreshError):
    """A response did not match the expected Ergast shape."""


@dataclass
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


def default_fetch(url: str, timeout_seconds: float = 30.0) -> HttpResponse:
    """Stdlib HTTP GET; HTTPError is returned as a response, not raised."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return HttpResponse(
                status=response.status,
                headers=dict(response.headers.items()),
                body=response.read(),
            )
    except urllib.error.HTTPError as error:  # 4xx/5xx arrive here
        headers = dict(error.headers.items()) if error.headers else {}
        return HttpResponse(status=error.code, headers=headers, body=error.read())


class RateLimiter:
    """Sleeps so at most one request starts per min_interval window."""

    def __init__(
        self,
        min_interval: float,
        sleep_fn: Callable[[float], None] = time.sleep,
        now_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._min_interval = min_interval
        self._sleep = sleep_fn
        self._now = now_fn
        self._last_request_at: float | None = None

    def wait(self) -> None:
        if self._last_request_at is not None:
            remaining = self._min_interval - (self._now() - self._last_request_at)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request_at = self._now()


class HourlyBudget:
    """Rolling one-hour request log, persisted so the budget survives re-runs."""

    WINDOW_SECONDS = 3600

    def __init__(
        self,
        log_path: Path,
        budget: int,
        now_fn: Callable[[], float] = time.time,
    ) -> None:
        self._log_path = log_path
        self._budget = budget
        self._now = now_fn
        self._timestamps = self._load()

    def _load(self) -> list[float]:
        if not self._log_path.exists():
            return []
        entries = json.loads(self._log_path.read_text(encoding="utf-8"))
        if not isinstance(entries, list):
            raise RefreshError(f"corrupt request log: {self._log_path}")
        return [float(entry) for entry in entries]

    def _recent(self, now: float) -> list[float]:
        cutoff = now - self.WINDOW_SECONDS
        return [stamp for stamp in self._timestamps if stamp > cutoff]

    def remaining(self) -> int:
        return self._budget - len(self._recent(self._now()))

    def record(self) -> None:
        self._timestamps = self._recent(self._now())
        self._timestamps.append(self._now())
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_path.write_text(json.dumps(self._timestamps), encoding="utf-8")


class CachingClient:
    """Cache-first JSON fetcher with rate limiting and budget accounting."""

    def __init__(
        self,
        base_url: str,
        cache_dir: Path,
        rate_limiter: RateLimiter,
        budget: HourlyBudget,
        fetch_fn: Callable[[str], HttpResponse] = default_fetch,
        sleep_fn: Callable[[float], None] = time.sleep,
        now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
        fresh_seasons: set[int] | None = None,
    ) -> None:
        self._fresh_seasons = fresh_seasons or set()
        self._base_url = base_url.rstrip("/")
        self._cache_dir = cache_dir
        self._limiter = rate_limiter
        self._budget = budget
        self._fetch = fetch_fn
        self._sleep = sleep_fn
        self._now = now_fn
        self.requests_made = 0
        self.cache_hits = 0

    def get_json(self, path: str, params: str) -> tuple[dict, str]:
        """Fetch `{base}/{path}?{params}` — (body, fetchedAt ISO) cache-first."""
        url = f"{self._base_url}/{path}?{params}"
        cache_path = self._cache_path(url)
        # An in-progress season must not retain old schedule/results responses
        # across refresh runs. Historical seasons remain cache-first.
        refresh_this_path = any(
            path == f"{season}.json" or path.startswith(f"{season}/")
            for season in self._fresh_seasons
        )
        if cache_path.exists() and not refresh_this_path:
            entry = json.loads(cache_path.read_text(encoding="utf-8"))
            self.cache_hits += 1
            return entry["body"], entry["fetchedAt"]

        body = self._fetch_with_retries(url)
        fetched_at = self._now().isoformat()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {"url": url, "fetchedAt": fetched_at, "body": body},
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return body, fetched_at

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self._cache_dir / f"{digest}.json"

    def _fetch_with_retries(self, url: str) -> dict:
        last_error: Exception | None = None
        for attempt in range(1, MAX_FETCH_ATTEMPTS + 1):
            if self._budget.remaining() <= 0:
                raise BudgetExhausted(
                    f"hourly request budget ({self._budget._budget}) spent; "
                    f"stopping before {url} — re-run later to resume"
                )
            self._limiter.wait()
            try:
                response = self._fetch(url)
            except OSError as network_error:
                last_error = network_error
                if attempt == MAX_FETCH_ATTEMPTS:
                    raise UpstreamError(
                        f"network failure fetching {url}"
                    ) from network_error
                self._sleep(2.0 * attempt)
                continue
            self._budget.record()
            self.requests_made += 1
            if response.status == 429:
                if attempt == MAX_FETCH_ATTEMPTS:
                    raise RateLimited(f"still rate-limited after backoff: {url}")
                self._sleep(self._retry_after_seconds(response, attempt))
                continue
            if response.status >= 500:
                if attempt == MAX_FETCH_ATTEMPTS:
                    raise UpstreamError(
                        f"upstream {response.status} after backoff: {url}"
                    )
                self._sleep(2.0 * attempt)
                continue
            if response.status != 200:
                raise UpstreamError(f"unexpected status {response.status}: {url}")
            body = json.loads(response.body.decode("utf-8"))
            if not isinstance(body, dict) or "MRData" not in body:
                raise UnexpectedShape(f"response missing MRData: {url}")
            return body
        raise RefreshError(f"retries exhausted for {url}: {last_error}")

    def _retry_after_seconds(self, response: HttpResponse, attempt: int) -> float:
        raw = response.headers.get("Retry-After") or response.headers.get(
            "retry-after"
        )
        if raw and raw.strip().isdigit():
            return float(raw.strip())
        return 2.0 * attempt  # doubling backoff when upstream gives no hint


# --------------------------------------------------------------------------
# Response parsing — Ergast-compatible shapes into canonical snapshot rows.
# Rows are plain dicts keyed exactly as the parquet schemas (and therefore the
# pydantic loaders) expect.
# --------------------------------------------------------------------------


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "unknown"


def parse_lap_time_ms(value: object) -> int | None:
    """"1:29.179" -> 89179; "1:31:44.742" -> 5504742; empty -> None."""
    if not isinstance(value, str) or not value.strip():
        return None
    parts = value.strip().split(":")
    try:
        seconds = float(parts[-1])
        minutes = int(parts[-2]) if len(parts) >= 2 else 0
        hours = int(parts[-3]) if len(parts) >= 3 else 0
    except ValueError:
        return None
    return round(hours * 3_600_000 + minutes * 60_000 + seconds * 1_000)


def parse_int(value: object) -> int | None:
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def parse_race_rows(schedule_races: list[dict]) -> list[dict]:
    rows = []
    for race in schedule_races:
        circuit = race.get("Circuit", {})
        location = circuit.get("Location", {})
        rows.append(
            {
                "season": int(race["season"]),
                "round": int(race["round"]),
                "race_id": slugify(race["raceName"]),
                "name": race["raceName"],
                "date": race["date"],
                "circuit_id": circuit.get("circuitId", "unknown"),
                "circuit_name": circuit.get("circuitName", "unknown"),
                "country": location.get("country", "unknown"),
                "locality": location.get("locality", "unknown"),
            }
        )
    return rows


def parse_result_rows(
    season: int, round_number: int, race_id: str, results: list[dict]
) -> list[dict]:
    rows = []
    for result in results:
        time_block = result.get("Time") or {}
        rows.append(
            {
                "season": season,
                "round": round_number,
                "race_id": race_id,
                "position": parse_int(result.get("position")),
                "position_text": result.get("positionText", "unknown"),
                "points": float(result.get("points") or 0.0),
                "driver_id": result["Driver"]["driverId"],
                "constructor_id": result["Constructor"]["constructorId"],
                "grid": parse_int(result.get("grid")),
                "laps": parse_int(result.get("laps")) or 0,
                "status": result.get("status", "unknown"),
                "finish_time_ms": parse_int(time_block.get("millis")),
            }
        )
    return rows


def parse_qualifying_rows(
    season: int, round_number: int, race_id: str, results: list[dict]
) -> list[dict]:
    rows = []
    for result in results:
        rows.append(
            {
                "season": season,
                "round": round_number,
                "race_id": race_id,
                "position": parse_int(result.get("position")),
                "driver_id": result["Driver"]["driverId"],
                "constructor_id": result["Constructor"]["constructorId"],
                "q1_ms": parse_lap_time_ms(result.get("Q1")),
                "q2_ms": parse_lap_time_ms(result.get("Q2")),
                "q3_ms": parse_lap_time_ms(result.get("Q3")),
            }
        )
    return rows


def parse_sprint_rows(
    season: int, round_number: int, race_id: str, results: list[dict]
) -> list[dict]:
    rows = []
    for result in results:
        rows.append(
            {
                "season": season,
                "round": round_number,
                "race_id": race_id,
                "position": parse_int(result.get("position")),
                "position_text": result.get("positionText", "unknown"),
                "points": float(result.get("points") or 0.0),
                "driver_id": result["Driver"]["driverId"],
                "constructor_id": result["Constructor"]["constructorId"],
                "status": result.get("status", "unknown"),
            }
        )
    return rows


# --------------------------------------------------------------------------
# Fetch orchestration
# --------------------------------------------------------------------------


def fetch_paginated_races(
    client: CachingClient, path: str
) -> tuple[list[dict], str]:
    """Page through the outer Races list; returns (races, lastFetchedAt)."""
    races: list[dict] = []
    fetched_at = ""
    offset = 0
    while True:
        body, fetched_at = client.get_json(path, f"limit={PAGE_LIMIT}&offset={offset}")
        mrdata = body["MRData"]
        total = int(mrdata.get("total", "0"))
        page = mrdata.get("RaceTable", {}).get("Races", [])
        races.extend(page)
        offset += len(page)
        if not page or offset >= total:
            return races, fetched_at


def fetch_round_rows(
    client: CachingClient, path: str, inner_key: str
) -> tuple[list[dict], str]:
    """Fetch one round's rows, paginating the INNER list.

    Jolpica's limit/offset page a round's result rows (total = row count) for
    per-round endpoints, not the outer single-race list.
    """
    rows: list[dict] = []
    fetched_at = ""
    offset = 0
    while True:
        body, fetched_at = client.get_json(path, f"limit={PAGE_LIMIT}&offset={offset}")
        mrdata = body["MRData"]
        total = int(mrdata.get("total", "0"))
        races = mrdata.get("RaceTable", {}).get("Races", [])
        if len(races) > 1:
            raise UnexpectedShape(f"expected a single race per-round query: {path}")
        got = races[0].get(inner_key, []) if races else []
        rows.extend(got)
        offset += len(got)
        if not got or offset >= total:
            return rows, fetched_at


def fetch_season(
    client: CachingClient,
    season: int,
    as_of: date | None = None,
) -> tuple[
    list[dict],
    dict[int, list[dict]],
    dict[int, list[dict]],
    dict[int, list[dict]],
    str,
]:
    """Fetch one season: schedule, then per-round results/qualifying/sprints.

    Returns (schedule_races, results_by_round, qualifying_by_round,
    sprints_by_round, maxFetchedAt).
    """
    schedule_races, fetched_at = fetch_paginated_races(client, f"{season}.json")
    if not schedule_races:
        raise UnexpectedShape(f"empty schedule for season {season}")
    # Exclude same-day races: the source may publish a classification during
    # the day, and a racing forecast must not train on that race's outcome.
    if as_of is not None:
        schedule_races = [
            race for race in schedule_races
            if date.fromisoformat(race["date"]) < as_of
        ]

    results_by_round: dict[int, list[dict]] = {}
    qualifying_by_round: dict[int, list[dict]] = {}
    sprints_by_round: dict[int, list[dict]] = {}

    for race in schedule_races:
        round_number = int(race["round"])
        results_block, results_at = fetch_round_rows(
            client, f"{season}/{round_number}/results.json", "Results"
        )
        fetched_at = max(fetched_at, results_at)
        if not results_block:
            raise UnexpectedShape(f"no results block for {season} r{round_number}")
        results_by_round[round_number] = results_block

        qualifying_block, qualifying_at = fetch_round_rows(
            client, f"{season}/{round_number}/qualifying.json", "QualifyingResults"
        )
        fetched_at = max(fetched_at, qualifying_at)
        if not qualifying_block:
            raise UnexpectedShape(
                f"no qualifying block for {season} r{round_number}"
            )
        qualifying_by_round[round_number] = qualifying_block

        if "Sprint" in race:
            sprint_block, sprint_at = fetch_round_rows(
                client, f"{season}/{round_number}/sprint.json", "SprintResults"
            )
            fetched_at = max(fetched_at, sprint_at)
            if not sprint_block:
                raise UnexpectedShape(
                    f"schedule flags a sprint but none returned: "
                    f"{season} r{round_number}"
                )
            sprints_by_round[round_number] = sprint_block

    return (
        schedule_races,
        results_by_round,
        qualifying_by_round,
        sprints_by_round,
        fetched_at,
    )


# --------------------------------------------------------------------------
# Snapshot assembly and writing
# --------------------------------------------------------------------------


def build_table_rows(
    seasons: list[int], client: CachingClient, as_of: date | None = None
) -> tuple[dict[str, list[dict]], list[str]]:
    """Fetch everything and parse into canonical row dicts per table."""
    races: list[dict] = []
    results: list[dict] = []
    qualifying: list[dict] = []
    sprints: list[dict] = []
    drivers_map: dict[str, dict] = {}
    constructors_map: dict[str, dict] = {}
    fetched_ats: list[str] = []

    for season in seasons:
        (
            schedule_races,
            results_by_round,
            qualifying_by_round,
            sprints_by_round,
            season_fetched_at,
        ) = fetch_season(client, season, as_of=as_of)
        fetched_ats.append(season_fetched_at)
        races.extend(parse_race_rows(schedule_races))

        for round_number, block in results_by_round.items():
            race_id = _race_id_for(races, season, round_number)
            results.extend(parse_result_rows(season, round_number, race_id, block))
        for round_number, block in qualifying_by_round.items():
            race_id = _race_id_for(races, season, round_number)
            qualifying.extend(
                parse_qualifying_rows(season, round_number, race_id, block)
            )
        for round_number, block in sprints_by_round.items():
            race_id = _race_id_for(races, season, round_number)
            sprints.extend(parse_sprint_rows(season, round_number, race_id, block))

        for entry_block in (
            *results_by_round.values(),
            *qualifying_by_round.values(),
            *sprints_by_round.values(),
        ):
            for entry in entry_block:
                _absorb_driver(entry["Driver"], drivers_map)
                _absorb_constructor(entry["Constructor"], constructors_map)

    tables: dict[str, list[dict]] = {
        "races": sorted(races, key=lambda r: (r["season"], r["round"])),
        "results": sorted(
            results,
            key=_result_sort_key,
        ),
        "qualifying": sorted(
            qualifying,
            key=_position_sort_key,
        ),
        "sprints": sorted(
            sprints,
            key=_position_sort_key,
        ),
        "drivers": [drivers_map[key] for key in sorted(drivers_map)],
        "constructors": [constructors_map[key] for key in sorted(constructors_map)],
    }
    return tables, sorted(set(fetched_ats))


def _race_id_for(races: list[dict], season: int, round_number: int) -> str:
    for race in races:
        if race["season"] == season and race["round"] == round_number:
            return race["race_id"]
    raise UnexpectedShape(f"no race row for {season} r{round_number}")


def _absorb_driver(block: dict, drivers_map: dict[str, dict]) -> None:
    driver_id = block["driverId"]
    if driver_id in drivers_map:
        return
    drivers_map[driver_id] = {
        "driver_id": driver_id,
        "code": block.get("code") or block.get("familyName", "")[:3].upper(),
        "given_name": block.get("givenName", "unknown"),
        "family_name": block.get("familyName", "unknown"),
        "nationality": block.get("nationality", "unknown"),
    }


def _absorb_constructor(block: dict, constructors_map: dict[str, dict]) -> None:
    constructor_id = block["constructorId"]
    if constructor_id in constructors_map:
        return
    constructors_map[constructor_id] = {
        "constructor_id": constructor_id,
        "name": block.get("name", "unknown"),
        "nationality": block.get("nationality", "unknown"),
    }


def _position_sort_key(row: dict) -> tuple:
    return (
        row["season"],
        row["round"],
        row["position"] if row["position"] is not None else 999,
        row["driver_id"],
    )


def _result_sort_key(row: dict) -> tuple:
    return _position_sort_key(row)


def parquet_schemas() -> dict:
    """Explicit pyarrow schemas, one per snapshot table.

    Declaring the schema (instead of inferring) keeps empty tables well-typed
    and pins column order and types regardless of data content.
    """
    import pyarrow as pa

    return {
        "races": pa.schema(
            [
                ("season", pa.int64()),
                ("round", pa.int64()),
                ("race_id", pa.string()),
                ("name", pa.string()),
                ("date", pa.string()),
                ("circuit_id", pa.string()),
                ("circuit_name", pa.string()),
                ("country", pa.string()),
                ("locality", pa.string()),
            ]
        ),
        "results": pa.schema(
            [
                ("season", pa.int64()),
                ("round", pa.int64()),
                ("race_id", pa.string()),
                ("position", pa.int64()),
                ("position_text", pa.string()),
                ("points", pa.float64()),
                ("driver_id", pa.string()),
                ("constructor_id", pa.string()),
                ("grid", pa.int64()),
                ("laps", pa.int64()),
                ("status", pa.string()),
                ("finish_time_ms", pa.int64()),
            ]
        ),
        "qualifying": pa.schema(
            [
                ("season", pa.int64()),
                ("round", pa.int64()),
                ("race_id", pa.string()),
                ("position", pa.int64()),
                ("driver_id", pa.string()),
                ("constructor_id", pa.string()),
                ("q1_ms", pa.int64()),
                ("q2_ms", pa.int64()),
                ("q3_ms", pa.int64()),
            ]
        ),
        "sprints": pa.schema(
            [
                ("season", pa.int64()),
                ("round", pa.int64()),
                ("race_id", pa.string()),
                ("position", pa.int64()),
                ("position_text", pa.string()),
                ("points", pa.float64()),
                ("driver_id", pa.string()),
                ("constructor_id", pa.string()),
                ("status", pa.string()),
            ]
        ),
        "drivers": pa.schema(
            [
                ("driver_id", pa.string()),
                ("code", pa.string()),
                ("given_name", pa.string()),
                ("family_name", pa.string()),
                ("nationality", pa.string()),
            ]
        ),
        "constructors": pa.schema(
            [
                ("constructor_id", pa.string()),
                ("name", pa.string()),
                ("nationality", pa.string()),
            ]
        ),
    }


def write_parquet_tables(tables: dict[str, list[dict]], data_dir: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    schemas = parquet_schemas()
    data_dir.mkdir(parents=True, exist_ok=True)
    for name in SNAPSHOT_TABLE_NAMES:
        table = pa.Table.from_pylist(tables[name], schema=schemas[name])
        pq.write_table(table, data_dir / f"{name}.parquet")


def build_provenance(
    dataset_id: str,
    tables: dict[str, list[dict]],
    table_hashes: dict[str, str],
    fetched_ats: list[str],
    base_url: str,
    endpoint_templates: list[str],
    seasons: list[int],
    as_of: date | None = None,
) -> dict:
    seasons_label = f"{seasons[0]}-{seasons[-1]}" if seasons else ""
    return {
        "schemaVersion": 1,
        "datasetId": dataset_id,
        "generatedAt": datetime.now(UTC).isoformat(),
        "snapshot": {
            "seasons": seasons_label,
            "format": "parquet",
            "sha256": combined_table_hash(table_hashes),
            "asOfDate": as_of.isoformat() if as_of else None,
        },
        "tables": {
            name: {"rows": len(tables[name]), "sha256": table_hashes[name]}
            for name in sorted(tables)
        },
        "sources": [
            {
                "provider": "jolpica-f1",
                "role": "primary historical results and standings",
                "baseUrl": base_url,
                "endpoints": endpoint_templates,
                "fetchedAt": max(fetched_ats) if fetched_ats else None,
                "license": LICENSE_JOLPICA,
            },
            {
                "provider": "openf1",
                "role": (
                    "2023+ session detail (lap timing, weather) — not fetched "
                    "in this dataset version"
                ),
                "baseUrl": "https://api.openf1.org",
                "endpoints": [],
                "fetchedAt": None,
                "license": "non-commercial free tier",
            },
        ],
        "dataLimitations": DATA_LIMITATIONS + (
            [f"snapshot includes only races dated strictly before {as_of.isoformat()}"]
            if as_of else []
        ),
    }


def run_refresh(
    seasons: list[int],
    data_dir: Path,
    cache_dir: Path,
    base_url: str,
    dataset_id: str,
    min_interval: float,
    budget: int,
    fetch_fn: Callable[[str], HttpResponse] = default_fetch,
    sleep_fn: Callable[[float], None] = time.sleep,
    wall_now_fn: Callable[[], float] = time.time,
    clock_now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
    as_of: date | None = None,
    fresh_seasons: set[int] | None = None,
) -> dict:
    """Run the full refresh; returns a summary dict for reporting/tests."""
    client = CachingClient(
        base_url=base_url,
        cache_dir=cache_dir,
        rate_limiter=RateLimiter(min_interval, sleep_fn=sleep_fn),
        budget=HourlyBudget(cache_dir / "request-log.json", budget, now_fn=wall_now_fn),
        fetch_fn=fetch_fn,
        sleep_fn=sleep_fn,
        now_fn=clock_now_fn,
        fresh_seasons=fresh_seasons,
    )

    tables, fetched_ats = build_table_rows(seasons, client, as_of=as_of)
    write_parquet_tables(tables, data_dir)

    table_hashes = {
        name: sha256_file(data_dir / f"{name}.parquet")
        for name in SNAPSHOT_TABLE_NAMES
    }
    endpoint_templates = [
        "{season}.json",
        "{season}/{round}/results.json",
        "{season}/{round}/qualifying.json",
        "{season}/{round}/sprint.json",
    ]
    provenance = build_provenance(
        dataset_id=dataset_id,
        tables=tables,
        table_hashes=table_hashes,
        fetched_ats=fetched_ats,
        base_url=base_url,
        endpoint_templates=endpoint_templates,
        seasons=seasons,
        as_of=as_of,
    )
    (data_dir / "provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
    )
    (data_dir / "DATASET_VERSION").write_text(f"{dataset_id}\n", encoding="utf-8")

    return {
        "tables": {name: len(rows) for name, rows in tables.items()},
        "tableHashes": table_hashes,
        "datasetSha256": provenance["snapshot"]["sha256"],
        "datasetId": dataset_id,
        "requestsMade": client.requests_made,
        "cacheHits": client.cache_hits,
        "budgetRemaining": client._budget.remaining(),
        "fetchedAt": provenance["sources"][0]["fetchedAt"],
    }


def parse_seasons(raw: str) -> list[int]:
    """"2020-2024" or "2020,2021" -> ascending unique season list."""
    seasons: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            seasons.update(range(int(start), int(end) + 1))
        else:
            seasons.add(int(part))
    if not seasons:
        raise ValueError(f"no seasons parsed from {raw!r}")
    return sorted(seasons)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--seasons", default=DEFAULT_SEASONS, help="e.g. 2020-2024 or 2020,2021"
    )
    parser.add_argument("--data-dir", default="data/snapshot")
    parser.add_argument("--cache-dir", default=".cache/jolpica")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--dataset-id", default=DEFAULT_DATASET_ID)
    parser.add_argument("--min-interval", type=float, default=DEFAULT_MIN_INTERVAL)
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    parser.add_argument(
        "--as-of", type=date.fromisoformat, default=None,
        help="exclusive YYYY-MM-DD cutoff for including fully finished races",
    )
    parser.add_argument(
        "--fresh-seasons", default="",
        help="seasons whose cached API responses are always re-fetched (e.g. 2026)",
    )
    args = parser.parse_args(argv)

    seasons = parse_seasons(args.seasons)
    data_dir = Path(args.data_dir)
    cache_dir = Path(args.cache_dir)

    try:
        summary = run_refresh(
            seasons=seasons,
            data_dir=data_dir,
            cache_dir=cache_dir,
            base_url=args.base_url,
            dataset_id=args.dataset_id,
            min_interval=args.min_interval,
            budget=args.budget,
            as_of=args.as_of,
            fresh_seasons=set(parse_seasons(args.fresh_seasons)) if args.fresh_seasons else set(),
        )
    except BudgetExhausted as error:
        print(f"JOLPICA_BUDGET_EXHAUSTED — stopping cleanly: {error}")
        print("The run is resumable: cached responses are kept, re-run later.")
        return EXIT_STOPPED
    except RateLimited as error:
        print(f"JOLPICA_RATE_LIMITED — stopping cleanly: {error}")
        print("The run is resumable: cached responses are kept, re-run later.")
        return EXIT_STOPPED

    print("refresh complete")
    print(f"  cutoff         : {args.as_of} (exclusive; same-day races excluded)")
    print(f"  dataset id     : {summary['datasetId']}")
    print(f"  dataset sha256 : {summary['datasetSha256']}")
    print(f"  fetched at     : {summary['fetchedAt']}")
    print(
        f"  requests made  : {summary['requestsMade']} "
        f"(cache hits: {summary['cacheHits']}, "
        f"budget left this hour: {summary['budgetRemaining']})"
    )
    for name in SNAPSHOT_TABLE_NAMES:
        print(f"  {name:<13}: {summary['tables'][name]} rows")

    # Self-check: the snapshot must load through the real ingestion loaders.
    # At scaffold time ingestion may still be a stub — note, do not fail.
    try:
        from f1engine.ingestion import load_snapshot

        dataset = load_snapshot(data_dir)
        print(
            f"  self-check     : load_snapshot OK — dataset {dataset.dataset_id}, "
            f"sha256 {dataset.dataset_sha256[:12]}…"
        )
    except NotImplementedError:
        print("  self-check     : ingestion not implemented yet — skipped")
    except Exception as error:  # noqa: BLE001 — report and stop the run
        print(
            f"  self-check     : FAILED — generated snapshot does not load: {error}"
        )
        return EXIT_STOPPED
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
