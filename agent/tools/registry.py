"""工具注册表 - 管理工具名称到执行器方法的映射"""

import dataclasses
from typing import Any


@dataclasses.dataclass
class ToolHandler:
    handler: Any
    is_async: bool = False
    pass_call: bool = False
    pass_ctx: bool = False
    no_args: bool = False


class ToolRegistry:
    """工具注册表 - 管理工具名称到执行器方法的映射

    职责：
    - 注册工具处理器及其调用元数据
    - 按名称查找处理器
    - 列出所有已注册工具
    """

    def __init__(self):
        self._handlers: dict[str, ToolHandler] = {}

    def register(
        self,
        tool_name: str,
        handler: Any,
        is_async: bool = False,
        pass_call: bool = False,
        pass_ctx: bool = False,
        no_args: bool = False,
    ) -> None:
        self._handlers[tool_name] = ToolHandler(
            handler=handler,
            is_async=is_async,
            pass_call=pass_call,
            pass_ctx=pass_ctx,
            no_args=no_args,
        )

    def get(self, tool_name: str) -> ToolHandler | None:
        return self._handlers.get(tool_name)

    def list_tools(self) -> list[str]:
        return list(self._handlers.keys())
