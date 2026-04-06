"""
Secret Guardrail — Comprehensive secret detection with REDACT-THEN-ALLOW behavior.

Decision policy:
  - ACCIDENTAL SECRETS (API keys, tokens, passwords, connection strings): REDACT → allow request
  - PROMPT INJECTION (attempts to extract/exfiltrate secrets): BLOCK → reject request
"""
import gc
import os
import re
import time
import json as _json
import unicodedata
import base64
import math
import urllib.parse
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from litellm.integrations.custom_guardrail import CustomGuardrail
from litellm.types.guardrails import GuardrailEventHooks

logger = __import__("logging").getLogger("litellm.secret_guardrail")


# ─────────────────────────────────────────────────────────────────────────────
# REDIS LOG RATE-LIMITER — suppress repeated REDACT warnings
# ─────────────────────────────────────────────────────────────────────────────

class _RedisRateLimiter:
    _TTL = 300

    def __init__(self, redis_url: str = "redis://127.0.0.1:6379/0"):
        self._redis = None
        self._redis_url = redis_url
        self._available = True

    def _ensure_client(self):
        if self._redis is not None:
            return
        try:
            import redis as _redis_mod
            self._redis = _redis_mod.Redis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
                retry_on_timeout=False,
            )
            self._redis.ping()
        except Exception:
            self._redis = None
            self._available = False

    def should_log(self, key: str) -> bool:
        if not self._available:
            return True
        self._ensure_client()
        if self._redis is None:
            return True
        try:
            return bool(self._redis.set(key, "1", ex=self._TTL, nx=True))
        except Exception:
            return True


_rate_limiter = _RedisRateLimiter(
    redis_url=os.environ.get("SCAN_CACHE_REDIS_URL", "redis://127.0.0.1:6379/0")
)

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1 — AI / LLM PROVIDER KEYS
# ─────────────────────────────────────────────────────────────────────────────

AI_PATTERNS = [
    # OpenAI (primary)
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "OpenAI API key"),
    (re.compile(r"sk-proj-[A-Za-z0-9_-]{20,}"), "OpenAI project API key"),
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), "Anthropic API key"),
    # LiteLLM master key
    (re.compile(r"sk-drZ[A-Za-z0-9_-]{30,}"), "LiteLLM master key"),
    (re.compile(r"sk-dr[A-Za-z0-9]{40}"), "LiteLLM master key"),
    # CLIProxyAPI
    (re.compile(r"ht44[A-Za-z0-9_-]{30,}"), "CLIProxyAPI key"),
    # Groq
    (re.compile(r"gsk_[A-Za-z0-9_-]{40,}"), "Groq API key"),
    # DeepSeek
    (re.compile(r"sk-[a-f0-9]{32}", re.I), "DeepSeek API key"),
    # Together AI
    (re.compile(r"toggl_[a-f0-9]{40}", re.I), "Together AI key"),
    (re.compile(r"sk-[a-f0-9]{40}", re.I), "Together AI vllm key"),
    # Replicate
    (re.compile(r"r8_[A-Za-z0-9_-]{40,}"), "Replicate API key"),
    # Fireworks AI
    (re.compile(r"fw_[A-Za-z0-9_-]{40,}"), "Fireworks AI key"),
    # HuggingFace
    (re.compile(r"hf_[A-Za-z0-9]{34}"), "HuggingFace token"),
    (re.compile(r"hf_[A-Za-z0-9]{76,}"), "HuggingFace inference endpoint token"),
    # Cohere
    (re.compile(r"(?i)cohere[_-]?api[_-]?key\s*[=:]\s*['\"]?[A-Za-z0-9_-]{30,}['\"]?"), "Cohere API key"),
    (re.compile(r"(?i)COHERE_API_KEY\s*[-=:]?\s*['\"]?sk-[a-zA-Z0-9_-]{30,}['\"]?"), "Cohere API key env"),
    # Mistral
    (re.compile(r"(?i)mistral[_-]?api[_-]?key\s*[=:]\s*['\"]?[A-Za-z0-9_-]{30,}['\"]?"), "Mistral API key"),
    # Perplexity
    (re.compile(r"(?i)pplx-[a-f0-9]{40}", re.I), "Perplexity API key"),
    # OpenRouter
    (re.compile(r"(?i)openrouter[_-]?api[_-]?key\s*[=:]\s*['\"]?sk-or-[a-zA-Z0-9_-]{30,}['\"]?"), "OpenRouter API key"),
    (re.compile(r"sk-or-[a-zA-Z0-9_-]{30,}"), "OpenRouter API key"),
    # Cerebras
    (re.compile(r"(?i)cerebras[_-]?api[_-]?key\s*[=:]\s*['\"]?[A-Za-z0-9_-]{30,}['\"]?"), "Cerebras API key"),
    (re.compile(r"cs_[a-zA-Z0-9_-]{40,}"), "Cerebras API key"),
    # xAI (Grok)
    (re.compile(r"(?i)xai[_-]?api[_-]?key\s*[=:]\s*['\"]?[A-Za-z0-9_-]{30,}['\"]?"), "xAI API key"),
    (re.compile(r"(?i)grok[_-]?api[_-]?key\s*[=:]\s*['\"]?[A-Za-z0-9_-]{30,}['\"]?"), "Grok API key"),
    # Vertex AI / GCP
    (re.compile(r"(?i)VERTEX_AI_API_KEY\s*[=:]\s*['\"]?[A-Za-z0-9_./-]{50,}['\"]?"), "Vertex AI API key"),
    # AWS Bedrock (uses AWS SDK — credentials come from env/IAM; still flag explicit keys)
    (re.compile(r"(?i)AWS_ACCESS_KEY_ID\s*[=:]\s*['\"]?AKIA[A-Z0-9]{16}['\"]?"), "AWS Access Key ID"),
    (re.compile(r"(?i)AWS_SECRET_ACCESS_KEY\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}['\"]?"), "AWS Secret Access Key"),
    # Azure OpenAI
    (re.compile(r"(?i)AZURE_OPENAI_API_KEY\s*[=:]\s*['\"]?[a-f0-9]{32,}['\"]?"), "Azure OpenAI API key"),
    (re.compile(r"(?i)AZURE_OPENAI_ENDPOINT\s*[=:]\s*['\"]?https://[^/]+\.openai\.azure\.com"), "Azure OpenAI Endpoint"),
    # Anyscale
    (re.compile(r"(?i)ANYSCALE_API_KEY\s*[=:]\s*['\"]?es_[A-Za-z0-9_-]{30,}['\"]?"), "Anyscale API key"),
    # Modal
    (re.compile(r"(?i)MODAL_API_TOKEN\s*[=:]\s*['\"]?[a-f0-9]{32,}['\"]?"), "Modal API token"),
    # Banana
    (re.compile(r"(?i)BANANA_API_KEY\s*[=:]\s*['\"]?[a-f0-9]{32,}['\"]?"), "Banana API key"),
    # Beam
    (re.compile(r"(?i)BEAM_CLIENT_ID\s*[=:]\s*['\"]?[a-f0-9]{32,}['\"]?"), "Beam client ID"),
    (re.compile(r"(?i)BEAM_CLIENT_SECRET\s*[=:]\s*['\"]?[a-f0-9]{32,}['\"]?"), "Beam client secret"),
    # Predictions (Replicate alternative)
    (re.compile(r"(?i)PREDICTIONS_API_KEY\s*[=:]\s*['\"]?[a-f0-9]{40,}['\"]?"), "Predictions API key"),
    # Stealth
    (re.compile(r"(?i)STEALTH_API_KEY\s*[=:]\s*['\"]?[a-zA-Z0-9_-]{30,}['\"]?"), "Stealth API key"),
    # OpenAI Generic
    (re.compile(r"(?i)OPENAI_API_KEY\s*[=:]\s*['\"]?sk-[a-zA-Z0-9_-]{20,}['\"]?"), "OpenAI API key env"),
    # Claude / Anthropic Generic
    (re.compile(r"(?i)ANTHROPIC_API_KEY\s*[=:]\s*['\"]?sk-ant-[a-zA-Z0-9_-]{20,}['\"]?"), "Anthropic API key env"),
    # Google Generative AI (Gemini)
    (re.compile(r"(?i)GOOGLE_API_KEY\s*[=:]\s*['\"]?[A-Za-z0-9_-]{30,}['\"]?"), "Google API key env"),
    # Mistral Generic
    (re.compile(r"(?i)MISTRAL_API_KEY\s*[=:]\s*['\"]?[A-Za-z0-9_-]{30,}['\"]?"), "Mistral API key env"),
    # Ollama (local, usually no key but flag anyway)
    (re.compile(r"(?i)OLLAMA_API_KEY\s*[=:]\s*['\"]?[a-zA-Z0-9_-]{10,}['\"]?"), "Ollama API key env"),
    # Lepton AI
    (re.compile(r"(?i)LEPTONAI_AUTH_TOKEN\s*[=:]\s*['\"]?[a-zA-Z0-9_-]{30,}['\"]?"), "Lepton AI token"),
    # Novita AI
    (re.compile(r"(?i)NOVITA_API_KEY\s*[=:]\s*['\"]?[a-f0-9]{32,}['\"]?"), "Novita AI key"),
    # Hyperbolic AI
    (re.compile(r"(?i)HYPERBOLIC_API_KEY\s*[=:]\s*['\"]?[a-f0-9]{32,}['\"]?"), "Hyperbolic AI key"),
    # Grok (xAI) Generic
    (re.compile(r"(?i)GROK_API_KEY\s*[=:]\s*['\"]?[a-zA-Z0-9_-]{30,}['\"]?"), "Grok API key env"),
    # AI21
    (re.compile(r"(?i)AI21_API_KEY\s*[=:]\s*['\"]?[a-zA-Z0-9_-]{30,}['\"]?"), "AI21 API key"),
    # Aleph Alpha
    (re.compile(r"(?i)ALEPH_ALPHA_API_KEY\s*[=:]\s*['\"]?[a-zA-Z0-9_-]{30,}['\"]?"), "Aleph Alpha API key"),
    # Vercel AI SDK
    (re.compile(r"(?i)VERCEL_AI_API_KEY\s*[=:]\s*['\"]?[a-zA-Z0-9_-]{30,}['\"]?"), "Vercel AI API key"),
]

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2 — MESSAGING / COMMUNICATION APIs
# ─────────────────────────────────────────────────────────────────────────────

