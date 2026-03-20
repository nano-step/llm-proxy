"""LiteLLM callback handler for logging token usage to SQLite."""
from litellm.integrations.custom_logger import CustomLogger
from token_db import log_usage, DB_PATH


class TokenLogger(CustomLogger):

    def __init__(self):
        super().__init__()
        self._registered = False
        print(f"[TokenLogger] initialized, logging to {DB_PATH}", flush=True)

    def _ensure_registered(self):
        if self._registered:
            return
        import litellm
        if self not in litellm._async_success_callback:
            litellm._async_success_callback.append(self)
        if self not in litellm._async_failure_callback:
            litellm._async_failure_callback.append(self)
        self._registered = True
        print("[TokenLogger] lazy-registered in async callbacks", flush=True)

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        self._ensure_registered()
        return data

    def _extract_agent(self, kwargs):
        lp = kwargs.get("litellm_params", {})
        lp_meta = lp.get("metadata", {}) if isinstance(lp, dict) else {}

        if isinstance(lp_meta, dict):
            alias = lp_meta.get("user_api_key_alias")
            if alias:
                return str(alias)

            lp_headers = lp_meta.get("headers", {})
            if isinstance(lp_headers, dict):
                agent = lp_headers.get("x-agent", lp_headers.get("x-user", ""))
                if agent:
                    return str(agent)

            user_agent = lp_meta.get("user_agent", "")
            if user_agent and user_agent != "cli-proxy-openai-compat":
                return str(user_agent)

        user = kwargs.get("user")
        if user:
            return str(user)

        metadata = kwargs.get("metadata", {})
        if isinstance(metadata, dict):
            agent = metadata.get("agent", metadata.get("user", ""))
            if agent:
                return str(agent)

        return "unknown"

    def _get_response_obj(self, kwargs, response_obj):
        # For streaming requests, LiteLLM delivers aggregated usage via
        # kwargs["async_complete_streaming_response"], not response_obj.
        streaming_resp = kwargs.get("async_complete_streaming_response")
        if streaming_resp is not None:
            return streaming_resp
        return response_obj

    def _extract_usage(self, kwargs, response_obj):
        resp = self._get_response_obj(kwargs, response_obj)

        usage = None
        if hasattr(resp, "usage") and resp.usage:
            usage = resp.usage
        elif isinstance(resp, dict) and resp.get("usage"):
            usage = resp["usage"]

        if usage is None:
            return 0, 0, 0

        if isinstance(usage, dict):
            prompt = usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0
            completion = usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
            total = usage.get("total_tokens", 0) or 0
        else:
            prompt = getattr(usage, "prompt_tokens", 0) or getattr(usage, "input_tokens", 0) or 0
            completion = getattr(usage, "completion_tokens", 0) or getattr(usage, "output_tokens", 0) or 0
            total = getattr(usage, "total_tokens", 0) or 0

        if total == 0 and (prompt > 0 or completion > 0):
            total = prompt + completion

        return prompt, completion, total

    def _calc_duration_ms(self, start_time, end_time):
        if not start_time or not end_time:
            return 0
        try:
            delta = end_time - start_time
            return int(delta.total_seconds() * 1000)
        except Exception:
            return 0

    def _handle_success(self, kwargs, response_obj, start_time, end_time):
        try:
            prompt_tokens, completion_tokens, total_tokens = self._extract_usage(kwargs, response_obj)
            model = kwargs.get("model", "unknown")
            agent = self._extract_agent(kwargs)
            duration_ms = self._calc_duration_ms(start_time, end_time)

            log_usage(
                model=model,
                agent=agent,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                duration_ms=duration_ms,
                status="success",
                error_message=None,
            )
            print(
                f"[TokenLogger] logged: model={model} agent={agent} "
                f"tokens={prompt_tokens}+{completion_tokens}={total_tokens} "
                f"duration={duration_ms}ms",
                flush=True,
            )
        except Exception as e:
            print(f"[TokenLogger] error in success handler: {e}", flush=True)

    def _handle_failure(self, kwargs, response_obj, start_time, end_time):
        try:
            model = kwargs.get("model", "unknown")
            agent = self._extract_agent(kwargs)
            duration_ms = self._calc_duration_ms(start_time, end_time)
            error_msg = str(response_obj) if response_obj else "Unknown error"

            log_usage(
                model=model,
                agent=agent,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                duration_ms=duration_ms,
                status="failure",
                error_message=error_msg,
            )
            print(
                f"[TokenLogger] logged failure: model={model} agent={agent} "
                f"error={error_msg[:100]} duration={duration_ms}ms",
                flush=True,
            )
        except Exception as e:
            print(f"[TokenLogger] error in failure handler: {e}", flush=True)

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        self._handle_success(kwargs, response_obj, start_time, end_time)

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        self._handle_failure(kwargs, response_obj, start_time, end_time)

    def log_success_event(self, kwargs, response_obj, start_time, end_time):
        self._handle_success(kwargs, response_obj, start_time, end_time)

    def log_failure_event(self, kwargs, response_obj, start_time, end_time):
        self._handle_failure(kwargs, response_obj, start_time, end_time)


token_logger_instance = TokenLogger()
