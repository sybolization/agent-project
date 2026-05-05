"""LLM 适配器抽象基类"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional


@dataclass
class LLMResponse:
    """统一的 LLM 响应格式"""
    success: bool
    content: str = ""
    reasoning_content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    model: str = ""
    raw_response: Optional[Dict[str, Any]] = None


class BaseLLMAdapter(ABC):
    """LLM 适配器抽象基类

    定义统一的 LLM 调用接口，子类实现具体的 API 调用逻辑。
    """

    @abstractmethod
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
        """对话接口，返回统一格式的 dict"""
        pass

    @abstractmethod
    async def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        tools: Optional[List[Dict]] = None,
    ) -> AsyncIterator[dict]:
        """流式聊天接口"""
        pass

    @abstractmethod
    async def check_connection(self) -> bool:
        """检查连接状态"""
        pass
