"""工具结果处理器和格式化器

提供 ToolResultHandler 和 ToolResultFormatter 抽象基类，
以及各工具的具体实现。
"""

from abc import ABC, abstractmethod
from typing import Any

from ..result import PhaseResult


class ToolResultHandler(ABC):
    """工具结果处理器基类

    每个处理器负责处理特定工具的执行结果，
    返回 PhaseResult 以决定后续流程。
    """

    tool_name: str = ""

    @abstractmethod
    def handle(self, result: dict, state: Any) -> PhaseResult:
        """处理工具执行结果

        Args:
            result: 工具执行结果字典
            state: Agent状态对象

        Returns:
            PhaseResult: 处理后的阶段结果
        """
        pass


class ToolResultFormatter(ABC):
    """工具结果格式化器基类

    每个格式化器负责将工具执行结果格式化为消息文本，
    用于回传给 LLM。
    """

    tool_name: str = ""

    @abstractmethod
    def format(self, result: dict) -> str:
        """格式化工具执行结果为消息文本

        Args:
            result: 工具执行结果字典

        Returns:
            str: 格式化后的消息文本
        """
        pass


class DefaultHandler(ToolResultHandler):
    """默认工具结果处理器

    用于未注册专用处理器的工具，返回错误状态。
    """

    tool_name = "default"

    def handle(self, result: dict, state: Any) -> PhaseResult:
        """处理未知工具结果

        Args:
            result: 工具执行结果字典
            state: Agent状态对象

        Returns:
            PhaseResult: 错误结果
        """
        return PhaseResult(status="error", message=f"未知工具结果: {result}")


class DefaultFormatter(ToolResultFormatter):
    """默认工具结果格式化器

    用于未注册专用格式化器的工具，返回通用格式。
    """

    tool_name = "default"

    def format(self, result: dict) -> str:
        """格式化未知工具结果

        Args:
            result: 工具执行结果字典

        Returns:
            str: 通用格式化文本
        """
        return f"工具执行结果: {result}"


# 导入各工具的具体实现
from .execute_command import ExecuteCommandHandler, ExecuteCommandFormatter
from .load_skill import LoadSkillHandler, LoadSkillFormatter
from .load_reference import LoadReferenceHandler, LoadReferenceFormatter
from .load_skill_category import LoadSkillCategoryHandler, LoadSkillCategoryFormatter
from .update_todo import UpdateTodoHandler, UpdateTodoFormatter
from .spawn_agents import SpawnAgentsHandler, SpawnAgentsFormatter
from .task_complete import TaskCompleteHandler
from .cdp import (
    CdpConnectHandler,
    CdpConnectFormatter,
    CdpExecuteHandler,
    CdpExecuteFormatter,
    CdpGetStateHandler,
    CdpGetStateFormatter,
    CdpEditHelpersHandler,
    CdpEditHelpersFormatter,
)

__all__ = [
    # 基类
    "ToolResultHandler",
    "ToolResultFormatter",
    # 默认处理器
    "DefaultHandler",
    "DefaultFormatter",
    # execute_command
    "ExecuteCommandHandler",
    "ExecuteCommandFormatter",
    # load_skill
    "LoadSkillHandler",
    "LoadSkillFormatter",
    # load_reference
    "LoadReferenceHandler",
    "LoadReferenceFormatter",
    # load_skill_category
    "LoadSkillCategoryHandler",
    "LoadSkillCategoryFormatter",
    # update_todo
    "UpdateTodoHandler",
    "UpdateTodoFormatter",
    # spawn_agents
    "SpawnAgentsHandler",
    "SpawnAgentsFormatter",
    # task_complete
    "TaskCompleteHandler",
    # cdp
    "CdpConnectHandler",
    "CdpConnectFormatter",
    "CdpExecuteHandler",
    "CdpExecuteFormatter",
    "CdpGetStateHandler",
    "CdpGetStateFormatter",
    "CdpEditHelpersHandler",
    "CdpEditHelpersFormatter",
]