MESSAGING_PATTERNS = [
    # Slack
    (re.compile(r"xox[baprs]-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{24,}"), "Slack OAuth token"),
    (re.compile(r"(?i)SLACK_BOT_TOKEN\s*[=:]\s*['\"]?xox[baprs]-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{24,}['\"]?"), "Slack bot token env"),
    (re.compile(r"(?i)SLACK_USER_TOKEN\s*[=:]\s*['\"]?xoxp-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{24,}['\"]?"), "Slack user token env"),
    (re.compile(r"https://hooks\.slack\.com/services/T[a-zA-Z0-9]+/B[a-zA-Z0-9]+/[a-zA-Z0-9]+"), "Slack webhook URL"),
    # Discord
    (re.compile(r"[A-Za-z0-9]{24,}\.[\w-]{6}\.[\w-]{11,}"), "Discord bot/user token"),
    (re.compile(r"(?i)DISCORD_BOT_TOKEN\s*[=:]\s*['\"]?[A-Za-z0-9]{24,}\.[\w-]{6}\.[\w-]{11,}['\"]?"), "Discord bot token env"),
    (re.compile(r"https://discord\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]{60,}"), "Discord webhook"),
    # Telegram
    (re.compile(r"[0-9]{8,10}:[A-Za-z0-9_-]{35}"), "Telegram bot token"),
    (re.compile(r"(?i)TELEGRAM_BOT_TOKEN\s*[=:]\s*['\"]?[0-9]{8,10}:[A-Za-z0-9_-]{35}['\"]?"), "Telegram bot token env"),
    # Twilio
    (re.compile(r"SK[a-f0-9]{32}", re.I), "Twilio API key"),
    (re.compile(r"AC[a-f0-9]{32}", re.I), "Twilio account SID"),
    (re.compile(r"(?i)TWILIO_ACCOUNT_SID\s*[=:]\s*['\"]?AC[a-f0-9]{32}['\"]?"), "Twilio account SID env"),
    (re.compile(r"(?i)TWILIO_AUTH_TOKEN\s*[=:]\s*['\"]?[a-f0-9]{32}['\"]?"), "Twilio auth token env"),
    # SendGrid
    (re.compile(r"SG\.[a-zA-Z0-9_-]{22}\.[a-zA-Z0-9_-]{43}"), "SendGrid API key"),
    (re.compile(r"(?i)SENDGRID_API_KEY\s*[=:]\s*['\"]?SG\.[a-zA-Z0-9_-]{22}\.[a-zA-Z0-9_-]{43}['\"]?"), "SendGrid API key env"),
    # Mailgun
    (re.compile(r"key-[a-f0-9]{32}"), "Mailgun API key"),
    (re.compile(r"(?i)MAILGUN_API_KEY\s*[=:]\s*['\"]?key-[a-f0-9]{32}['\"]?"), "Mailgun API key env"),
    (re.compile(r"https://api\.mailgun\.net/v3/"), "Mailgun API endpoint"),
    # Mailchimp
    (re.compile(r"[a-f0-9]{32}-us[0-9]{1,2}"), "Mailchimp API key"),
    (re.compile(r"(?i)MAILCHIMP_API_KEY\s*[=:]\s*['\"]?[a-f0-9]{32}-us[0-9]{1,2}['\"]?"), "Mailchimp API key env"),
    # WhatsApp (via Twilio)
    (re.compile(r"(?i)WHATSAPP_FROM\s*[=:]\s*['\"]?\+?[0-9]{10,15}['\"]?"), "WhatsApp from number"),
    # Zoom
    (re.compile(r"(?i)ZOOM_API_KEY\s*[=:]\s*['\"]?[A-Za-z0-9]{30,}['\"]?"), "Zoom API key"),
    (re.compile(r"(?i)ZOOM_API_SECRET\s*[=:]\s*['\"]?[A-Za-z0-9]{30,}['\"]?"), "Zoom API secret"),
    (re.compile(r"(?i)ZOOM_JWT_TOKEN\s*[=:]\s*['\"]?eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+['\"]?"), "Zoom JWT token"),
    # Microsoft Teams
    (re.compile(r"(?i)TEAMS_CLIENT_ID\s*[=:]\s*['\"]?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}['\"]?"), "Teams client ID"),
    (re.compile(r"(?i)TEAMS_CLIENT_SECRET\s*[=:]\s*['\"]?[A-Za-z0-9_-]{30,}['\"]?"), "Teams client secret"),
    # Gmail / Google Workspace
    (re.compile(r"(?i)GMAIL_CLIENT_ID\s*[=:]\s*['\"]?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}['\"]?"), "Gmail client ID"),
    (re.compile(r"(?i)GMAIL_CLIENT_SECRET\s*[=:]\s*['\"]?[A-Za-z0-9_-]{20,}['\"]?"), "Gmail client secret"),
    # Instagram Basic Display
    (re.compile(r"(?i)INSTAGRAM_ACCESS_TOKEN\s*[=:]\s*['\"]?[A-Za-z0-9_-]{50,}['\"]?"), "Instagram access token"),
    # Twitter / X
    (re.compile(r"(?i)TWITTER_API_KEY\s*[=:]\s*['\"]?[A-Za-z0-9_-]{25,}['\"]?"), "Twitter API key"),
    (re.compile(r"(?i)TWITTER_API_SECRET\s*[=:]\s*['\"]?[A-Za-z0-9_-]{45,}['\"]?"), "Twitter API secret"),
    (re.compile(r"(?i)TWITTER_BEARER_TOKEN\s*[=:]\s*['\"]?A{2}[A-Za-z0-9_-]{80,}['\"]?"), "Twitter bearer token"),
    # LINE Messaging API
    (re.compile(r"(?i)LINE_CHANNEL_ACCESS_TOKEN\s*[=:]\s*['\"]?[A-Za-z0-9_-]{50,}['\"]?"), "LINE channel access token"),
    # WeChat
    (re.compile(r"(?i)WECHAT_APPID\s*[=:]\s*['\"]?wx[0-9a-f]{16}['\"]?"), "WeChat app ID"),
    (re.compile(r"(?i)WECHAT_APPSECRET\s*[=:]\s*['\"]?[a-f0-9]{32}['\"]?"), "WeChat app secret"),
    # Intercom
    (re.compile(r"(?i)INTERCOM_ACCESS_TOKEN\s*[=:]\s*['\"]?dG9rO[a-zA-Z0-9_-]{40,}['\"]?"), "Intercom access token"),
    # Zendesk
    (re.compile(r"(?i)ZENDESK_API_TOKEN\s*[=:]\s*['\"]?[a-zA-Z0-9_-]{30,}['\"]?"), "Zendesk API token"),
    (re.compile(r"(?i)ZENDESK_API_KEY\s*[=:]\s*['\"]?[a-zA-Z0-9_-]{30,}['\"]?"), "Zendesk API key"),
    # SendBird (prefix required to avoid matching every UUID)
    (re.compile(r"(?i)SENDBIRD[_-]?APP[_-]?ID\s*[=:]\s*['\"]?[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}['\"]?"), "SendBird application ID"),
    # Vonage (Nexmo)
    (re.compile(r"(?i)NEXMO_API_KEY\s*[=:]\s*['\"]?[a-f0-9]{8}['\"]?"), "Nexmo/Vonage API key"),
    (re.compile(r"(?i)NEXMO_API_SECRET\s*[=:]\s*['\"]?[A-Za-z0-9]{16}['\"]?"), "Nexmo/Vonage API secret"),
    # Plivo
    (re.compile(r"(?i)PLIVO_AUTH_ID\s*[=:]\s*['\"]?MA[A-Z0-9]{20}['\"]?"), "Plivo auth ID"),
    (re.compile(r"(?i)PLIVO_AUTH_TOKEN\s*[=:]\s*['\"]?[A-Za-z0-9]{20}['\"]?"), "Plivo auth token"),
    # MessageBird
    (re.compile(r"(?i)MESSAGEBIRD_API_KEY\s*[=:]\s*['\"]?[a-f0-9]{32}['\"]?"), "MessageBird API key"),
    # Sinch
    (re.compile(r"(?i)SINCH_APP_KEY\s*[=:]\s*['\"]?[a-f0-9]{32}['\"]?"), "Sinch app key"),
    (re.compile(r"(?i)SINCH_APP_SECRET\s*[=:]\s*['\"]?[a-f0-9]{32}['\"]?"), "Sinch app secret"),
    # Vonage SMS
    (re.compile(r"(?i)VONAGE_API_KEY\s*[=:]\s*['\"]?[a-f0-9]{8}['\"]?"), "Vonage API key"),
    (re.compile(r"(?i)VONAGE_API_SECRET\s*[=:]\s*['\"]?[A-Za-z0-9]{16}['\"]?"), "Vonage API secret"),
]

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3 — CLOUD PROVIDER KEYS
# ─────────────────────────────────────────────────────────────────────────────

