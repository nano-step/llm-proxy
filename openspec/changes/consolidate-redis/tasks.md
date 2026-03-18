## 1. Create Redis Docker Compose

- [x] 1.1 Create `/home/deployer/redis/` directory
- [x] 1.2 Create `/home/deployer/redis/redis.conf` with: maxmemory 256mb, allkeys-lru eviction, RDB save schedule (3600 1 300 100 60 10000), bind 0.0.0.0
- [x] 1.3 Create `/home/deployer/redis/docker-compose.yml` with redis:8-alpine, named volume `redis_data`, port `127.0.0.1:6379:6379`, healthcheck, restart always
- [x] 1.4 Start new Redis on temporary port (6399) to avoid conflict with host Redis, verify healthcheck passes

## 2. Migrate WordPress Data

- [x] 2.1 Dump host Redis data: `redis-cli --rdb /tmp/redis-dump.rdb`
- [x] 2.2 Stop host Redis: `sudo systemctl stop redis-server`
- [x] 2.3 Copy RDB dump into new Redis container volume
- [x] 2.4 Update docker-compose port to `127.0.0.1:6379:6379` and restart container
- [x] 2.5 Verify key counts: db0 (~344 keys) and db1 (~2086 keys) match source

## 3. Update Stock-Bot

- [x] 3.1 Patch `/home/deployer/stock-bot/services/price_cache.py`: add `db=int(os.getenv("REDIS_DB", "0"))` param to `redis.Redis()` constructor
- [x] 3.2 Update `/home/deployer/stock-bot/.env`: set `REDIS_PORT=6379` and add `REDIS_DB=2`
- [x] 3.3 Restart stock-bot: `sudo systemctl restart stock-bot`
- [x] 3.4 Verify stock-bot connects to new Redis db2: `redis-cli -n 2 KEYS "stock_price:*"` returns keys after bot activity

## 4. Decommission Old Redis Instances

- [x] 4.1 Disable host Redis: `sudo systemctl disable redis-server`
- [x] 4.2 Remove stock-redis container: `docker rm -f stock-redis`
- [x] 4.3 Verify only one Redis is running: `ss -tlnp | grep 6379` shows only the docker-compose container
- [x] 4.4 Verify port 6380 is no longer in use

## 5. End-to-End Verification

- [x] 5.1 WordPress blog.thnkandgrow.com: load homepage, verify Redis cache hits in db1
- [x] 5.2 WordPress meandyou.space: load homepage, verify Redis cache hits in db0 (502 is pre-existing php7.4-fpm issue, Redis db0 data intact: 343 keys)
- [x] 5.3 Stock-bot: trigger a price lookup, verify cache key appears in db2
- [x] 5.4 Restart test: `docker compose restart` in `/home/deployer/redis/`, verify all consumers reconnect
