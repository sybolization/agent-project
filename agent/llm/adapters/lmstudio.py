"""LM Studio 适配器"""

import json
import logging
import os
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from .base import BaseLLMAdapter

# 清理代理环境变量，避免 httpx 使用系统代理
for proxy_var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
    os.environ.pop(proxy_var, None)

logger = logging.getLogger(__name__)


class LMStudioAdapter(BaseLLMAdapter):
    """LM Studio 本地 LLM 适配器

    使用 OpenAI 兼容格式 /v1/chat/completions 端点。
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 4060,
        model: str = "qwen3.5-9b-uncensored-hauhaucs-aggressive",
        context_length: int = 65536,
    ):
        self.host = host
        self.port = port
        self.model = model
        self.context_length = context_length
        self.base_url = f"http://{host}:{port}"

    async def check_connection(self) -> bool:
        try:
            async with httpx.AsyncClient(proxy=None) as client:
                response = await client.get(
                    f"{self.base_url}/v1/models",
                    timeout=10.0
                )
                return response.status_code == 200
        except Exception as e:
            logger.error(f"LM Studio 连接检查失败: {e}")
            return False

    async def chat_interleaved(
        self,
        messages=None,
        content=None,
        system_prompt=None,
        temperature=0.7,
        response_format=None,
        tools=None,
        tool_choice=None,
    ) -> Dict[str, Any]:
        if messages is not None:
            request_messages = list(messages)
            if system_prompt:
                request_messages.insert(0, {"role": "system", "content": system_prompt})
        elif content is not None:
            if system_prompt is None:
                system_prompt = "You are a helpful assistant that analyzes web content with images."
            request_messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content}
            ]
        else:
            return {"success": False, "error": "必须提供 messages 或 content"}

        try:
            async with httpx.AsyncClient(timeout=300.0, proxy=None) as client:
                request_data = {
                    "model": self.model,
                    "messages": request_messages,
                    "temperature": temperature,
                    "context_length": self.context_length,
                }

                if response_format:
                    request_data["response_format"] = response_format

                if tools:
                    request_data["tools"] = tools
                    if tool_choice:
                        request_data["tool_choice"] = tool_choice

                url = f"{self.base_url}/v1/chat/completions"
                logger.debug(f"LM Studio 请求: {url}, messages: {len(request_messages)}, tools: {len(tools) if tools else 0}")

                response = await client.post(url, json=request_data)

                if response.status_code == 200:
                    data = response.json()
                    choices = data.get("choices", [])
                    if choices:
                        message = choices[0].get("message", {})
                        result_content = message.get("content", "")
                        reasoning_content = message.get("reasoning_content", "")

                        tool_calls = []
                        raw_tool_calls = message.get("tool_calls", [])
                        for tc in raw_tool_calls:
                            func = tc.get("function", {})
                            args_str = func.get("arguments", "{}")
                            try:
                                args = json.loads(args_str) if isinstance(args_str, str) else args_str
                            except json.JSONDecodeError:
                                args = {}
                            tool_calls.append({
                                "id": tc.get("id", ""),
                                "name": func.get("name", ""),
                                "arguments": args
                            })

                        return {
                            "success": True,
                            "content": result_content,
                            "reasoning_content": reasoning_content,
                            "tool_calls": tool_calls,
                            "model": data.get("model", self.model),
                            "raw_response": data
                        }
                    return {"success": False, "error": "LM Studio 返回空响应"}
                else:
                    error_msg = f"LM Studio 错误: {response.status_code}"
                    logger.error(f"{error_msg}: {response.text[:500]}")
                    return {"success": False, "error": error_msg, "details": response.text}

        except Exception as e:
            logger.error(f"LM Studio 请求出错: {e}")
            return {"success": False, "error": str(e)}

    async def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        tools: Optional[List[Dict]] = None,
    ) -> AsyncIterator[dict]:
        async with httpx.AsyncClient(timeout=300.0, proxy=None) as client:
            request_data = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "stream": True,
                "context_length": self.context_length,
            }

            if tools:
                request_data["tools"] = tools

            url = f"{self.base_url}/v1/chat/completions"

            async with client.stream("POST", url, json=request_data) as response:
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    line = line[6:].strip()
                    if line == "[DONE]":
                        break
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    choices = data.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    if "content" in delta and delta["content"]:
                        yield {"type": "text", "content": delta["content"]}
                    if "tool_calls" in delta:
                        for tc in delta["tool_calls"]:
                            func = tc.get("function", {})
                            args_str = func.get("arguments", "{}")
                            try:
                                args = json.loads(args_str) if isinstance(args_str, str) else args_str
                            except json.JSONDecodeError:
                                args = {}
                            yield {
                                "type": "tool_call",
                                "id": tc.get("id", ""),
                                "name": func.get("name", ""),
                                "arguments": args
                            }
                    if choices[0].get("finish_reason") == "stop":
                        break
