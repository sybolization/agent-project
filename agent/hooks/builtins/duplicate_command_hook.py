"""重复命令检测 Hook"""

import logging
from typing import Optional, List, Dict, Any

from ..types import HookEvent, HookResult, HookEventName

logger = logging.getLogger(__name__)


def create_duplicate_command_hook(action_history: Optional[List[Dict[str, Any]]] = None) -> callable:
    """创建重复命令检测 Hook

    检测用户是否重复执行相同的命令，如果重复则注入警告消息。

    Args:
        action_history: 可选的行动历史列表引用，用于检测重复

    Returns:
        Hook 处理函数
    """
    _action_history = action_history or []

    def duplicate_command_hook(event: HookEvent) -> HookResult:
        """重复命令检测 Hook 处理器

        只处理 execute_command 工具的 PreToolUse 事件。
        检测命令是否在历史中已执行过。
        """
        if event.name != HookEventName.PRE_TOOL_USE:
            return HookResult.continue_()

        tool_name = event.payload.get("tool_name", "")
        if tool_name != "execute_command":
            return HookResult.continue_()

        tool_input = event.payload.get("input", {})
        command = tool_input.get("command", "")

        if not command:
            return HookResult.continue_()

        # 检查是否重复
        duplicate_action = None
        for action in reversed(_action_history):
            if action.get("tool_name") == "execute_command":
                args = action.get("arguments", {})
                if args.get("command", "") == command:
                    duplicate_action = action
                    break

        if duplicate_action:
            result_summary = duplicate_action.get("result_summary", "未知")
            warning_message = (
                f"[重复操作警告] 命令 \"{command}\" 已在之前执行过"
                f"（结果: {result_summary}）。"
                f"如果你需要获取最新数据，请继续执行。如果不需要，请跳过此步骤。"
            )
            logger.info(f"[DuplicateCommandHook] 检测到重复命令: {command}")
            return HookResult.inject(warning_message)

        return HookResult.continue_()

    duplicate_command_hook.__name__ = "duplicate_command_hook"
    return duplicate_command_hook
