import collections
import json
import logging
import os
import subprocess
import sys
import time
import urllib.request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("litellm.watchdog")

SIGNAL_FILE = "/tmp/litellm-emergency-stop.json"
POLL_INTERVAL = 2

DB_CHECK_INTERVAL = 12
DB_FAIL_WINDOW_SEC = 60
DB_FAIL_THRESHOLD = 5
DB_RESTART_COOLDOWN = 120
DB_MAX_RESTARTS = 3
DB_HEALTHY_RESET_SEC = 600

_ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_ENV_FILE):
    import re as _re
    for _line in open(_ENV_FILE):
        _m = _re.match(r'^([^#=]+)=(.*)', _line.strip())
        if _m and not os.environ.get(_m.group(1).strip()):
            os.environ[_m.group(1).strip()] = _m.group(2).strip()

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

_last_restart_count = {}
_mem_alert_sent_at: float = 0.0
MEM_ALERT_THRESHOLD_MB = 1024
MEM_ALERT_COOLDOWN_SEC = 300

def init_restart_count() -> None:
    global _last_restart_count
    try:
        result = subprocess.run(
            ["pm2", "jlist"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return
        processes = json.loads(result.stdout)
        for p in processes:
            if p.get("name") == "litellm-proxy":
                _last_restart_count["litellm-proxy"] = p.get("restart_time", 0)
                break
    except Exception:
        pass

QUICK_ACTIONS_MARKUP = {
    "inline_keyboard": [[
        {"text": "▶️ Start",   "callback_data": "action:start_litellm"},
        {"text": "🔄 Restart", "callback_data": "confirm:restart"},
        {"text": "⛔ Stop",    "callback_data": "confirm:stop"},
        {"text": "📊 Status",  "callback_data": "action:status"},
    ]]
}


def send_telegram(html_text: str, with_actions: bool = False) -> None:
    if not BOT_TOKEN or not CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        body: dict = {
            "chat_id": CHAT_ID,
            "text": html_text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if with_actions:
            body["reply_markup"] = QUICK_ACTIONS_MARKUP
        payload = json.dumps(body).encode()
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except Exception as exc:
        logger.error("telegram send failed: %s", exc)


def check_restarts() -> None:
    global _last_restart_count
    try:
        result = subprocess.run(
            ["pm2", "jlist"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return
        processes = json.loads(result.stdout)
        for p in processes:
            if p.get("name") == "litellm-proxy":
                current_restarts = p.get("restart_time", 0)
                prev = _last_restart_count.get("litellm-proxy", 0)
                if prev > 0 and current_restarts > prev:
                    mem_bytes = (p.get("monit") or {}).get("memory", 0)
                    mem_mb = mem_bytes / (1024 * 1024)
                    status = p.get("pm2_env", {}).get("status", "?")
                    send_telegram(
                        f"🔄 <b>LiteLLM restarted</b>\n"
                        f"<b>Restart #:</b> {current_restarts}\n"
                        f"<b>Status:</b> {status}\n"
                        f"<b>Memory now:</b> {mem_mb:.0f} MB",
                        with_actions=True,
                    )
                _last_restart_count["litellm-proxy"] = current_restarts
                break
    except Exception as exc:
        logger.debug("restart check error: %s", exc)


def check_memory() -> None:
    global _mem_alert_sent_at
    try:
        result = subprocess.run(
            ["pm2", "jlist"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return
        processes = json.loads(result.stdout)
        for p in processes:
            if p.get("name") == "litellm-proxy":
                mem_bytes = (p.get("monit") or {}).get("memory", 0)
                mem_mb = mem_bytes / (1024 * 1024)
                if mem_mb >= MEM_ALERT_THRESHOLD_MB:
                    now = time.time()
                    if now - _mem_alert_sent_at >= MEM_ALERT_COOLDOWN_SEC:
                        _mem_alert_sent_at = now
                        logger.warning("litellm-proxy memory high: %.0fMB", mem_mb)
                        send_telegram(
                            f"🧠 <b>LiteLLM high memory</b>\n"
                            f"<b>Usage:</b> {mem_mb:.0f} MB / {MEM_ALERT_THRESHOLD_MB} MB threshold\n"
                            f"<b>Risk:</b> OOM crash imminent",
                            with_actions=True,
                        )
                break
    except Exception as exc:
        logger.debug("memory check error: %s", exc)


def stop_litellm(signal: dict) -> None:
    reason = signal.get("reason", "unknown")
    count = signal.get("count", "?")
    window = signal.get("window_sec", "?")

    logger.warning("emergency stop triggered: %s — %s errors in %ss", reason, count, window)

    send_telegram(
        f"⚠️ <b>LiteLLM stopping in 5s</b>\n"
        f"<b>Reason:</b> {reason}\n"
        f"<b>Burst:</b> {count} errors in {window}s\n"
        f"Executing <code>pm2 stop litellm-proxy</code>…",
        with_actions=True,
    )
    time.sleep(5)

    try:
        result = subprocess.run(
            ["pm2", "stop", "litellm-proxy"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            logger.info("pm2 stop litellm-proxy: OK")
            send_telegram(
                f"🔴 <b>LiteLLM STOPPED</b>\n"
                f"<b>Reason:</b> {reason}\n"
                f"\n"
                f"To resume: <code>pm2 start litellm-proxy</code>",
                with_actions=True,
            )
        else:
            err = result.stderr.strip()
            logger.error("pm2 stop failed: %s", err)
            send_telegram(f"❌ <b>pm2 stop failed</b>\n<pre>{err}</pre>")
    except Exception as exc:
        logger.error("pm2 stop error: %s", exc)
        send_telegram(f"❌ <b>pm2 stop error</b>\n<pre>{exc}</pre>")


_db_fail_timestamps: collections.deque = collections.deque()
_db_restart_count: int = 0
_db_last_check_at: float = 0.0
_db_cooldown_until: float = 0.0
_db_healthy_since: float = 0.0
_db_shutdown: bool = False


def _litellm_master_key() -> str:
    return os.environ.get("LITELLM_MASTER_KEY", "")


def _litellm_port() -> str:
    return os.environ.get("LITELLM_PORT", "4000")


def _fetch_db_status() -> str:
    url = f"http://127.0.0.1:{_litellm_port()}/health/readiness"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {_litellm_master_key()}"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read())
    return data.get("db", "unknown")


def _restart_litellm_proxy(reason: str) -> bool:
    try:
        result = subprocess.run(
            ["pm2", "restart", "litellm-proxy"],
            capture_output=True, text=True, timeout=20,
        )
        if result.returncode == 0:
            logger.warning("pm2 restart litellm-proxy: OK (%s)", reason)
            return True
        logger.error("pm2 restart failed: %s", result.stderr.strip())
        return False
    except Exception as exc:
        logger.error("pm2 restart error: %s", exc)
        return False


def _stop_litellm_proxy(reason: str) -> None:
    try:
        result = subprocess.run(
            ["pm2", "stop", "litellm-proxy"],
            capture_output=True, text=True, timeout=20,
        )
        if result.returncode == 0:
            logger.warning("pm2 stop litellm-proxy: OK (%s)", reason)
        else:
            logger.error("pm2 stop failed: %s", result.stderr.strip())
    except Exception as exc:
        logger.error("pm2 stop error: %s", exc)


def check_db_health() -> None:
    global _db_fail_timestamps, _db_restart_count, _db_last_check_at
    global _db_cooldown_until, _db_healthy_since, _db_shutdown

    if _db_shutdown:
        return

    now = time.time()

    if now < _db_cooldown_until:
        return

    if now - _db_last_check_at < DB_CHECK_INTERVAL:
        return

    _db_last_check_at = now

    try:
        db_status = _fetch_db_status()
    except Exception as exc:
        logger.warning("db health fetch failed: %s", exc)
        return

    if db_status == "connected":
        if _db_healthy_since == 0.0:
            _db_healthy_since = now
        elif _db_restart_count > 0 and (now - _db_healthy_since) >= DB_HEALTHY_RESET_SEC:
            logger.info("db healthy for %ds — resetting restart counter", DB_HEALTHY_RESET_SEC)
            send_telegram("✅ <b>LiteLLM DB stable</b>\nHealthy 10 min straight — restart counter reset to 0.")
            _db_restart_count = 0
            _db_fail_timestamps.clear()
        return

    _db_healthy_since = 0.0
    _db_fail_timestamps.append(now)

    cutoff = now - DB_FAIL_WINDOW_SEC
    while _db_fail_timestamps and _db_fail_timestamps[0] < cutoff:
        _db_fail_timestamps.popleft()

    window_count = len(_db_fail_timestamps)
    logger.warning("db status=%s  failures-in-window=%d/%d", db_status, window_count, DB_FAIL_THRESHOLD)

    if window_count < DB_FAIL_THRESHOLD:
        return

    _db_fail_timestamps.clear()

    if _db_restart_count >= DB_MAX_RESTARTS:
        logger.error("db still unhealthy after %d restarts — shutting down", DB_MAX_RESTARTS)
        send_telegram(
            f"🚨 <b>LiteLLM DB unrecoverable — SHUTTING DOWN</b>\n"
            f"<b>Restarts attempted:</b> {DB_MAX_RESTARTS}\n"
            f"<b>DB status:</b> {db_status}\n"
            f"Manual intervention required.",
            with_actions=True,
        )
        _stop_litellm_proxy("db unrecoverable after max restarts")
        _db_shutdown = True
        return

    _db_restart_count += 1
    logger.warning("db unhealthy — triggering restart %d/%d", _db_restart_count, DB_MAX_RESTARTS)
    send_telegram(
        f"⚠️ <b>LiteLLM DB disconnected — restarting</b>\n"
        f"<b>DB status:</b> {db_status}\n"
        f"<b>Failures in last 60s:</b> {DB_FAIL_THRESHOLD}\n"
        f"<b>Restart:</b> {_db_restart_count}/{DB_MAX_RESTARTS}",
        with_actions=True,
    )
    _restart_litellm_proxy(f"db={db_status} restart {_db_restart_count}/{DB_MAX_RESTARTS}")
    _db_cooldown_until = time.time() + DB_RESTART_COOLDOWN


def main() -> None:
    global _last_restart_count
    init_restart_count()
    logger.info("watchdog started — polling %s every %ss", SIGNAL_FILE, POLL_INTERVAL)
    send_telegram("👁 <b>LiteLLM watchdog started</b>")

    while True:
        try:
            if os.path.exists(SIGNAL_FILE):
                try:
                    with open(SIGNAL_FILE) as f:
                        signal = json.load(f)
                except Exception:
                    signal = {}
                try:
                    os.remove(SIGNAL_FILE)
                except Exception:
                    pass
                stop_litellm(signal)
            check_restarts()
            check_memory()
            check_db_health()
        except Exception as exc:
            logger.error("watchdog loop error: %s", exc)

        time.sleep(POLL_INTERVAL)


def run_test() -> None:
    print("Sending test message sequence to Telegram...")
    send_telegram("🧪 <b>LiteLLM Monitor — Test</b>\n\nSimulating error burst detection…")
    time.sleep(2)
    send_telegram(
        "⚠️ <b>LiteLLM stopping in 5s</b>\n"
        "<b>Reason:</b> AuthenticationError (401) [TEST]\n"
        "<b>Burst:</b> 10 errors in 10s\n"
        "Executing <code>pm2 stop litellm-proxy</code>…"
    )
    time.sleep(2)
    send_telegram(
        "🔴 <b>LiteLLM STOPPED</b> [TEST — no actual stop]\n"
        "<b>Reason:</b> AuthenticationError (401)\n"
        "\n"
        "To resume: <code>pm2 start litellm-proxy</code>"
    )
    print("Done — check your Telegram.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        run_test()
    else:
        main()
