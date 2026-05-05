"""CDP 执行器 - 处理 Chrome DevTools Protocol 工具调用"""

import logging
from typing import Optional

from ...config import LLMConfig
from ...browser.cdp_client import CDPClient, CDPError, CDPConnectionError, CDPCommandError
from ...browser.cdp_helpers import CDPHelpers
from ...browser.cdp_context import CDPContextProvider
from ...browser.cdp_self_heal import SelfHealEngine
from ...errors import CdpExecutionError

logger = logging.getLogger(__name__)


class CdpExecutor:
    """CDP 执行器

    负责 Chrome DevTools Protocol 的完整执行流程：
    - CDP 连接管理
    - CDP 命令执行
    - 浏览器状态获取
    - Helper 函数编辑
    - 自愈机制
    """

    def __init__(self):
        self._cdp_client: Optional[CDPClient] = None
        self._cdp_helpers: Optional[CDPHelpers] = None
        self._cdp_context: Optional[CDPContextProvider] = None
        self._cdp_self_heal: Optional[SelfHealEngine] = None

    @property
    def cdp_client(self):
        return self._cdp_client

    @property
    def cdp_helpers(self):
        return self._cdp_helpers

    @property
    def cdp_context(self):
        return self._cdp_context

    @property
    def is_connected(self) -> bool:
        return self._cdp_client is not None and self._cdp_client.is_connected()

    async def execute_cdp_connect(self, args: dict) -> dict:
        host = args.get("host", "localhost")
        port = args.get("port", 9222)
        cookie_store_path = args.get("cookie_store_path", ".cdp_state/cookies.json")

        try:
            if self._cdp_client and self._cdp_client.is_connected():
                return {
                    "type": "cdp_already_connected",
                    "message": f"Already connected to Chrome at {self._cdp_client._host}:{self._cdp_client._port}",
                    "target_id": self._cdp_client._target_id,
                }

            client = CDPClient(host=host, port=port, cookie_store_path=cookie_store_path)
            await client.connect()

            self._cdp_client = client
            self._cdp_helpers = CDPHelpers(client)
            self._cdp_context = CDPContextProvider(client)
            self._cdp_context.include_screenshot = LLMConfig.CDP_SCREENSHOT_ENABLED
            self._cdp_self_heal = SelfHealEngine(self._cdp_helpers)

            functions = self._cdp_helpers.list_functions()

            return {
                "type": "cdp_connected",
                "message": f"Connected to Chrome CDP at {host}:{port}",
                "target_id": client._target_id,
                "cookie_store_path": cookie_store_path,
                "available_functions": functions,
                "should_record": True,
                "record_data": {
                    "tool_name": "cdp_connect",
                    "arguments": args,
                    "result_summary": f"CDP connected: {host}:{port}"
                }
            }
        except CDPConnectionError as e:
            raise CdpExecutionError(
                f"CDP 连接失败: {e}。请确保 Chrome 以 --remote-debugging-port={port} 启动",
                tool_name="cdp_connect",
                arguments={"host": host, "port": port},
                fatal=True,
            ) from e
        except Exception as e:
            raise CdpExecutionError(
                f"CDP 连接错误: {e}",
                tool_name="cdp_connect",
                arguments={"host": host, "port": port},
                fatal=False,
            ) from e

    async def execute_cdp_execute(self, args: dict) -> dict:
        if not self._cdp_client or not self._cdp_client.is_connected():
            return {
                "type": "error",
                "message": "Not connected to Chrome. Call cdp_connect first."
            }

        func_name = args.get("function", "")
        func_args = args.get("args", {})

        if func_name == "raw":
            method = args.get("method", "")
            params = args.get("params", {})
            if not method:
                return {"type": "error", "message": "method is required when function='raw'"}
            try:
                result = await self._cdp_client.execute(method, params)
                return {
                    "type": "cdp_result",
                    "result": result,
                    "should_record": True,
                    "record_data": {
                        "tool_name": "cdp_execute",
                        "arguments": args,
                        "result_summary": f"CDP raw: {method}"
                    }
                }
            except CDPCommandError as e:
                raise CdpExecutionError(
                    f"CDP 命令错误: {e}",
                    tool_name="cdp_execute",
                    arguments={"method": method, "params": params},
                    fatal=False,
                ) from e
            except Exception as e:
                raise CdpExecutionError(
                    f"CDP 执行错误: {e}",
                    tool_name="cdp_execute",
                    arguments={"method": method, "params": params},
                    fatal=False,
                ) from e

        if not self._cdp_helpers.has_function(func_name):
            helpers_source = self._cdp_helpers.get_helpers_source()
            available = self._cdp_helpers.list_functions()
            return {
                "type": "missing_function",
                "message": f"Function '{func_name}' not found. Available: {available}. Use cdp_edit_helpers to add it.",
                "missing_function": func_name,
                "available_functions": available,
                "helpers_source": helpers_source[:2000],
            }

        try:
            result = await self._cdp_helpers.call_function(func_name, **func_args)

            result_summary = str(result)[:200] if result is not None else "None"

            return {
                "type": "cdp_result",
                "function": func_name,
                "result": result,
                "should_record": True,
                "record_data": {
                    "tool_name": "cdp_execute",
                    "arguments": args,
                    "result_summary": f"CDP {func_name}: {result_summary}"
                }
            }
        except CDPCommandError as e:
            if self._cdp_self_heal.detect_stale_node_id(str(e)):
                heal_result = await self._cdp_self_heal.heal_stale_node_id()
                if heal_result["success"]:
                    try:
                        result = await self._cdp_helpers.call_function(func_name, **func_args)
                        return {
                            "type": "cdp_result",
                            "function": func_name,
                            "result": result,
                            "should_record": True,
                            "record_data": {
                                "tool_name": "cdp_execute",
                                "arguments": args,
                                "result_summary": f"CDP {func_name} (auto-healed): {str(result)[:200]}"
                            }
                        }
                    except Exception as retry_err:
                        logger.warning(f"[CDP] self-heal retry 失败: {retry_err}")
            missing = self._cdp_self_heal.detect_missing_function(str(e))
            if missing:
                return {
                    "type": "missing_function",
                    "message": f"Function '{missing}' not found. Use cdp_edit_helpers to add it.",
                    "missing_function": missing,
                    "available_functions": self._cdp_helpers.list_functions(),
                }
            raise CdpExecutionError(
                f"CDP 命令错误: {e}",
                tool_name="cdp_execute",
                arguments={"function": func_name, "func_args": func_args},
                fatal=False,
            ) from e
        except CDPError as e:
            raise CdpExecutionError(
                f"CDP 错误: {e}",
                tool_name="cdp_execute",
                arguments={"function": func_name, "func_args": func_args},
                fatal=False,
            ) from e
        except Exception as e:
            raise CdpExecutionError(
                f"CDP 执行异常: {e}",
                tool_name="cdp_execute",
                arguments={"function": func_name, "func_args": func_args},
                fatal=False,
            ) from e

    async def execute_cdp_get_state(self) -> dict:
        if not self._cdp_client or not self._cdp_client.is_connected():
            return {
                "type": "error",
                "message": "Not connected to Chrome. Call cdp_connect first."
            }

        try:
            context = await self._cdp_context.get_context()
            screenshot = context.pop("screenshot", None)
            formatted = self._cdp_context.format_context_for_llm(context)

            return {
                "type": "cdp_state",
                "content": formatted,
                "context": context,
                "formatted": formatted,
                "screenshot": screenshot,
                "should_record": True,
                "record_data": {
                    "tool_name": "cdp_get_state",
                    "arguments": {},
                    "result_summary": f"CDP state: {context.get('url', 'unknown')}"
                }
            }
        except Exception as e:
            raise CdpExecutionError(
                f"获取浏览器状态失败: {e}",
                tool_name="cdp_get_state",
                fatal=False,
            ) from e

    async def execute_cdp_edit_helpers(self, args: dict) -> dict:
        if not self._cdp_helpers:
            return {
                "type": "error",
                "message": "CDP helpers not initialized. Call cdp_connect first."
            }

        name = args.get("name", "")
        code = args.get("code", "")
        execute_immediately = args.get("execute_immediately", False)
        execute_args = args.get("execute_args", {})

        if not name or not code:
            return {"type": "error", "message": "name and code are required"}

        is_safe, reason = self._cdp_self_heal.validate_code_safety(code)
        if not is_safe:
            return {
                "type": "error",
                "message": f"Code validation failed: {reason}. The code contains potentially dangerous operations."
            }

        result = await self._cdp_self_heal.add_function(name, code)

        if result["success"]:
            if execute_immediately:
                try:
                    exec_result = await self._cdp_helpers.call_function(name, **execute_args)
                    return {
                        "type": "helpers_updated_and_executed",
                        "message": result["message"],
                        "function_name": name,
                        "available_functions": self._cdp_helpers.list_functions(),
                        "execution_result": exec_result,
                        "should_record": True,
                        "record_data": {
                            "tool_name": "cdp_edit_helpers",
                            "arguments": args,
                            "result_summary": f"Added and executed function: {name}"
                        }
                    }
                except Exception as e:
                    raise CdpExecutionError(
                        f"函数 {name} 添加成功但执行失败: {e}",
                        tool_name="cdp_edit_helpers",
                        arguments={"function_name": name},
                        fatal=False,
                    ) from e
            return {
                "type": "helpers_updated",
                "message": result["message"],
                "function_name": name,
                "available_functions": self._cdp_helpers.list_functions(),
                "should_record": True,
                "record_data": {
                    "tool_name": "cdp_edit_helpers",
                    "arguments": args,
                    "result_summary": f"Added function: {name}"
                }
            }
        else:
            return {
                "type": "error",
                "message": result["message"]
            }
