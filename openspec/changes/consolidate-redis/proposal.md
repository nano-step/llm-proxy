## Why

The server runs 3 separate Redis instances (host systemd Redis 8.4.0 on :6379, stock-redis Docker 7.4.8 on :6380, and n8n_redis Docker Swarm 8.4.0 internal) serving WordPress, stock-bot, and N8N respectively. This wastes ~50-100MB RAM and uses inconsistent management approaches (systemd, `docker run`, Swarm service). Consolidating the host Redis and stock-redis into a single docker-compose service simplifies operations. N8N's Swarm Redis is left as-is due to Swarm overlay networking constraints.

## What Changes

- **New**: Single Redis 8-alpine docker-compose deployment at `/home/deployer/redis/`
- **Remove**: Host systemd `redis-server` service (disable and stop)
- **Remove**: Standalone `stock-redis` Docker container
- **Modify**: stock-bot `.env` — switch from `:6380` to `:6379` with `REDIS_DB=2`
- **Modify**: stock-bot `price_cache.py` — add `REDIS_DB` env var support
- **No change**: N8N keeps its own Swarm Redis (overlay network isolation prevents cross-stack sharing)
- **No change**: WordPress configs (host/port/db unchanged — `127.0.0.1:6379`, db0 and db1)

## Capabilities

### New Capabilities
- `shared-redis`: Single Redis docker-compose deployment with database-level isolation, persistence, and healthcheck for WordPress and stock-bot consumers

### Modified Capabilities

## Impact

- **Services affected**: WordPress (2 sites), stock-bot
- **Not affected**: N8N (keeps its own Swarm Redis)
- **Downtime**: Brief Redis unavailability (~30s) during switchover; WordPress loses cache temporarily, stock-bot cache rebuilds on TTL
- **Data migration**: WordPress db0 + db1 must be migrated (2430 keys total); stock-bot data is transient (no migration needed)
- **Dependencies**: Docker, docker-compose
- **Files modified**: `/home/deployer/stock-bot/.env`, `/home/deployer/stock-bot/services/price_cache.py`
- **Systemd**: `redis-server.service` disabled
