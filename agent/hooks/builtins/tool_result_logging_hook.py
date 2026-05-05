"""工具结果记录 Hook"""

import logging
from typing import Optional, Any

from ..types import HookEvent, HookResult, HookEventName, HookExitCode
from ...session.logger import InteractionLogger

logger = logging.getLogger(__name__)


def create_tool_result_logging_hook(interaction_logger: Optional[Any] = None) -> callable:
    """创建工具结果记录 Hook

    在工具执行后记录结果到 interaction_logger。

    Args:
        interaction_logger: InteractionLogger 实例，用于记录交互日志

    Returns:
        Hook 处理函数
    """
    _interaction_logger = interaction_logger

    def tool_result_logging_hook(event: HookEvent) -> HookResult:
        """工具结果记录 Hook 处理器

        只处理 PostToolUse 事件。
        记录工具执行结果到日志。
        """
        if event.name != HookEventName.POST_TOOL_USE:
            return HookResult.continue_()

        tool_name = event.payload.get("tool_name", "")
        tool_input = event.payload.get("input", {})
        tool_output = event.payload.get("output", {})

        if _interaction_logger is not None:
            result_type = "unknown"
            if isinstance(tool_output, dict):
                result_type = tool_output.get("type", "unknown")

            _interaction_logger.emit(InteractionLogger.EVENT_TOOL_RESULT, {
                "tool": tool_name,
                "arguments": tool_input,
                "result_type": result_type,
            })

        logger.debug(f"[ToolResultLoggingHook] 工具执行完成: {tool_name}")

        return HookResult.continue_()

    tool_result_logging_hook.__name__ = "tool_result_logging_hook"
    return tool_result_logging_hook
