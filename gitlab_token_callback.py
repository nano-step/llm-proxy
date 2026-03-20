"""GitLab OIDC token callback — inline token refresh via async_pre_call_hook.

Proactively refreshes tokens before expiry (300s skew) and reactively
invalidates on 401 so the next request auto-heals with a fresh token.
"""
import asyncio
import json
import logging
import os
import time
import urllib.request

from litellm.integrations.custom_logger import CustomLogger

logger = logging.getLogger("litellm.gitlab_token")

GITLAB_PAT = os.environ.get("GITLAB_PAT", "")
GITLAB_INSTANCE = os.environ.get("GITLAB_INSTANCE", "https://gitlab.com")
TOKEN_ENDPOINT = f"{GITLAB_INSTANCE}/api/v4/ai/third_party_agents/direct_access"
REFRESH_SKEW_SEC = 300


class GitLabTokenManager:

    def __init__(self):
        self._token: str = ""
        self._headers: dict = {}
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def is_valid(self) -> bool:
        return bool(self._token) and time.time() < self._expires_at

    @property
    def needs_refresh(self) -> bool:
        return time.time() >= (self._expires_at - REFRESH_SKEW_SEC)

    def invalidate(self):
        """Force next get_headers() to fetch a fresh token."""
        self._expires_at = 0.0
        logger.info("[gitlab-token] invalidated — next call will refresh")

    def _fetch_token_sync(self) -> dict:
        body = json.dumps({
            "feature_flags": {
                "duo_agent_platform_agentic_chat": True,
                "duo_agent_platform": True,
            }
        }).encode()
        req = urllib.request.Request(
            TOKEN_ENDPOINT,
            data=body,
            headers={
                "PRIVATE-TOKEN": GITLAB_PAT,
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())

    async def get_headers(self) -> dict:
        if not self.needs_refresh:
            return self._headers

        async with self._lock:
            if not self.needs_refresh:
                return self._headers

            try:
                loop = asyncio.get_event_loop()
                token_data = await loop.run_in_executor(None, self._fetch_token_sync)

                self._token = token_data["token"]
                self._expires_at = token_data["expires_at"]
                self._headers = {
                    k: v for k, v in token_data["headers"].items() if k != "x-api-key"
                }
                self._headers["Authorization"] = f"Bearer {self._token}"

                logger.info(
                    "[gitlab-token] refreshed, expires %s",
                    time.strftime("%H:%M:%S", time.localtime(self._expires_at)),
                )
            except Exception as e:
                if self.is_valid:
                    logger.warning(
                        "[gitlab-token] refresh failed, using cached token (expires %s): %s",
                        time.strftime("%H:%M:%S", time.localtime(self._expires_at)),
                        e,
                    )
                else:
                    logger.error("[gitlab-token] refresh failed and no valid cached token: %s", e)
                    raise

        return self._headers


class GitLabOIDCCallback(CustomLogger):

    def __init__(self):
        self.token_manager = GitLabTokenManager()

    async def async_pre_call_hook(
        self,
        user_api_key_dict,
        cache,
        data: dict,
        call_type,
    ):
        headers = await self.token_manager.get_headers()

        if "extra_headers" not in data or data["extra_headers"] is None:
            data["extra_headers"] = {}
        data["extra_headers"].update(headers)

        return data

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        """On 401/auth failure, invalidate token so next request gets a fresh one."""
        try:
            status = getattr(response_obj, "status_code", None)
            error_str = str(response_obj) if response_obj else ""

            is_auth_failure = (
                status == 401
                or "401" in error_str
                or "Unauthorized" in error_str
                or "AuthenticationError" in error_str
                or "Forbidden by auth provider" in error_str
            )

            if is_auth_failure:
                self.token_manager.invalidate()
        except Exception as e:
            logger.warning("[gitlab-token] error in failure handler: %s", e)


proxy_handler_instance = GitLabOIDCCallback()
