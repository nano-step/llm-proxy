"""Telegram notification callback for LiteLLM.

Sends Telegram alerts on LLM call failures (rate limit, auth, quota, 5xx).
Registered as a CustomLogger callback alongside gitlab_token_callback and secret_guardrail.

Setup:
    Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in the environment (.env).
    If either is unset, the notifier is silently disabled.
"""
import asyncio
import collections
import json
import logging
import os
import time
import urllib.request
import urllib.error
from typing import Optional

import litellm
from litellm.integrations.custom_logger import CustomLogger

logger = logging.getLogger("litellm.telegram_notifier")

COOLDOWN_SECONDS = 60
_ALERT_CODES = {"429", "401", "402", "403"}

BURST_WINDOW_SEC = 10
BURST_THRESHOLD = 10
SIGNAL_FILE = "/tmp/litellm-emergency-stop.json"

_EXCEPTION_LABELS: list[tuple[type, str]] = [
    (litellm.RateLimitError,         "🚦 Rate Limit"),
    (litellm.AuthenticationError,    "🔑 Auth Failure"),
    (litellm.PermissionDeniedError,  "🔒 Permission Denied"),
    (litellm.BudgetExceededError,    "💳 Budget Exceeded"),
    (litellm.InternalServerError,    "💥 Provider 500"),
    (litellm.ServiceUnavailableError,"⚠️ Provider 503"),
    (litellm.BadGatewayError,        "⚠️ Provider 502"),
]


class TelegramNotifierCallback(CustomLogger):

    def __init__(self):
        super().__init__()
        self._bot_token: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self._chat_id: str = os.environ.get("TELEGRAM_CHAT_ID", "")
        self._cooldown: dict[str, float] = {}
        self._burst_timestamps: collections.deque = collections.deque()

        if self._bot_token and self._chat_id:
            self._send_telegram_sync("🟢 <b>LiteLLM proxy started</b>")
        else:
            logger.info("[telegram-notifier] disabled — TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")

    def _enabled(self) -> bool:
        return bool(self._bot_token and self._chat_id)

    def _make_fingerprint(self, error_class: str, error_code: str, model: str) -> str:
        return f"{error_class}:{error_code}:{model}"

    def _is_in_cooldown(self, fingerprint: str) -> bool:
        last = self._cooldown.get(fingerprint, 0.0)
        return (time.time() - last) < COOLDOWN_SECONDS

    def _mark_sent(self, fingerprint: str) -> None:
        self._cooldown[fingerprint] = time.time()

    def _send_telegram_sync(self, html_text: str) -> None:
        """Fire-and-forget HTTP POST to Telegram sendMessage. Never raises."""
        try:
            url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
            payload = json.dumps({
                "chat_id": self._chat_id,
                "text": html_text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }).encode()
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
        except Exception as exc:
            logger.error("[telegram-notifier] failed to send message: %s", exc)

    async def _send_telegram(self, html_text: str) -> None:
        """Async wrapper — runs sync HTTP call in executor to avoid blocking the event loop."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._send_telegram_sync, html_text)

    def _check_burst(self, error_class: str, error_code: str) -> bool:
        now = time.time()
        self._burst_timestamps.append(now)
        cutoff = now - BURST_WINDOW_SEC
        while self._burst_timestamps and self._burst_timestamps[0] < cutoff:
            self._burst_timestamps.popleft()
        if len(self._burst_timestamps) >= BURST_THRESHOLD:
            if not os.path.exists(SIGNAL_FILE):
                payload = {
                    "reason": f"{error_class} ({error_code})",
                    "count": len(self._burst_timestamps),
                    "window_sec": BURST_WINDOW_SEC,
                    "timestamp": now,
                }
                try:
                    with open(SIGNAL_FILE, "w") as f:
                        json.dump(payload, f)
                    logger.error("[telegram-notifier] burst threshold reached — wrote emergency stop signal")
                except Exception as exc:
                    logger.error("[telegram-notifier] failed to write signal file: %s", exc)
            return True
        return False

    def _classify(self, error_code: str, exception: object) -> Optional[str]:
        if error_code in _ALERT_CODES or (error_code.isdigit() and int(error_code) >= 500):
            labels = {"429": "🚦 Rate Limit", "401": "🔑 Auth Failure",
                      "402": "💳 Quota Exceeded", "403": "🔒 Permission Denied"}
            return labels.get(error_code, f"💥 Provider Error ({error_code})")

        for exc_type, label in _EXCEPTION_LABELS:
            if isinstance(exception, exc_type):
                return label

        return None

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        if not self._enabled():
            return

        try:
            slo: Optional[dict] = kwargs.get("standard_logging_object") or {}
            error_info: dict = slo.get("error_information") or {}
            exception = kwargs.get("exception")

            error_code: str = str(error_info.get("error_code") or getattr(exception, "status_code", "") or "")
            error_class: str = str(error_info.get("error_class") or (type(exception).__name__ if exception else ""))
            llm_provider: str = str(error_info.get("llm_provider") or getattr(exception, "llm_provider", "") or "")
            error_str: str = str(slo.get("error_str") or exception or "")
            model: str = str(slo.get("model") or kwargs.get("model") or "unknown")

            label = self._classify(error_code, exception)
            if label is None:
                return

            self._check_burst(error_class, error_code)

            fingerprint = self._make_fingerprint(error_class, error_code, model)
            if self._is_in_cooldown(fingerprint):
                return

            self._mark_sent(fingerprint)

            snippet = error_str[:300].strip()
            if len(error_str) > 300:
                snippet += "…"

            lines = [
                f"<b>{label}</b>",
                f"<b>Model:</b> <code>{model}</code>",
            ]
            if llm_provider:
                lines.append(f"<b>Provider:</b> {llm_provider}")
            if error_class:
                lines.append(f"<b>Class:</b> {error_class}")
            if snippet:
                lines.append(f"\n<pre>{snippet}</pre>")

            await self._send_telegram("\n".join(lines))

        except Exception as exc:
            logger.error("[telegram-notifier] error in failure handler: %s", exc)


notifier_instance = TelegramNotifierCallback()