CLOUD_PATTERNS = [
    # AWS Access Keys (comprehensive)
    (re.compile(r"AKIA[A-Z0-9]{16}"), "AWS Access Key ID (AKIA*)"),
    (re.compile(r"ABIA[A-Z0-9]{16}"), "AWS Boot Camp Access Key ID"),
    (re.compile(r"AGPA[A-Z0-9]{16}"), "AWS Grafana Access Key ID"),
    (re.compile(r"AIDA[A-Z0-9]{16}"), "AWS IAM user/role Access Key ID"),
    (re.compile(r"AIPA[A-Z0-9]{16}"), "AWS instance profile Access Key ID"),
    (re.compile(r"AKIAIOSFODNN7EXAMPLE"), "AWS example Access Key ID"),
    (re.compile(r"AROA[A-Z0-9]{16}"), "AWS role assumption Access Key ID"),
    (re.compile(r"ASIA[A-Z0-9]{16}"), "AWS temporary/Session Access Key ID"),
    (re.compile(r"A3T[A-Z0-9]{16}"), "AWS Tools for Powershell Access Key"),
    # AWS Secret Access Key (40-char base64)
    (re.compile(r"(?i)AWS_SECRET_ACCESS_KEY\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}['\"]?"), "AWS Secret Access Key env"),
    # AWS Session Token
    (re.compile(r"(?i)AWS_SESSION_TOKEN\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{300,}['\"]?"), "AWS session token"),
    (re.compile(r"(?i)AWS_SECURITY_TOKEN\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{300,}['\"]?"), "AWS security token"),
    # Azure
    (re.compile(r"(?i)AZURE_STORAGE_ACCOUNT\s*[=:]\s*['\"]?[a-z0-9]{20}['\"]?"), "Azure storage account name (non-secret identifier)"),
    (re.compile(r"(?i)AZURE_STORAGE_KEY\s*[=:]\s*['\"]?[a-zA-Z0-9+/]{86}==['\"]?"), "Azure storage key"),
    (re.compile(r"(?i)AZURE_STORAGE_CONNECTION_STRING\s*[=:]\s*['\"]?DefaultEndpointsProtocol=https;AccountName=[^;]+;AccountKey=[^;]+;"), "Azure storage connection string"),
    (re.compile(r"(?i)AZURE_CLIENT_SECRET\s*[=:]\s*['\"]?[A-Za-z0-9_-]{30,}['\"]?"), "Azure AD client secret"),
    (re.compile(r"(?i)AZURE_CLIENT_ID\s*[=:]\s*['\"]?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}['\"]?"), "Azure client ID"),
    (re.compile(r"(?i)AZURE_TENANT_ID\s*[=:]\s*['\"]?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}['\"]?"), "Azure tenant ID"),
    (re.compile(r"(?i)COSMOSDB_CONNECTION_STRING\s*[=:]\s*['\"]?AccountEndpoint=https://[^;]+;AccountKey=[^;]+;"), "Azure CosmosDB connection string"),
    # GCP Service Account JSON
    (re.compile(r'"type":\s*"service_account"'), "GCP service account JSON"),
    (re.compile(r'(?i)"private_key":\s*"-----BEGIN PRIVATE KEY-----'), "GCP service account private key"),
    (re.compile(r"(?i)GOOGLE_APPLICATION_CREDENTIALS\s*[=:]\s*['\"]?.+\.json['\"]?"), "GCP credentials file path"),
    (re.compile(r"(?i)GCP_SERVICE_ACCOUNT\s*[=:]\s*['\"]?\{"), "GCP service account JSON env"),
    # GCP API Key
    (re.compile(r"(?i)GCP_API_KEY\s*[=:]\s*['\"]?AIza[0-9A-Za-z_-]{30,}['\"]?"), "GCP API key"),
    (re.compile(r"AIza[0-9A-Za-z_-]{30,}"), "GCP API key"),
    # DigitalOcean
    (re.compile(r"(?i)DIGITALOCEAN_ACCESS_TOKEN\s*[=:]\s*['\"]?[a-f0-9]{64}['\"]?"), "DigitalOcean access token"),
    (re.compile(r"(?i)DO_ACCESS_TOKEN\s*[=:]\s*['\"]?[a-f0-9]{64}['\"]?"), "DigitalOcean access token (short)"),
    (re.compile(r"(?i)DIGITALOCEAN_TOKEN\s*[=:]\s*['\"]?[a-f0-9]{64}['\"]?"), "DigitalOcean token"),
    (re.compile(r"(?i)DIGITALOCEAN_SPACES_ACCESS_KEY\s*[=:]\s*['\"]?[A-Z0-9]{20}['\"]?"), "DigitalOcean Spaces access key"),
    (re.compile(r"(?i)DIGITALOCEAN_SPACES_SECRET_KEY\s*[=:]\s*['\"]?[a-zA-Z0-9_-]{40}['\"]?"), "DigitalOcean Spaces secret key"),
    # Vultr
    (re.compile(r"(?i)VULTR_API_KEY\s*[=:]\s*['\"]?[A-Z0-9]{36}['\"]?"), "Vultr API key"),
    # Linode
    (re.compile(r"(?i)LINODE_API_TOKEN\s*[=:]\s*['\"]?[A-Za-z0-9_-]{60}['\"]?"), "Linode API token"),
    (re.compile(r"(?i)LINODE_TOKEN\s*[=:]\s*['\"]?[A-Za-z0-9_-]{60}['\"]?"), "Linode token"),
    # Cloudflare
    (re.compile(r"(?i)CLOUDFLARE_API_KEY\s*[=:]\s*['\"]?[a-f0-9]{37}['\"]?"), "Cloudflare API key (global)"),
    (re.compile(r"(?i)CLOUDFLARE_API_TOKEN\s*[=:]\s*['\"]?[a-zA-Z0-9_-]{40,}['\"]?"), "Cloudflare API token"),
    (re.compile(r"(?i)CLOUDFLARE_ZONE_API_TOKEN\s*[=:]\s*['\"]?[a-zA-Z0-9_-]{40,}['\"]?"), "Cloudflare zone token"),
    # Oracle Cloud
    (re.compile(r"(?i)OCI_API_KEY\s*[=:]\s*['\"]?[a-f0-9]{86}['\"]?"), "Oracle Cloud API key (fingerprint)"),
    (re.compile(r"(?i)OCI_TENANCY\s*[=:]\s*['\"]?ocid1\.tenancy\.[a-z0-9_-]+['\"]?"), "Oracle Cloud tenancy OCID"),
    (re.compile(r"(?i)OCI_USER\s*[=:]\s*['\"]?ocid1\.user\.[a-z0-9_-]+['\"]?"), "Oracle Cloud user OCID"),
    # IBM Cloud
    (re.compile(r"(?i)IBMCLOUD_API_KEY\s*[=:]\s*['\"]?[a-zA-Z0-9_-]{44}['\"]?"), "IBM Cloud API key"),
    # Alibaba Cloud
    (re.compile(r"(?i)ALIBABA_CLOUD_ACCESS_KEY_ID\s*[=:]\s*['\"]?LTAI[A-Za-z0-9]{16}['\"]?"), "Alibaba Cloud access key ID"),
    (re.compile(r"(?i)ALIBABA_CLOUD_ACCESS_KEY_SECRET\s*[=:]\s*['\"]?[a-zA-Z0-9]{30}['\"]?"), "Alibaba Cloud access key secret"),
    # Scaleway
    (re.compile(r"(?i)SCW_SECRET_KEY\s*[=:]\s*['\"]?[a-f0-9]{32}['\"]?"), "Scaleway secret key"),
    (re.compile(r"(?i)SCALEWAY_ACCESS_KEY\s*[=:]\s*['\"]?[a-z0-9]{8}['\"]?"), "Scaleway access key"),
    # Render
    (re.compile(r"(?i)RENDER_API_KEY\s*[=:]\s*['\"]?rnb_[a-zA-Z0-9_-]{30,}['\"]?"), "Render API key"),
    # Railway
    (re.compile(r"(?i)RAILWAY_TOKEN\s*[=:]\s*['\"]?[a-f0-9]{32}['\"]?"), "Railway token"),
    # Fly.io
    (re.compile(r"(?i)FLY_API_TOKEN\s*[=:]\s*['\"]?[a-zA-Z0-9_-]{50,}['\"]?"), "Fly.io API token"),
    # Heroku
    (re.compile(r"(?i)HEROKU_API_KEY\s*[=:]\s*['\"]?[a-f0-9]{30,}['\"]?"), "Heroku API key"),
    # Netlify
    (re.compile(r"(?i)NETLIFY_ACCESS_TOKEN\s*[=:]\s*['\"]?[A-Za-z0-9_-]{40,}['\"]?"), "Netlify access token"),
    (re.compile(r"(?i)NETLIFY_AUTH_TOKEN\s*[=:]\s*['\"]?[A-Za-z0-9_-]{40,}['\"]?"), "Netlify auth token"),
    # Supabase
    (re.compile(r"(?i)SUPABASE_SERVICE_ROLE_KEY\s*[=:]\s*['\"]?eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+['\"]?"), "Supabase service role key"),
    (re.compile(r"(?i)SUPABASE_ANON_KEY\s*[=:]\s*['\"]?eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+['\"]?"), "Supabase anon key"),
    # PlanetScale
    (re.compile(r"(?i)PLANETSCALE_DATABASE_URL\s*[=:]\s*['\"]?mysql://[^:]+:[^@]+@"), "PlanetScale connection URL"),
    (re.compile(r"(?i)PLANETSCALE_DB_PLANETSCALE_PASSWORD\s*[=:]\s*['\"]?[a-z0-9_-]{50,}['\"]?"), "PlanetScale password"),
    # Neon
    (re.compile(r"(?i)NEON_CONNECTION_STRING\s*[=:]\s*['\"]?postgresql://[^:]+:[^@]+@"), "Neon connection string"),
    (re.compile(r"(?i)DATABASE_URL\s*[=:]\s*['\"]?postgresql://[^:]+:[^@]+@"), "PostgreSQL connection string env"),
]

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4 — DATABASE CONNECTION STRINGS
# ─────────────────────────────────────────────────────────────────────────────

DB_PATTERNS = [
    # PostgreSQL
    (re.compile(r"(?i)(postgres://|postgresql://)[^\s'\"]{20,}"), "PostgreSQL connection string"),
    # MySQL
    (re.compile(r"(?i)(mysql://|mariadb://)[^\s'\"]{20,}"), "MySQL/MariaDB connection string"),
    # MongoDB
    (re.compile(r"(?i)mongodb(\+srv)?://[^\s'\"]{20,}"), "MongoDB connection string"),
    (re.compile(r"(?i)MONGO_URI\s*[=:]\s*['\"]?mongodb(\+srv)?://[^\s'\"]{20,}['\"]?"), "MongoDB URI env"),
    # Redis
    (re.compile(r"(?i)redis://[^\s'\"]{15,}"), "Redis connection string"),
    (re.compile(r"(?i)rediss://[^\s'\"]{15,}"), "Redis SSL connection string"),
    (re.compile(r"(?i)REDIS_URL\s*[=:]\s*['\"]?redis[s]?://[^\s'\"]{15,}['\"]?"), "Redis URL env"),
    # Elasticsearch
    (re.compile(r"(?i)https?://[^\s'\"]{10,}elastic[a-z0-9_-]*:[^@\s'\"]{10,}@[^\s'\"]{10,}"), "Elasticsearch URL with credentials"),
    (re.compile(r"(?i)ELASTICSEARCH_URL\s*[=:]\s*['\"]?https?://[^\s'\"]{10,}['\"]?"), "Elasticsearch URL env"),
    # SQL Server
    (re.compile(r"(?i)mssql://[^\s'\"]{20,}"), "SQL Server connection string"),
    (re.compile(r"(?i)(sqlserver|sql_server)_connection\s*[=:]\s*['\"]?Server=[^;]+;Database=[^;]+;(User Id|UID)=[^;]+;(Password|PWD)=[^;]+;"), "SQL Server connection string"),
    # DynamoDB
    (re.compile(r"(?i)dynamodb://[^\s'\"]{10,}"), "DynamoDB connection string"),

    # Cassandra
    (re.compile(r"(?i)(cassandra://|cql://)[^\s'\"]{20,}"), "Cassandra connection string"),
    # InfluxDB
    (re.compile(r"(?i)(influxdb://|http[s]?://)[^\s'\"]{10,}:[^\s'\"]{10,}@"), "InfluxDB URL with credentials"),
    (re.compile(r"(?i)INFLUXDB_TOKEN\s*[=:]\s*['\"]?[A-Za-z0-9_-]{20,}['\"]?"), "InfluxDB token"),
    # ClickHouse
    (re.compile(r"(?i)clickhouse://[^\s'\"]{15,}"), "ClickHouse connection string"),
    # CouchDB
    (re.compile(r"(?i)couchdb://[^\s'\"]{15,}"), "CouchDB connection string"),
    # Snowflake
    (re.compile(r"(?i)snowflake://[^\s'\"]{20,}"), "Snowflake connection string"),

    (re.compile(r"(?i)SNOWFLAKE_PASSWORD\s*[=:]\s*['\"]?[A-Za-z0-9_-]{8,}['\"]?"), "Snowflake password"),
    # Redshift
    (re.compile(r"(?i)redshift://[^\s'\"]{20,}"), "Redshift connection string"),
    # Neo4j
    (re.compile(r"(?i)neo4j://[^\s'\"]{15,}"), "Neo4j connection string"),
    (re.compile(r"(?i)neo4j\+s://[^\s'\"]{15,}"), "Neo4j SSL connection string"),
    # TimescaleDB
    (re.compile(r"(?i)timescale://[^\s'\"]{20,}"), "TimescaleDB connection string"),
    # CockroachDB
    (re.compile(r"(?i)cockroachdb://[^\s'\"]{20,}"), "CockroachDB connection string"),
    (re.compile(r"(?i)CRDB_DATABASE_URL\s*[=:]\s*['\"]?cockroachdb://[^\s'\"]{20,}['\"]?"), "CockroachDB URL env"),
    # Firestore

]

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5 — DEVOPS / CI/CD
# ─────────────────────────────────────────────────────────────────────────────

