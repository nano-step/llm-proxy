import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("litellm.bot_commander")

_ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_ENV_FILE):
    for _line in open(_ENV_FILE):
        _m = re.match(r'^([^#=]+)=(.*)', _line.strip())
        if _m and not os.environ.get(_m.group(1).strip()):
            os.environ[_m.group(1).strip()] = _m.group(2).strip()

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
ALLOWED_USER_IDS: set[int] = {
    int(x.strip())
    for x in os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "").split(",")
    if x.strip().lstrip("-").isdigit()
}

POLL_TIMEOUT = 30

ACTIONS_REQUIRING_CONFIRM = {"stop", "restart"}


def _api(method: str, **params) -> dict:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    payload = json.dumps(params).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=POLL_TIMEOUT + 5) as resp:
        return json.loads(resp.read())


def send_message(chat_id: int, html_text: str, reply_markup: dict = None) -> dict:
    kwargs = dict(chat_id=chat_id, text=html_text,
                  parse_mode="HTML", disable_web_page_preview=True)
    if reply_markup:
        kwargs["reply_markup"] = reply_markup
    try:
        return _api("sendMessage", **kwargs)
    except Exception as exc:
        logger.error("sendMessage failed: %s", exc)
        return {}


def edit_message(chat_id: int, message_id: int, html_text: str, reply_markup: dict = None) -> None:
    kwargs = dict(chat_id=chat_id, message_id=message_id, text=html_text,
                  parse_mode="HTML", disable_web_page_preview=True)
    if reply_markup:
        kwargs["reply_markup"] = reply_markup
    try:
        _api("editMessageText", **kwargs)
    except Exception as exc:
        logger.error("editMessageText failed: %s", exc)


def answer_callback(callback_query_id: str) -> None:
    try:
        _api("answerCallbackQuery", callback_query_id=callback_query_id)
    except Exception as exc:
        logger.error("answerCallbackQuery failed: %s", exc)


def pm2_action(action: str, process: str = "litellm-proxy") -> str:
    try:
        result = subprocess.run(
            ["pm2", action, process],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return f"✅ <code>pm2 {action} {process}</code> OK"
        return f"❌ Failed:\n<pre>{result.stderr.strip()[:300]}</pre>"
    except Exception as exc:
        return f"❌ Error: {exc}"


def pm2_status() -> str:
    try:
        result = subprocess.run(["pm2", "jlist"], capture_output=True, text=True, timeout=10)
        procs = json.loads(result.stdout)
        lines = []
        for p in procs:
            name = p.get("name", "?")
            status = p.get("pm2_env", {}).get("status", "?")
            restarts = p.get("pm2_env", {}).get("restart_time", 0)
            mem = p.get("monit", {}).get("memory", 0)
            mem_mb = f"{mem // 1024 // 1024}MB" if mem else "?"
            icon = "🟢" if status == "online" else ("🔴" if status == "stopped" else "🟡")
            lines.append(f"{icon} <b>{name}</b> — {status}, ↺{restarts}, {mem_mb}")
        return "\n".join(lines) if lines else "No processes found."
    except Exception as exc:
        return f"❌ Error: {exc}"


def main_menu_markup() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "📊 Status",   "callback_data": "action:status"},
                {"text": "🧪 Test",     "callback_data": "action:test"},
            ],
            [
                {"text": "🔄 Restart",  "callback_data": "confirm:restart"},
                {"text": "⛔ Stop",     "callback_data": "confirm:stop"},
                {"text": "▶️ Start",    "callback_data": "action:start_litellm"},
            ],
        ]
    }


def confirm_markup(action: str) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Yes, proceed", "callback_data": f"action:{action}"},
                {"text": "❌ Cancel",       "callback_data": "action:cancel"},
            ]
        ]
    }


def show_menu(chat_id: int) -> None:
    send_message(
        chat_id,
        "🤖 <b>LiteLLM Commander</b>\nWhat would you like to do?",
        reply_markup=main_menu_markup(),
    )


