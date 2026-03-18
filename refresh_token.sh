#!/bin/bash
set -e
: "${GITLAB_PAT:?GITLAB_PAT must be set}"
RESP=$(curl -s -X POST "https://gitlab.com/api/v4/ai/third_party_agents/direct_access" \
  -H "PRIVATE-TOKEN: $GITLAB_PAT" \
  -H "Content-Type: application/json" \
  -d '{"feature_flags":{"duo_agent_platform_agentic_chat":true,"duo_agent_platform":true}}')

TOKEN=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")
HEADERS_JSON=$(echo "$RESP" | python3 -c "
import sys,json
d = json.load(sys.stdin)['headers']
d.pop('x-api-key', None)
print(json.dumps(d))
")
EXPIRES=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['expires_at'])")

echo "$TOKEN" > /home/deployer/litellm/.token
echo "$HEADERS_JSON" > /home/deployer/litellm/.headers
echo "$EXPIRES" > /home/deployer/litellm/.expires
echo "Token refreshed, expires at $(date -d @$EXPIRES)"