DEVOPS_PATTERNS = [
    # GitHub
    (re.compile(r"ghp_[A-Za-z0-9_-]{36}"), "GitHub Personal Access Token (fine-grained)"),
    (re.compile(r"gho_[A-Za-z0-9_-]{36}"), "GitHub OAuth Access Token"),
    (re.compile(r"ghu_[A-Za-z0-9_-]{36}"), "GitHub User-to-Server Token"),
    (re.compile(r"ghs_[A-Za-z0-9_-]{36}"), "GitHub Server-to-Server Token"),
    (re.compile(r"ghr_[A-Za-z0-9_-]{36}"), "GitHub Refresh Token"),
    (re.compile(r"github_pat_[a-zA-Z0-9]{22}_[a-zA-Z0-9]{59}"), "GitHub fine-grained PAT"),
    (re.compile(r"(?i)GITHUB_TOKEN\s*[=:]\s*['\"]?ghp_[A-Za-z0-9_-]{36}['\"]?"), "GitHub token env"),
    (re.compile(r"(?i)GH_TOKEN\s*[=:]\s*['\"]?ghp_[A-Za-z0-9_-]{36}['\"]?"), "GitHub token short env"),
    # GitLab
    (re.compile(r"glpat-[a-zA-Z0-9_-]{20}"), "GitLab Personal Access Token"),
    (re.compile(r"glptt-[a-f0-9]{40}"), "GitLab Pipeline Trigger Token"),
    (re.compile(r"GR1348941[a-zA-Z0-9_-]{20}"), "GitLab Runner Registration Token"),
    (re.compile(r"glgo-[a-zA-Z0-9_-]{20}"), "GitLab OAuth Access Token"),
    (re.compile(r"glcbt-[a-zA-Z0-9_-]{20}"), "GitLab CI/CD Build Token"),
    (re.compile(r"glft-[a-zA-Z0-9_-]{20}"), "GitLab Feed Token"),
    (re.compile(r"(?i)GITLAB_TOKEN\s*[=:]\s*['\"]?glpat-[a-zA-Z0-9_-]{20}['\"]?"), "GitLab PAT env"),
    # Bitbucket
    (re.compile(r"ATBB[A-Za-z0-9_-]{42}"), "Bitbucket App Password"),
    (re.compile(r"(?i)BITBUCKET_TOKEN\s*[=:]\s*['\"]?ATBB[A-Za-z0-9_-]{42}['\"]?"), "Bitbucket token env"),
    (re.compile(r"(?i)BITBUCKET_APP_PASSWORD\s*[=:]\s*['\"]?ATBB[A-Za-z0-9_-]{42}['\"]?"), "Bitbucket app password env"),
    # NPM
    (re.compile(r"npm_[A-Za-z0-9_-]{8,}"), "NPM access token"),
    (re.compile(r"(?i)NPM_TOKEN\s*[=:]\s*['\"]?npm_[A-Za-z0-9_-]{8,}['\"]?"), "NPM token env"),
    # PyPI
    (re.compile(r"pypi-AgEIcBlpbi[a-zA-Z0-9_-]{60,}"), "PyPI upload token"),
    (re.compile(r"(?i)PYPI_TOKEN\s*[=:]\s*['\"]?pypi-AgEIcBlpb[a-zA-Z0-9_-]{60,}['\"]?"), "PyPI token env"),
    (re.compile(r"(?i)TWINE_PASSWORD\s*[=:]\s*['\"]?[a-zA-Z0-9_-]{20,}['\"]?"), "PyPI/twine password"),
    # Docker
    (re.compile(r"(?i)docker[_-]?hub[_-]?password\s*[=:]\s*['\"]?[A-Za-z0-9_-]{8,}['\"]?"), "Docker Hub password"),
    (re.compile(r"(?i)docker[_-]?config[_-]?json\s*[=:]\s*['\"]?\{[^}]{50,}"), "Docker config JSON (may contain auth)"),
    (re.compile(r"(?i)DOCKER_REGISTRY_PASSWORD\s*[=:]\s*['\"]?[A-Za-z0-9_-]{8,}['\"]?"), "Docker registry password"),
    # Kubernetes
    (re.compile(r"(?i)KUBECONFIG\s*[=:]\s*['\"]?apiVersion:"), "Kubernetes config YAML"),
    (re.compile(r"(?i)KUBERNETES_TOKEN\s*[=:]\s*['\"]?[A-Za-z0-9_-]{60,}['\"]?"), "Kubernetes service account token"),
    (re.compile(r"(?i)KUBE_CONFIG\s*[=:]\s*['\"]?-----BEGIN CERTIFICATE-----"), "Kubeconfig certificate"),
    # Jenkins
    (re.compile(r"(?i)JENKINS_API_TOKEN\s*[=:]\s*['\"]?[a-f0-9]{32}['\"]?"), "Jenkins API token"),
    (re.compile(r"(?i)JENKINS_PASSWORD\s*[=:]\s*['\"]?[A-Za-z0-9_-]{8,}['\"]?"), "Jenkins password"),
    # CircleCI
    (re.compile(r"(?i)CIRCLECI_API_TOKEN\s*[=:]\s*['\"]?[a-f0-9]{40}['\"]?"), "CircleCI API token"),
    (re.compile(r"(?i)CIRCLE_TOKEN\s*[=:]\s*['\"]?[a-f0-9]{40}['\"]?"), "CircleCI token short"),
    # GitHub Actions

    (re.compile(r"(?i)GH_CR_TOKEN\s*[=:]\s*['\"]?[A-Za-z0-9_-]{30,}['\"]?"), "GitHub container registry token"),
    # Terraform Cloud
    (re.compile(r"(?i)TF_TOKEN_app\.terraform\.io\s*[=:]\s*['\"]?atlas[A-Za-z0-9_-]{30,}['\"]?"), "Terraform Cloud token"),
    (re.compile(r"(?i)TERRAFORM_TOKEN\s*[=:]\s*['\"]?atlas[A-Za-z0-9_-]{30,}['\"]?"), "Terraform token env"),
    # Ansible
    (re.compile(r"(?i)ANSIBLE_VAULT_PASSWORD\s*[=:]\s*['\"]?[A-Za-z0-9_-]{8,}['\"]?"), "Ansible vault password"),
    # Puppet
    (re.compile(r"(?i)PUPPETDB_PASSWORD\s*[=:]\s*['\"]?[A-Za-z0-9_-]{8,}['\"]?"), "PuppetDB password"),
    # Artifactory
    (re.compile(r"(?i)ARTIFACTORY_API_KEY\s*[=:]\s*['\"]?[A-Za-z0-9_-]{30,}['\"]?"), "Artifactory API key"),
    (re.compile(r"(?i)ARTIFACTORY_PASSWORD\s*[=:]\s*['\"]?[A-Za-z0-9_-]{8,}['\"]?"), "Artifactory password"),
    # S3 (direct)
    (re.compile(r"(?i)s3://[^\s'\"]{10,}:[^\s'\"]{10,}@"), "S3 URL with credentials"),
    # CloudFormation
    (re.compile(r"(?i)CLOUDFORMATION_TEMPLATE\s*[=:]\s*['\"]?AWSTemplateFormatVersion:"), "CloudFormation template YAML"),
    # Pulumi
    (re.compile(r"(?i)PULUMI_ACCESS_TOKEN\s*[=:]\s*['\"]?pul-[a-f0-9]{40}['\"]?"), "Pulumi access token"),
    # Vercel
    (re.compile(r"(?i)VERCEL_TOKEN\s*[=:]\s*['\"]?[A-Za-z0-9_-]{24,}['\"]?"), "Vercel token"),
    # GitHub Deploy Key (SSH)
    (re.compile(r"-----BEGIN\s+(RSA|EC|DSA|OPENSSH|PGP)?\s*PRIVATE\s+KEY-----"), "Private key (generic)"),
    # AWS ARN (not a secret but can expose account ID)
    (re.compile(r"arn:aws:iam::[0-9]{12}:"), "AWS ARN (account ID exposure)"),
]

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6 — ENTERPRISE / SaaS KEYS
# ─────────────────────────────────────────────────────────────────────────────

