## ADDED Requirements

### Requirement: Extract token usage from streaming responses
The `TokenLogger` callback SHALL extract token usage from `kwargs["async_complete_streaming_response"].usage` when the request is a streaming response. It SHALL fall back to `response_obj.usage` when the streaming key is not present (non-streaming requests).

#### Scenario: Streaming Anthropic/Claude request completes successfully
- **WHEN** a streaming chat completion request to an Anthropic/Claude model completes through the LiteLLM proxy
- **THEN** the callback SHALL extract `prompt_tokens`, `completion_tokens`, and `total_tokens` from `kwargs["async_complete_streaming_response"].usage` and log them to `usage.db` with `status="success"`

#### Scenario: Non-streaming request completes successfully
- **WHEN** a non-streaming chat completion request completes through the LiteLLM proxy
- **THEN** the callback SHALL extract token usage from `response_obj.usage` and log them to `usage.db` with `status="success"`

#### Scenario: Streaming response has no usage data
- **WHEN** a streaming request completes but neither `kwargs["async_complete_streaming_response"].usage` nor `response_obj.usage` contains token counts
- **THEN** the callback SHALL log the request with `prompt_tokens=0`, `completion_tokens=0`, `total_tokens=0` and print a warning to stdout

### Requirement: Log failed requests
The `TokenLogger` callback SHALL log failed requests to `usage.db` with `status="failure"` and the error message, regardless of whether the request was streaming or non-streaming.

#### Scenario: Request fails with an error
- **WHEN** a chat completion request fails (timeout, auth error, upstream error)
- **THEN** the callback SHALL log the request with `status="failure"`, `error_message` containing the error description, and zero token counts

### Requirement: Support both sync and async callback paths
The `TokenLogger` SHALL implement both synchronous (`log_success_event`, `log_failure_event`) and asynchronous (`async_log_success_event`, `async_log_failure_event`) methods with identical extraction logic.

#### Scenario: Sync callback path is invoked
- **WHEN** LiteLLM invokes the synchronous callback path (e.g., non-proxy direct SDK usage)
- **THEN** the callback SHALL extract and log token usage identically to the async path

### Requirement: Callback initialization confirmation
The `TokenLogger` SHALL print a confirmation message to stdout during `__init__` to confirm it was loaded and registered by the LiteLLM proxy.

#### Scenario: LiteLLM proxy starts with token_logger configured
- **WHEN** the LiteLLM proxy starts and loads `token_logger.token_logger_instance` from `litellm_config.yaml`
- **THEN** the stdout log SHALL contain a message indicating TokenLogger was initialized (e.g., `[TokenLogger] initialized, logging to /data/litellm/usage.db`)

### Requirement: Enable stream usage in LiteLLM config
The `litellm_config.yaml` SHALL include `litellm_settings.always_include_stream_usage: true` to ensure streaming responses from all providers include token usage data.

#### Scenario: LiteLLM config loaded with stream usage enabled
- **WHEN** the LiteLLM proxy loads `litellm_config.yaml`
- **THEN** the `always_include_stream_usage` setting SHALL be `true`
