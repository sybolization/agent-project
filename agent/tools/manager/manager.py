"""工具管理器 - 统一管理所有工具的定义、注册和获取"""

from typing import Optional, List

from ...state import AgentPhase
from ..protocol import ToolDefinition


class ToolManager:
    """工具管理器

    统一管理所有工具的定义、注册和获取。
    通过控制传给API的工具schema来约束模型行为。
    """

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        self._disabled_tools: set[str] = set()

    def register_tool(self, tool: ToolDefinition) -> None:
        """注册工具"""
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """获取工具定义"""
        return self._tools.get(name)

    def disable_tool(self, name: str) -> None:
        self._disabled_tools.add(name)

    def enable_tool(self, name: str) -> None:
        self._disabled_tools.discard(name)

    def is_tool_enabled(self, name: str) -> bool:
        return name not in self._disabled_tools

    def get_disabled_tools(self) -> list[str]:
        return list(self._disabled_tools)

    def disable_tools(self, names: list[str]) -> None:
        self._disabled_tools.update(names)

    def enable_tools(self, names: list[str]) -> None:
        self._disabled_tools -= set(names)

    def enable_all_tools(self) -> None:
        self._disabled_tools.clear()

    def get_tools_for_phase(
        self,
        phase: AgentPhase,
        exclude_tools: Optional[List[str]] = None
    ) -> List[dict]:
        """获取指定阶段可用的工具schema列表"""
        tools = []
        for tool in self._tools.values():
            if tool.is_available_for_phase(phase):
                if tool.name in self._disabled_tools:
                    continue
                if exclude_tools and tool.name in exclude_tools:
                    continue
                tools.append(tool.schema)
        return tools

    def get_tool_names_for_phase(
        self,
        phase: AgentPhase,
        exclude_tools: Optional[List[str]] = None
    ) -> List[str]:
        """获取指定阶段可用的工具名称列表"""
        names = []
        for tool in self._tools.values():
            if tool.is_available_for_phase(phase):
                if tool.name in self._disabled_tools:
                    continue
                if exclude_tools and tool.name in exclude_tools:
                    continue
                names.append(tool.name)
        return names

    def get_phase_tools_description(
        self,
        phase: AgentPhase,
        exclude_tools: Optional[List[str]] = None
    ) -> str:
        """获取指定阶段工具的描述文本（用于提示词）"""
        names = self.get_tool_names_for_phase(phase, exclude_tools)
        return ", ".join(f"`{name}`" for name in names)

    def get_phase_tools_guidance(
        self,
        phase: AgentPhase,
        exclude_tools: Optional[List[str]] = None
    ) -> str:
        """获取指定阶段的工具使用引导"""
        tools = []
        for tool in self._tools.values():
            if tool.is_available_for_phase(phase):
                if tool.name in self._disabled_tools:
                    continue
                if exclude_tools and tool.name in exclude_tools:
                    continue
                if tool.usage_hint:
                    tools.append(f"- {tool.name}: {tool.usage_hint}")

        if not tools:
            return "此阶段无可用工具，请直接输出内容。"

        return "可用工具:\n" + "\n".join(tools)

    def register(self, tool_def: ToolDefinition) -> None:
        """注册工具 - 一步完成 schema + executor + handler + formatter 注册"""
        self._tools[tool_def.name] = tool_def

    def get_handler(self, tool_name: str):
        """获取工具的结果处理器"""
        tool = self._tools.get(tool_name)
        if tool and tool.executor and hasattr(tool.executor, 'handle'):
            return tool.executor.handle
        return None

    def get_formatter(self, tool_name: str):
        """获取工具的结果格式化器"""
        tool = self._tools.get(tool_name)
        if tool and tool.executor and hasattr(tool.executor, 'format'):
            return tool.executor.format
        return None

    def get_available_tool_names(self) -> list[str]:
        """获取所有已注册的工具名称"""
        return list(self._tools.keys())


# 全局工具管理器实例
_tool_manager: Optional[ToolManager] = None


def get_tool_manager() -> ToolManager:
    """获取全局工具管理器"""
    global _tool_manager
    if _tool_manager is None:
        _tool_manager = ToolManager()
        register_all_tools()
    return _tool_manager


def register_all_tools():
    """注册所有工具 - 从 builtin 模块自动发现"""
    global _tool_manager
    from ..builtin import register_all_builtin
    register_all_builtin(_tool_manager)


def get_tools_for_phase(phase, exclude_tools=None):
    """便捷函数 - 获取指定阶段的工具schema列表"""
    manager = get_tool_manager()
    return manager.get_tools_for_phase(phase, exclude_tools)


def get_available_tool_names(phase=None, exclude_tools=None):
    """便捷函数 - 获取可用工具名称"""
    manager = get_tool_manager()
    if phase is not None:
        return manager.get_tool_names_for_phase(phase, exclude_tools)
    return manager.get_available_tool_names()


def get_phase_tools_description(phase, exclude_tools=None):
    """便捷函数 - 获取阶段工具描述"""
    manager = get_tool_manager()
    return manager.get_phase_tools_description(phase, exclude_tools)


def disable_tools_globally(tool_names):
    """便捷函数 - 全局禁用工具"""
    manager = get_tool_manager()
    manager.disable_tools(tool_names)


def enable_tools_globally(tool_names):
    """便捷函数 - 全局启用工具"""
    manager = get_tool_manager()
    manager.enable_tools(tool_names)
