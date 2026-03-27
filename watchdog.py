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

_ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_ENV_FILE):
    import re as _re
    for _line in open(_ENV_FILE):
        _m = _re.match(r'^([^#=]+)=(.*)', _line.strip())
        if _m and not os.environ.get(_m.group(1).strip()):
            os.environ[_m.group(1).strip()] = _m.group(2).strip()

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def send_telegram(html_text: str) -> None:
    if not BOT_TOKEN or not CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = json.dumps({
            "chat_id": CHAT_ID,
            "text": html_text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }).encode()
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except Exception as exc:
        logger.error("telegram send failed: %s", exc)


def stop_litellm(signal: dict) -> None:
    reason = signal.get("reason", "unknown")
    count = signal.get("count", "?")
    window = signal.get("window_sec", "?")

    logger.warning("emergency stop triggered: %s — %s errors in %ss", reason, count, window)

    send_telegram(
        f"⚠️ <b>LiteLLM stopping in 5s</b>\n"
        f"<b>Reason:</b> {reason}\n"
        f"<b>Burst:</b> {count} errors in {window}s\n"
        f"Executing <code>pm2 stop litellm-proxy</code>…"
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
                f"To resume: <code>pm2 start litellm-proxy</code>"
            )
        else:
            err = result.stderr.strip()
            logger.error("pm2 stop failed: %s", err)
            send_telegram(f"❌ <b>pm2 stop failed</b>\n<pre>{err}</pre>")
    except Exception as exc:
        logger.error("pm2 stop error: %s", exc)
        send_telegram(f"❌ <b>pm2 stop error</b>\n<pre>{exc}</pre>")


def main() -> None:
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