def execute_action(action: str, chat_id: int, message_id: int) -> None:
    if action == "status":
        edit_message(chat_id, message_id, f"<b>PM2 Status</b>\n\n{pm2_status()}",
                     reply_markup={"inline_keyboard": [[{"text": "↩ Back", "callback_data": "action:menu"}]]})

    elif action == "test":
        edit_message(chat_id, message_id,
                     "🧪 <b>Test notification</b>\n\nAll systems operational.\nWatchdog: active | Notifier: active",
                     reply_markup={"inline_keyboard": [[{"text": "↩ Back", "callback_data": "action:menu"}]]})

    elif action == "stop":
        edit_message(chat_id, message_id, "⏳ Stopping <code>litellm-proxy</code>…")
        result = pm2_action("stop")
        edit_message(chat_id, message_id, result,
                     reply_markup={"inline_keyboard": [[{"text": "↩ Menu", "callback_data": "action:menu"}]]})

    elif action == "start_litellm":
        edit_message(chat_id, message_id, "⏳ Starting <code>litellm-proxy</code>…")
        result = pm2_action("start")
        edit_message(chat_id, message_id, result,
                     reply_markup={"inline_keyboard": [[{"text": "↩ Menu", "callback_data": "action:menu"}]]})

    elif action == "restart":
        edit_message(chat_id, message_id, "⏳ Restarting <code>litellm-proxy</code>…")
        result = pm2_action("restart")
        edit_message(chat_id, message_id, result,
                     reply_markup={"inline_keyboard": [[{"text": "↩ Menu", "callback_data": "action:menu"}]]})

    elif action == "cancel":
        edit_message(chat_id, message_id, "❌ Cancelled.",
                     reply_markup={"inline_keyboard": [[{"text": "↩ Menu", "callback_data": "action:menu"}]]})

    elif action == "menu":
        edit_message(chat_id, message_id,
                     "🤖 <b>LiteLLM Commander</b>\nWhat would you like to do?",
                     reply_markup=main_menu_markup())


def process_update(update: dict) -> None:
    if "callback_query" in update:
        cq = update["callback_query"]
        user_id: int = cq.get("from", {}).get("id", 0)
        chat_id: int = cq.get("message", {}).get("chat", {}).get("id", 0)
        message_id: int = cq.get("message", {}).get("message_id", 0)
        data: str = cq.get("data", "")

        answer_callback(cq["id"])

        if user_id not in ALLOWED_USER_IDS:
            logger.warning("unauthorized callback user_id=%s data=%s", user_id, data)
            return

        logger.info("callback from user_id=%s: %s", user_id, data)

        if data.startswith("confirm:"):
            action = data.split(":", 1)[1]
            labels = {"stop": "⛔ Stop", "restart": "🔄 Restart"}
            edit_message(
                chat_id, message_id,
                f"⚠️ <b>Confirm: {labels.get(action, action)} litellm-proxy?</b>",
                reply_markup=confirm_markup(action),
            )
        elif data.startswith("action:"):
            action = data.split(":", 1)[1]
            execute_action(action, chat_id, message_id)
        return

    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return

    user_id: int = msg.get("from", {}).get("id", 0)
    chat_id: int = msg.get("chat", {}).get("id", 0)
    text: str = msg.get("text", "")

    if not text.startswith("/"):
        return

    if user_id not in ALLOWED_USER_IDS:
        logger.warning("unauthorized user_id=%s tried: %s", user_id, text)
        send_message(chat_id, "⛔ Unauthorized.")
        return

    logger.info("command from user_id=%s: %s", user_id, text)
    show_menu(chat_id)


def main() -> None:
    if not BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set — exiting")
        sys.exit(1)
    if not ALLOWED_USER_IDS:
        logger.error("TELEGRAM_ALLOWED_USER_IDS not set — exiting")
        sys.exit(1)

    logger.info("bot_commander started — allowed users: %s", ALLOWED_USER_IDS)
    send_message(int(CHAT_ID), "🤖 <b>LiteLLM Commander online</b>\nTap /start or send any command.",
                 reply_markup=main_menu_markup())

    offset = 0
    while True:
        try:
            data = _api("getUpdates", offset=offset, timeout=POLL_TIMEOUT)
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                process_update(update)
        except Exception as exc:
            logger.error("poll error: %s", exc)
            time.sleep(5)


if __name__ == "__main__":
    main()
