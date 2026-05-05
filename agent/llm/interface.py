"""
LLM 接口模块 - 向后兼容的适配器包装层

支持 LM Studio 本地模型和 DeepSeek API 两种后端。
通过适配器模式委托给具体实现。
"""
import os

for proxy_var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
    os.environ.pop(proxy_var, None)

import json
import logging
from typing import Optional, Dict, Any, List, AsyncIterator

from ..config import LLMConfig
from .adapters import create_adapter, BaseLLMAdapter

logger = logging.getLogger(__name__)


class LLMInterface:
    """
    LLM 接口适配器包装层

    向后兼容的接口层，内部委托给具体的适配器实例。
    支持通过 LLM_PROVIDER 环境变量切换后端，或通过构造参数指定。
    """

    def __init__(self, provider: str = None, model: str = None, reasoning_effort: str = None):
        self.provider = provider or LLMConfig.PROVIDER
        self.model = model
        self.reasoning_effort = reasoning_effort

        self._adapter = create_adapter(
            provider=provider,
            model=model,
            reasoning_effort=reasoning_effort,
        )

        logger.info(
            f"初始化 LLM 接口: provider={self.provider}, "
            f"adapter={type(self._adapter).__name__}"
        )

    async def check_connection(self) -> bool:
        return await self._adapter.check_connection()

    async def chat_interleaved(
        self,
        messages: Optional[List[Dict[str, Any]]] = None,
        content: Optional[List[Dict]] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        response_format: Optional[Dict] = None,
        tools: Optional[List[Dict]] = None,
        tool_choice: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        对话接口

        使用 OpenAI 兼容端点 /v1/chat/completions
        支持标准 messages 格式或交错 content 格式
        支持 Tool Calling (Function Calling)

        Args:
            messages: 标准格式消息列表 (优先使用)
            content: 交错的内容数组 (向后兼容)
            system_prompt: 系统提示词 (当使用 content 时)
            temperature: 温度参数
            response_format: 响应格式
            tools: 工具定义列表
            tool_choice: 工具选择策略

        Returns:
            Dict: 包含 success, content, reasoning_content, tool_calls, model
        """
        return await self._adapter.chat_interleaved(
            messages=messages,
            content=content,
            system_prompt=system_prompt,
            temperature=temperature,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
        )

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        tools: Optional[List[Dict]] = None,
    ) -> AsyncIterator[dict]:
        """
        流式聊天接口

        Args:
            messages: 标准格式消息列表
            temperature: 温度参数
            tools: 工具定义列表

        Yields:
            Dict: {"type": "text", "content": "..."} 或
                  {"type": "tool_call", "id": "...", "name": "...", "arguments": {...}}
        """
        async for chunk in self._adapter.stream_chat(
            messages=messages,
            temperature=temperature,
            tools=tools,
        ):
            yield chunk


_llm_interface: Optional[LLMInterface] = None


def get_llm_interface(
    provider: str = None,
    model: str = None,
    reasoning_effort: str = None,
) -> LLMInterface:
    """获取 LLM 接口单例

    首次调用时根据配置创建实例，支持传入参数覆盖默认配置。

    Args:
        provider: LLM 提供商
        model: 模型名
        reasoning_effort: 思考强度
    """
    global _llm_interface
    if _llm_interface is None or provider is not None or model is not None:
        _llm_interface = LLMInterface(
            provider=provider,
            model=model,
            reasoning_effort=reasoning_effort,
        )
    return _llm_interface
