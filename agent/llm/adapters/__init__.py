"""LLM 适配器模块"""

import logging
from typing import Optional

from .base import BaseLLMAdapter, LLMResponse
from .deepseek import DeepSeekAdapter
from .lmstudio import LMStudioAdapter

logger = logging.getLogger(__name__)

__all__ = [
    "BaseLLMAdapter",
    "LLMResponse",
    "DeepSeekAdapter",
    "LMStudioAdapter",
    "create_adapter",
]


def create_adapter(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
) -> BaseLLMAdapter:
    """创建 LLM 适配器实例

    根据 provider 创建对应的适配器，参数优先级：显式传入 > 环境变量 > 默认值。

    Args:
        provider: LLM 提供商 ("deepseek" 或 "lmstudio")，None 时从 LLMConfig 读取
        model: 模型名，None 时使用提供商默认
        reasoning_effort: DeepSeek 思考强度，None 时使用 DeepSeekConfig 默认

    Returns:
        BaseLLMAdapter 实例
    """
    from ..config import LMStudioConfig, DeepSeekConfig
    from ...config import LLMConfig

    provider = provider or LLMConfig.PROVIDER

    if provider == "deepseek":
        return DeepSeekAdapter(
            api_key=DeepSeekConfig.API_KEY,
            model=model or DeepSeekConfig.MODEL,
            base_url=DeepSeekConfig.BASE_URL,
            reasoning_effort=reasoning_effort or DeepSeekConfig.REASONING_EFFORT,
            thinking_enabled=DeepSeekConfig.THINKING_ENABLED,
        )
    else:
        return LMStudioAdapter(
            host=LMStudioConfig.HOST,
            port=LMStudioConfig.PORT,
            model=model or LMStudioConfig.MODEL,
            context_length=LMStudioConfig.CONTEXT_LENGTH,
        )
