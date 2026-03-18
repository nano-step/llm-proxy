#!/bin/bash
set -e
cd "$(dirname "$0")"

# Step 1: Refresh token + write config
python3 -c "
from proxy import fetch_token, write_config
td = fetch_token()
write_config(td)
import time
print(f'[token] OK, expires {time.strftime(\"%H:%M:%S\", time.localtime(td[\"expires_at\"]))}', flush=True)
"

# Step 2: Kill ALL litellm processes (not just the one on port 4000)
pkill -f "litellm --config" 2>/dev/null || true
sleep 3

# Step 3: Restart systemd service (single manager)
systemctl --user restart litellm-proxy.service
echo "[restart] litellm-proxy.service restarted"
