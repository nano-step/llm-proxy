## ADDED Requirements

### Requirement: TTL cache for all-time aggregate queries
The backend SHALL use `cachetools.TTLCache` to cache the result of all-time aggregate queries. The cache SHALL have a `maxsize` of 32 entries and a `ttl` of 60 seconds. The `/api/alltime` endpoint SHALL be the primary consumer of this cache. The cache SHALL be module-level (not per-request) so it persists across requests within the same process.

#### Scenario: Cache hit avoids SQL query
- **WHEN** `/api/alltime` is called and the cache contains a valid (non-expired) entry
- **THEN** the cached result is returned without executing any SQL query

#### Scenario: Cache miss triggers SQL query
- **WHEN** `/api/alltime` is called and the cache is empty or expired
- **THEN** a full-table aggregate SQL query is executed and the result is stored in the cache

#### Scenario: Cache auto-expires after TTL
- **WHEN** 60 seconds have elapsed since the cache was last populated
- **THEN** the next call to `/api/alltime` triggers a fresh SQL query

### Requirement: cachetools dependency
The project SHALL add `cachetools` as a Python dependency. It SHALL be installed via `pip install cachetools`. No other caching dependencies SHALL be added.

#### Scenario: Import succeeds
- **WHEN** the application starts
- **THEN** `from cachetools import TTLCache, cached` imports successfully without errors

### Requirement: Cache does not affect non-aggregate endpoints
Only the `/api/alltime` endpoint SHALL use the TTL cache. Time-series endpoints (`/api/hourly`, `/api/daily`, `/api/latency`, `/api/cumulative`) SHALL NOT be cached because their results change frequently based on query parameters and new incoming data.

#### Scenario: Hourly data is always fresh
- **WHEN** `/api/hourly?days=1` is called multiple times within 60 seconds while new usage data is being logged
- **THEN** each call returns the latest data including newly logged entries
