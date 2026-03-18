#!/bin/bash
set -e
cd "$(dirname "$0")"
python3 -c "
from proxy import fetch_token, write_config
td = fetch_token()
write_config(td)
import time
print(f'[token] OK, expires {time.strftime(\"%H:%M:%S\", time.localtime(td[\"expires_at\"]))}', flush=True)
"

# Kill ALL litellm processes then restart via pm2
echo "[token] Restarting litellm-proxy..."
pkill -f "litellm --config" 2>/dev/null || true
sleep 5
pm2 restart litellm-proxy
echo "[token] Done"
