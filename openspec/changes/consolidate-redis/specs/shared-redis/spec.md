## ADDED Requirements

### Requirement: Single Redis docker-compose deployment
The system SHALL provide a single Redis instance via docker-compose at `/home/deployer/redis/docker-compose.yml` using `redis:8-alpine` image with a named volume for data persistence.

#### Scenario: Redis container starts and is healthy
- **WHEN** `docker compose up -d` is run in `/home/deployer/redis/`
- **THEN** a Redis container starts on port 6379, passes healthcheck (`redis-cli ping` returns PONG), and is accessible from `127.0.0.1:6379`

#### Scenario: Redis survives host reboot
- **WHEN** the host reboots
- **THEN** the Redis container auto-restarts (restart policy: `always`) and all persisted data is available

### Requirement: Database-level consumer isolation
The system SHALL isolate each consumer into a dedicated Redis database number: db0 for meandyou.space WordPress, db1 for blog.thnkandgrow.com WordPress, db2 for stock-bot.

#### Scenario: WordPress blog uses db1
- **WHEN** blog.thnkandgrow.com WordPress writes a cache key
- **THEN** the key is stored in Redis db1 with prefix `thnkandgrow_`

#### Scenario: Stock-bot uses db2
- **WHEN** stock-bot writes a price cache entry
- **THEN** the key is stored in Redis db2 with prefix `stock_price:`

#### Scenario: Consumer databases are isolated
- **WHEN** stock-bot flushes its database (`FLUSHDB` on db2)
- **THEN** WordPress keys in db0 and db1 are unaffected

### Requirement: Memory limit and eviction policy
The system SHALL configure Redis with `maxmemory 256mb` and `maxmemory-policy allkeys-lru` to prevent unbounded memory growth.

#### Scenario: Memory limit enforced
- **WHEN** Redis memory usage approaches 256MB
- **THEN** Redis evicts least-recently-used keys to stay within the limit

### Requirement: Data migration from host Redis
WordPress data (db0 and db1) from the host systemd Redis SHALL be migrated to the new Redis container with zero key loss.

#### Scenario: WordPress keys preserved after migration
- **WHEN** the new Redis container is running with migrated data
- **THEN** `DBSIZE` for db0 and db1 matches the counts from the old host Redis (±5 keys for TTL expiry)

### Requirement: Old Redis instances removed
After migration and verification, the host systemd `redis-server` SHALL be stopped and disabled, and the `stock-redis` Docker container SHALL be removed.

#### Scenario: No duplicate Redis processes
- **WHEN** consolidation is complete
- **THEN** the host systemd redis-server is disabled, the stock-redis container is removed, port 6380 is free, and port 6379 is served exclusively by the docker-compose container

### Requirement: Stock-bot database selection via environment
The stock-bot `price_cache.py` SHALL read `REDIS_DB` environment variable to select the Redis database number, defaulting to 0 if unset.

#### Scenario: Stock-bot connects to db2
- **WHEN** `REDIS_DB=2` is set in stock-bot `.env` and `REDIS_PORT=6379`
- **THEN** stock-bot price cache reads/writes keys in Redis db2
