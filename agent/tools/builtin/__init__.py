"""Builtin 工具集 - 统一入口

职责:
1. 聚合所有内置工具子模块的 tool_definition 列表
2. 将它们注册到 ToolManager

注意: 依赖注入不在此处处理。各工具模块导出的 tool_definition
已包含 executor=None，实际的 executor 注入在 ToolManager 或独立工厂中完成。
"""

from agent.tools.manager.manager import ToolManager

from .skill import SKILL_TOOLS
from .cdp import CDP_TOOLS
from .task import TASK_TOOLS
from .phase import PHASE_TOOLS
from .todo import TODO_TOOLS
from .spawn import SPAWN_TOOLS
from .command import COMMAND_TOOLS


def register_all_builtin(manager: ToolManager) -> None:
    """注册所有内置工具到 ToolManager

    遍历所有工具类别，逐 tool_definition 调用 manager.register_tool() 注册。
    """
    all_tool_defs = [
        *SKILL_TOOLS,
        *CDP_TOOLS,
        *TASK_TOOLS,
        *PHASE_TOOLS,
        *TODO_TOOLS,
        *SPAWN_TOOLS,
        *COMMAND_TOOLS,
    ]

    for tool_def in all_tool_defs:
        manager.register_tool(tool_def)