ENTERPRISE_PATTERNS = [
    # Stripe
    (re.compile(r"sk_live_[0-9a-zA-Z]{24,}"), "Stripe live secret key"),
    (re.compile(r"sk_test_[0-9a-zA-Z]{24,}"), "Stripe test secret key"),
    (re.compile(r"rk_live_[0-9a-zA-Z]{24,}"), "Stripe live restricted key"),
    (re.compile(r"rk_test_[0-9a-zA-Z]{24,}"), "Stripe test restricted key"),
    (re.compile(r"whsec_[0-9a-fA-F]{32}"), "Stripe webhook secret"),
    (re.compile(r"(?i)STRIPE_SECRET_KEY\s*[=:]\s*['\"]?sk_live_[0-9a-zA-Z]{24,}['\"]?"), "Stripe live key env"),
    (re.compile(r"(?i)STRIPE_WEBHOOK_SECRET\s*[=:]\s*['\"]?whsec_[0-9a-fA-F]{32}['\"]?"), "Stripe webhook secret env"),
    # Shopify
    (re.compile(r"shpat_[a-f0-9]{32}", re.I), "Shopify Admin API shared secret"),
    (re.compile(r"shpca_[a-f0-9]{32}", re.I), "Shopify Customer API token"),
    (re.compile(r"shppa_[a-f0-9]{32}", re.I), "Shopify Partner API token"),
    (re.compile(r"shptu_[a-f0-9]{32}", re.I), "Shopify Storefront API token"),
    (re.compile(r"(?i)SHOPIFY_ACCESS_TOKEN\s*[=:]\s*['\"]?shpat_[a-f0-9]{32}['\"]?"), "Shopify access token env"),
    # Salesforce
    (re.compile(r"(?i)SF_CLIENT_ID\s*[=:]\s*['\"]?[0-9a-f]{32}['\"]?"), "Salesforce client ID"),
    (re.compile(r"(?i)SF_CLIENT_SECRET\s*[=:]\s*['\"]?[A-Za-z0-9_-]{30,}['\"]?"), "Salesforce client secret"),
    (re.compile(r"(?i)SF_PASSWORD\s*[=:]\s*['\"]?[A-Za-z0-9_-]{8,}['\"]?"), "Salesforce password"),
    (re.compile(r"(?i)SF_SECURITY_TOKEN\s*[=:]\s*['\"]?[A-Za-z0-9_-]{15,}['\"]?"), "Salesforce security token"),
    # Datadog
    (re.compile(r"(?i)DD_API_KEY\s*[=:]\s*['\"]?[a-f0-9]{32}['\"]?"), "Datadog API key"),
    (re.compile(r"(?i)DATADOG_API_KEY\s*[=:]\s*['\"]?[a-f0-9]{32}['\"]?"), "Datadog API key env"),
    (re.compile(r"(?i)DATADOG_APP_KEY\s*[=:]\s*['\"]?[a-f0-9]{40}['\"]?"), "Datadog application key"),
    # Sentry
    (re.compile(r"(?i)SENTRY_DSN\s*[=:]\s*['\"]?https://[a-f0-9]{32}@[^\s'\"]{10,}"), "Sentry DSN"),
    (re.compile(r"(?i)SENTRY_AUTH_TOKEN\s*[=:]\s*['\"]?sntrys_[a-zA-Z0-9_-]{50,}['\"]?"), "Sentry auth token"),
    (re.compile(r"(?i)SENTRY_API_KEY\s*[=:]\s*['\"]?[a-f0-9]{32}['\"]?"), "Sentry API key"),
    # Grafana
    (re.compile(r"(?i)GRAFANA_TOKEN\s*[=:]\s*['\"]?eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+['\"]?"), "Grafana service account token"),
    (re.compile(r"(?i)GRAFANA_API_KEY\s*[=:]\s*['\"]?eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+['\"]?"), "Grafana API key env"),
    # New Relic
    (re.compile(r"(?i)NEW_RELIC_LICENSE_KEY\s*[=:]\s*['\"]?[a-f0-9]{40}['\"]?"), "New Relic license key"),
    (re.compile(r"(?i)NEW_RELIC_API_KEY\s*[=:]\s*['\"]?NRAK[A-Za-z0-9_-]{30,}['\"]?"), "New Relic API key"),
    (re.compile(r"(?i)NR_LICENSE_KEY\s*[=:]\s*['\"]?[a-f0-9]{40}['\"]?"), "New Relic license key short"),
    # PagerDuty
    (re.compile(r"(?i)PAGERDUTY_API_KEY\s*[=:]\s*['\"]?[a-zA-Z0-9_-]{20,}['\"]?"), "PagerDuty API key"),
    (re.compile(r"(?i)PD_API_KEY\s*[=:]\s*['\ba-zA-Z0-9_-]{20,}['\"]?"), "PagerDuty API key short"),
    # Jira
    (re.compile(r"(?i)JIRA_API_TOKEN\s*[=:]\s*['\"]?[A-Za-z0-9_-]{24}['\"]?"), "Jira API token"),
    (re.compile(r"(?i)JIRA_TOKEN\s*[=:]\s*['\"]?[A-Za-z0-9_-]{24}['\"]?"), "Jira token"),
    (re.compile(r"(?i)JIRA_PASSWORD\s*[=:]\s*['\"]?[A-Za-z0-9_-]{8,}['\"]?"), "Jira password"),
    # Linear
    (re.compile(r"(?i)LINEAR_API_KEY\s*[=:]\s*['\"]?lin_[A-Za-z0-9_-]{40,}['\"]?"), "Linear API key"),
    # Notion
    (re.compile(r"(?i)NOTION_API_KEY\s*[=:]\s*['\"]?secret_[a-zA-Z0-9_-]{40,}['\"]?"), "Notion API key"),
    # HubSpot
    (re.compile(r"(?i)HUBSPOT_API_KEY\s*[=:]\s*['\"]?[a-f0-9]{32}['\"]?"), "HubSpot API key"),
    (re.compile(r"(?i)HUBSPOT_ACCESS_TOKEN\s*[=:]\s*['\"]?pat-[a-z0-9-]{36}['\"]?"), "HubSpot access token"),
    # Intercom
    (re.compile(r"(?i)INTERCOM_API_KEY\s*[=:]\s*['\"]?[a-z0-9]{30,}['\"]?"), "Intercom API key"),
    # Confluent
    (re.compile(r"(?i)CONFLUENT_API_KEY\s*[=:]\s*['\"]?[A-Za-z0-9_-]{30,}['\"]?"), "Confluent API key"),
    (re.compile(r"(?i)CONFLUENT_API_SECRET\s*[=:]\s*['\"]?[A-Za-z0-9_-]{30,}['\"]?"), "Confluent API secret"),
    # Contentful

    (re.compile(r"(?i)CONTENTFUL_DELIVERY_TOKEN\s*[=:]\s*['\"]?[A-Za-z0-9_-]{43}['\"]?"), "Contentful delivery token"),
    (re.compile(r"(?i)CONTENTFUL_ACCESS_TOKEN\s*[=:]\s*['\"]?[A-Za-z0-9_-]{43}['\"]?"), "Contentful access token"),
    # Algolia
    (re.compile(r"(?i)ALGOLIA_API_KEY\s*[=:]\s*['\"]?[A-Za-z0-9_-]{30,}['\"]?"), "Algolia API key"),
    (re.compile(r"(?i)ALGOLIA_ADMIN_KEY\s*[=:]\s*['\"]?[A-Za-z0-9_-]{30,}['\"]?"), "Algolia admin key"),

    # Amplitude
    (re.compile(r"(?i)AMPLITUDE_API_KEY\s*[=:]\s*['\"]?[a-f0-9]{32}['\"]?"), "Amplitude API key"),
    (re.compile(r"(?i)MIXPANEL_TOKEN\s*[=:]\s*['\"]?[a-f0-9]{16}['\"]?"), "Mixpanel token"),
    # Segment
    (re.compile(r"(?i)SEGMENT_WRITE_KEY\s*[=:]\s*['\"]?[A-Za-z0-9_-]{20,}['\"]?"), "Segment write key"),
    # LaunchDarkly
    (re.compile(r"(?i)LD_ACCESS_TOKEN\s*[=:]\s*['\"]?sdk-[a-f0-9-]{36}['\"]?"), "LaunchDarkly access token"),
    # Fastly
    (re.compile(r"(?i)FASTLY_API_TOKEN\s*[=:]\s*['\"]?[A-Za-z0-9_-]{30,}['\"]?"), "Fastly API token"),
    (re.compile(r"(?i)FASTLY_API_KEY\s*[=:]\s*['\"]?[A-Za-z0-9_-]{30,}['\"]?"), "Fastly API key"),
    # Cloudinary
    (re.compile(r"(?i)CLOUDINARY_API_KEY\s*[=:]\s*['\"]?[0-9]{8}['\"]?"), "Cloudinary API key"),
    (re.compile(r"(?i)CLOUDINARY_API_SECRET\s*[=:]\s*['\"]?[A-Za-z0-9_-]{40}['\"]?"), "Cloudinary API secret"),
    # Twilio (extra)
    (re.compile(r"(?i)TWILIO_AUTH_SID\s*[=:]\s*['\"]?AC[a-f0-9]{32}['\"]?"), "Twilio auth SID"),
    # Nexmo (Vonage)
    (re.compile(r"(?i)NEXMO_API_KEY\s*[=:]\s*['\"]?[a-f0-9]{8}['\"]?"), "Nexmo API key"),
    (re.compile(r"(?i)NEXMO_API_SECRET\s*[=:]\s*['\"]?[A-Za-z0-9]{16}['\"]?"), "Nexmo API secret"),
    # FastSMS
    (re.compile(r"(?i)FASTSMS_API_KEY\s*[=:]\s*['\"]?[a-z0-9]{30,}['\"]?"), "FastSMS API key"),
    # Mailjet
    (re.compile(r"(?i)MAILJET_API_KEY\s*[=:]\s*['\"]?[a-f0-9]{30,}['\"]?"), "Mailjet API key"),
    (re.compile(r"(?i)MAILJET_SECRET_KEY\s*[=:]\s*['\"]?[a-f0-9]{30,}['\"]?"), "Mailjet secret key"),
    # SendinBlue
    (re.compile(r"(?i)SENDINBLUE_API_KEY\s*[=:]\s*['\"]?[a-z0-9_-]{30,}['\"]?"), "SendinBlue API key"),
    # Mailtrap
    (re.compile(r"(?i)MAILTRAP_API_KEY\s*[=:]\s*['\"]?[a-f0-9]{30,}['\"]?"), "Mailtrap API key"),
    # Postmark
    (re.compile(r"(?i)POSTMARK_API_TOKEN\s*[=:]\s*['\"]?[a-z0-9]{30,}['\"]?"), "Postmark API token"),
    # Asana
    (re.compile(r"(?i)ASANA_TOKEN\s*[=:]\s*['\"]?[0-9]{15}:[a-zA-Z0-9_-]{30,}['\"]?"), "Asana token"),
    # Trello
    (re.compile(r"(?i)TRELLO_API_KEY\s*[=:]\s*['\"]?[a-f0-9]{32}['\"]?"), "Trello API key"),
    (re.compile(r"(?i)TRELLO_TOKEN\s*[=:]\s*['\"]?[a-f0-9-]{48}['\"]?"), "Trello token"),
    # Airtable
    (re.compile(r"(?i)AIRTABLE_API_KEY\s*[=:]\s*['\"]?key[A-Za-z0-9]{14}['\"]?"), "Airtable API key"),
    # Webflow
    (re.compile(r"(?i)WEBFLOW_API_KEY\s*[=:]\s*['\"]?[a-f0-9]{32}['\"]?"), "Webflow API key"),
    (re.compile(r"(?i)WEBFLOW_API_TOKEN\s*[=:]\s*['\"]?[a-f0-9]{32}['\"]?"), "Webflow API token"),
    # Contentstack
    (re.compile(r"(?i)CONTENTSTACK_API_KEY\s*[=:]\s*['\"]?[a-z0-9]{32}['\"]?"), "Contentstack API key"),
    (re.compile(r"(?i)CONTENTSTACK_DELIVERY_TOKEN\s*[=:]\s*['\"]?[a-z0-9]{43}['\"]?"), "Contentstack delivery token"),
    # Storyblok
    (re.compile(r"(?i)STORYBLOK_API_KEY\s*[=:]\s*['\"]?[a-z0-9_-]{30,}['\"]?"), "Storyblok API key"),
    (re.compile(r"(?i)STORYBLOK_TOKEN\s*[=:]\s*['\"]?[a-z0-9_-]{30,}['\"]?"), "Storyblok token"),
    # Sumo Logic
    (re.compile(r"(?i)SUMOLOGIC_ACCESS_ID\s*[=:]\s*['\"]?[A-Za-z0-9_-]{14}['\"]?"), "Sumo Logic access ID"),
    (re.compile(r"(?i)SUMOLOGIC_ACCESS_KEY\s*[=:]\s*['\"]?[A-Za-z0-9_-]{30,}['\"]?"), "Sumo Logic access key"),
    # Papertrail
    (re.compile(r"(?i)PAPERTRAIL_API_TOKEN\s*[=:]\s*['\"]?[a-f0-9]{30,}['\"]?"), "Papertrail API token"),
    # Loggly
    (re.compile(r"(?i)LOGGLY_TOKEN\s*[=:]\s*['\"]?[a-z0-9-]{30,}['\"]?"), "Loggly token"),
    # Logz.io
    (re.compile(r"(?i)LOGZ_IO_TOKEN\s*[=:]\s*['\"]?[a-z0-9-]{30,}['\"]?"), "Logz.io token"),
    # Scalyr
    (re.compile(r"(?i)SCALYR_API_KEY\s*[=:]\s*['\"]?[a-zA-Z0-9_-]{30,}['\"]?"), "Scalyr API key"),
    # Kevel
    (re.compile(r"(?i)KEVEL_AD_API_KEY\s*[=:]\s*['\"]?[a-z0-9_-]{30,}['\"]?"), "Kevel Ad API key"),
    # AdMob
    (re.compile(r"(?i)ADMOB_API_KEY\s*[=:]\s*['\"]?[a-f0-9]{40}['\"]?"), "AdMob API key"),
    # App Center (VS App Center)
    (re.compile(r"(?i)APP_CENTER_API_TOKEN\s*[=:]\s*['\"]?[a-f0-9]{30,}['\"]?"), "App Center API token"),
    # Launchpad
    (re.compile(r"(?i)LAUNCHPAD_API_KEY\s*[=:]\s*['\"]?[a-zA-Z0-9_-]{30,}['\"]?"), "Launchpad API key"),
    # Vimeo
    (re.compile(r"(?i)VIMEO_TOKEN\s*[=:]\s*['\"]?[a-z0-9_-]{30,}['\"]?"), "Vimeo token"),
    (re.compile(r"(?i)VIMEO_ACCESS_TOKEN\s*[=:]\s*['\"]?[a-z0-9_-]{30,}['\"]?"), "Vimeo access token"),
    # YouTube Data API
    (re.compile(r"(?i)YOUTUBE_API_KEY\s*[=:]\s*['\"]?AIza[0-9A-Za-z_-]{30,}['\"]?"), "YouTube API key"),
    # OpenStreetMap
    (re.compile(r"(?i)OSM_API_KEY\s*[=:]\s*['\"]?[A-Za-z0-9_-]{30,}['\"]?"), "OpenStreetMap API key"),
    # Mapbox
    (re.compile(r"(?i)MAPBOX_ACCESS_TOKEN\s*[=:]\s*['\"]?pk\.[A-Za-z0-9_-]{60,}['\"]?"), "Mapbox access token"),
    (re.compile(r"(?i)MAPBOX_SECRET_TOKEN\s*[=:]\s*['\"]?sk\.[A-Za-z0-9_-]{60,}['\"]?"), "Mapbox secret token"),
    # Mapbox styles
    (re.compile(r"pk\.[A-Za-z0-9_-]{60,}"), "Mapbox public token"),
    # Dropbox
    (re.compile(r"(?i)DROPBOX_API_KEY\s*[=:]\s*['\"]?[a-z0-9_-]{30,}['\"]?"), "Dropbox API key"),
    (re.compile(r"(?i)DROPBOX_ACCESS_TOKEN\s*[=:]\s*['\"]?[a-zA-Z0-9_-]{50,}['\"]?"), "Dropbox access token"),
    (re.compile(r"(?i)DROPBOX_REFRESH_TOKEN\s*[=:]\s*['\"]?[a-zA-Z0-9_-]{50,}['\"]?"), "Dropbox refresh token"),
    # Box
    (re.compile(r"(?i)BOX_API_KEY\s*[=:]\s*['\"]?[a-z0-9]{32}['\"]?"), "Box API key"),
    (re.compile(r"(?i)BOX_ACCESS_TOKEN\s*[=:]\s*['\"]?[a-zA-Z0-9_-]{40,}['\"]?"), "Box access token"),
    # OneLogin
    (re.compile(r"(?i)ONELOGIN_API_TOKEN\s*[=:]\s*['\"]?[a-z0-9_-]{30,}['\"]?"), "OneLogin API token"),
    (re.compile(r"(?i)ONELOGIN_CLIENT_SECRET\s*[=:]\s*['\"]?[a-z0-9_-]{30,}['\"]?"), "OneLogin client secret"),
    # Okta
    (re.compile(r"(?i)OKTA_API_TOKEN\s*[=:]\s*['\"]?[a-zA-Z0-9_-]{30,}['\"]?"), "Okta API token"),
    (re.compile(r"(?i)OKTA_CLIENT_ID\s*[=:]\s*['\"]?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}['\"]?"), "Okta client ID"),
    (re.compile(r"(?i)OKTA_CLIENT_SECRET\s*[=:]\s*['\"]?[a-zA-Z0-9_-]{30,}['\"]?"), "Okta client secret"),
    # Auth0
    (re.compile(r"(?i)AUTH0_CLIENT_ID\s*[=:]\s*['\"]?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}['\"]?"), "Auth0 client ID"),
    (re.compile(r"(?i)AUTH0_CLIENT_SECRET\s*[=:]\s*['\"]?[a-zA-Z0-9_-]{30,}['\"]?"), "Auth0 client secret"),
    (re.compile(r"(?i)AUTH0_DOMAIN\s*[=:]\s*['\"]?[a-z0-9_-]+\.auth0\.com['\"]?"), "Auth0 domain"),
    # Clerk
    (re.compile(r"(?i)CLERK_PUBLISHABLE_KEY\s*[=:]\s*['\"]?pk_[a-zA-Z0-9_-]+['\"]?"), "Clerk publishable key"),
    (re.compile(r"(?i)CLERK_SECRET_KEY\s*[=:]\s*['\"]?sk_[a-zA-Z0-9_-]+['\"]?"), "Clerk secret key"),
    # Supabase (extra)
    (re.compile(r"(?i)SUPABASE_URL\s*[=:]\s*['\"]?https://[a-z0-9_-]+\.supabase\.co['\"]?"), "Supabase URL"),
    # Clerk
    (re.compile(r"(?i)NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY\s*[=:]\s*['\"]?pk_[a-zA-Z0-9_-]+['\"]?"), "Clerk publishable key (Next.js)"),
]

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 7 — JWT / TOKEN PATTERNS
# ─────────────────────────────────────────────────────────────────────────────

