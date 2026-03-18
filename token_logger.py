"""LiteLLM callback handler for logging token usage to SQLite."""
import time
from litellm.integrations.custom_logger import CustomLogger
from token_db import log_usage


class TokenLogger(CustomLogger):
    """Custom logger that captures LiteLLM API calls and logs to SQLite."""
    
    def log_success_event(self, kwargs, response_obj, start_time, end_time):
        """Log successful API calls."""
        try:
            # Extract model
            model = kwargs.get("model", "unknown")
            
            # Extract agent from metadata or headers
            agent = "unknown"
            metadata = kwargs.get("metadata", {})
            if isinstance(metadata, dict):
                agent = metadata.get("agent", metadata.get("user", "unknown"))
            
            # If not in metadata, check headers
            if agent == "unknown":
                headers = kwargs.get("headers", {})
                if isinstance(headers, dict):
                    agent = headers.get("x-agent", headers.get("x-user", "unknown"))
            
            # Extract token usage
            prompt_tokens = 0
            completion_tokens = 0
            total_tokens = 0
            
            if hasattr(response_obj, "usage") and response_obj.usage:
                usage = response_obj.usage
                prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
                completion_tokens = getattr(usage, "completion_tokens", 0) or 0
                total_tokens = getattr(usage, "total_tokens", 0) or 0
            
            # Calculate duration
            duration_ms = int((end_time - start_time) * 1000) if start_time and end_time else 0
            
            # Log to database
            log_usage(
                model=model,
                agent=agent,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                duration_ms=duration_ms,
                status="success",
                error_message=None
            )
            
        except Exception as e:
            # Silently catch all exceptions - logging must never crash litellm
            print(f"TokenLogger error in log_success_event: {e}")
    
    def log_failure_event(self, kwargs, response_obj, start_time, end_time):
        """Log failed API calls."""
        try:
            # Extract model
            model = kwargs.get("model", "unknown")
            
            # Extract agent from metadata or headers
            agent = "unknown"
            metadata = kwargs.get("metadata", {})
            if isinstance(metadata, dict):
                agent = metadata.get("agent", metadata.get("user", "unknown"))
            
            # If not in metadata, check headers
            if agent == "unknown":
                headers = kwargs.get("headers", {})
                if isinstance(headers, dict):
                    agent = headers.get("x-agent", headers.get("x-user", "unknown"))
            
            # Extract error message
            error_message = str(response_obj) if response_obj else "Unknown error"
            
            # Calculate duration
            duration_ms = int((end_time - start_time) * 1000) if start_time and end_time else 0
            
            # Log to database
            log_usage(
                model=model,
                agent=agent,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                duration_ms=duration_ms,
                status="failure",
                error_message=error_message
            )
            
        except Exception as e:
            # Silently catch all exceptions - logging must never crash litellm
            print(f"TokenLogger error in log_failure_event: {e}")


# Pre-instantiated instance for litellm config callback registration
token_logger_instance = TokenLogger()
