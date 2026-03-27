#!/usr/bin/env python3
"""LiteLLM proxy wrapper — refreshes GitLab OIDC token, writes config, runs LiteLLM."""
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request

import yaml

GITLAB_PAT = os.environ["GITLAB_PAT"]
GITLAB_INSTANCE = os.environ.get("GITLAB_INSTANCE", "https://gitlab.com")
AI_GATEWAY = os.environ.get("AI_GATEWAY", "https://cloud.gitlab.com/ai/v1/proxy/anthropic")
PORT = int(os.environ.get("LITELLM_PORT", "4000"))
MASTER_KEY = os.environ["LITELLM_MASTER_KEY"]
REFRESH_SEC = 2700

MODELS = [
    ("gitlab/claude-sonnet-4-6", "anthropic/claude-sonnet-4-6"),
    ("gitlab/claude-opus-4-6", "anthropic/claude-opus-4-6"),
    ("gitlab/claude-sonnet-4-5", "anthropic/claude-sonnet-4-5-20250929"),
    ("gitlab/claude-haiku-4-5", "anthropic/claude-haiku-4-5-20251001"),
]

COPILOT_MODELS = []

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "litellm_config.yaml")


def fetch_token():
    url = f"{GITLAB_INSTANCE}/api/v4/ai/third_party_agents/direct_access"
    body = json.dumps({"feature_flags": {
        "duo_agent_platform_agentic_chat": True,
        "duo_agent_platform": True,
    }}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "PRIVATE-TOKEN": GITLAB_PAT,
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def write_config(token_data):
    # NOTE: Do NOT write Authorization/token values to disk.
    # Token injection happens at runtime via gitlab_token_callback.

    gitlab_models = [{
        "model_name": name,
        "litellm_params": {
            "model": model,
            "api_base": AI_GATEWAY,
            "api_key": "gitlab-oidc",
        },
    } for name, model in MODELS]

    copilot_models = [{
        "model_name": name,
        "litellm_params": {
            "model": model,
        },
    } for name, model in COPILOT_MODELS]

    config = {
        "model_list": gitlab_models + copilot_models,
        "general_settings": {"master_key": MASTER_KEY},
        "litellm_settings": {
            "callbacks": [
                "gitlab_token_callback.proxy_handler_instance",
                "secret_guardrail.guardrail_instance",
                "telegram_notifier.notifier_instance",
            ],
        },
    }
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False)


def refresh_loop():
    while True:
        time.sleep(REFRESH_SEC)
        try:
            td = fetch_token()
            write_config(td)
            print("[token] refreshed successfully", flush=True)
        except Exception as e:
            print(f"[token] refresh error: {e}", flush=True)


def kill_stale_port():
    """Kill orphaned processes from a previous crash that still hold our port."""
    import re
    try:
        out = subprocess.check_output(["ss", "-tlnp"], text=True)
        for line in out.splitlines():
            if f":{PORT} " in line or f":{PORT}" in line:
                m = re.search(r"pid=(\d+)", line)
                if m:
                    pid = int(m.group(1))
                    if pid != os.getpid():
                        print(f"[cleanup] killing stale pid {pid} on port {PORT}", flush=True)
                        os.kill(pid, signal.SIGKILL)
                        time.sleep(2)
    except Exception as e:
        print(f"[cleanup] warning: {e}", flush=True)


def start_litellm():
    litellm_bin = os.path.expanduser("~/.local/bin/litellm")
    cmd = [litellm_bin, "--config", CONFIG_PATH, "--port", str(PORT), "--num_workers", "1"]
    proc = subprocess.Popen(cmd, preexec_fn=os.setsid)
    return proc


def main():
    kill_stale_port()

    print("[startup] fetching GitLab OIDC token...", flush=True)
    td = fetch_token()
    write_config(td)
    print("[startup] token OK", flush=True)

    threading.Thread(target=refresh_loop, daemon=True).start()

    proc = start_litellm()
    print(f"[startup] LiteLLM starting on port {PORT}", flush=True)

    for i in range(30):
        time.sleep(1)
        try:
            test_conn = urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health/liveliness", timeout=2)
            test_conn.read()
            test_conn.close()
            print(f"[startup] LiteLLM ready after {i+1}s", flush=True)
            break
        except Exception:
            pass
    else:
        print("[startup] WARNING: LiteLLM not ready after 30s", flush=True)

    def shutdown(*_):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, OSError):
            proc.terminate()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    proc.wait()


if __name__ == "__main__":
    main()
