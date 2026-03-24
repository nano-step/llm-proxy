"""
Fallback API Base Fixer

Workaround for LiteLLM v1.82.6 bug where fallback models inherit the wrong api_base.
This callback intercepts requests and ensures the correct api_base is used based on model name.
"""

from litellm.integrations.custom_logger import CustomLogger
import litellm


class FallbackFixer(CustomLogger):
    
    def __init__(self):
        super().__init__()
        self.model_map = {}
    
    def _build_model_map(self):
        """Build a map of model_name -> api_base from proxy router"""
        try:
            # Access the proxy's router instance
            from litellm.proxy.proxy_server import llm_router
            
            if llm_router and hasattr(llm_router, 'model_list'):
                for deployment in llm_router.model_list:
                    model_name = deployment.get('model_name')
                    litellm_params = deployment.get('litellm_params', {})
                    api_base = litellm_params.get('api_base')
                    if model_name and api_base:
                        self.model_map[model_name] = api_base
        except Exception as e:
            litellm._logging.verbose_logger.debug(f"[fallback-fixer] Could not build model map: {e}")
    
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        """Fix api_base before the request is sent"""
        if not self.model_map:
            self._build_model_map()
        
        model = data.get('model')
        current_api_base = data.get('api_base')
        
        if model and model in self.model_map:
            correct_api_base = self.model_map[model]
            
            # Check if api_base is wrong
            if current_api_base and current_api_base != correct_api_base:
                data['api_base'] = correct_api_base
                litellm._logging.verbose_logger.info(
                    f"[fallback-fixer] Corrected api_base for {model}: "
                    f"{current_api_base} -> {correct_api_base}"
                )


fallback_fixer_instance = FallbackFixer()
