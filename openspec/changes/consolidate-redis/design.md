## Context

The server (`sudox-01`) runs 3 Redis instances under different management layers:

1. **Host Redis** (systemd `redis-server`, v8.4.0) — `127.0.0.1:6379` — serves 2 WordPress sites using db0 (meandyou.space, 344 keys) and db1 (blog.thnkandgrow.com, 2086 keys). RDB snapshots enabled, no AOF, no auth, no maxmemory.
2. **stock-redis** (standalone `docker run`, v7.4.8) — `127.0.0.1:6380` — serves stock-bot price cache (10 TTL keys). Uses anonymous volume, `--save 60 1`.
3. **n8n_redis** (Docker Swarm service, v8.4.0) — Docker-internal only — serves N8N Bull job queues (345 keys). Named volume `n8n_redis_storage`.

N8N's Redis is excluded from consolidation because Swarm services run on overlay networks that cannot join external bridge networks. Cross-stack Redis sharing would require either hardcoded Docker bridge IPs (fragile) or migrating N8N out of Swarm (scope creep).

## Goals / Non-Goals

**Goals:**
- Single Redis instance (docker-compose) replacing host systemd Redis and stock-redis
- Database-level isolation per consumer (db0-db2)
- Persistence (RDB snapshots) for WordPress data
- Memory limit to prevent runaway usage
- Zero data loss for WordPress keys during migration

**Non-Goals:**
- Consolidating N8N's Swarm Redis (overlay network constraint)
- Redis Cluster or Sentinel (single-server, no HA needed)
- Redis auth/ACLs (localhost-only access, same trust model as current)
- Changing WordPress Redis plugin config beyond host/port/db

## Decisions

### 1. Docker Compose standalone

**Choice**: Plain `docker compose` in `/home/deployer/redis/`.

**Rationale**: Simple, declarative, `restart: always` for auto-recovery. Port published to `127.0.0.1:6379` only — same as current host Redis. WordPress and stock-bot connect via localhost, no config changes needed for WordPress.

### 2. Database assignment

| DB | Consumer | Rationale |
|----|----------|-----------|
| 0  | meandyou.space WP | Existing db0, no migration friction |
| 1  | blog.thnkandgrow.com WP | Existing db1, no migration friction |
| 2  | stock-bot | New assignment, cache-only (no migration needed) |

**Rationale**: WordPress sites keep their current DB numbers to avoid key prefix collisions. Stock-bot gets a new number since its data is transient.

### 3. Data migration approach

**Choice**: Use `redis-cli --rdb` to dump host Redis, copy RDB into new container volume, restart to load.

**Sequence**:
1. Start new Redis container on a temporary port (e.g. 6399) to avoid conflict
2. Stop host Redis and stock-redis
3. Copy host Redis RDB dump into new container volume
4. Restart new Redis container on port 6379 (loads dump)
5. Verify key counts match

### 4. Redis configuration

- Image: `redis:8-alpine`
- maxmemory: `256mb` with `allkeys-lru` eviction
- RDB: `save 3600 1 300 100 60 10000` (matches current host config)
- bind: `0.0.0.0` (container-internal, port only exposed to `127.0.0.1` on host)
- Port mapping: `127.0.0.1:6379:6379`

## Risks / Trade-offs

- **[WordPress cache miss during switchover]** → ~30s of uncached DB queries. WordPress auto-rebuilds cache.
- **[Single point of failure]** → Same as current (single server). Docker restart policy `always` ensures auto-recovery.
- **[stock-bot code change needed]** → `price_cache.py` doesn't read `REDIS_DB` env var. Requires small code patch to pass `db` param to `redis.Redis()`. Low risk — 1-line change.
- **[N8N left on separate Redis]** → Accepted trade-off. N8N's 345 transient keys don't justify the Swarm networking complexity.