JWT_PATTERNS = [
    # Bearer token
    (re.compile(r"(?i)Bearer\s+[A-Za-z0-9_-]{20,}"), "Bearer token"),
    # JWT (generic)
    (re.compile(r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"), "JWT token"),
    # GitHub OAuth
    (re.compile(r"(?i)GITHUB_OAUTH_TOKEN\s*[=:]\s*['\"]?gho_[A-Za-z0-9_-]{36}['\"]?"), "GitHub OAuth token env"),
    # Google OAuth
    (re.compile(r"(?i)GOOGLE_OAUTH_TOKEN\s*[=:]\s*['\"]?ya29\.[A-Za-z0-9_-]+['\"]?"), "Google OAuth token"),
    # Azure AD
    (re.compile(r"(?i)AZURE_AD_ACCESS_TOKEN\s*[=:]\s*['\"]?eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+['\"]?"), "Azure AD access token"),
    (re.compile(r"(?i)AZURE_AD_REFRESH_TOKEN\s*[=:]\s*['\"]?[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+['\"]?"), "Azure AD refresh token"),
    # Facebook Access Token
    (re.compile(r"(?i)FACEBOOK_ACCESS_TOKEN\s*[=:]\s*['\"]?EAACEdEose0cBA[0-9A-Za-z_-]+['\"]?"), "Facebook access token"),
    # LinkedIn
    (re.compile(r"(?i)LINKEDIN_ACCESS_TOKEN\s*[=:]\s*['\"]?AQXd[0-9A-Za-z_-]+['\"]?"), "LinkedIn access token"),
    # Spotify
    (re.compile(r"(?i)SPOTIFY_ACCESS_TOKEN\s*[=:]\s*['\"]?BQ[0-9A-Za-z_-]+['\"]?"), "Spotify access token"),
    # Reddit
    (re.compile(r"(?i)REDDIT_ACCESS_TOKEN\s*[=:]\s*['\"]?eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+['\"]?"), "Reddit access token"),
    # Twitch
    (re.compile(r"(?i)TWITCH_ACCESS_TOKEN\s*[=:]\s*['\"]?[a-zA-Z0-9_-]{30,}['\"]?"), "Twitch access token"),
]

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 8 — PASSWORD / SECRET ASSIGNMENT PATTERNS
# ─────────────────────────────────────────────────────────────────────────────

PASSWORD_PATTERNS = [
    (re.compile(r"(?i)(password|passwd|pwd|contraseña|contrasena|pass)\s*[=:]\s*['\"]?[^\s'\"]{8,80}['\"]?"), "Password assignment"),
    (re.compile(r"(?i)(secret|private|pvt)[_-](key|token|pwd|pass)\s*[=:]\s*['\"]?[^\s'\"]{10,}['\"]?"), "Secret/private key assignment"),
    (re.compile(r"(?i)(db|database|dbase)[_-](pass|pwd|passwd|password|secret)\s*[=:]\s*['\"]?[^\s'\"]{8,}['\"]?"), "Database password assignment"),
    (re.compile(r"(?i)token[_-](secret|key)\s*[=:]\s*['\"]?[^\s'\"]{10,}['\"]?"), "Token assignment"),
    (re.compile(r"(?i)(api[_-]?key|apikey)[_-](secret|key)\s*[=:]\s*['\"]?[^\s'\"]{15,}['\"]?"), "API key assignment"),
    (re.compile(r"(?i)(client[_-]?secret|client[_-]?key)\s*[=:]\s*['\"]?[^\s'\"]{15,}['\"]?"), "Client secret assignment"),
    (re.compile(r"(?i)access[_-](key|token)\s*[=:]\s*['\"]?[^\s'\"]{15,}['\"]?"), "Access key assignment"),
    # ── Generic env-var patterns: catch ANY_PREFIX_PASSWORD=, ANY_PREFIX_SECRET=, etc. ──
    (re.compile(r"(?i)[A-Z_]*PASSWORD\s*[=:]\s*['\"]?[^\s'\"]{6,}['\"]?"), "Generic password assignment"),
    (re.compile(r"(?i)[A-Z_]*_SECRET\s*[=:]\s*['\"]?[^\s'\"]{6,}['\"]?"), "Generic secret assignment"),
    (re.compile(r"(?i)[A-Z_]*_TOKEN\s*[=:]\s*['\"]?[^\s'\"]{6,}['\"]?"), "Generic token assignment"),
    (re.compile(r"(?i)[A-Z_]*_API_KEY\s*[=:]\s*['\"]?[^\s'\"]{6,}['\"]?"), "Generic API key assignment"),
    # ── YAML-style: password: value, secret: value (indented or top-level) ──
    (re.compile(r"(?im)^\s*password\s*:\s*['\"]?[^\s'\"]{6,}['\"]?"), "YAML password value"),
    (re.compile(r"(?im)^\s*secret\s*:\s*['\"]?[^\s'\"]{6,}['\"]?"), "YAML secret value"),
    (re.compile(r"(?im)^\s*token\s*:\s*['\"]?[^\s'\"]{6,}['\"]?"), "YAML token value"),
    (re.compile(r"(?im)^\s*api_key\s*:\s*['\"]?[^\s'\"]{6,}['\"]?"), "YAML api_key value"),
]

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 9 — HIGH-ENTROPY STRINGS (careful thresholds to avoid false positives)
# ─────────────────────────────────────────────────────────────────────────────

# Matches base64 strings with entropy > 4.8 (very random-looking, unlikely in normal text)
# Threshold 4.8 = high confidence random, avoids catching legitimate base64 (e.g., data URIs)
_BASE64_ENTROPY_RE = re.compile(r"[A-Za-z0-9+/]{32,}={0,2}")


def _high_entropy_base64(text: str) -> list[str]:
    """Detect high-entropy base64 strings (entropy > 4.8)."""
    findings = []
    for match in _BASE64_ENTROPY_RE.finditer(text):
        s = match.group()
        if len(s) < 32:
            continue
        # Very rough entropy check using character distribution
        unique_chars = len(set(s))
        if unique_chars >= 30 and len(s) >= 40:  # Very high unique ratio = random
            findings.append(f"High-entropy base64 ({len(s)} chars, {unique_chars} unique)")
    return findings


# Matches hex strings with entropy > 3.5
_HEX_ENTROPY_RE = re.compile(r"[a-f0-9]{32,}", re.I)


def _high_entropy_hex(text: str) -> list[str]:
    """Detect high-entropy hex strings."""
    findings = []
    for match in _HEX_ENTROPY_RE.finditer(text):
        s = match.group()
        if len(s) < 32:
            continue
        unique_chars = len(set(s.lower()))
        # Very random hex = all 16 chars used, or very long
        if unique_chars >= 12 and len(s) >= 40:
            findings.append(f"High-entropy hex ({len(s)} chars, {unique_chars}/16 unique)")
    return findings


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 10 — PROMPT INJECTION (BLOCK, not redact)
# ─────────────────────────────────────────────────────────────────────────────

INJECTION_PATTERNS = [
    # Secret exfiltration (with possessive context: my/your/the/api/system)
    (re.compile(r"(?i)(reveal|show|print|send|extract|leak|exfiltrate)[a-z\s]*(my|your|the|api|system|access|private)\s*(secret|credential|key|token|password|passwd)s?\b"), "Secret exfiltration attempt"),
    # Secret exfiltration (verb + secret noun directly, no possessive needed)
    (re.compile(r"(?i)(reveal|extract|leak|exfiltrate|dump|steal)\s+(secrets?|credentials?|passwords?|tokens?)\b"), "Secret exfiltration attempt (direct)"),
    (re.compile(r"(?i)(ignore|disregard|forget)[a-z\s]*(previous|above|all|system|safety|instruction)"), "Instruction override attempt"),
    (re.compile(r"(?i)你现在是|你现在扮演|忽略之前|ignore\s+previous|forget\s+instructions"), "Language/model override (jailbreak)"),
    (re.compile(r"(?i)你是一个.*角色"), "Role-play injection"),
    (re.compile(r"(?i)\b(DAN|Do\s+Anything\s+Now)\b"), "DAN jailbreak attempt"),
    (re.compile(r"(?i)(pretend you are|act as|roleplay|role-play|you are now|you are a)[^.\n]{0,50}(model|AI|assistant|bot)"), "Role-play jailbreak attempt"),
    (re.compile(r"(?i)(developer|devops|maintenance|jailbreak)[ _-]?mode"), "Developer/maintenance mode attempt"),
    (re.compile(r"(?i)^\s*[/#*>]+\s*(system|admin|override)", re.MULTILINE), "Admin directive injection"),
    # System prompt extraction
    (re.compile(r"(?i)(what is|show me|tell me)[a-z\s]*(your|the|system)[a-z\s]*(prompt|instruction|system|configuration)"), "System prompt extraction"),
    (re.compile(r"(?i)repeat[a-z\s]*the[a-z\s]*(instruction|word|phrase)[a-z\s]*above"), "Prompt repetition injection"),
    (re.compile(r"(?i)start[a-z\s]*with[a-z\s]*the[a-z\s]*sentence"), "Prefix injection"),
    # Chinese prompt injection
    (re.compile(r"泄露|密钥|密码|令牌|凭据|凭证"), "Chinese: secret exfiltration keywords"),
    # Encoding bypass
    (re.compile(r"(?i)(base64|hex|encode|decode|转码)[a-z\s]*(secret|key|token)"), "Encoding-based exfiltration"),
    # Override injection
    (re.compile(r"(?i)new\s+instruction[s]?:\s*"), "New instruction injection"),
    (re.compile(r"(?i)^[/#*>]+\s*(system|admin|override)", re.MULTILINE), "Admin directive injection"),
]

# ─────────────────────────────────────────────────────────────────────────────
# ALL REDACT PATTERNS (secrets → redaction)
# ─────────────────────────────────────────────────────────────────────────────

REDACT_PATTERNS = (
    AI_PATTERNS
    + MESSAGING_PATTERNS
    + CLOUD_PATTERNS
    + DB_PATTERNS
    + DEVOPS_PATTERNS
    + ENTERPRISE_PATTERNS
    + JWT_PATTERNS
    + PASSWORD_PATTERNS
)


class NormalizationPipeline:
    _B64_RE = re.compile(r'[A-Za-z0-9+/=_-]{16,}')
    _HEX_RE = re.compile(r'[a-fA-F0-9]{32,}')
    _MAX_DECODE_SEGMENTS = 10
    _MAX_DECODE_BYTES = 1024

    def generate_views(self, text: str) -> Dict[str, str]:
        stripped = ''.join(c for c in text if unicodedata.category(c) != 'Cf')
        nfkc = unicodedata.normalize('NFKC', stripped)
        del stripped
        unicode_norm = nfkc.casefold()
        ws_collapsed = re.sub(r'\s+', '', unicode_norm)
        alnum = re.sub(r'[^a-z0-9]', '', ws_collapsed)
        decode_parts = [urllib.parse.unquote(nfkc)]
        decode_parts.extend(self._decode_b64_segments(nfkc))
        decode_parts.extend(self._decode_hex_segments(nfkc))
        del nfkc
        decoded = '\n'.join(p.casefold() for p in decode_parts)
        del decode_parts

        return {
            'unicode_normalized': unicode_norm,
            'whitespace_collapsed': ws_collapsed,
            'alnum_only': alnum,
            'decode_attempted': decoded,
        }

    def _decode_b64_segments(self, text: str) -> List[str]:
        results = []
        for i, m in enumerate(self._B64_RE.finditer(text)):
            if i >= self._MAX_DECODE_SEGMENTS:
                break
            seg = m.group()
            for decoder in (base64.b64decode, base64.urlsafe_b64decode):
                try:
                    pad = seg + '=' * (-len(seg) % 4)
                    raw = decoder(pad)
                    if len(raw) > self._MAX_DECODE_BYTES:
                        raw = raw[:self._MAX_DECODE_BYTES]
                    decoded = raw.decode('utf-8', errors='ignore')
                    if decoded and any(c.isprintable() for c in decoded):
                        results.append(decoded)
                        break
                except Exception:
                    continue
        return results

    def _decode_hex_segments(self, text: str) -> List[str]:
        results = []
        for i, m in enumerate(self._HEX_RE.finditer(text)):
            if i >= self._MAX_DECODE_SEGMENTS:
                break
            seg = m.group()
            try:
                raw = bytes.fromhex(seg)
                if len(raw) > self._MAX_DECODE_BYTES:
                    raw = raw[:self._MAX_DECODE_BYTES]
                decoded = raw.decode('utf-8', errors='ignore')
                if decoded:
                    results.append(decoded)
            except Exception:
                continue
        return results


@dataclass
class VaultMatch:
    secret_id: str
    confidence: float
    detector: str


class SecretVault:
    _ALLOWLISTED_ENV_KEYS = {
        'LITELLM_MASTER_KEY', 'GITLAB_PAT', 'DATABASE_URL', 'UI_PASSWORD',
    }
    _ALLOWLISTED_ENV_PATTERNS = ('_API_KEY', '_SECRET', '_TOKEN')
    _SECRET_KEYWORDS = {'key', 'token', 'secret', 'password', 'credential', 'api', 'auth', 'bearer'}
    _KGRAM_K = 8
    _MIN_SECRET_LEN = 8
    _TOKEN_RELOAD_INTERVAL = 60

    def __init__(self, env_path: str = '', token_path: str = '', headers_path: str = ''):
        self._normalizer = NormalizationPipeline()
        self._secrets: Dict[str, Dict[str, str]] = {}
        self._kgram_index: Dict[str, set] = {}
        self._token_path = token_path
        self._token_mtime: float = 0.0
        self._last_token_check: float = 0.0

        self._load_env_file(env_path)
        self._load_env_vars()
        self._load_token_file(token_path)
        self._load_headers_file(headers_path)
        self._build_kgram_index()
        logger.info('[secret-vault] loaded %d secrets', len(self._secrets))

    def _add_secret(self, secret_id: str, value: str):
        value = value.strip()
        if len(value) < self._MIN_SECRET_LEN:
            return
        views = self._normalizer.generate_views(value)
        self._secrets[secret_id] = {
            'raw': value,
            'normalized': views['unicode_normalized'],
            'alnum': views['alnum_only'],
        }

    def _load_env_file(self, path: str):
        if not path or not os.path.isfile(path):
            logger.warning('[secret-vault] env file not found: %s', path)
            return
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' not in line:
                        continue
                    key, _, val = line.partition('=')
                    key = key.strip()
                    val = val.strip()
                    self._add_secret(f'env:{key}', val)
        except Exception as e:
            logger.warning('[secret-vault] error loading env file: %s', e)

    def _load_env_vars(self):
        for key, val in os.environ.items():
            if key in self._ALLOWLISTED_ENV_KEYS or any(key.endswith(p) for p in self._ALLOWLISTED_ENV_PATTERNS):
                self._add_secret(f'os:{key}', val)

    def _load_token_file(self, path: str):
        if not path or not os.path.isfile(path):
            return
        try:
            self._token_mtime = os.path.getmtime(path)
            self._last_token_check = time.time()
            with open(path) as f:
                token = f.read().strip()
            self._add_secret('file:.token', token)
        except Exception as e:
            logger.warning('[secret-vault] error loading token file: %s', e)

    def _load_headers_file(self, path: str):
        if not path or not os.path.isfile(path):
            return
        try:
            import json as _json
            with open(path) as f:
                headers = _json.load(f)
            auth = headers.get('Authorization', '')
            if auth:
                self._add_secret('file:.headers:Authorization', auth)
        except Exception as e:
            logger.warning('[secret-vault] error loading headers file: %s', e)

    def _build_kgram_index(self):
        self._kgram_index.clear()
        for sid, forms in self._secrets.items():
            alnum = forms['alnum']
            if len(alnum) < self._KGRAM_K:
                continue
            for i in range(len(alnum) - self._KGRAM_K + 1):
                kg = alnum[i:i + self._KGRAM_K]
                if kg not in self._kgram_index:
                    self._kgram_index[kg] = set()
                self._kgram_index[kg].add(sid)

    def _maybe_reload_token(self):
        if not self._token_path:
            return
        now = time.time()
        if now - self._last_token_check < self._TOKEN_RELOAD_INTERVAL:
            return
        self._last_token_check = now
        try:
            mtime = os.path.getmtime(self._token_path)
            if mtime != self._token_mtime:
                self._load_token_file(self._token_path)
                self._build_kgram_index()
                logger.info('[secret-vault] reloaded token file')
        except Exception:
            pass

    def match_views(self, views: Dict[str, str]) -> List[VaultMatch]:
        self._maybe_reload_token()
        matches = []
        seen_ids = set()

        for sid, forms in self._secrets.items():
            for view_name in ('unicode_normalized', 'whitespace_collapsed', 'alnum_only', 'decode_attempted'):
                view_text = views.get(view_name, '')
                if not view_text:
                    continue
                form_key = 'alnum' if view_name == 'alnum_only' else 'normalized'
                secret_form = forms.get(form_key, '')
                if secret_form and secret_form in view_text and sid not in seen_ids:
                    matches.append(VaultMatch(secret_id=sid, confidence=1.0, detector='vault_exact'))
                    seen_ids.add(sid)

            if sid in seen_ids:
                continue
            raw = forms.get('raw', '')
            for view_name in ('unicode_normalized', 'whitespace_collapsed', 'decode_attempted'):
                view_text = views.get(view_name, '')
                if raw and raw in view_text and sid not in seen_ids:
                    matches.append(VaultMatch(secret_id=sid, confidence=1.0, detector='vault_exact_raw'))
                    seen_ids.add(sid)

        alnum_view = views.get('alnum_only', '')
        if alnum_view:
            for sid, forms in self._secrets.items():
                if sid in seen_ids:
                    continue
                alnum_secret = forms.get('alnum', '')
                if len(alnum_secret) < self._KGRAM_K:
                    continue
                total_kgrams = len(alnum_secret) - self._KGRAM_K + 1
                hit_count = 0
                for i in range(len(alnum_view) - self._KGRAM_K + 1):
                    kg = alnum_view[i:i + self._KGRAM_K]
                    if kg in self._kgram_index and sid in self._kgram_index[kg]:
                        hit_count += 1
                coverage = hit_count / total_kgrams if total_kgrams > 0 else 0
                if coverage >= 0.3:
                    matches.append(VaultMatch(secret_id=sid, confidence=0.8, detector='vault_kgram'))
                    seen_ids.add(sid)
                elif coverage >= 0.2:
                    text_lower = views.get('unicode_normalized', '')
                    if any(kw in text_lower for kw in self._SECRET_KEYWORDS):
                        matches.append(VaultMatch(secret_id=sid, confidence=0.7, detector='vault_kgram_ctx'))
                        seen_ids.add(sid)

        return matches


@dataclass
class RedactionEvent:
    detector: str
    secret_id: Optional[str]
    confidence: float


@dataclass
class RedactionResult:
    redacted_text: str
    blocked: bool
    events: List[RedactionEvent] = field(default_factory=list)


class RedactionEngine:
    _ENTROPY_B64_RE = re.compile(r'[A-Za-z0-9+/=_-]{32,}')
    _ENTROPY_HEX_RE = re.compile(r'[a-fA-F0-9]{40,}')

    def __init__(self, vault: SecretVault):
        self._normalizer = NormalizationPipeline()
        self._vault = vault

    def scan_and_redact(self, text: str) -> RedactionResult:
        if not text:
            return RedactionResult(redacted_text=text, blocked=False)

        views = self._normalizer.generate_views(text)
        events: List[RedactionEvent] = []
        blocked = False
        redacted = text

        vault_matches = self._vault.match_views(views)
        for vm in vault_matches:
            events.append(RedactionEvent(detector=vm.detector, secret_id=vm.secret_id, confidence=vm.confidence))
            if vm.confidence >= 0.9:
                blocked = True
            forms = self._vault._secrets.get(vm.secret_id, {})
            for form_val in (forms.get('raw', ''), forms.get('normalized', '')):
                if form_val and form_val in redacted:
                    masked = self._partial_mask(form_val)
                    redacted = redacted.replace(form_val, masked)

        for view_name in ('unicode_normalized', 'whitespace_collapsed'):
            view_text = views.get(view_name, '')
            if not view_text:
                continue
            for pattern, label in REDACT_PATTERNS:
                if pattern.search(view_text) and not pattern.search(redacted):
                    events.append(RedactionEvent(detector=f'regex_{view_name}', secret_id=label, confidence=0.6))

        del views

        for pattern, label in REDACT_PATTERNS:
            for match in pattern.finditer(redacted):
                secret = match.group()
                masked = self._partial_mask(secret)
                redacted = redacted.replace(secret, masked, 1)
                events.append(RedactionEvent(detector='regex_raw', secret_id=label, confidence=0.8))

        redacted = self._entropy_redact(redacted, events)

        return RedactionResult(redacted_text=redacted, blocked=blocked, events=events)

    def _entropy_redact(self, text: str, events: List[RedactionEvent]) -> str:
        for m in self._ENTROPY_B64_RE.finditer(text):
            s = m.group()
            entropy = self._shannon_entropy(s)
            if entropy >= 4.5:
                events.append(RedactionEvent(detector='entropy_b64', secret_id=None, confidence=0.5))
                masked = self._partial_mask(s)
                text = text.replace(s, masked, 1)

        for m in self._ENTROPY_HEX_RE.finditer(text):
            s = m.group()
            entropy = self._shannon_entropy(s)
            if entropy >= 3.0:
                events.append(RedactionEvent(detector='entropy_hex', secret_id=None, confidence=0.5))
                masked = self._partial_mask(s)
                text = text.replace(s, masked, 1)

        return text

    @staticmethod
    def _shannon_entropy(s: str) -> float:
        if not s:
            return 0.0
        from collections import Counter
        counts = Counter(s)
        length = len(s)
        return -sum((c / length) * math.log2(c / length) for c in counts.values())

    @staticmethod
    def _partial_mask(secret: str) -> str:
        """
        Partially mask a secret, showing first 5 and last 3 characters.
        Example: sk-proj-abc123def456ghi789 -> sk-pr****789
        """
        if len(secret) <= 8:
            # Too short to partially mask safely
            return '****'
        
        prefix_len = min(5, len(secret) // 3)
        suffix_len = min(3, len(secret) // 4)
        
        prefix = secret[:prefix_len]
        suffix = secret[-suffix_len:]
        
        return f"{prefix}****{suffix}"


# ─────────────────────────────────────────────────────────────────────────────
# GUARDRAIL CLASS
# ─────────────────────────────────────────────────────────────────────────────

class SecretGuardrail(CustomGuardrail):

    _gc_counter = 0
    _GC_EVERY_N = 50

    def __init__(self, action: str = "redact", check_injection: bool = True):
        super().__init__(guardrail_name="hide-secrets")
        self.action = action
        self.check_injection = check_injection

        litellm_dir = os.path.dirname(os.path.abspath(__file__))
        vault = SecretVault(
            env_path=os.path.join(litellm_dir, ".env"),
            token_path=os.path.join(litellm_dir, ".token"),
            headers_path=os.path.join(litellm_dir, ".headers"),
        )
        self._engine = RedactionEngine(vault)

    def _check_injection(self, content: str) -> str | None:
        for pattern, label in INJECTION_PATTERNS:
            if pattern.search(content):
                return label
        return None

    def _apply_redaction(self, content_list: list, original: str, redacted: str):
        for block in content_list:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type", "")
            if block_type == "text" and block.get("text") == original:
                block["text"] = redacted
                return
            elif block_type == "tool_result":
                inner = block.get("content", "")
                if isinstance(inner, str) and inner == original:
                    block["content"] = redacted
                    return
                elif isinstance(inner, list):
                    self._apply_redaction(inner, original, redacted)
            elif block_type == "tool_use":
                inp = block.get("input")
                if isinstance(inp, dict):
                    for k, v in inp.items():
                        if isinstance(v, str) and v == original:
                            inp[k] = redacted
                            return

    def _extract_text_blocks(self, raw_content, _source: str = "text") -> list[tuple]:
        if isinstance(raw_content, str):
            return [(raw_content, _source)]
        if isinstance(raw_content, list):
            blocks = []
            for block in raw_content:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type", "")
                if block_type == "text":
                    text = block.get("text", "")
                    if isinstance(text, str):
                        blocks.append((text, _source))
                elif block_type == "tool_result":
                    inner = block.get("content", "")
                    blocks.extend(self._extract_text_blocks(inner, _source="tool_result"))
                elif block_type == "tool_use":
                    inp = block.get("input")
                    if isinstance(inp, dict):
                        for v in inp.values():
                            if isinstance(v, str):
                                blocks.append((v, "tool_use"))
                    elif isinstance(inp, str):
                        blocks.append((inp, "tool_use"))
            return blocks
        return []

    async def async_pre_call_hook(
        self,
        user_api_key_dict,
        cache,
        data,
        call_type,
    ):
        start_time = time.time()

        if not (isinstance(call_type, str) and call_type in (
            "chat_completion", "acompletion", "completion",
            "anthropic_messages",
        )):
            return data

        messages = data.get("messages", [])

        # ── Accumulate findings, log ONE summary line at the end ──────────────
        vault_secrets: list = []
        header_secrets: list = []
        prompt_secrets: list = []
        injection_warnings: list = []
        had_redaction = False
        had_block = False

        all_text_parts = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            raw_content = msg.get("content", "")
            if raw_content:
                all_text_parts.extend(t for t, _ in self._extract_text_blocks(raw_content))

        if all_text_parts:
            concatenated = "\n".join(all_text_parts)
            normalizer = NormalizationPipeline()
            concat_views = normalizer.generate_views(concatenated)
            vault_matches = self._engine._vault.match_views(concat_views)
            if vault_matches:
                vault_secrets = [m.secret_id for m in vault_matches]
            del concatenated, concat_views, normalizer

        extra_headers = data.get("extra_headers", {})
        if extra_headers:
            import json as _json
            headers_text = _json.dumps(extra_headers, default=str)
            headers_result = self._engine.scan_and_redact(headers_text)
            if headers_result.events:
                header_secrets = [e.secret_id for e in headers_result.events if e.secret_id]

        for msg in messages:
            if not isinstance(msg, dict):
                continue
            raw_content = msg.get("content", "")
            if not raw_content:
                continue

            msg_role = msg.get("role", "")
            text_blocks = self._extract_text_blocks(raw_content)

            for text_content, block_source in text_blocks:
                if self.check_injection and msg_role == "user" and block_source == "text":
                    injection = self._check_injection(text_content)
                    if injection:
                        injection_warnings.append(injection)

                result = self._engine.scan_and_redact(text_content)
                if result.events:
                    had_redaction = True
                    if result.blocked:
                        had_block = True
                    for e in result.events:
                        if e.secret_id:  # skip None (entropy-only)
                            prompt_secrets.append(e.secret_id)
                    # warn-only mode: do not redact content, just log

        should_log = had_block or bool(injection_warnings)
        if not should_log and (vault_secrets or header_secrets or prompt_secrets):
            should_log = _rate_limiter.should_log("sl:redact_rate")

        if should_log and (vault_secrets or header_secrets or prompt_secrets or injection_warnings):
            summary_parts = []
            if vault_secrets:
                summary_parts.append(f"vault=[{'|'.join(sorted(set(vault_secrets)))}]")
            if header_secrets:
                summary_parts.append(f"headers=[{'|'.join(sorted(set(header_secrets)))}]")
            if prompt_secrets:
                unique_prompts = sorted(set(prompt_secrets))
                summary_parts.append(f"prompt=[{'|'.join(unique_prompts)}]")
            if injection_warnings:
                summary_parts.append(f"injection=[{'|'.join(sorted(set(injection_warnings)))}]")
            action = "WARN"
            logger.warning("[secret-guardrail] %s — %s", action, "; ".join(summary_parts))

        # ── Report to LiteLLM standard guardrail logging ─────────────────────
        end_time = time.time()
        all_event_types = sorted(set(
            vault_secrets + header_secrets + prompt_secrets + injection_warnings
        ))
        total_events = len(vault_secrets) + len(header_secrets) + len(prompt_secrets) + len(injection_warnings)

        if had_block:
            guardrail_action = "blocked"
        elif had_redaction:
            guardrail_action = "redacted"
        else:
            guardrail_action = "clean"

        guardrail_summary = {
            "action": guardrail_action,
            "events_count": total_events,
            "event_types": all_event_types,
        }
        guardrail_status = "guardrail_intervened" if (had_redaction or had_block) else "success"

        try:
            self.add_standard_logging_guardrail_information_to_request_data(
                guardrail_json_response=guardrail_summary,
                request_data=data,
                guardrail_status=guardrail_status,
                start_time=start_time,
                end_time=end_time,
                guardrail_provider="secret_guardrail",
                event_type=GuardrailEventHooks.pre_call,
            )
        except Exception as e:
            logger.debug("[secret-guardrail] failed to report to standard logging: %s", e)

        SecretGuardrail._gc_counter += 1
        if SecretGuardrail._gc_counter >= self._GC_EVERY_N:
            SecretGuardrail._gc_counter = 0
            gc.collect()

        return data

    async def async_post_call_success_hook(self, data, user_api_key_dict, response):
        start_time = time.time()
        post_redacted_any = False
        post_blocked = False
        post_event_types: list = []

        try:
            if not hasattr(response, "choices"):
                return response

            for choice in response.choices:
                if not hasattr(choice, "message") or not hasattr(choice.message, "content"):
                    continue
                content = choice.message.content
                if not content or not isinstance(content, str):
                    continue

                result = self._engine.scan_and_redact(content)

                if result.blocked:
                    post_blocked = True
                    for e in result.events:
                        if e.secret_id:
                            post_event_types.append(e.secret_id)
                    # warn-only mode: do not block response, just log
                    logger.warning(
                        "[secret-guardrail] WARN (would-block) response — vault match: %s",
                        [e.secret_id for e in result.events],
                    )
                elif result.events:
                    post_redacted_any = True
                    for e in result.events:
                        if e.secret_id:
                            post_event_types.append(e.secret_id)
                    # warn-only mode: do not redact response, just log
                    logger.warning(
                        "[secret-guardrail] WARN secrets detected in response: %s",
                        [e.secret_id for e in result.events],
                    )

            if post_blocked or post_redacted_any:
                if not hasattr(response, "_hidden_params"):
                    response._hidden_params = {}
                if "additional_headers" not in response._hidden_params:
                    response._hidden_params["additional_headers"] = {}
                status = "blocked" if post_blocked else "redacted"
                response._hidden_params["additional_headers"]["X-LiteLLM-Secrets-Redacted"] = status

        except Exception as e:
            logger.error("[secret-guardrail] error in post-call hook: %s", e)

        end_time = time.time()
        if post_blocked:
            post_action = "blocked"
        elif post_redacted_any:
            post_action = "redacted"
        else:
            post_action = "clean"

        post_summary = {
            "action": post_action,
            "events_count": len(post_event_types),
            "event_types": sorted(set(post_event_types)),
        }
        post_status = "guardrail_intervened" if (post_redacted_any or post_blocked) else "success"

        try:
            self.add_standard_logging_guardrail_information_to_request_data(
                guardrail_json_response=post_summary,
                request_data=data if isinstance(data, dict) else {},
                guardrail_status=post_status,
                start_time=start_time,
                end_time=end_time,
                guardrail_provider="secret_guardrail",
                event_type=GuardrailEventHooks.post_call,
            )
        except Exception as e:
            logger.debug("[secret-guardrail] failed to report post-call to standard logging: %s", e)

        return response


_litellm_dir = os.path.dirname(os.path.abspath(__file__))

guardrail_instance = SecretGuardrail(
    action=os.environ.get("SECRET_GUARDRAIL_ACTION", "redact"),
    check_injection=os.environ.get("SECRET_GUARDRAIL_CHECK_INJECTION", "true").lower() != "false",
)
