"""LLM module - LLM接口模块"""

from .config import DeepSeekConfig, LMStudioConfig


def __getattr__(name):
    if name == "LLMInterface":
        from .interface import LLMInterface
        return LLMInterface
    if name == "get_llm_interface":
        from .interface import get_llm_interface
        return get_llm_interface
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "LLMInterface",
    "get_llm_interface",
    "DeepSeekConfig",
    "LMStudioConfig",
]
